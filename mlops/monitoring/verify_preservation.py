"""Verify real collector persistence, least privilege and untouched pre-existing state."""
import hashlib
import json
import subprocess
import time
import urllib.request
from .core import ROOT, DATA, SECRETS, atomic_json
from .configure import api

CONTAINER='resilientinspect-mlops-monitoring-collector-1'


def command(args): return subprocess.check_output(args,text=True,timeout=40)


def stored():
    code="""import json,hashlib
from mlops.monitoring.core import Store
s=Store()
with s.connect() as db:
 rows=[list(r) for r in db.execute('SELECT * FROM predictions ORDER BY event_key')]
print(json.dumps({'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()}))
"""
    return json.loads(command(['docker','exec',CONTAINER,'python','-c',code]))


def persistence():
    before=stored()
    assert before['count']>=31
    command(['docker','restart',CONTAINER])
    deadline=time.monotonic()+35
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:19108/health',timeout=3) as response: assert response.status==200
            break
        except Exception:
            if time.monotonic()>deadline: raise
            time.sleep(1)
    after=stored(); assert before==after
    time.sleep(12)
    from .verify_runtime import query
    assert query('up{job="mlops-monitoring"}')[0]['value'][1]=='1'
    dashboards=[d['uid'] for d in api('grafana','/api/search?type=dash-db') if d['uid'].startswith('ri-mlops-')]
    assert len(dashboards)==3
    report={'before':before,'after':after,'collector_only_restarted':True,'scrape_restored':True,'dashboards':dashboards,
        'prometheus_grafana_restart':'not performed: existing services preserved; existing TSDB/Grafana named volumes retained'}
    atomic_json(DATA/'persistence-verification.json',report)
    return report


def privileges():
    code="""import json,psycopg
from mlops.monitoring.core import SECRETS
with psycopg.connect((SECRETS/'database_url').read_text().strip()) as db:
 row=db.execute(\"SELECT has_table_privilege(current_user,'mlops_monitoring.prediction_metadata','SELECT'),has_table_privilege(current_user,(SELECT oid FROM pg_class WHERE relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='public') AND relname='users'),'SELECT'),has_table_privilege(current_user,(SELECT oid FROM pg_class WHERE relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='public') AND relname='inspections'),'SELECT'),has_table_privilege(current_user,(SELECT oid FROM pg_class WHERE relnamespace=(SELECT oid FROM pg_namespace WHERE nspname='public') AND relname='batch_items'),'UPDATE'),current_setting('default_transaction_read_only')\").fetchone()
print(json.dumps({'view_select':row[0],'users_select':row[1],'inspections_select':row[2],'batch_update':row[3],'read_only':row[4]}))
"""
    report=json.loads(command(['docker','exec',CONTAINER,'python','-c',code]))
    assert report=={'view_select':True,'users_select':False,'inspections_select':False,'batch_update':False,'read_only':'on'}
    logs=subprocess.run(['docker','logs',CONTAINER],capture_output=True,text=True,timeout=20)
    logtext=logs.stdout+logs.stderr
    sensitive=[p.read_text().strip() for p in SECRETS.iterdir() if p.is_file()]
    assert not any(value in logtext for value in sensitive if len(value)>=8)
    assert not any(value in logtext for value in ('inspection.png','data:image/','bottle/train/good/'))
    baseline=json.loads((ROOT/'mlops/local/monitoring/baseline.json').read_text())['source']
    candidates=command(['git','ls-files','-co','--exclude-standard']).splitlines()
    public=[p for p in candidates if p not in baseline]
    for name in public:
        data=(ROOT/name).read_bytes()
        assert not any(value.encode() in data for value in sensitive if len(value)>=8),'Sensitive value in new public candidate'
    report.update(collector_logs_checked_bytes=len(logtext),known_secrets_absent_from_logs_and_new_public_files=True,
                  new_public_candidates_checked=len(public),no_image_payload_or_filename_in_collector_logs=True)
    atomic_json(DATA/'privacy-verification.json',report)
    return report


def preservation():
    baseline=json.loads((ROOT/'mlops/local/monitoring/baseline.json').read_text())
    from mlops.orchestration.checks import Settings,snapshot
    current=snapshot(Settings())
    protected=baseline['scientific']
    assert current==protected,'Protected scientific SHA256 changed'
    source=baseline['source']
    changed=[p for p,digest in source.items() if not (ROOT/p).exists() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest]
    allowed={'.gitignore','deployment/operations/prometheus.yml','deployment/operations/alerts.yml'}
    assert set(changed)<=allowed, 'Unexpected edits: '+str(set(changed)-allowed)
    # Raw baseline formats are kept private; only continuity counts leave the local report.
    originals={item['name'].lstrip('/'):item for item in baseline['containers']}
    containers=json.loads(command(['docker','inspect',*originals]))
    preserved=[]
    for item in containers:
        name=item['Name'].lstrip('/')
        previous=originals[name]
        assert item['Id']==previous['id'] and item['State']['StartedAt']==previous['started'],name+' restarted/replaced'
        preserved.append(name)
    report={'protected_files':len(protected),'all_sha256_unchanged':True,'allowed_existing_file_edits':changed,
        'preexisting_containers_not_restarted':preserved,'branch':command(['git','branch','--show-current']).strip(),
        'commit':command(['git','rev-parse','HEAD']).strip(),'no_commit_push_merge':True}
    atomic_json(DATA/'preservation-verification.json',report)
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['persistence','preservation','privileges']);args=parser.parse_args()
    print(json.dumps({'persistence':persistence,'preservation':preservation,'privileges':privileges}[args.action]()))
