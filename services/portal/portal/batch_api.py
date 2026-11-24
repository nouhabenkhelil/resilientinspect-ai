"""Authenticated batch routes. Multipart parsing happens only after authorization/CSRF."""
import asyncio
import csv
from datetime import timedelta
import hashlib
import io
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from sqlalchemy import func, select, text
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, Response
from .batch_config import BatchConfig
from .batch_models import BatchEvent, BatchItem, InspectionBatch
from .batch_queue import TERMINAL, event, recount
from .batch_science import CATEGORIES, ENGINES, MODELS, infer, metadata
from .batch_storage import PrivateStorage, clean_filename
from .models import ModelRelease, User, utcnow
from .security import PERMISSIONS, PublicError, acquire_lease, audit, permission, principal, protect_write, rate_limit, release_lease
from .uploads import validate_image


def batch_scope(user):
    return True if user.role == 'admin' else InspectionBatch.owner_id == user.id


async def authorized_batch(session, user, identity, lock=False):
    statement = select(InspectionBatch).where(InspectionBatch.id == identity, batch_scope(user))
    if lock: statement = statement.with_for_update()
    batch = (await session.execute(statement)).scalar_one_or_none()
    if batch is None: raise PublicError(404, 'batch_not_found', 'Lot introuvable dans votre périmètre.')
    if batch.results_expires_at <= utcnow(): raise PublicError(410, 'batch_expired', 'La conservation de ce lot est terminée.')
    return batch


def batch_json(batch):
    return {key: str(value) if isinstance(value, UUID) else value.isoformat() if hasattr(value, 'isoformat') else value
        for key, value in ((name, getattr(batch, name)) for name in ('id', 'owner_id', 'category', 'model', 'engine', 'status',
            'total', 'total_bytes', 'processed', 'normal_count', 'anomaly_count', 'error_count', 'cancelled_count', 'cancel_requested',
            'created_at', 'finished_at', 'images_expires_at', 'results_expires_at', 'images_purged_at'))}


def item_json(item, batch, release=None):
    return {'id': str(item.id), 'position': item.position, 'filename': item.filename, 'file_sha256': item.file_sha256,
            'file_bytes': item.file_bytes, 'status': item.status, 'attempts': item.attempts, 'anomaly_score': item.anomaly_score,
            'threshold': item.threshold, 'decision': item.decision, 'engine': item.engine,
            'inference_time_ms': item.inference_time_ms, 'error': {'code': item.error_code} if item.error_code else None,
            'version': release.checkpoint_sha256 if release else None,
            'calibration_sha256': release.calibration_sha256 if release else None,
            'request_id': str(item.upstream_request_id) if item.upstream_request_id else None,
            'image_available': item.file_deleted_at is None and batch.images_expires_at > utcnow(),
            'finished_at': item.finished_at.isoformat() if item.finished_at else None}


