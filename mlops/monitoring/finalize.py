"""Publish aggregate verification only; execution artifacts stay ignored and private."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from .core import ROOT, DATA, atomic_json
from .configure import api


def prefect(endpoint,payload):
    request=urllib.request.Request('http://127.0.0.1:4200/api/'+endpoint,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response: return json.load(response)


def main():
    (ROOT/'reports/experiments/monitoring_verification.json').touch(exist_ok=True)
    evidence={name:json.loads((DATA/(name+'-verification.json')).read_text()) for name in
              ('inference','alert','rule','browser','persistence','privacy','preservation')}
    assert evidence['rule']['exit_code']==0 and len(evidence['alert']['resolved'])==10
    assert evidence['browser']['datasource_health']=='OK' and not evidence['browser']['page_errors']
    targets=api('prometheus','/api/v1/targets')['data']['activeTargets']
    assert len(targets)==3 and all(t['health']=='up' for t in targets)
    assert api('grafana','/api/datasources/uid/ri-prom/health')['status']=='OK'
    deployments=prefect('deployments/filter',{})
    monitoring=next(d for d in deployments if d['name']=='local-monitoring')
    existing=next(d for d in deployments if d['name']=='local-readonly')
    assert monitoring['schedules'][0]['schedule']['interval']==60 and not monitoring['paused']
    assert existing['schedules'][0]['schedule']['interval']==3600 and not existing['paused']
    finished=prefect('flow_runs/filter',{'deployments':{'id':{'any_':[monitoring['id']]}},
        'flow_runs':{'state':{'type':{'any_':['COMPLETED','FAILED']}}},'sort':'START_TIME_DESC','limit':30})
    assert finished and finished[0]['state_name']=='Completed'
    alerts=api('prometheus','/api/v1/query?'+urllib.parse.urlencode({'query':'ALERTS{alertstate="firing",scope="mlops"}'}))['data']['result']
    assert not any(a['metric'].get('source')=='synthetic' for a in alerts)
    observed={q:api('prometheus','/api/v1/query?'+urllib.parse.urlencode({'query':q}))['data']['result'] for q in
        ['ri_mon_host_memory_ratio{source="production"}','ri_mon_host_cpu_ratio{source="production"}',
         'ri_mon_models_ready{source="production"}','ri_mon_sql_up','ri_mon_drift_age_seconds','ri_mon_host_collection_age_seconds']}
    versions={'python_host':sys.version.split()[0], 'psutil':importlib.metadata.version('psutil'),
        'PyYAML':importlib.metadata.version('PyYAML'),'prometheus':api('prometheus','/api/v1/status/buildinfo')['data']['version'],
        'grafana':api('grafana','/api/health')['version']}
    image=subprocess.check_output(['docker','inspect','resilientinspect-mlops-monitoring-collector-1','--format','{{.Image}}'],text=True).strip()
    runtime_code="import json,sys,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0],**{k:m.version(k) for k in ['psycopg','prometheus-client']}}))"
    versions['collector']=json.loads(subprocess.check_output(['docker','exec','resilientinspect-mlops-monitoring-collector-1','python','-c',runtime_code],text=True))
    versions['prefect']=subprocess.check_output([str(ROOT/'.venv-prefect/Scripts/python.exe'),'-c',"import prefect; print(prefect.__version__)"],text=True).strip()
    candidates=subprocess.check_output(['git','ls-files','-co','--exclude-standard'],text=True,cwd=ROOT).splitlines()
    created=[p for p in candidates if p not in json.loads((ROOT/'mlops/local/monitoring/baseline.json').read_text())['source']]
    changed=evidence['preservation']['allowed_existing_file_edits']
    output={'verified_at_epoch':time.time(),'status':'operational_local_with_documented_scope',
        'versions':versions,'collector_image_id':image,'existing_file_changes':changed,'new_files':sorted(created),
        'evidence':evidence,'live_observations':observed,'live_alerts':[a['metric'] for a in alerts],
        'prefect':{'monitoring_deployment_id':monitoring['id'],'interval_seconds':60,
                   'latest_completed_run':finished[0]['id'],'existing_flow_interval_seconds':3600,
                   'visible_failed_setup_runs':sum(r['state_name']=='Failed' for r in finished)},
        'tests':{**json.loads((DATA/'tests-verification.json').read_text()),
                 'promtool_scenarios':evidence['rule']['cases'],'promtool_trigger_resolution_assertions':evidence['rule']['trigger_and_resolution_assertions'],
                 'grafana_dashboards':3,'grafana_panels':sum(d['visible_panels'] for d in evidence['browser']['dashboards'])},
        'limits':['Optional proxy observes only its own traffic; portal metrics remain separate.',
                  'No production ground truth, no accuracy/AUROC/F1; no image feature drift.',
                  'Reference is frozen normal validation; product mix can explain score shifts.',
                  'Legacy 18080/8001/5000 were not serving initially; industrial UI remains on 18180.',
                  'Existing Prometheus/Grafana not restarted; dedicated metadata restart persistence verified.',
                  'Local runners must remain running; no OS boot service installed.',
                  'No remote CI run or external notification configured.']}
    atomic_json(ROOT/'reports/experiments/monitoring_verification.json',output)
    print(json.dumps({'status':output['status'],'tests':output['tests'],'versions':versions,'live_alerts':output['live_alerts']}))


if __name__=='__main__': main()
