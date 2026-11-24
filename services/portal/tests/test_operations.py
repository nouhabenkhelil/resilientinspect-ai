"""Operational fixtures are not scientific predictions or live failure evidence."""
import json
import logging
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import text
from portal.operations import snapshot
from portal.telemetry import HTTPMetrics, JsonFormatter
from portal.security import Database
from sqlalchemy.exc import DBAPIError


@pytest.mark.asyncio
@pytest.mark.parametrize('role,status', [('admin',200),('ai_engineer',200),('operator',403),('auditor',403)])
async def test_operations_permissions_and_measured_sql(h, role, status):
    _, client, _ = await h.identity(role)
    response = await client.get('/api/operations')
    assert response.status_code == status
    assert (await client.get('/api/operations/events')).status_code == status
    if status == 200:
        data = response.json()
        assert data['database_up'] and data['database_ms'] > 0
        assert data['queue']['pending'] == 0
        assert data['queue']['mean_inference_ms'] is None
        assert data['models'] == {'pytorch':15,'onnxruntime':14}
        assert data['storage']['free_bytes'] > 0


@pytest.mark.asyncio
async def test_metrics_fail_closed_and_no_uuid_labels(h, tmp_path, monkeypatch):
    for path in ['/operations','/operations/events']:
        assert (await h.client.get('/api'+path)).status_code == 401
    secret = 'metric-token-' + 'a'*48
    key = tmp_path/'token'; key.write_text(secret)
    monkeypatch.setenv('METRICS_TOKEN_FILE', str(key))
    assert (await h.client.get('/api/metrics')).status_code == 401
    assert (await h.client.get('/api/metrics', headers={'Authorization':'Bearer wrong'})).status_code == 401
    random = str(uuid4())
    await h.client.get('/api/batches/'+random)
    response = await h.client.get('/api/metrics', headers={'Authorization':'Bearer '+secret})
    assert response.status_code == 200
    assert '/batches/{identity}' in response.text
    assert random not in response.text and secret not in response.text


def test_json_formatter_drops_credentials_queries_and_exception_text():
    record = logging.LogRecord('httpx', logging.ERROR, '', 0, 'GET /callback?code=secret password=%s', ('password',), None)
    record.event = 'http.completed'; record.request_id = str(uuid4())
    record.authorization = 'Bearer token'; record.cookie = 'session'; record.image = 'private'
    data = json.loads(JsonFormatter().format(record))
    assert data['event'] == 'http.completed' and data['request_id'] == record.request_id
    assert all(word not in json.dumps(data) for word in ('password','secret','Bearer','session','private'))


@pytest.mark.asyncio
async def test_observer_sql_timeout_and_fresh_connection_recovery(h):
    db=Database(h.settings,observational=True)
    try:
        with pytest.raises(DBAPIError):
            async with db.sessions() as session: await session.execute(text('SELECT pg_sleep(3)'))
        async with db.sessions() as session: assert (await session.execute(text('SELECT 1'))).scalar_one()==1
    finally: await db.engine.dispose()


def test_http_histograms_use_route_templates_and_bounded_window():
    metrics = HTTPMetrics()
    scope = {'route':SimpleNamespace(path='/batches/{batch_id}'), 'method':'GET'}
    metrics.observe(scope,200,.02); metrics.observe(scope,503,.08)
    data=metrics.summary()
    assert data['requests']==2 and data['errors_5xx']==1
    assert data['mean_ms']==50 and data['p95_ms']==80
    assert 'route="/batches/{batch_id}"' in metrics.render().decode()
