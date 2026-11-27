"""Idempotent additive provisioning; existing Prometheus reloads via SIGHUP, never restart."""
import base64
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import yaml
from .core import ROOT, DATA, SECRETS, CONFIG, atomic_json

OPS = ROOT/'deployment/operations'
PRIVATE = ROOT/'deployment/industrial/local/observability/secrets'
MARKER = '# BEGIN MLOPS MONITORING (managed by mlops.monitoring.configure)'


def command(args, content=None):
    result=subprocess.run(args,input=content,text=True,capture_output=True,timeout=90)
    if result.returncode: raise RuntimeError('Monitoring command failed: '+args[0]+' (details withheld)')
    return result.stdout


def api(service, path, payload=None):
    port,user,secret = (19090,'ri-operator','prometheus_password') if service=='prometheus' else (13000,'ri-admin','grafana_password')
    credential=SECRETS/secret if service=='grafana' and (SECRETS/secret).exists() else PRIVATE/secret
    auth=base64.b64encode((user+':'+credential.read_text().strip()).encode()).decode()
    request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,
        headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(request,timeout=30) as response: return json.load(response)


def provision():
    DATA.mkdir(parents=True,exist_ok=True); SECRETS.mkdir(parents=True,exist_ok=True)
    for name in ('hmac_key','database_password'):
        if not (SECRETS/name).exists(): (SECRETS/name).write_text(secrets.token_urlsafe(48))
    (SECRETS/'metrics_token').write_text((PRIVATE/'metrics_token').read_text().strip())
    password=(SECRETS/'database_password').read_text().strip()
    if not all(c.isalnum() or c in '-_' for c in password): raise ValueError('credential encoding')
    (SECRETS/'database_url').write_text(f'postgresql://ri_mlops_monitor:{password}@postgres:5432/portal')
    if not (DATA/'activation.json').exists(): atomic_json(DATA/'activation.json',{'activated_at':time.time()})
    sql=f"""
    BEGIN;
    CREATE SCHEMA IF NOT EXISTS mlops_monitoring AUTHORIZATION ri_migrator;
    CREATE OR REPLACE VIEW mlops_monitoring.prediction_metadata WITH (security_barrier=true) AS
      SELECT i.upstream_request_id::text AS identity,i.model,i.category,r.checkpoint_sha256 AS version,i.engine,
             i.anomaly_score,i.threshold,i.decision,i.inference_time_ms,extract(epoch FROM i.updated_at) AS timestamp
        FROM inspections i JOIN model_releases r ON i.release_id=r.id
        WHERE i.status='completed' AND i.upstream_request_id IS NOT NULL
      UNION ALL
      SELECT i.upstream_request_id::text,b.model,b.category,r.checkpoint_sha256,i.engine,
             i.anomaly_score,i.threshold,i.decision,i.inference_time_ms,extract(epoch FROM i.finished_at)
        FROM batch_items i JOIN inspection_batches b ON i.batch_id=b.id JOIN model_releases r ON i.release_id=r.id
        WHERE i.status='completed' AND i.upstream_request_id IS NOT NULL;
    DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='ri_mlops_monitor') THEN
      CREATE ROLE ri_mlops_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $$;
    ALTER ROLE ri_mlops_monitor PASSWORD '{password}';
    ALTER ROLE ri_mlops_monitor SET default_transaction_read_only=on;
    ALTER ROLE ri_mlops_monitor SET statement_timeout=3000;
    GRANT CONNECT ON DATABASE portal TO ri_mlops_monitor;
    GRANT USAGE ON SCHEMA mlops_monitoring TO ri_mlops_monitor;
    GRANT SELECT ON mlops_monitoring.prediction_metadata TO ri_mlops_monitor;
    COMMIT;
    """
    command(['docker','exec','-i','resilientinspect-industrial-postgres-1','psql','-U','ri_migrator','-d','portal','-v','ON_ERROR_STOP=1','-q'],sql)
    from .reference import freeze
    value=freeze()
    # Restrict local secret/storage directory to the current Windows user, SYSTEM and Administrators.
    if __import__('os').name=='nt':
        user=command(['whoami']).strip()
        for path in (DATA,SECRETS):
            command(['icacls',str(path),'/inheritance:r','/grant:r',user+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'])
    return len(value['groups'])


def rules():
    a=CONFIG['alerts']
    expressions={
        'MLOpsScienceUnavailable':'ri_mon_service_up == 0',
        'MLOpsScrapeUnavailable':'up{job="mlops-monitoring"} == 0 or ri_mon_scrape_probe_up == 0',
        'MLOpsHighErrorRate':f'ri_mon_api_error_ratio > {a["error_ratio"]}',
        'MLOpsHighLatency':f'ri_mon_api_p95_seconds > {a["p95_seconds"]}',
        'MLOpsHighCPU':f'ri_mon_host_cpu_ratio > {a["cpu_ratio"]}',
        'MLOpsHighRAM':f'ri_mon_host_memory_ratio > {a["memory_ratio"]}',
        'MLOpsModelsNotReady':'ri_mon_models_ready{engine="pytorch"} < 15 or ri_mon_models_ready{engine="onnxruntime"} < 14',
        'MLOpsScoreDrift':f'ri_mon_drift_ks_distance > {CONFIG["ks_distance"]}',
        'MLOpsAnomalyRateDrift':f'ri_mon_drift_anomaly_rate_delta > {CONFIG["anomaly_rate_delta"]}',
        'MLOpsControlStale':f'ri_mon_control_age_seconds > {CONFIG["freshness_seconds"]} or ri_mon_host_collection_age_seconds > {CONFIG["freshness_seconds"]} or ri_mon_drift_age_seconds > {CONFIG["freshness_seconds"]} or ri_mon_sql_up == 0 or ri_mon_collection_truncated > 0 or ri_mon_host_collection_up == 0 or ri_mon_drift_report_up == 0 or ri_mon_invalid_rows > 0'
    }
    return {'groups':[{'name':'ri-mlops-monitoring','rules':[{'alert':name,'expr':expr,'for':a['for'],
        'labels':{'severity':'warning','scope':'mlops'},'annotations':{'summary':name+' — inspect source label before interpreting; no external notifications'}} for name,expr in expressions.items()]}]}


def reload_prometheus():
    job='''  - job_name: mlops-monitoring
    honor_labels: true
    authorization: {type: Bearer, credentials_file: /run/secrets/metrics_token}
    scrape_timeout: 8s
    static_configs: [{targets: ['mlops-monitoring:9108'], labels: {source: production}}]
'''
    additions=[(OPS/'prometheus.yml',job),(OPS/'alerts.yml',yaml.safe_dump(rules()['groups'],sort_keys=False))]
    for path,extra in additions:
        original=path.read_text().split(MARKER)[0].rstrip()+'\n'
        backup=DATA/(path.name+'.before')
        if not backup.exists(): backup.write_text(original)
        # In-place write preserves Docker single-file bind mount identity.
        with path.open('w',newline='\n') as handle: handle.write(original+MARKER+'\n'+extra)
    command(['docker','exec','resilientinspect-observability-prometheus-1','promtool','check','config','/etc/prometheus/prometheus.yml'])
    command(['docker','kill','--signal','HUP','resilientinspect-observability-prometheus-1'])


def dashboards():
    from .dashboards import definitions
    folder=Path(__file__).with_name('dashboards'); folder.mkdir(exist_ok=True)
    for dashboard in definitions():
        (folder/(dashboard['uid']+'.json')).write_text(json.dumps(dashboard,indent=2))
        # Existing file provider reloads this mounted directory automatically, without login/restart.
        (OPS/'dashboards'/(dashboard['uid']+'.json')).write_text(json.dumps(dashboard,indent=2))
    # Docker Desktop bind mounts may not propagate filesystem watch notifications.
    # Explicit authenticated provisioning reload activates new files without a restart.
    api('grafana','/api/admin/provisioning/dashboards/reload',{})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['provision','connect']); args=parser.parse_args()
    if args.action=='provision': print(json.dumps({'references':provision(),'credentials':'withheld'}))
    else:
        reload_prometheus(); dashboards(); print('{"monitoring_connected":true,"existing_services_restarted":false}')
