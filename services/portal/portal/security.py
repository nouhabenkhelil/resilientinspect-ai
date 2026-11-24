"""Opaque sessions, resource scopes and transactional PostgreSQL limits."""
import hashlib
import hmac
import logging
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .models import AuditEvent, Inspection, InspectionGrant, RateBucket, Session, User, WorkLease, utcnow

logger = logging.getLogger("portal.security")
PERMISSIONS = {
    "admin": {"inspect", "readiness", "admin", "audit"},
    "ai_engineer": {"inspect", "readiness"},
    "operator": {"inspect"},
    "auditor": {"audit"},
}


class PublicError(Exception):
    def __init__(self, status, code, message="La requête ne peut pas être traitée."):
        self.status, self.code, self.message = status, code, message


class Database:
    def __init__(self, settings):
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=8, max_overflow=2, echo=False)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)


def digest(settings, value):
    return hmac.new(settings.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def csrf(settings, cookie):
    return digest(settings, "csrf:" + cookie)


def scope_for(user):
    if user.role == "admin":
        return True
    return or_(Inspection.owner_id == user.id, Inspection.id.in_(select(InspectionGrant.inspection_id).where(InspectionGrant.user_id == user.id)))


async def audit(db, request, action, outcome, actor=None, resource=None):
    async with db.sessions() as session:
        session.add(AuditEvent(actor_id=actor.id if actor else None, resource_id=resource,
                               action=action, outcome=outcome, request_id=request.state.request_id))
        await session.commit()
    logger.info("action=%s outcome=%s request_id=%s actor=%s resource=%s", action, outcome,
                request.state.request_id, actor.id if actor else "anonymous", resource or "none")


async def principal(request):
    settings, db = request.app.state.settings, request.app.state.db
    cookie = request.cookies.get(settings.cookie_name, "")
    if not (32 <= len(cookie) <= 128):
        raise PublicError(401, "authentication_required", "Connexion requise.")
    async with db.sessions() as session:
        saved = await session.get(Session, digest(settings, cookie))
        user = await session.get(User, saved.user_id) if saved else None
        now = utcnow()
        if not saved or saved.revoked_at or not user or not user.enabled or user.role not in PERMISSIONS:
            request.state.clear_session = True
            raise PublicError(401, "session_invalid", "Session expirée ou révoquée.")
        if saved.expires_at <= now or saved.last_seen_at + timedelta(seconds=settings.idle_seconds) <= now:
            saved.revoked_at = now
            await session.commit()
            request.state.clear_session = True
            await audit(db, request, "session.expired", "denied", user)
            raise PublicError(401, "session_expired", "Votre session a expiré. Reconnectez-vous.")
        saved.last_seen_at = now
        await session.commit()
    request.state.user = user
    request.state.session_hash = saved.token_hash
    return user


def permission(user, name):
    if name not in PERMISSIONS.get(user.role, set()):
        raise PublicError(403, "permission_denied", "Cette action n’est pas autorisée pour votre rôle.")


def protect_write(request):
    settings = request.app.state.settings
    cookie = request.cookies.get(settings.cookie_name, "")
    token = request.headers.get("x-csrf-token", "")
    if request.headers.get("origin") != settings.origin or not token or not hmac.compare_digest(token, csrf(settings, cookie)):
        raise PublicError(403, "csrf_rejected", "La protection de session a refusé cette opération.")


async def rate_limit(db, key, seconds, limit):
    now = utcnow()
    window = int(now.timestamp()) // seconds * seconds
    async with db.sessions() as session:
        statement = insert(RateBucket).values(key=key, window=window, count=1, expires_at=now + timedelta(seconds=seconds * 2))
        statement = statement.on_conflict_do_update(index_elements=[RateBucket.key, RateBucket.window],
                     set_={"count": RateBucket.count + 1}, where=RateBucket.count < limit).returning(RateBucket.count)
        count = (await session.execute(statement)).scalar_one_or_none()
        await session.execute(delete(RateBucket).where(RateBucket.expires_at < now))
        await session.commit()
    if count is None:
        raise PublicError(429, "rate_limited", "Quota temporaire atteint. Réessayez plus tard.")


async def acquire_lease(db, settings, user):
    now = utcnow()
    async with db.sessions() as session:
        # Serializes only the short capacity transaction, never the actual inference.
        await session.execute(text("SELECT pg_advisory_xact_lock(1865432191)"))
        stale = select(WorkLease.inspection_id).where(WorkLease.expires_at <= now, WorkLease.inspection_id.is_not(None))
        await session.execute(update(Inspection).where(Inspection.id.in_(stale), Inspection.status == "processing")
                              .values(status="failed", error_code="worker_interrupted", updated_at=now))
        await session.execute(delete(WorkLease).where(WorkLease.expires_at <= now))
        global_count = (await session.execute(select(func.count()).select_from(WorkLease))).scalar_one()
        personal = (await session.execute(select(func.count()).select_from(WorkLease).where(WorkLease.user_id == user.id))).scalar_one()
        if global_count >= settings.max_inflight or personal:
            raise PublicError(429, "capacity_limited", "Un traitement est déjà en cours. Réessayez plus tard.")
        lease = WorkLease(id=uuid4(), user_id=user.id, expires_at=now + timedelta(seconds=settings.inference_timeout + 20))
        session.add(lease)
        await session.commit()
        return lease.id


async def release_lease(db, lease):
    async with db.sessions() as session:
        await session.execute(delete(WorkLease).where(WorkLease.id == lease))
        await session.commit()


async def inspection_for(db, user, identity: UUID):
    async with db.sessions() as session:
        row = (await session.execute(select(Inspection).where(Inspection.id == identity, scope_for(user)))).scalar_one_or_none()
    if row is None:
        raise PublicError(404, "inspection_not_found", "Inspection absente ou inaccessible.")
    return row
