"""Durable PostgreSQL queue: batch-row locks, SKIP LOCKED and fenced item leases."""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import func, or_, select
from .batch_models import BatchEvent, BatchItem, InspectionBatch
from .batch_science import release_reference
from .models import User, WorkLease, utcnow
from .security import PERMISSIONS, PublicError, acquire_lease

TERMINAL = {'completed', 'completed_with_errors', 'failed', 'cancelled'}
ITEM_TERMINAL = {'completed', 'failed', 'cancelled'}
RETRYABLE = {'inference_unavailable', 'inference_timeout'}


def event(session, batch, kind, *, item=None, actor=None, error=None, request_id=None):
    session.add(BatchEvent(batch_id=batch.id, item_id=item.id if item else None, actor_id=actor,
                          kind=kind, error_code=error, attempt=item.attempts if item else None,
                          request_id=request_id or uuid4()))


async def recount(session, batch):
    await session.flush()
    rows = (await session.execute(select(BatchItem.status, BatchItem.decision, func.count()).where(
        BatchItem.batch_id == batch.id).group_by(BatchItem.status, BatchItem.decision))).all()
    counts = {(state, decision): count for state, decision, count in rows}
    batch.normal_count = counts.get(('completed', 'normal'), 0)
    batch.anomaly_count = counts.get(('completed', 'anomaly'), 0)
    batch.error_count = sum(n for (state, _), n in counts.items() if state == 'failed')
    batch.cancelled_count = sum(n for (state, _), n in counts.items() if state == 'cancelled')
    batch.processed = batch.normal_count + batch.anomaly_count + batch.error_count + batch.cancelled_count
    previous = batch.status
    if batch.processed == batch.total:
        batch.status = ('cancelled' if batch.cancel_requested else 'failed' if batch.error_count == batch.total
                        else 'completed_with_errors' if batch.error_count else 'completed')
        batch.finished_at = batch.finished_at or utcnow()
    elif batch.cancel_requested:
        batch.status = 'cancelling'
    else:
        batch.status = 'running' if batch.processed or any(s == 'running' for s, _ in counts) else 'queued'
    if batch.status in TERMINAL and previous not in TERMINAL:
        event(session, batch, 'batch.' + batch.status)


async def claim(db, settings, config):
    now = utcnow()
    eligible = select(BatchItem.id).where(BatchItem.batch_id == InspectionBatch.id,
        or_((BatchItem.status.in_(['queued', 'retrying'])) & (BatchItem.not_before <= now),
            (BatchItem.status == 'running') & (BatchItem.lease_until <= now))).exists()
    busy_owner = select(WorkLease.id).where(WorkLease.user_id == InspectionBatch.owner_id, WorkLease.expires_at > now).exists()
    async with db.sessions() as session:
        batch = (await session.execute(select(InspectionBatch).where(InspectionBatch.status.not_in(TERMINAL), eligible, ~busy_owner)
            .order_by(InspectionBatch.created_at, InspectionBatch.id).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if batch is None:
            return None
        owner = await session.get(User, batch.owner_id)
        authorized = owner and owner.enabled and 'inspect' in PERMISSIONS.get(owner.role, set())
        expired = (await session.execute(select(BatchItem).where(BatchItem.batch_id == batch.id,
            BatchItem.status == 'running', BatchItem.lease_until <= now).with_for_update())).scalars().all()
        for item in expired:
            item.claim_token, item.lease_until = None, None
            if batch.cancel_requested or not authorized:
                item.status, item.finished_at = 'cancelled', now
            elif item.attempts >= config.max_attempts:
                item.status, item.error_code, item.finished_at = 'failed', 'worker_interrupted', now
            else:
                item.status, item.error_code = 'retrying', 'worker_interrupted'
                item.not_before = now + timedelta(seconds=config.retry_seconds)
            event(session, batch, 'item.recovered', item=item, error='worker_interrupted')
        await session.flush()
        if not authorized or batch.cancel_requested or min(batch.images_expires_at, batch.results_expires_at) <= now:
            pending = (await session.execute(select(BatchItem).where(BatchItem.batch_id == batch.id,
                BatchItem.status.in_(['queued', 'retrying'])))).scalars().all()
            for item in pending:
                item.status, item.finished_at = ('failed' if authorized and not batch.cancel_requested else 'cancelled'), now
                item.error_code = ('results_expired' if batch.results_expires_at <= now else 'image_expired') if item.status == 'failed' else 'authorization_revoked' if not authorized else None
                event(session, batch, 'item.' + item.status, item=item, error=item.error_code)
            if not authorized: batch.cancel_requested = True
            await recount(session, batch)
            await session.commit()
            return None
        item = (await session.execute(select(BatchItem).where(BatchItem.batch_id == batch.id,
            BatchItem.status.in_(['queued', 'retrying']), BatchItem.not_before <= now)
            .order_by(BatchItem.position).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if item is None:
            await recount(session, batch)
            await session.commit()
            return None
        try:
            work_lease = await acquire_lease(db, settings, owner)
        except PublicError as error:
            if error.status != 429: raise
            await recount(session, batch)
            await session.commit()
            return None
        item.status, item.attempts = 'running', item.attempts + 1
        item.claim_token, item.lease_until = uuid4(), now + timedelta(seconds=config.lease_seconds)
        item.started_at = item.started_at or now
        item.error_code = None
        batch.status = 'running'
        event(session, batch, 'item.reserved', item=item)
        await session.commit()
        return batch, item, work_lease


async def finalize(db, config, batch_id, item_id, token, *, result=None, selected=None, error=None):
    async with db.sessions() as session:
        batch = (await session.execute(select(InspectionBatch).where(InspectionBatch.id == batch_id).with_for_update())).scalar_one_or_none()
        if batch is None: return False
        item = (await session.execute(select(BatchItem).where(BatchItem.id == item_id).with_for_update())).scalar_one()
        if item.status != 'running' or item.claim_token != token:
            return False  # A stale worker can never overwrite a newer reservation or terminal result.
        owner = await session.get(User, batch.owner_id)
        authorized = owner and owner.enabled and 'inspect' in PERMISSIONS.get(owner.role, set())
        now = utcnow()
        item.claim_token, item.lease_until = None, None
        if batch.cancel_requested or not authorized:
            item.status, item.finished_at = 'cancelled', now
            if not authorized: batch.cancel_requested = True
        elif result is not None:
            item.release_id = await release_reference(session, batch, selected)
            item.status, item.finished_at = 'completed', now
            item.engine, item.anomaly_score, item.threshold, item.decision = result['engine'], result['anomaly_score'], result['threshold'], result['decision']
            item.inference_time_ms, item.upstream_request_id = result['inference_time_ms'], result['request_id']
            item.error_code = None
        elif error in RETRYABLE and item.attempts < config.max_attempts:
            item.status, item.error_code = 'retrying', error
            item.not_before = now + timedelta(seconds=config.retry_seconds * item.attempts)
        else:
            item.status, item.error_code, item.finished_at = 'failed', error or 'processing_failed', now
        event(session, batch, 'item.' + item.status, item=item, error=item.error_code)
        await recount(session, batch)
        await session.commit()
        return True
