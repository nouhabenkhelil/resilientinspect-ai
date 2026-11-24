"""Security fixtures are deliberately distinct from real scientific inference QA."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import base64
import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from portal.models import Inspection, LoginFlow, Session, User, utcnow
from portal.security import PublicError, acquire_lease, digest, rate_limit, release_lease
from portal.settings import Settings
from portal.uploads import validate_image

pytestmark = pytest.mark.asyncio


async def test_health_and_anonymous_denied(h):
    assert (await h.client.get("/api/health")).json() == {"status": "ok", "service": "portal"}
    for route in ("/auth/session", "/status", "/readiness", "/model/metadata", "/inspections", "/admin/users", "/audit"):
        response = await h.client.get("/api" + route)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
    assert (await h.prediction(h.client, {})).status_code == 401
    assert not h.requests


async def begin(h):
    response = await h.client.get("/api/auth/login")
    assert response.status_code == 303
    params = parse_qs(urlsplit(response.headers["location"]).query)
    h.provider.nonce = params["nonce"][0]
    assert params["code_challenge_method"] == ["S256"]
    return params


async def test_real_code_pkce_signature_session_logout(h):
    params = await begin(h)
    async with h.app.state.db.sessions() as db:
        flow = (await db.execute(select(LoginFlow))).scalar_one()
        verifier = h.app.state.oidc.cipher.decrypt(flow.verifier.encode()).decode()
        assert flow.state_hash != params["state"][0]
        assert flow.verifier != verifier
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected]
    callback = "/api/auth/callback?state=" + params["state"][0] + "&code=isolated-code"
    # Exercise the cryptographic adapter directly as well as through the sanitized HTTP route.
    assert (await h.app.state.oidc.identity("isolated-code", h.provider.nonce, verifier))["role"] == "operator"
    response = await h.client.get(callback)
    assert response.status_code == 303, response.text
    assert h.provider.last_form["code_verifier"] == [verifier]
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    cookie = h.client.cookies.get(h.settings.cookie_name)
    assert cookie and "." not in cookie
    profile = (await h.client.get("/api/auth/session")).json()
    assert profile["user"]["role"] == "operator"
    assert h.provider.id_token not in str(profile)
    async with h.app.state.db.sessions() as db:
        stored = (await db.execute(select(Session))).scalar_one()
        assert stored.token_hash == digest(h.settings, cookie) and stored.token_hash != cookie
    assert (await h.client.get(callback)).status_code == 401
    headers = {"Origin": h.settings.origin, "X-CSRF-Token": profile["csrf_token"]}
    assert (await h.client.post("/api/auth/logout", headers=headers)).status_code == 200
    h.client.cookies.set(h.settings.cookie_name, cookie)
    assert (await h.client.get("/api/auth/session")).status_code == 401


@pytest.mark.parametrize("patch", [
    {"nonce": "wrong"}, {"aud": "other-client"}, {"iss": "https://attacker.invalid"},
    {"exp": 1}, {"iat": 9999999999}, {"sub": ""},
    {"resource_access": {}}, {"resource_access": {"portal-test": {"roles": ["admin", "operator"]}}},
])
async def test_invalid_signed_claims_refused(h, patch):
    params = await begin(h)
    h.provider.patch = patch
    response = await h.client.get("/api/auth/callback", params={"state": params["state"][0], "code": "isolated-code"})
    assert response.status_code in {401, 403}
    assert not h.client.cookies.get(h.settings.cookie_name)


async def test_state_redirect_and_callback_issuer(h):
    for target in ("https://evil.invalid", "//evil.invalid", "/admin"):
        assert (await h.client.get("/api/auth/login", params={"return_to": target})).status_code == 400
    params = await begin(h)
    for query in ({"state": "x" * 48, "code": "code"}, {"state": params["state"][0], "code": "code", "iss": "evil"}):
        assert (await h.client.get("/api/auth/callback", params=query)).status_code == 401
    h.client.cookies.clear()
    assert (await h.client.get("/api/auth/callback", params={"state": params["state"][0], "code": "code"})).status_code == 401


@pytest.mark.parametrize("bad_signature,algorithm", [(True, "RS256"), (False, "RS512")])
async def test_bad_signature_and_unapproved_algorithm(h, bad_signature, algorithm):
    params = await begin(h)
    h.provider.bad_signature, h.provider.algorithm = bad_signature, algorithm
    response = await h.client.get("/api/auth/callback", params={"state": params["state"][0], "code": "isolated-code"})
    assert response.status_code == 401
    assert not h.client.cookies.get(h.settings.cookie_name)


async def test_provider_unavailable_fails_closed(h):
    h.app.state.oidc.internal = lambda value: (_ for _ in ()).throw(ValueError("private provider failure"))
    response = await h.client.get("/api/auth/login")
    assert response.status_code == 503
    assert "private provider failure" not in response.text


@pytest.mark.parametrize("condition", ["expired", "revoked", "idle"])
async def test_expired_or_revoked_session(h, condition):
    _, client, _ = await h.identity(**{condition: True})
    assert (await client.get("/api/auth/session")).status_code == 401


@pytest.mark.parametrize("role,admin,audit,inspect,ready", [
    ("admin", 200, 200, 200, 200), ("ai_engineer", 403, 403, 200, 200),
    ("operator", 403, 403, 200, 403), ("auditor", 403, 200, 403, 403),
])
async def test_role_matrix(h, role, admin, audit, inspect, ready):
    _, client, headers = await h.identity(role)
    assert (await client.get("/api/admin/users")).status_code == admin
    assert (await client.get("/api/audit")).status_code == audit
    assert (await client.get("/api/readiness")).status_code == ready
    assert (await h.prediction(client, headers)).status_code == inspect


async def test_idor_grant_and_readonly_auditor(h):
    owner, client, headers = await h.identity()
    _, other, other_headers = await h.identity()
    auditor, reader, reader_headers = await h.identity("auditor")
    admin, manager, manager_headers = await h.identity("admin")
    response = await h.prediction(client, headers)
    assert response.status_code == 200, response.text
    identity = response.headers["x-inspection-id"]
    assert (await other.get("/api/inspections/" + identity)).status_code == 404
    assert (await other.get("/api/inspections")).json()["total"] == 0
    assert (await reader.get("/api/inspections/" + identity)).status_code == 404
    route = f"/api/admin/inspections/{identity}/grants/{auditor.id}"
    assert (await other.post(route, headers=other_headers)).status_code == 403
    assert (await manager.post(route, headers=manager_headers)).status_code == 200
    assert (await reader.get("/api/inspections/" + identity)).status_code == 200
    assert (await h.prediction(reader, reader_headers)).status_code == 403
    detail = (await reader.get("/api/inspections/" + identity)).json()
    assert "image" not in str(detail) and detail["version"] == "a" * 64
    assert (await client.get("/api/inspections", params={"order": "SQL", "limit": 1000})).status_code == 422
    assert (await client.patch(f"/api/admin/users/{owner.id}/enabled", headers=headers, json={"enabled": True, "role": "admin"})).status_code in {403, 422}


async def test_csrf_admin_revocation_and_disable(h):
    user, client, headers = await h.identity()
    admin, manager, admin_headers = await h.identity("admin")
    for invalid in ({}, {**headers, "Origin": "https://evil.invalid"}, {**headers, "X-CSRF-Token": "wrong"}):
        assert (await h.prediction(client, invalid)).status_code == 403
    assert not h.requests
    assert (await manager.patch(f"/api/admin/users/{admin.id}/enabled", headers=admin_headers, json={"enabled": False})).status_code == 409
    assert (await manager.post(f"/api/admin/users/{user.id}/revoke-sessions", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/auth/session")).status_code == 401
    assert (await manager.patch(f"/api/admin/users/{user.id}/enabled", headers=admin_headers, json={"enabled": False})).status_code == 200


async def test_uploads_and_fixed_destination(h):
    _, client, headers = await h.identity()
    for name, body in (("script.exe", h.png), ("mismatch.jpg", h.png), ("bad.png", b"not an image")):
        response = await client.post("/api/predict", headers=headers, data={"model": "B0", "category": "bottle"}, files={"file": (name, body, "image/png")})
        assert response.status_code in {400, 413, 415, 422}
    assert not h.requests
    assert (await h.prediction(client, headers, url="http://evil.invalid")).status_code in {400, 422}
    with pytest.raises(PublicError):
        validate_image(h.png, "x.png", replace(h.settings, max_pixels=1))
    response = await client.post("/api/predict", headers={**headers, "Content-Length": str(11 * 1024 * 1024)}, content=b"x")
    assert response.status_code == 413
    h.upstream_status = 503
    response = await h.prediction(client, headers)
    assert response.status_code == 503 and "private internal detail" not in response.text
    async with h.app.state.db.sessions() as db:
        rows = (await db.execute(select(Inspection))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "failed" and rows[0].image_sha256 is None


async def test_atomic_quotas_and_capacity(h):
    user, _, _ = await h.identity()
    async def consume():
        try:
            await rate_limit(h.app.state.db, "isolated-race", 60, 3)
            return 200
        except PublicError as error:
            return error.status
    results = await asyncio.gather(*(consume() for _ in range(10)))
    assert results.count(200) == 3 and results.count(429) == 7
    lease = await acquire_lease(h.app.state.db, h.settings, user)
    with pytest.raises(PublicError) as error:
        await acquire_lease(h.app.state.db, h.settings, user)
    assert error.value.status == 429
    await release_lease(h.app.state.db, lease)
    lease = await acquire_lease(h.app.state.db, h.settings, user)
    await release_lease(h.app.state.db, lease)


async def test_database_privileges_and_safe_logs(h, caplog):
    _, client, headers = await h.identity()
    assert (await h.prediction(client, headers)).status_code == 200
    url = h.settings.database_url
    engine = create_engine(url)
    for table in ("audit_events", "model_releases", "categories"):
        with pytest.raises(DBAPIError), engine.begin() as db:
            db.execute(text(f"DELETE FROM {table}"))
    engine.dispose()
    for secret in (h.settings.session_secret, h.settings.client_secret, client.cookies.get(h.settings.cookie_name), "isolated-access-token"):
        assert secret not in caplog.text


async def test_production_fail_closed(h):
    with pytest.raises(ValueError): Settings()
    with pytest.raises(ValueError): replace(h.settings, mode="production")
    production = replace(h.settings, mode="production", origin="https://portal.example.invalid", issuer="https://idp.example.invalid/realm")
    assert production.secure_cookie and production.cookie_name.startswith("__Host-")
    with pytest.raises(ValueError): replace(h.settings, mode="auth-disabled")
