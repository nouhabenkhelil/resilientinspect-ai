"""Operational snapshots: measured values only; missing probes remain null."""
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import time
from fastapi import FastAPI, Request
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import text
from starlette.responses import JSONResponse, Response
import httpx2 as httpx
from .security import Database, permission, principal
from .batch_config import WorkerConfig
from .telemetry import configure_logging, service_authorized


async def snapshot(db, client, storage_root):
    result = {'measured_at': datetime.now(timezone.utc).isoformat(), 'database_up': False, 'database_ms': None,
              'science_up': False, 'models': None, 'gateway_up': False, 'idp_up': False, 'worker_up': None, 'worker_age_seconds': None,
              'worker_starts': None, 'worker_failures': None, 'queue': None, 'storage': None}
    start = time.perf_counter()
    try:
        async with asyncio.timeout(3):
            async with db.sessions() as session:
                await session.execute(text('SELECT 1'))
                result['database_ms'] = (time.perf_counter() - start) * 1000
                result['database_up'] = True
                row = (await session.execute(text("""SELECT
                    count(*) FILTER (WHERE status IN ('queued','retrying')) AS pending,
                    count(*) FILTER (WHERE status='running') AS running,
                    count(*) FILTER (WHERE status='failed') AS failed,
                    count(*) FILTER (WHERE status='failed' AND finished_at>now()-interval '15 minutes') AS failed_recent,
                    coalesce(sum(greatest(attempts-1,0)),0) AS retries,
                    avg(inference_time_ms) FILTER (WHERE status='completed') AS mean_inference_ms,
                    extract(epoch FROM now()-min(not_before) FILTER (WHERE status IN ('queued','retrying'))) AS oldest_pending_seconds
                    FROM batch_items"""))).mappings().one()
                result['queue'] = {k: float(v) if v is not None else None for k, v in row.items()}
                pulse = (await session.execute(text("SELECT extract(epoch FROM now()-max(updated_at) FILTER (WHERE status='ready')) AS age, coalesce(sum(starts),0) AS starts, coalesce(sum(failures),0) AS failures FROM service_heartbeats WHERE service='worker'"))).mappings().one()
                result.update(worker_age_seconds=float(pulse['age']) if pulse['age'] is not None else None,
                    worker_up=pulse['age'] is not None and float(pulse['age']) < 20, worker_starts=int(pulse['starts']), worker_failures=int(pulse['failures']))
    except Exception: pass
    async def probe(path, key):
        try:
            async with asyncio.timeout(3):
                response = await client.get(path)
                result[key] = response.status_code == 200
                if key == 'science_up' and result[key]:
                    data = response.json()['ready_models_by_engine']
                    result['models'] = {engine: int(data[engine]) for engine in ('pytorch', 'onnxruntime')}
        except Exception: pass
    await asyncio.gather(probe(os.getenv('SCIENTIFIC_URL', 'http://science:8000') + '/health', 'science_up'),
                         probe(os.getenv('GATEWAY_URL', 'http://portal:8000') + '/health', 'gateway_up'),
                         probe(os.getenv('OIDC_INTERNAL_URL', 'http://idp:8080/realms/resilientinspect') + '/.well-known/openid-configuration', 'idp_up'))
    try:
        disk = shutil.disk_usage(storage_root)
        result['storage'] = {'free_bytes': disk.free, 'total_bytes': disk.total}
    except OSError: pass
    return result


def render_snapshot(data):
    registry = CollectorRegistry()
    def gauge(name, help, value):
        if value is not None: Gauge(name, help, registry=registry).set(float(value))
    for service in ('database', 'science', 'gateway', 'worker', 'idp'):
        gauge('ri_' + service + '_up', 'Measured service availability', data[service + '_up'])
    gauge('ri_database_probe_seconds', 'Successful PostgreSQL SELECT 1 duration', data['database_ms'] / 1000 if data['database_ms'] is not None else None)
    for key in ('worker_age_seconds', 'worker_starts', 'worker_failures'):
        gauge('ri_' + key, 'Durable worker heartbeat observation', data[key])
    if data['queue']:
        for key, value in data['queue'].items(): gauge('ri_batch_' + key, 'Measured batch SQL aggregate', value)
    if data['models']:
        model_gauge = Gauge('ri_models_available', 'Admitted scientific models', ['engine'], registry=registry)
        for engine, count in data['models'].items(): model_gauge.labels(engine).set(count)
    if data['storage']:
        for key, value in data['storage'].items(): gauge('ri_storage_' + key, 'Docker private-volume filesystem bytes', value)
    return generate_latest(registry)


def register_operations(app):
    @app.get('/metrics')
    async def metrics(request: Request):
        if not service_authorized(request): return JSONResponse({'code': 'metrics_authentication_required'}, status_code=401)
        return Response(app.state.http_metrics.render(), media_type='text/plain; version=0.0.4')

    @app.get('/operations')
    async def operations(request: Request):
        user = await principal(request); permission(user, 'readiness')
        data = await snapshot(app.state.db, app.state.upstream, app.state.batch_config.storage_root)
        data['http'] = app.state.http_metrics.summary()
        return data

    @app.get('/operations/events')
    async def events(request: Request):
        user = await principal(request); permission(user, 'readiness')
        async with app.state.db.sessions() as session:
            rows = (await session.execute(text("SELECT kind,error_code,created_at FROM batch_events WHERE error_code IS NOT NULL OR kind IN ('batch.failed','item.recovered') ORDER BY created_at DESC LIMIT 30"))).mappings().all()
        return {'items': [{'kind': r['kind'], 'error_code': r['error_code'], 'at': r['created_at'].isoformat()} for r in rows]}


def observer_app():
    configure_logging('observer')
    url = Path(os.environ['OBSERVER_DATABASE_URL_FILE']).read_text().strip()
    db = Database(WorkerConfig(database_url=url),observational=True)
    client = httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose(); await db.engine.dispose()
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    @app.get('/health')
    async def health(): return {'status': 'ok'}
    @app.get('/metrics')
    async def metrics(request: Request):
        if not service_authorized(request): return JSONResponse({'code': 'metrics_authentication_required'}, status_code=401)
        return Response(render_snapshot(await snapshot(db, client, Path('/private/images'))), media_type='text/plain; version=0.0.4')
    return app
