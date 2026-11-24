"""Actual worker/SQL outages and scientific recovery, exclusively in the restored clone."""
import json
from pathlib import Path
import secrets
import time
import sys
import yaml
from backup import ROOT,LOCAL,run
from recovery import wait


def main():
    folder=Path(json.loads((LOCAL/'recovery-current.json').read_text())['folder']).resolve()
    if folder.parent!=(ROOT/'deployment/industrial/local').resolve() or not folder.name.startswith('resilientinspect-recovery-'): raise ValueError('Not an isolated recovery project')
    compose=folder/'compose.yml'; doc=yaml.safe_load(compose.read_text()); dc=['docker','compose','-f',str(compose)]
    def sql(query): return run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',query]).decode().strip()
    private=folder/'observer-secrets'; private.mkdir(exist_ok=True)
    token=(LOCAL/'secrets/metrics_token').read_text().strip(); password=(LOCAL/'secrets/observer_password').read_text().strip()
    (private/'metrics_token').write_text(token)
    (private/'observer_database_url').write_text(f'postgresql+psycopg://ri_observer:{password}@postgres:5432/portal')
    sql("ALTER ROLE ri_observer PASSWORD '"+password+"';")
    doc['services']['worker']['environment']={k:v for k,v in doc['services']['worker']['environment'].items() if k in ('DATABASE_URL','SCIENTIFIC_URL','BATCH_STORAGE_ROOT')}
    doc['services']['worker']['mem_limit']='256m'
    doc['services']['recovery-observer']={'image':'resilientinspect-portal:local','command':['uvicorn','portal.operations:observer_app','--factory','--host','0.0.0.0','--port','8000','--no-access-log'],
      'environment':{'OBSERVER_DATABASE_URL_FILE':'/run/secrets/observer_database_url','METRICS_TOKEN_FILE':'/run/secrets/metrics_token','SCIENTIFIC_URL':'http://science:8000','GATEWAY_URL':'http://recovery-portal:8000'},
      'volumes':[str(private)+':/run/secrets:ro','images:/private:ro'],'networks':['recovery','inference'],'read_only':True,'tmpfs':['/tmp'],'mem_limit':'192m','cap_drop':['ALL']}
    promconfig=folder/'prometheus.yml'
    promconfig.write_text(yaml.safe_dump({'global':{'scrape_interval':'10s','scrape_timeout':'8s','evaluation_interval':'5s'},'rule_files':['/etc/prometheus/alerts.yml'],
      'scrape_configs':[{'job_name':'recovery-observer','authorization':{'type':'Bearer','credentials_file':'/run/secrets/metrics_token'},'static_configs':[{'targets':['recovery-observer:8000']}]}]}))
    doc['services']['recovery-prometheus']={'image':'prom/prometheus:v3.16.0@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06',
      'command':['--config.file=/etc/prometheus/prometheus.yml','--storage.tsdb.path=/tmp/prometheus'],
      'volumes':[str(promconfig)+':/etc/prometheus/prometheus.yml:ro',str(ROOT/'deployment/operations/alerts.yml')+':/etc/prometheus/alerts.yml:ro',str(private)+':/run/secrets:ro'],
      'networks':['recovery'],'read_only':True,'tmpfs':['/tmp'],'mem_limit':'192m','cap_drop':['ALL']}
    compose.write_text(yaml.safe_dump(doc,sort_keys=False))
    run(dc+['up','-d','--no-deps','worker','recovery-observer','recovery-prometheus'])
    def alerts():
        code="import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://recovery-prometheus:9090/api/v1/alerts'))['data']['alerts']))"
        return json.loads(run(dc+['exec','-T','recovery-observer','python','-c',code]))
    def state(name,firing):
        rows=alerts(); found=any(r['labels']['alertname']==name and r['state']=='firing' for r in rows)
        return True if found==firing else False
    wait(lambda:state('WorkerInactive',False),120)
    source=json.loads((folder/'authenticated/business.json').read_text())
    completed={b['id'] for b in source['batches'] if b['status']=='completed'}
    known=json.loads((ROOT/'deployment/industrial/local/batch-qa-state.json').read_text())
    admitted={value['id'] for value in known['jobs'].values()}
    item=next(i for i in source['items'] if i['status']=='completed' and i['batch_id'] in completed and i['batch_id'] in admitted)
    itemid=item['id']; batchid=item['batch_id']
    # Stale reservation simulation mutates only the cloned item, reusing its authenticated real image.
    run(dc+['stop','-t','110','worker'])
    wait(lambda:state('WorkerInactive',True),150)
    worker_fired=alerts()
    resumed='--resume-completed' in sys.argv
    if not resumed:
        sql(f"BEGIN; UPDATE batch_items SET status='running',attempts=1,claim_token='{secrets.token_hex(16)}'::uuid,lease_until=now()-interval '1 second',not_before=now()-interval '1 second',finished_at=NULL,anomaly_score=NULL,threshold=NULL,decision=NULL,inference_time_ms=NULL,release_id=NULL,engine=NULL,upstream_request_id=NULL WHERE id='{itemid}'; UPDATE inspection_batches SET status='running',finished_at=NULL,processed=processed-1,{ 'normal_count' if item['decision']=='normal' else 'anomaly_count'}={ 'normal_count' if item['decision']=='normal' else 'anomaly_count'}-1 WHERE id='{batchid}'; COMMIT;")
    began=time.monotonic(); run(dc+['start','worker'])
    def finished():
        value=json.loads(sql(f"SELECT to_jsonb(i) FROM batch_items i WHERE id='{itemid}';"))
        return value if value['status']=='completed' else False
    result=wait(finished,240)
    prediction_recovery_seconds=round(time.monotonic()-began,3) if not resumed else None
    for key in ('anomaly_score','threshold','decision','engine','release_id'):
        if result[key]!=item[key]: raise RuntimeError('Restored real prediction differs in '+key)
    assert result['attempts']==2
    (LOCAL/'recovered-prediction.json').write_text(json.dumps({'original':item,'recovered':result,'exact_original_result':True,'recovery_seconds':prediction_recovery_seconds}))
    wait(lambda:state('WorkerInactive',False),120)
    worker_resolved=alerts()
    # Kill only the clone worker, to verify recorded heartbeat detection and restart recovery.
    cid=run(dc+['ps','-q','worker']).decode().strip()
    run(['docker','kill','--signal','SIGKILL',cid])
    run(['docker','start',cid])
    wait(lambda:sql("SELECT count(*) FROM service_heartbeats WHERE updated_at>now()-interval '15 seconds' AND status='ready';")=='1',120)
    # PostgreSQL outage in the clone: live V3 and V2 are never stopped.
    run(dc+['stop','-t','30','postgres'])
    try:
        wait(lambda:state('PostgreSQLUnavailable',True),150)
        pg_fired=alerts()
    finally:
        pgcid=run(dc+['ps','-a','-q','postgres']).decode().strip(); run(['docker','start',pgcid])
    wait(lambda:state('PostgreSQLUnavailable',False),150)
    # Advisory-lock connection loss exits the worker; unless-stopped must reconnect it.
    wait(lambda:sql("SELECT count(*) FROM service_heartbeats WHERE updated_at>now()-interval '15 seconds' AND status='ready';")=='1',150)
    pg_resolved=alerts()
    event_interval=float(sql(f"SELECT extract(epoch FROM (max(created_at) FILTER (WHERE kind='item.completed')-max(created_at) FILTER (WHERE kind='item.recovered'))) FROM batch_events WHERE item_id='{itemid}';"))
    report={'project':folder.name,'worker_alert_fired':[r['labels']['alertname'] for r in worker_fired if r['state']=='firing'],
      'worker_alert_resolved':not any(r['labels']['alertname']=='WorkerInactive' and r['state']=='firing' for r in worker_resolved),
      'postgres_alert_fired':[r['labels']['alertname'] for r in pg_fired if r['state']=='firing'],
      'postgres_alert_resolved':not any(r['labels']['alertname']=='PostgreSQLUnavailable' and r['state']=='firing' for r in pg_resolved),
      'real_recovered_image':{'item_id':itemid,'attempts':result['attempts'],'engine':result['engine'],'score':result['anomaly_score'],'threshold':result['threshold'],'decision':result['decision'],'exact_original_result':True},
      'worker_recovery_seconds':prediction_recovery_seconds,'inference_time_ms':result['inference_time_ms'],
      'recovered_event_to_completed_seconds':event_interval,
      'reused_successful_prediction':resumed,'worker_sigkill_recovered':True,'postgres_reconnected':True}
    (LOCAL/'fault-verification.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report))


if __name__=='__main__': main()
