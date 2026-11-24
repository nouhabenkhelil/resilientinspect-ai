"""Read-only batch runtime/provenance/log audit. Never prints environments or raw logs."""
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen
import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'deployment/industrial/local'
DC = ['docker', 'compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml']


def run(arguments, content=None):
    result = subprocess.run(arguments, cwd=ROOT, input=content, capture_output=True, check=True)
    return result.stdout.decode('utf-8', errors='replace')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline_dir = LOCAL / 'sprint2-baseline'
    baseline = json.loads((baseline_dir / 'index.json').read_text())
    preserved = []
    for entry in baseline['files']:
        if entry['path'] == 'deployment/industrial/compose.yml': continue
        assert sha(ROOT / entry['path']) == entry['sha256'], 'Pre-existing file changed'
        preserved.append(entry['path'])
    before = yaml.safe_load((baseline_dir / 'deployment/industrial/compose.yml').read_text())
    final = yaml.safe_load((ROOT / 'deployment/industrial/compose.yml').read_text())
    for service in ('postgres', 'idp', 'science', 'migrate', 'tests', 'web'):
        assert before['services'][service] == final['services'][service], 'Unexpected pre-existing Compose service change'
    assert (ROOT / 'deployment/industrial/compose.yml').read_bytes().startswith(b'\n')
    assert final['services']['tests']['environment']['PORTAL_DB_PASSWORD'] is None
    private_values = []
    for line in (LOCAL / '.env').read_text().splitlines():
        key, _, value = line.partition('=')
        if ('SECRET' in key or 'PASSWORD' in key) and len(value) >= 20: private_values.append(value)
    accounts = json.loads((LOCAL / 'accounts.json').read_text())
    private_values += [entry['password'] for entry in accounts['accounts'].values()]
    logs = run(DC + ['logs', '--no-color', '--no-log-prefix'])
    assert not any(value in logs for value in private_values), 'Sensitive configured value in logs (redacted)'
    import re
    assert not re.search(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', logs), 'JWT-like value in logs (redacted)'
    services = []
    for service in ('postgres', 'science', 'portal', 'worker', 'web', 'idp'):
        identity = run(DC + ['ps', '-q', service]).strip()
        details = json.loads(run(['docker', 'inspect', identity]))[0]
        ports = [f"{v['HostIp']}:{v['HostPort']}" for values in (details['HostConfig'].get('PortBindings') or {}).values() for v in values or []]
        assert details['State']['Running']
        if service in ('postgres', 'science', 'portal', 'worker'): assert not ports
        if service in ('web', 'idp'): assert all(p.startswith('127.0.0.1:') for p in ports)
        mounts = details['Mounts']
        if service == 'science': assert all(not m['RW'] for m in mounts if m['Type'] == 'bind')
        if service in ('portal', 'worker'):
            assert any(m.get('Name') == 'resilientinspect-industrial_batch-images' and m['Destination'] == '/private' for m in mounts)
        if service == 'web': assert not any(m.get('Name') == 'resilientinspect-industrial_batch-images' for m in mounts)
        if service == 'worker':
            names = {entry.partition('=')[0] for entry in details['Config']['Env']}
            assert not names & {'OIDC_CLIENT_SECRET', 'PORTAL_SESSION_SECRET', 'MIGRATION_DATABASE_URL'}
        services.append({'service': service, 'status': details['State']['Status'], 'health': details['State'].get('Health', {}).get('Status'),
                         'ports': ports, 'image_id': details['Image'], 'read_only_root': details['HostConfig']['ReadonlyRootfs']})
    code = "import os,json,importlib.util; from pathlib import Path; p=Path('/private/images'); print(json.dumps({'torch_installed':importlib.util.find_spec('torch') is not None,'directory_mode':oct(p.stat().st_mode & 511),'directory_uid':p.stat().st_uid,'files':len(list(p.iterdir())),'private_file_modes':all((x.stat().st_mode & 511)==384 for x in p.iterdir())}))"
    storage = json.loads(run(DC + ['exec', '-T', 'worker', 'python', '-c', code]))
    assert not storage['torch_installed'] and storage['directory_mode'] == '0o700' and storage['directory_uid'] == 10002 and storage['private_file_modes']
    sql = "SELECT jsonb_build_object('revision',(SELECT version_num FROM alembic_version),'legacy_inspections',(SELECT count(*) FROM inspections),'batches',(SELECT count(*) FROM inspection_batches),'completed_items',(SELECT count(*) FROM batch_items WHERE status='completed'),'cancelled_items',(SELECT count(*) FROM batch_items WHERE status='cancelled'),'recovered_events',(SELECT count(*) FROM batch_events WHERE kind='item.recovered'),'attempts',(SELECT sum(attempts) FROM batch_items));"
    database = json.loads(run(DC + ['exec', '-T', 'postgres', 'psql', '-U', 'ri_migrator', '-d', 'portal', '-qAtc', sql]))
    assert database['revision'] == '0f2e340aabb2' and database['legacy_inspections'] == 11
    assert database['completed_items'] >= 50 and database['cancelled_items'] >= 10 and database['recovered_events'] >= 1
    privileges = run(DC + ['exec', '-T', 'postgres', 'psql', '-U', 'ri_migrator', '-d', 'portal', '-qAtc',
        "SELECT has_table_privilege('ri_app','batch_events','UPDATE') OR has_table_privilege('ri_app','batch_events','DELETE');"]).strip()
    assert privileges == 'f'
    database['batch_events_append_only_for_runtime_role'] = True
    with urlopen('http://localhost:8001/health') as response: models = json.load(response)['ready_models_by_engine']
    assert models == {'pytorch': 15, 'onnxruntime': 14}
    for port in (18080, 18180):
        with urlopen(f'http://localhost:{port}') as response: assert response.status == 200
    code_paths = list((ROOT / 'services/portal/portal').glob('*.py')) + list((ROOT / 'frontend/src/portal').glob('*'))
    report = {'services': services, 'storage': storage, 'database': database, 'models': models,
              'coexistence_http': {'v2': 200, 'v3': 200}, 'configured_secret_log_matches': 0, 'jwt_log_matches': 0,
              'preexisting_files_preserved': preserved, 'preexisting_compose_changes_preserved': True,
              'code_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in code_paths if p.is_file()}}
    (LOCAL / 'batch-runtime-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'code_sha256'}, indent=2))


if __name__ == '__main__': main()
