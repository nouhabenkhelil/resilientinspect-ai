"""Isolated PostgreSQL fixtures. Never connect these tests to the serving database."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import io
import os
import secrets
import time
from urllib.parse import parse_qs
from uuid import uuid4

from alembic import command
from alembic.config import Config
import httpx2 as httpx
from joserfc import jwt
from joserfc.jwk import RSAKey
from PIL import Image
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.routing import Mount

from portal.app import create_app
from portal.models import Session, User, utcnow
from portal.security import csrf, digest
from portal.settings import Settings
from portal.batch_config import BatchConfig


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    url = os.environ["TEST_DATABASE_URL"]
    assert make_url(url).database == "portal_tests", "Refusing a non-test database"
    os.environ["MIGRATION_DATABASE_URL"] = url
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
    return url


class Provider:
    def __init__(self):
        self.key = RSAKey.generate_key(2048, parameters={"kid": "isolated-test-key"})
        self.nonce = ""
        self.patch = {}
        self.issuer = "http://localhost:18585/realms/test"
        self.last_form = {}
        self.id_token = ""
        self.bad_signature = False
        self.algorithm = "RS256"

    def handle(self, request):
        prefix = self.issuer
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": prefix, "authorization_endpoint": prefix + "/auth",
                "token_endpoint": prefix + "/token", "jwks_uri": prefix + "/certs", "end_session_endpoint": prefix + "/logout",
                "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]})
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        assert request.url.path.endswith("/token")
        self.last_form = parse_qs(request.content.decode())
        assert self.last_form["grant_type"] == ["authorization_code"]
        now = int(time.time())
        claims = {"iss": prefix, "sub": "isolated-subject", "aud": "portal-test", "iat": now, "exp": now + 900,
                  "nonce": self.nonce, "name": "Isolated operator", "email": "test@example.invalid", "email_verified": True,
                  "resource_access": {"portal-test": {"roles": ["operator"]}}}
        claims.update(self.patch)
        signing_key = RSAKey.generate_key(2048) if self.bad_signature else self.key
        self.id_token = jwt.encode({"alg": self.algorithm, "kid": "isolated-test-key"}, claims, signing_key)
        return httpx.Response(200, json={"access_token": "isolated-access-token", "token_type": "Bearer", "id_token": self.id_token})


class Harness:
    async def identity(self, role="operator", expired=False, revoked=False, idle=False):
        cookie = secrets.token_urlsafe(48)
        now = utcnow()
        user = User(issuer=self.settings.issuer, subject=str(uuid4()), display_name="Isolated " + role, role=role)
        async with self.app.state.db.sessions() as db:
            db.add(user)
            await db.flush()
            db.add(Session(token_hash=digest(self.settings, cookie), user_id=user.id,
                           expires_at=now + timedelta(seconds=-10 if expired else 600),
                           last_seen_at=now - timedelta(seconds=700 if idle else 0), revoked_at=now if revoked else None))
            await db.commit()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.root), base_url=self.settings.origin)
        client.cookies.set(self.settings.cookie_name, cookie)
        self.clients.append(client)
        return user, client, {"Origin": self.settings.origin, "X-CSRF-Token": csrf(self.settings, cookie)}

    async def upstream(self, request):
        self.requests.append(request)
        assert request.url.host == "science"
        assert not request.headers.get("cookie") and not request.headers.get("authorization")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "ready_models": 15, "ready_models_by_engine": {"pytorch": 15, "onnxruntime": 14}})
        if request.url.path == "/model/metadata":
            return httpx.Response(200, json={"models": [{"model": "B0", "category": "bottle", "checkpoint_sha256": "a" * 64,
                "calibration_sha256": "b" * 64, "threshold": 0.2, "available_engines": ["pytorch", "onnxruntime"]}]})
        if self.pause:
            await asyncio.sleep(self.pause)
        if self.upstream_status != 200:
            return httpx.Response(self.upstream_status, json={"code": self.upstream_code, "message": "private internal detail"})
        return httpx.Response(200, json={"model": "B0", "category": "bottle", "engine": "pytorch", "version": "a" * 64,
             "anomaly_score": 0.1, "threshold": 0.2, "decision": "normal", "inference_time_ms": 2.5, "request_id": str(uuid4())})

    async def prediction(self, client, headers, **changes):
        data = {"model": "B0", "category": "bottle", "engine": "pytorch"}
        data.update(changes)
        return await client.post("/api/predict", headers=headers, data=data,
                                 files={"file": ("isolated.png", self.png, "image/png")})


@pytest_asyncio.fixture
async def h(migrated_database, tmp_path):
    owner = create_engine(migrated_database)
    with owner.begin() as db:
        db.execute(text("TRUNCATE users, login_flows, rate_buckets, model_releases CASCADE"))
    owner.dispose()
    app_url = make_url(migrated_database).set(username="ri_app", password=os.environ["PORTAL_DB_PASSWORD"])
    h = Harness()
    h.settings = Settings(mode="development", origin="http://localhost:18180", issuer="http://localhost:18585/realms/test",
                         oidc_internal="http://idp:8080/realms/test", client_id="portal-test", client_secret=secrets.token_urlsafe(36),
                         session_secret=secrets.token_urlsafe(48), database_url=app_url.render_as_string(hide_password=False))
    h.provider = Provider()
    h.requests, h.clients, h.pause, h.upstream_status = [], [], 0, 200
    h.upstream_code = 'onnx_unavailable'
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(out, format="PNG")
    h.png = out.getvalue()
    h.batch_config = BatchConfig(storage_root=tmp_path, min_free_bytes=0)
    h.app = create_app(h.settings, oidc_transport=httpx.MockTransport(h.provider.handle), scientific_transport=httpx.MockTransport(h.upstream), batch_config=h.batch_config)
    h.root = Starlette(routes=[Mount("/api", app=h.app)])
    h.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=h.root), base_url=h.settings.origin)
    h.clients.append(h.client)
    yield h
    for client in h.clients:
        await client.aclose()
    await h.app.state.upstream.aclose()
    await h.app.state.db.engine.dispose()
