"""Isolated PostgreSQL/security/queue fixtures, never claimed as real inference."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import hashlib
import os
from uuid import UUID, uuid4
import httpx2 as httpx
import pytest
from sqlalchemy import func, select, update
from starlette.applications import Starlette
from starlette.routing import Mount
from portal.app import create_app
from portal.batch_models import BatchEvent, BatchItem, InspectionBatch
from portal.batch_queue import claim, finalize
from portal.batch_retention import purge
from portal.batch_storage import PrivateStorage, clean_filename
from portal.batch_worker import process
from portal.models import Inspection, User, WorkLease, utcnow
from portal.security import PublicError, release_lease

pytestmark = pytest.mark.asyncio


async def upload(h, client, headers, count=2, filename='fixture.png', key=None, content=None):
    return await client.post('/api/batches', headers={**headers, 'Idempotency-Key': key or str(uuid4())},
        data={'model': 'B0', 'category': 'bottle', 'engine': 'pytorch'},
        files=[('files', (filename, h.png if content is None else content, 'image/png')) for _ in range(count)])


async def complete(h):
    job = await claim(h.app.state.db, h.settings, h.batch_config)
    assert job is not None
    await process(h.app.state.db, h.app.state.upstream, h.settings, h.batch_config, job)
    return job


async def ready_again(h):
    async with h.app.state.db.sessions() as db:
        await db.execute(update(BatchItem).where(BatchItem.status == 'retrying').values(not_before=utcnow() - timedelta(seconds=1)))
        await db.commit()


async def test_create_private_idempotent_and_complete(h):
    _, client, headers = await h.identity()
    key = str(uuid4())
    response = await upload(h, client, headers, key=key)
    assert response.status_code == 202, response.text
    batch = response.json()
    assert batch['processed'] == 0 and batch['total'] == 2
    assert (await upload(h, client, headers, key=key)).json()['id'] == batch['id']
    async with h.app.state.db.sessions() as db:
        assert (await db.execute(select(func.count()).select_from(InspectionBatch))).scalar_one() == 1
        items = (await db.execute(select(BatchItem))).scalars().all()
        for item in items:
            path = PrivateStorage(h.batch_config).path(item.file_ref)
            assert path.name != item.filename and len(path.name) == 32
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item.file_sha256
    await complete(h)
    assert (await client.get('/api/batches/' + batch['id'] + '/progress')).json()['processed'] == 1
    await complete(h)
    result = (await client.get('/api/batches/' + batch['id'])).json()
    assert result['status'] == 'completed' and result['normal_count'] == result['processed'] == 2
    rows = (await client.get('/api/batches/' + batch['id'] + '/items')).json()['items']
    assert all(r['version'] == 'a' * 64 and r['anomaly_score'] == 0.1 for r in rows)
    assert (await client.get(f"/api/batches/{batch['id']}/items/{rows[0]['id']}/image")).content == h.png


@pytest.mark.parametrize('role,expected', [('operator', 202), ('ai_engineer', 202), ('admin', 202), ('auditor', 403)])
async def test_batch_role_create(h, role, expected):
    _, client, headers = await h.identity(role)
    assert (await upload(h, client, headers)).status_code == expected


async def test_anonymous_csrf_and_idor(h):
    assert (await upload(h, h.client, {})).status_code == 401
    _, owner, headers = await h.identity()
    _, other, other_headers = await h.identity()
    _, reader, reader_headers = await h.identity('auditor')
    _, admin, _ = await h.identity('admin')
    assert (await upload(h, owner, {})).status_code == 403
    response = await upload(h, owner, headers)
    identity = response.json()['id']
    item = (await owner.get(f'/api/batches/{identity}/items')).json()['items'][0]
    for route in ['', '/progress', '/items', '/errors', '/events', '/export.csv', f"/items/{item['id']}/image"]:
        assert (await other.get(f'/api/batches/{identity}' + route)).status_code == 404
        assert (await reader.get(f'/api/batches/{identity}' + route)).status_code == 404
        assert (await h.client.get(f'/api/batches/{identity}' + route)).status_code == 401
    assert (await other.get('/api/batches')).json()['total'] == 0
    assert (await other.post(f'/api/batches/{identity}/cancel', headers=other_headers)).status_code == 404
    assert (await reader.post(f'/api/batches/{identity}/cancel', headers=reader_headers)).status_code == 403
    assert (await admin.get(f'/api/batches/{identity}')).status_code == 200


@pytest.mark.parametrize('name,content,status', [('payload.zip', b'zip', 415), ('fake.jpg', None, 415), ('bad.png', b'bad', 400), ('empty.png', b'', 400)])
async def test_invalid_upload_atomic_cleanup(h, name, content, status):
    _, client, headers = await h.identity()
    response = await upload(h, client, headers, filename=name, content=content)
    assert response.status_code == status
    assert (await client.get('/api/batches')).json()['total'] == 0
    assert not list(h.batch_config.storage_root.iterdir())


async def test_path_sanitization_and_csv_formula(h):
    _, client, headers = await h.identity()
    response = await upload(h, client, headers, filename='../../=SUM(1).png')
    identity = response.json()['id']
    rows = (await client.get(f'/api/batches/{identity}/items')).json()['items']
    assert rows[0]['filename'] == '=SUM(1).png'
    csv = await client.get(f'/api/batches/{identity}/export.csv')
    assert csv.status_code == 200 and "'=SUM(1).png" in csv.text and '../../' not in csv.text
    assert clean_filename('C:\\fakepath\\photo.png') == 'photo.png'
    assert len(list(h.batch_config.storage_root.iterdir())) == 2
    with pytest.raises(ValueError): PrivateStorage(h.batch_config).path('../../escape')


async def test_upload_count_file_and_body_limits(h):
    _, client, headers = await h.identity()
    assert (await upload(h, client, headers, count=51)).status_code == 400
    assert (await upload(h, client, headers, count=1, content=b'x' * (10 * 1024 * 1024 + 1))).status_code == 413
    response = await client.post('/api/batches', headers={**headers, 'Content-Length': str(102 * 1024 * 1024)}, content=b'x')
    assert response.status_code == 413


async def test_total_size_limit_without_large_fixture(h):
    _, client, headers = await h.identity()
    config = replace(h.batch_config, max_file_bytes=128, max_batch_bytes=130)
    app = create_app(h.settings, batch_config=config, oidc_transport=httpx.MockTransport(h.provider.handle), scientific_transport=httpx.MockTransport(h.upstream))
    root = Starlette(routes=[Mount('/api', app=app)])
    isolated = httpx.AsyncClient(transport=httpx.ASGITransport(app=root), base_url=h.settings.origin)
    isolated.cookies.update(client.cookies)
    try:
        assert (await upload(h, isolated, headers)).status_code == 413
        assert not list(config.storage_root.iterdir())
    finally:
        await isolated.aclose(); await app.state.upstream.aclose(); await app.state.db.engine.dispose()


async def test_cancel_idempotence_and_no_new_claim(h):
    _, client, headers = await h.identity()
    identity = (await upload(h, client, headers)).json()['id']
    route = f'/api/batches/{identity}/cancel'
    assert (await client.post(route, headers=headers)).json()['status'] == 'cancelled'
    assert (await client.post(route, headers=headers)).json()['cancelled_count'] == 2
    assert await claim(h.app.state.db, h.settings, h.batch_config) is None


async def test_atomic_claim_and_fenced_finalization(h):
    _, client, headers = await h.identity()
    await upload(h, client, headers)
    jobs = await asyncio.gather(*(claim(h.app.state.db, h.settings, h.batch_config) for _ in range(4)))
    assert len([j for j in jobs if j]) == 1
    batch, item, lease = next(j for j in jobs if j)
    assert not await finalize(h.app.state.db, h.batch_config, batch.id, item.id, uuid4(), error='processing_failed')
    assert await finalize(h.app.state.db, h.batch_config, batch.id, item.id, item.claim_token, error='processing_failed')
    assert not await finalize(h.app.state.db, h.batch_config, batch.id, item.id, item.claim_token, error='processing_failed')
    await release_lease(h.app.state.db, lease)


async def test_retry_bounded_and_csv_filters(h):
    _, client, headers = await h.identity()
    identity = (await upload(h, client, headers, count=1)).json()['id']
    h.upstream_status, h.upstream_code = 503, 'inference_unavailable'
    for _ in range(3):
        await complete(h); await ready_again(h)
    data = (await client.get(f'/api/batches/{identity}')).json()
    assert data['status'] == 'failed' and data['error_count'] == 1
    errors = (await client.get(f'/api/batches/{identity}/errors')).json()
    assert errors['items'][0]['attempts'] == 3 and errors['items'][0]['error']['code'] == 'inference_unavailable'
    assert (await client.get(f'/api/batches/{identity}/items?filter=normal')).json()['total'] == 0
    assert await claim(h.app.state.db, h.settings, h.batch_config) is None


async def test_crashed_reservation_recovers_and_old_token_refused(h):
    _, client, headers = await h.identity()
    await upload(h, client, headers, count=1)
    batch, old, _ = await claim(h.app.state.db, h.settings, h.batch_config)
    async with h.app.state.db.sessions() as db:
        await db.execute(update(BatchItem).where(BatchItem.id == old.id).values(lease_until=utcnow() - timedelta(seconds=1)))
        await db.execute(update(WorkLease).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    assert await claim(h.app.state.db, h.settings, h.batch_config) is None
    await ready_again(h)
    renewed = await claim(h.app.state.db, h.settings, h.batch_config)
    assert renewed[1].attempts == 2 and renewed[1].claim_token != old.claim_token
    assert not await finalize(h.app.state.db, h.batch_config, batch.id, old.id, old.claim_token, error='processing_failed')
    await process(h.app.state.db, h.app.state.upstream, h.settings, h.batch_config, renewed)
    async with h.app.state.db.sessions() as db:
        assert (await db.get(BatchItem, old.id)).status == 'completed'
        assert (await db.execute(select(func.count()).select_from(BatchEvent).where(BatchEvent.kind == 'item.completed'))).scalar_one() == 1


async def test_retention_isolated_and_preserves_sprint1(h):
    user, client, headers = await h.identity()
    identity = UUID((await upload(h, client, headers, count=1)).json()['id'])
    await complete(h)
    async with h.app.state.db.sessions() as db:
        original = Inspection(owner_id=user.id, category='bottle', model='B0', engine='pytorch', gateway_request_id=uuid4())
        db.add(original); await db.commit(); original_id = original.id
    now = utcnow()
    dry = await purge(h.app.state.db, h.batch_config, now=now + timedelta(hours=25))
    assert dry['images'] == 1 and dry['execute'] is False
    assert len(list(h.batch_config.storage_root.iterdir())) == 1
    images = await purge(h.app.state.db, h.batch_config, execute=True, now=now + timedelta(hours=25))
    assert images['images'] == 1 and not list(h.batch_config.storage_root.iterdir())
    assert (await client.get(f'/api/batches/{identity}')).status_code == 200
    results = await purge(h.app.state.db, h.batch_config, execute=True, now=now + timedelta(days=31))
    assert results['batches'] == 1
    async with h.app.state.db.sessions() as db:
        assert await db.get(InspectionBatch, identity) is None
        assert await db.get(Inspection, original_id) is not None
        assert await db.get(User, user.id) is not None


async def test_storage_integrity_error(h):
    _, client, headers = await h.identity()
    identity = (await upload(h, client, headers, count=1)).json()['id']
    path = next(h.batch_config.storage_root.iterdir()); path.write_bytes(b'tampered')
    await complete(h)
    item = (await client.get(f'/api/batches/{identity}/errors')).json()['items'][0]
    assert item['error']['code'] == 'image_integrity_failed'


async def test_busy_owner_does_not_starve_other_owner(h):
    _, first, first_headers = await h.identity()
    _, second, second_headers = await h.identity()
    await upload(h, first, first_headers)
    await upload(h, second, second_headers)
    one = await claim(h.app.state.db, h.settings, h.batch_config)
    two = await claim(h.app.state.db, h.settings, h.batch_config)
    assert one and two and one[0].owner_id != two[0].owner_id
    assert await claim(h.app.state.db, h.settings, h.batch_config) is None
    for job in (one, two):
        await process(h.app.state.db, h.app.state.upstream, h.settings, h.batch_config, job)


async def test_running_cancellation_and_revoked_owner(h):
    user, client, headers = await h.identity()
    identity = (await upload(h, client, headers)).json()['id']
    job = await claim(h.app.state.db, h.settings, h.batch_config)
    response = await client.post(f'/api/batches/{identity}/cancel', headers=headers)
    assert response.json()['status'] == 'cancelling'
    await process(h.app.state.db, h.app.state.upstream, h.settings, h.batch_config, job)
    assert (await client.get(f'/api/batches/{identity}')).json()['cancelled_count'] == 2
    identity = (await upload(h, client, headers)).json()['id']
    async with h.app.state.db.sessions() as db:
        await db.execute(update(User).where(User.id == user.id).values(enabled=False))
        await db.commit()
    assert await claim(h.app.state.db, h.settings, h.batch_config) is None
    async with h.app.state.db.sessions() as db:
        assert (await db.get(InspectionBatch, UUID(identity))).status == 'cancelled'


async def test_result_access_expires_even_without_purge_worker(h):
    _, client, headers = await h.identity()
    identity = UUID((await upload(h, client, headers)).json()['id'])
    async with h.app.state.db.sessions() as db:
        await db.execute(update(InspectionBatch).where(InspectionBatch.id == identity).values(results_expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    for route in ['', '/progress', '/items', '/export.csv']:
        assert (await client.get(f'/api/batches/{identity}{route}')).status_code == 410
    assert (await client.get('/api/batches')).json()['total'] == 0


async def test_orphan_purge_only_old_uuid_files(h):
    storage = PrivateStorage(h.batch_config)
    ref = storage.write(h.png)
    old = (utcnow() - timedelta(hours=25)).timestamp()
    os.utime(storage.path(ref), (old, old))
    unrelated = h.batch_config.storage_root / 'keep.png'
    unrelated.write_bytes(h.png)
    assert (await purge(h.app.state.db, h.batch_config))['orphans'] == 1
    assert storage.path(ref).exists()
    assert (await purge(h.app.state.db, h.batch_config, execute=True))['orphans'] == 1
    assert not storage.path(ref).exists() and unrelated.exists()
