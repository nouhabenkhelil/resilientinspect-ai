"""Industrial BFF. Authentication is mandatory in every deployment mode."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import math
import secrets
import time
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, or_, select, text, update
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse, Response
import httpx2 as httpx

from .models import AuditEvent, Inspection, InspectionGrant, LoginFlow, ModelRelease, Session, User, WorkLease, utcnow
from .oidc import OIDC
from .security import (Database, PERMISSIONS, PublicError, acquire_lease, audit, csrf, digest,
                       inspection_for, permission, principal, protect_write, rate_limit, release_lease, scope_for)
from .settings import Settings
from .uploads import validate_image
from .telemetry import HTTPMetrics, configure_logging

MODELS = {"B0", "A1", "T0", "T1", "T2"}
CATEGORIES = {"bottle", "hazelnut", "leather"}
for name in ("httpx", "httpx2", "httpcore", "httpcore2", "authlib", "sqlalchemy.engine"):
    logging.getLogger(name).setLevel(logging.WARNING)


def public_user(user):
    return {"id": str(user.id), "name": user.display_name, "email": user.email, "role": user.role,
            "enabled": user.enabled, "permissions": sorted(PERMISSIONS[user.role])}


class EnabledChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class BodyLimit:
    def __init__(self, app, max_bytes, batch_bytes):
        self.app, self.max_bytes, self.batch_bytes = app, max_bytes, batch_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        scope.setdefault("state", {})["request_id"] = uuid4()
        try: scope['state']['correlation_id'] = UUID(dict(scope.get('headers', [])).get(b'x-correlation-id', b'').decode())
        except (ValueError, UnicodeError): scope['state']['correlation_id'] = scope['state']['request_id']
        began = time.perf_counter()
        status = 503
        route = scope['path'].removeprefix(scope.get('root_path', ''))
        limit = self.batch_bytes if route == '/batches' and scope['method'] == 'POST' else self.max_bytes
        size = 0
        started = False
        async def bounded():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise PublicError(413, "body_too_large", "Le corps de la requête dépasse la limite.")
            return message
        async def secured(message):
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message['status']
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", str(scope["state"]["request_id"]).encode()))
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer"), (b'x-correlation-id', str(scope['state']['correlation_id']).encode())])
                message["headers"] = headers
            await send(message)
        length = dict(scope.get("headers", [])).get(b"content-length", b"0")
        try:
            oversized = int(length) > limit
        except ValueError:
            oversized = True
        if oversized:
            response = JSONResponse({"code": "body_too_large", "message": "Requête trop volumineuse.",
                                       "request_id": str(scope["state"]["request_id"])}, status_code=413)(scope, receive, secured)
            await response
            scope['app'].state.http_metrics.observe(scope, status, time.perf_counter() - began)
            return
        try:
            await self.app(scope, bounded, secured)
        except Exception:
            # Catch before ServerErrorMiddleware/Uvicorn can log arbitrary exception text.
            logging.getLogger("portal.security").error("action=request.failed request_id=%s", scope["state"]["request_id"])
            if not started:
                await JSONResponse({"code": "service_unavailable", "message": "Le service est temporairement indisponible.",
                                    "request_id": str(scope["state"]["request_id"])}, status_code=503)(scope, receive, secured)
        finally:
            scope['app'].state.http_metrics.observe(scope, status, time.perf_counter() - began)


def create_app(settings=None, *, oidc_transport=None, scientific_transport=None, batch_config=None):
    settings = settings or Settings.from_env()
    configure_logging('portal')
    db = Database(settings)
    oidc = OIDC(settings, oidc_transport)
    upstream = httpx.AsyncClient(base_url=settings.scientific_url, timeout=settings.inference_timeout,
                                follow_redirects=False, trust_env=False, transport=scientific_transport,
                                limits=httpx.Limits(max_connections=settings.max_inflight + 4, max_keepalive_connections=4))

    @asynccontextmanager
    async def lifespan(app):
        async with db.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        yield
        await upstream.aclose()
        await db.engine.dispose()

    app = FastAPI(title="ResilientInspect Industrial Portal", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.db, app.state.oidc, app.state.upstream = settings, db, oidc, upstream
    app.state.http_metrics = HTTPMetrics()
    from .batch_api import register_batches
    register_batches(app, batch_config)
    from .operations import register_operations
    register_operations(app)
    app.add_middleware(BodyLimit, max_bytes=settings.max_file_bytes + 64 * 1024,
                       batch_bytes=app.state.batch_config.max_batch_bytes + 1024 * 1024)

    @app.exception_handler(PublicError)
    async def denied(request, error):
        await audit(db, request, "request." + error.code, "denied", getattr(request.state, "user", None))
        response = JSONResponse({"code": error.code, "message": error.message,
                                 "request_id": str(request.state.request_id)}, status_code=error.status)
        if getattr(request.state, "clear_session", False):
            response.delete_cookie(settings.cookie_name, path="/", secure=settings.secure_cookie, httponly=True, samesite="lax")
        if error.status == 429:
            response.headers["Retry-After"] = "60"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return await denied(request, PublicError(422, "invalid_input", "Vérifiez les paramètres de la requête."))

    @app.exception_handler(HTTPException)
    async def invalid_http(request, error):
        return await denied(request, PublicError(error.status_code, "invalid_request"))

    @app.exception_handler(Exception)
    async def failure(request, error):
        # Never log arbitrary exception messages, provider tokens, SQL parameters or request bodies.
        logging.getLogger("portal.security").error("action=request.failed request_id=%s", request.state.request_id)
        return JSONResponse({"code": "service_unavailable", "message": "Le service est temporairement indisponible.",
                             "request_id": str(request.state.request_id)}, status_code=503)

    async def get_upstream(path, params=None):
        try:
            async with asyncio.timeout(15):
                response = await upstream.get(path, params=params)
            if response.status_code not in {200, 503} or len(response.content) > 2 * 1024 * 1024:
                raise ValueError("Unexpected internal response")
            return response
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise PublicError(503, "inference_unavailable", "Le service d’inférence est indisponible.") from None

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "portal"}

    @app.get("/auth/login")
    async def login(request: Request, return_to: str = "/"):
        if return_to != "/":
            raise PublicError(400, "invalid_redirect", "Destination de retour non autorisée.")
        await rate_limit(db, "login:" + digest(settings, request.client.host), 600, 30)
        state, nonce, verifier, cookie = [secrets.token_urlsafe(48) for _ in range(4)]
        try:
            location = await oidc.authorization(state, nonce, verifier)
        except Exception:
            raise PublicError(503, "oidc_unavailable", "Le fournisseur de connexion est indisponible.") from None
        async with db.sessions() as session:
            await session.execute(delete(LoginFlow).where(LoginFlow.expires_at < utcnow()))
            session.add(LoginFlow(state_hash=digest(settings, state), cookie_hash=digest(settings, cookie), nonce=nonce,
                                  verifier=oidc.cipher.encrypt(verifier.encode()).decode(), expires_at=utcnow() + timedelta(minutes=5)))
            await session.commit()
        response = RedirectResponse(location, status_code=303)
        response.set_cookie("ri_oidc_flow", cookie, max_age=300, httponly=True, secure=settings.secure_cookie,
                            samesite="lax", path="/api/auth")
        await audit(db, request, "login.started", "accepted")
        return response

    @app.get("/auth/callback")
    async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
        cookie = request.cookies.get("ri_oidc_flow", "")
        if any(len(request.query_params.getlist(k)) > 1 for k in ("state", "code", "iss", "error")) or request.query_params.get("iss", settings.issuer) != settings.issuer:
            raise PublicError(401, "invalid_login_state", "Réponse de connexion invalide.")
        if error or not (16 <= len(state) <= 128 and 1 <= len(code) <= 4096 and 32 <= len(cookie) <= 128):
            raise PublicError(401, "login_failed", "La connexion a été refusée. Réessayez.")
        async with db.sessions() as session:
            flow = (await session.execute(select(LoginFlow).where(LoginFlow.state_hash == digest(settings, state)).with_for_update())).scalar_one_or_none()
            if not flow or flow.expires_at <= utcnow() or not hmac.compare_digest(flow.cookie_hash, digest(settings, cookie)):
                raise PublicError(401, "invalid_login_state", "La connexion a expiré ou son état est invalide.")
            nonce, verifier = flow.nonce, oidc.cipher.decrypt(flow.verifier.encode()).decode()
            await session.delete(flow)
            await session.commit()  # Consume once, including unsuccessful provider exchanges.
        try:
            identity = await oidc.identity(code, nonce, verifier)
        except PublicError:
            raise
        except Exception:
            raise PublicError(401, "login_failed", "La réponse du fournisseur de connexion a été refusée.") from None
        now = utcnow()
        raw = secrets.token_urlsafe(48)
        async with db.sessions() as session:
            user = (await session.execute(select(User).where(User.issuer == settings.issuer, User.subject == identity["subject"]))).scalar_one_or_none()
            if user and not user.enabled:
                raise PublicError(403, "account_disabled", "Ce compte est suspendu.")
            if not user:
                user = User(issuer=settings.issuer, subject=identity["subject"], display_name=identity["name"],
                            email=identity["email"], role=identity["role"])
                session.add(user)
                await session.flush()
            else:
                user.display_name, user.email, user.role = identity["name"], identity["email"], identity["role"]
            old_cookie = request.cookies.get(settings.cookie_name, "")
            if old_cookie:
                await session.execute(update(Session).where(Session.token_hash == digest(settings, old_cookie)).values(revoked_at=now))
            session.add(Session(token_hash=digest(settings, raw), user_id=user.id, created_at=now, last_seen_at=now,
                                expires_at=min(now + timedelta(seconds=settings.session_seconds), datetime.fromtimestamp(identity["expires"], timezone.utc))))
            await session.commit()
        response = RedirectResponse(settings.origin + "/", status_code=303)
        response.set_cookie(settings.cookie_name, raw, httponly=True, secure=settings.secure_cookie, samesite="lax",
                            max_age=min(settings.session_seconds, max(0, int(identity["expires"] - time.time()))), path="/")
        response.delete_cookie("ri_oidc_flow", path="/api/auth", httponly=True, secure=settings.secure_cookie, samesite="lax")
        await audit(db, request, "login.completed", "accepted", user)
        return response

    @app.get("/auth/session")
    async def profile(request: Request):
        user = await principal(request)
        return {"user": public_user(user), "csrf_token": csrf(settings, request.cookies[settings.cookie_name])}

    @app.post("/auth/logout")
    async def logout(request: Request):
        user = await principal(request)
        protect_write(request)
        async with db.sessions() as session:
            await session.execute(update(Session).where(Session.token_hash == request.state.session_hash).values(revoked_at=utcnow()))
            await session.commit()
        await audit(db, request, "logout.completed", "accepted", user)
        try:
            logout_url = await oidc.logout_url()
        except Exception:
            logout_url = settings.origin + "/"
        response = JSONResponse({"logout_url": logout_url})
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.secure_cookie, httponly=True, samesite="lax")
        return response

    @app.get("/status")
    async def status(request: Request):
        await principal(request)
        response = await get_upstream("/health")
        data = response.json()
        allowed = {key: data[key] for key in ("status", "version", "device", "ready_models", "expected_models", "ready_models_by_engine", "request_id") if key in data}
        return JSONResponse(allowed, status_code=response.status_code)

    @app.get("/readiness")
    async def readiness(request: Request):
        user = await principal(request)
        permission(user, "readiness")
        async with db.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        response = await get_upstream("/health")
        return JSONResponse({"database": "ready", "authentication": "configured", "inference": response.json()},
                            status_code=response.status_code)

    @app.get("/model/metadata")
    async def metadata(request: Request, model: str | None = None, category: str | None = None):
        await principal(request)
        if (model is not None and model not in MODELS) or (category is not None and category not in CATEGORIES):
            raise PublicError(422, "invalid_input", "Modèle ou catégorie invalide.")
        response = await get_upstream("/model/metadata", {k: v for k, v in {"model": model, "category": category}.items() if v})
        if response.status_code != 200:
            raise PublicError(503, "metadata_unavailable")
        data = response.json()
        for item in data.get("models", []):
            item["training_environment"] = None
            item["serving_environment"] = {"device": "cpu"}
        return data

    async def predict(request, visualize):
        user = await principal(request)
        permission(user, "inspect")
        protect_write(request)
        await rate_limit(db, f"predict-minute:{user.id}", 60, settings.prediction_per_minute)
        await rate_limit(db, f"predict-hour:{user.id}", 3600, settings.prediction_per_hour)
        lease = await acquire_lease(db, settings, user)
        record = None
        started = time.perf_counter()
        try:
            async with asyncio.timeout(settings.inference_timeout):
                async with request.form(max_files=1, max_fields=3, max_part_size=settings.max_file_bytes) as form:
                    if set(form) - {"file", "model", "category", "engine"} or any(len(form.getlist(k)) != 1 for k in form):
                        raise PublicError(422, "invalid_input", "Champs d’inspection invalides.")
                    file, model, category, engine = form.get("file"), form.get("model"), form.get("category"), form.get("engine", "pytorch")
                    if not isinstance(file, UploadFile) or model not in MODELS or category not in CATEGORIES or engine not in {"pytorch", "onnxruntime"}:
                        raise PublicError(422, "invalid_input", "Vérifiez l’image, le modèle, la catégorie et le moteur.")
                    content = await file.read(settings.max_file_bytes + 1)
                    mime = await run_in_threadpool(validate_image, content, file.filename or "", settings)
                record = Inspection(id=uuid4(), owner_id=user.id, model=model, category=category, engine=engine,
                                    gateway_request_id=request.state.request_id,
                                    image_sha256=hashlib.sha256(content).hexdigest() if settings.store_image_hash else None)
                async with db.sessions() as session:
                    session.add(record)
                    await session.execute(update(WorkLease).where(WorkLease.id == lease).values(inspection_id=record.id))
                    await session.commit()
                # Fixed allowlisted destination; original bytes, no cookie/token forwarding.
                response = await upstream.post("/predict/visualize" if visualize else "/predict",
                    data={"model": model, "category": category, "engine": engine},
                    files={"file": ("inspection.png" if mime == "image/png" else "inspection.jpg", content, mime)},
                    headers={"X-Portal-Request-ID": str(request.state.request_id)})
                if response.status_code != 200:
                    try: code = response.json().get("code", "inference_unavailable")
                    except ValueError: code = "inference_unavailable"
                    allowed_codes = {"onnx_unavailable", "model_unavailable", "explanation_divergence", "invalid_image", "image_too_large"}
                    raise PublicError(response.status_code if response.status_code in {400, 409, 413, 415, 422, 503} else 503,
                                      code if code in allowed_codes else "inference_unavailable",
                                      "Ce moteur est indisponible ou l’inspection a été refusée. Aucun repli automatique.")
                if len(response.content) > 6 * 1024 * 1024:
                    raise PublicError(502, "invalid_inference_response")
                result = response.json()
                if (result.get("model") != model or result.get("category") != category or result.get("engine", "pytorch") != engine
                        or not all(type(result.get(k)) in (int, float) and math.isfinite(result[k]) for k in ("anomaly_score", "threshold", "inference_time_ms"))
                        or not (0 <= result["anomaly_score"] <= 1 and 0 <= result["threshold"] <= 1 and result["inference_time_ms"] >= 0)
                        or result.get("decision") != ("anomaly" if result["anomaly_score"] > result["threshold"] else "normal")):
                    raise PublicError(502, "invalid_inference_response")
                upstream_id = UUID(result["request_id"])
                meta_response = await get_upstream("/model/metadata", {"model": model, "category": category})
                selected = meta_response.json().get("models", [])
                if len(selected) != 1 or selected[0]["checkpoint_sha256"] != result["version"] or engine not in selected[0].get("available_engines", ["pytorch"]):
                    raise PublicError(502, "model_binding_mismatch")
                meta = selected[0]
                async with db.sessions() as session:
                    # Serialize release registration only; no load, threshold selection or weight modification.
                    await session.execute(text("SELECT pg_advisory_xact_lock(1865432192)"))
                    release = (await session.execute(select(ModelRelease).where(ModelRelease.family == model, ModelRelease.category == category,
                                                               ModelRelease.checkpoint_sha256 == result["version"]))).scalar_one_or_none()
                    if release is None:
                        release = ModelRelease(family=model, category=category, checkpoint_sha256=result["version"], calibration_sha256=meta["calibration_sha256"])
                        session.add(release)
                        await session.flush()
                    elif release.calibration_sha256 != meta["calibration_sha256"]:
                        raise PublicError(502, "calibration_binding_mismatch")
                    await session.execute(update(Inspection).where(Inspection.id == record.id).values(
                        release_id=release.id, status="completed", anomaly_score=result["anomaly_score"], threshold=result["threshold"],
                        decision=result["decision"], inference_time_ms=result["inference_time_ms"], upstream_request_id=upstream_id,
                        gateway_time_ms=(time.perf_counter() - started) * 1000, updated_at=utcnow()))
                    await session.commit()
                await audit(db, request, "inspection.completed", "accepted", user, record.id)
                return JSONResponse(result, headers={"X-Request-ID": str(upstream_id), "X-Inspection-ID": str(record.id),
                                                     "X-Portal-Request-ID": str(request.state.request_id)})
        except (TimeoutError, httpx.HTTPError):
            raise PublicError(504, "inference_timeout", "Le délai de traitement est dépassé.") from None
        except (ValueError, KeyError, TypeError):
            raise PublicError(502, "invalid_inference_response", "La réponse interne n’a pas pu être validée.") from None
        finally:
            if record:
                async with db.sessions() as session:
                    await session.execute(update(Inspection).where(Inspection.id == record.id, Inspection.status == "processing")
                                          .values(status="failed", error_code="inspection_failed", updated_at=utcnow()))
                    await session.commit()
            await release_lease(db, lease)

    @app.post("/predict")
    async def predict_route(request: Request):
        return await predict(request, False)

    @app.post("/predict/visualize")
    async def visualize_route(request: Request):
        return await predict(request, True)

    def inspection_json(row, release=None):
        return {"id": str(row.id), "owner_id": str(row.owner_id), "model": row.model, "category": row.category,
                "engine": row.engine, "status": row.status, "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(), "anomaly_score": row.anomaly_score, "threshold": row.threshold,
                "decision": row.decision, "inference_time_ms": row.inference_time_ms, "gateway_time_ms": row.gateway_time_ms,
                "request_id": str(row.upstream_request_id or row.gateway_request_id),
                "gateway_request_id": str(row.gateway_request_id), "error_code": row.error_code,
                "version": release.checkpoint_sha256 if release else None,
                "calibration_sha256": release.calibration_sha256 if release else None}

    @app.get("/inspections")
    async def history(request: Request, limit: int = 50, offset: int = 0, model: str | None = None,
                      category: str | None = None, status: str | None = None, order: str = "desc"):
        user = await principal(request)
        if not (1 <= limit <= 100 and 0 <= offset <= 100000 and order in {"asc", "desc"}) or (model and model not in MODELS) or (category and category not in CATEGORIES) or (status and status not in {"processing", "completed", "failed"}):
            raise PublicError(422, "invalid_filter", "Filtres ou pagination invalides.")
        filters = [scope_for(user)]
        for column, value in ((Inspection.model, model), (Inspection.category, category), (Inspection.status, status)):
            if value: filters.append(column == value)
        async with db.sessions() as session:
            total = (await session.execute(select(func.count()).select_from(Inspection).where(*filters))).scalar_one()
            ordering = Inspection.created_at.desc() if order == "desc" else Inspection.created_at.asc()
            rows = (await session.execute(select(Inspection, ModelRelease).outerjoin(ModelRelease, Inspection.release_id == ModelRelease.id)
                                          .where(*filters).order_by(ordering, Inspection.id).offset(offset).limit(limit))).all()
        return {"items": [inspection_json(i, r) for i, r in rows], "total": total, "limit": limit, "offset": offset}

    @app.get("/inspections/{identity}")
    async def details(request: Request, identity: UUID):
        user = await principal(request)
        row = await inspection_for(db, user, identity)
        async with db.sessions() as session:
            release = await session.get(ModelRelease, row.release_id) if row.release_id else None
        await audit(db, request, "inspection.read", "accepted", user, identity)
        return inspection_json(row, release)

    @app.get("/admin/users")
    async def users(request: Request, limit: int = 50, offset: int = 0):
        user = await principal(request)
        permission(user, "admin")
        if not (1 <= limit <= 100 and 0 <= offset <= 100000): raise PublicError(422, "invalid_filter")
        async with db.sessions() as session:
            rows = (await session.execute(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit))).scalars().all()
        return {"items": [public_user(row) for row in rows]}

    @app.post("/admin/users/{identity}/revoke-sessions")
    async def revoke(request: Request, identity: UUID):
        user = await principal(request)
        permission(user, "admin")
        protect_write(request)
        async with db.sessions() as session:
            if not await session.get(User, identity): raise PublicError(404, "user_not_found")
            await session.execute(update(Session).where(Session.user_id == identity, Session.revoked_at.is_(None)).values(revoked_at=utcnow()))
            await session.commit()
        await audit(db, request, "admin.sessions_revoked", "accepted", user)
        return {"status": "revoked"}

    @app.patch("/admin/users/{identity}/enabled")
    async def enabled(request: Request, identity: UUID, change: EnabledChange):
        user = await principal(request)
        permission(user, "admin")
        protect_write(request)
        if identity == user.id and not change.enabled: raise PublicError(409, "self_disable_refused")
        async with db.sessions() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(1865432193)"))
            actor = await session.get(User, user.id)
            if not actor or not actor.enabled or actor.role != "admin":
                raise PublicError(403, "permission_denied")
            target = await session.get(User, identity)
            if target is None: raise PublicError(404, "user_not_found")
            target.enabled = change.enabled
            if not change.enabled:
                await session.execute(update(Session).where(Session.user_id == identity).values(revoked_at=utcnow()))
            await session.commit()
        await audit(db, request, "admin.account_enabled" if change.enabled else "admin.account_disabled", "accepted", user)
        return {"status": "updated"}

    @app.post("/admin/inspections/{identity}/grants/{user_id}")
    async def grant(request: Request, identity: UUID, user_id: UUID):
        user = await principal(request)
        permission(user, "admin")
        protect_write(request)
        await inspection_for(db, user, identity)
        async with db.sessions() as session:
            if not await session.get(User, user_id): raise PublicError(404, "user_not_found")
            exists = await session.get(InspectionGrant, (identity, user_id))
            if not exists: session.add(InspectionGrant(inspection_id=identity, user_id=user_id, granted_by=user.id))
            await session.commit()
        await audit(db, request, "admin.inspection_granted", "accepted", user, identity)
        return {"status": "granted"}

    @app.get("/audit")
    async def events(request: Request, limit: int = 50, offset: int = 0):
        user = await principal(request)
        permission(user, "audit")
        if not (1 <= limit <= 100 and 0 <= offset <= 100000): raise PublicError(422, "invalid_filter")
        async with db.sessions() as session:
            query = select(AuditEvent)
            if user.role != "admin":
                resources = select(Inspection.id).where(scope_for(user))
                query = query.where(or_(AuditEvent.actor_id == user.id, AuditEvent.resource_id.in_(resources)))
            rows = (await session.execute(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).offset(offset).limit(limit))).scalars().all()
        return {"items": [{"id": str(r.id), "actor_id": str(r.actor_id) if r.actor_id else None,
                            "resource_id": str(r.resource_id) if r.resource_id else None, "action": r.action,
                            "outcome": r.outcome, "request_id": str(r.request_id), "created_at": r.created_at.isoformat()} for r in rows]}

    return app