def register_batches(app, config=None):
    config = config or BatchConfig.from_env()
    app.state.batch_config = config
    storage = PrivateStorage(config)
    router = APIRouter()
    upload_gate = asyncio.Semaphore(1)  # Bound multipart temp space and Pillow memory per portal process.
    db, settings, client = app.state.db, app.state.settings, app.state.upstream

    @router.get('/batches/limits')
    async def limits(request: Request):
        await principal(request)
        return {'max_images': config.max_images, 'max_file_bytes': config.max_file_bytes, 'max_batch_bytes': config.max_batch_bytes,
                'max_pixels': config.max_pixels, 'image_retention_hours': config.image_retention_hours,
                'result_retention_days': config.result_retention_days, 'max_active_per_user': config.max_active_per_user,
                'storage': 'ready' if storage.ready() else 'unavailable'}

    @router.post('/batches')
    async def create(request: Request):
        user = await principal(request)
        permission(user, 'inspect')
        protect_write(request)
        try: key = UUID(request.headers.get('Idempotency-Key', ''))
        except ValueError: raise PublicError(422, 'idempotency_key_required', 'Une clé de soumission UUID est requise.') from None
        async with db.sessions() as session:
            previous = (await session.execute(select(InspectionBatch).where(InspectionBatch.owner_id == user.id,
                InspectionBatch.submission_key == key))).scalar_one_or_none()
            if previous:
                if previous.results_expires_at <= utcnow(): raise PublicError(410, 'batch_expired')
                return JSONResponse(batch_json(previous), status_code=200)
        await rate_limit(db, 'batch-create:' + str(user.id), 60, 3)
        refs, persisted, acquired = [], False, False
        try:
            async with asyncio.timeout(60):
                await upload_gate.acquire()
                acquired = True
                async with request.form(max_files=config.max_images, max_fields=3, max_part_size=config.max_file_bytes) as form:
                    if set(form) - {'files', 'model', 'category', 'engine'} or any(len(form.getlist(k)) > 1 for k in ('model', 'category', 'engine')):
                        raise PublicError(422, 'invalid_input')
                    model, category, engine = form.get('model'), form.get('category'), form.get('engine', 'pytorch')
                    files = form.getlist('files')
                    if model not in MODELS or category not in CATEGORIES or engine not in ENGINES or not (1 <= len(files) <= config.max_images):
                        raise PublicError(422, 'invalid_batch', 'Vérifiez les images, le modèle, la catégorie et le moteur.')
                    await metadata(client, model, category, engine)  # No silent fallback for an unavailable engine.
                    async with db.sessions() as session:
                        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 1865432400 + user.id.int % 1000000000})
                        previous = (await session.execute(select(InspectionBatch).where(InspectionBatch.owner_id == user.id,
                            InspectionBatch.submission_key == key))).scalar_one_or_none()
                        if previous:
                            if previous.results_expires_at <= utcnow(): raise PublicError(410, 'batch_expired')
                            return JSONResponse(batch_json(previous), status_code=200)
                        active = (await session.execute(select(func.count()).select_from(InspectionBatch).where(
                            InspectionBatch.owner_id == user.id, InspectionBatch.status.not_in(TERMINAL)))).scalar_one()
                        if active >= config.max_active_per_user: raise PublicError(429, 'batch_capacity', 'Trop de lots sont déjà en attente pour votre compte.')
                        items, total_bytes, batch_id = [], 0, uuid4()
                        for position, file in enumerate(files, 1):
                            if not isinstance(file, UploadFile): raise PublicError(422, 'invalid_upload')
                            filename = clean_filename(file.filename)
                            content = await file.read(config.max_file_bytes + 1)
                            total_bytes += len(content)
                            if total_bytes > config.max_batch_bytes: raise PublicError(413, 'batch_too_large', 'La taille totale du lot dépasse la limite.')
                            mime = await run_in_threadpool(validate_image, content, filename, config)
                            ref = await run_in_threadpool(storage.write, content)
                            refs.append(ref)
                            items.append(BatchItem(id=uuid4(), batch_id=batch_id, position=position, file_ref=ref,
                                filename=filename, file_sha256=hashlib.sha256(content).hexdigest(), file_bytes=len(content), mime=mime))
                        current = await session.get(User, user.id, populate_existing=True)
                        if not current or not current.enabled or 'inspect' not in PERMISSIONS.get(current.role, set()):
                            raise PublicError(403, 'permission_denied')
                        now = utcnow()
                        batch = InspectionBatch(id=batch_id, owner_id=user.id, submission_key=key, category=category, model=model,
                            engine=engine, total=len(items), total_bytes=total_bytes,
                            images_expires_at=now + timedelta(hours=config.image_retention_hours),
                            results_expires_at=now + timedelta(days=config.result_retention_days))
                        session.add(batch)
                        await session.flush()
                        session.add_all(items)
                        event(session, batch, 'batch.created', actor=user.id, request_id=request.state.request_id)
                        await session.commit()
                        persisted = True
                        result = batch_json(batch)
                await audit(db, request, 'batch.created', 'accepted', user)
                return JSONResponse(result, status_code=202)
        except TimeoutError:
            raise PublicError(408, 'upload_timeout', 'Le délai de réception du lot est dépassé.') from None
        finally:
            if acquired: upload_gate.release()
            if refs and not persisted:
                # A commit transport failure is ambiguous: keep files until an orphan sweep if SQL is unavailable.
                try:
                    async with db.sessions() as session:
                        exists = (await session.execute(select(InspectionBatch.id).where(InspectionBatch.owner_id == user.id,
                            InspectionBatch.submission_key == key))).first()
                    if not exists:
                        for ref in refs: await run_in_threadpool(storage.delete, ref)
                except Exception:
                    pass

    @router.get('/batches')
    async def listing(request: Request, limit: int = 20, offset: int = 0):
        user = await principal(request)
        if not (1 <= limit <= 100 and 0 <= offset <= 100000): raise PublicError(422, 'invalid_filter')
        async with db.sessions() as session:
            visible = [batch_scope(user), InspectionBatch.results_expires_at > utcnow()]
            total = (await session.execute(select(func.count()).select_from(InspectionBatch).where(*visible))).scalar_one()
            batches = (await session.execute(select(InspectionBatch).where(*visible).order_by(
                InspectionBatch.created_at.desc(), InspectionBatch.id).offset(offset).limit(limit))).scalars().all()
        return {'items': [batch_json(b) for b in batches], 'total': total, 'limit': limit, 'offset': offset}

    @router.get('/batches/{identity}')
    @router.get('/batches/{identity}/progress')
    async def details(request: Request, identity: UUID):
        user = await principal(request)
        async with db.sessions() as session:
            batch = await authorized_batch(session, user, identity)
            return batch_json(batch)

    @router.get('/batches/{identity}/items')
    async def items(request: Request, identity: UUID, limit: int = 20, offset: int = 0, filter: str = 'all'):
        user = await principal(request)
        if not (1 <= limit <= 100 and 0 <= offset <= 100000) or filter not in {'all', 'normal', 'anomaly', 'error'}:
            raise PublicError(422, 'invalid_filter')
        async with db.sessions() as session:
            batch = await authorized_batch(session, user, identity)
            conditions = [BatchItem.batch_id == batch.id]
            if filter in {'normal', 'anomaly'}: conditions += [BatchItem.status == 'completed', BatchItem.decision == filter]
            elif filter == 'error': conditions += [BatchItem.status.in_(['failed', 'retrying'])]
            total = (await session.execute(select(func.count()).select_from(BatchItem).where(*conditions))).scalar_one()
            rows = (await session.execute(select(BatchItem, ModelRelease).outerjoin(ModelRelease, BatchItem.release_id == ModelRelease.id)
                .where(*conditions).order_by(BatchItem.position).offset(offset).limit(limit))).all()
            return {'items': [item_json(i, batch, r) for i, r in rows], 'total': total, 'limit': limit, 'offset': offset}

    @router.get('/batches/{identity}/errors')
    async def errors(request: Request, identity: UUID, limit: int = 20, offset: int = 0):
        return await items(request, identity, limit, offset, 'error')

    @router.get('/batches/{identity}/events')
    async def events(request: Request, identity: UUID, limit: int = 50, offset: int = 0):
        user = await principal(request)
        if not (1 <= limit <= 100 and 0 <= offset <= 100000): raise PublicError(422, 'invalid_filter')
        async with db.sessions() as session:
            await authorized_batch(session, user, identity)
            rows = (await session.execute(select(BatchEvent).where(BatchEvent.batch_id == identity)
                .order_by(BatchEvent.created_at, BatchEvent.id).offset(offset).limit(limit))).scalars().all()
        return {'items': [{'id': str(r.id), 'kind': r.kind, 'item_id': str(r.item_id) if r.item_id else None,
            'attempt': r.attempt, 'error_code': r.error_code, 'created_at': r.created_at.isoformat()} for r in rows]}

    @router.post('/batches/{identity}/cancel')
    async def cancel(request: Request, identity: UUID):
        user = await principal(request)
        permission(user, 'inspect')
        protect_write(request)
        async with db.sessions() as session:
            batch = await authorized_batch(session, user, identity, lock=True)
            if batch.status not in TERMINAL and not batch.cancel_requested:
                batch.cancel_requested = True
                pending = (await session.execute(select(BatchItem).where(BatchItem.batch_id == identity,
                    BatchItem.status.in_(['queued', 'retrying'])))).scalars().all()
                for item in pending: item.status, item.finished_at = 'cancelled', utcnow()
                event(session, batch, 'batch.cancel_requested', actor=user.id, request_id=request.state.request_id)
                await recount(session, batch)
                await session.commit()
            result = batch_json(batch)
        await audit(db, request, 'batch.cancel_requested', 'accepted', user)
        return result

    @router.get('/batches/{identity}/export.csv')
    async def export(request: Request, identity: UUID):
        user = await principal(request)
        async with db.sessions() as session:
            batch = await authorized_batch(session, user, identity)
            rows = (await session.execute(select(BatchItem, ModelRelease).outerjoin(ModelRelease, BatchItem.release_id == ModelRelease.id)
                .where(BatchItem.batch_id == identity).order_by(BatchItem.position))).all()
            event(session, batch, 'batch.exported', actor=user.id, request_id=request.state.request_id)
            await session.commit()
        output = io.StringIO(newline='')
        writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
        headers = ['item_id', 'filename', 'file_sha256', 'status', 'model', 'category', 'requested_engine', 'engine', 'score', 'threshold',
                   'decision', 'checkpoint_sha256', 'calibration_sha256', 'inference_time_ms', 'attempts', 'error_code']
        writer.writerow(headers)
        for item, release in rows:
            label = "'" + item.filename if item.filename.lstrip().startswith(('=', '+', '-', '@')) else item.filename
            writer.writerow([item.id, label, item.file_sha256, item.status, batch.model, batch.category, batch.engine, item.engine,
                item.anomaly_score, item.threshold, item.decision, release.checkpoint_sha256 if release else '',
                release.calibration_sha256 if release else '', item.inference_time_ms, item.attempts, item.error_code])
        await audit(db, request, 'batch.exported', 'accepted', user)
        return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename="batch-{identity}.csv"'})

    async def private_item(request, identity, item_id, write=False):
        user = await principal(request)
        if write:
            permission(user, 'inspect')
            protect_write(request)
        async with db.sessions() as session:
            batch = await authorized_batch(session, user, identity)
            item = (await session.execute(select(BatchItem).where(BatchItem.id == item_id, BatchItem.batch_id == identity))).scalar_one_or_none()
            if item is None: raise PublicError(404, 'batch_item_not_found')
            if item.file_deleted_at or batch.images_expires_at <= utcnow(): raise PublicError(410, 'image_expired')
        return user, batch, item

    @router.get('/batches/{identity}/items/{item_id}/image')
    async def image(request: Request, identity: UUID, item_id: UUID):
        user, batch, item = await private_item(request, identity, item_id)
        content = await run_in_threadpool(storage.read, item.file_ref, item.file_sha256, config.max_file_bytes)
        async with db.sessions() as session:
            event(session, batch, 'image.read', item=item, actor=user.id, request_id=request.state.request_id)
            await session.commit()
        return Response(content, media_type=item.mime, headers={'Content-Disposition': 'inline; filename="private-inspection.png"' if item.mime == 'image/png' else 'inline; filename="private-inspection.jpg"'})

    @router.post('/batches/{identity}/items/{item_id}/explanation')
    async def explanation(request: Request, identity: UUID, item_id: UUID):
        user, batch, item = await private_item(request, identity, item_id, write=True)
        if item.status != 'completed': raise PublicError(409, 'result_not_ready')
        await rate_limit(db, 'predict-minute:' + str(user.id), 60, settings.prediction_per_minute)
        await rate_limit(db, 'predict-hour:' + str(user.id), 3600, settings.prediction_per_hour)
        lease = await acquire_lease(db, settings, user)
        try:
            async with asyncio.timeout(settings.inference_timeout):
                content = await run_in_threadpool(storage.read, item.file_ref, item.file_sha256, config.max_file_bytes)
                selected = await metadata(client, batch.model, batch.category, batch.engine)
                result = await infer(client, batch, item, content, selected, visualize=True)
                async with db.sessions() as session:
                    release = await session.get(ModelRelease, item.release_id)
                    if (result['anomaly_score'] != item.anomaly_score or result['threshold'] != item.threshold
                            or result['decision'] != item.decision or result['version'] != release.checkpoint_sha256
                            or selected['calibration_sha256'] != release.calibration_sha256):
                        raise PublicError(409, 'explanation_binding_mismatch')
                    event(session, batch, 'image.explained', item=item, actor=user.id, request_id=request.state.request_id)
                    await session.commit()
                return result
        except TimeoutError:
            raise PublicError(504, 'inference_timeout') from None
        finally:
            await release_lease(db, lease)

    app.include_router(router)
