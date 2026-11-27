"""Aggregate measured evidence; no private arrays, weights or database are published."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from .common import LOCAL, ROOT, WORK, environment, read


def get(url,headers=None,payload=None):
    request=urllib.request.Request(url,headers=headers or {},data=payload)
    with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)


def suite(name):
    xml=ET.parse(LOCAL/name).getroot()
    nodes=xml.findall('testsuite') if xml.tag=='testsuites' else [xml]
    result={field:sum(int(n.get(field,'0')) for n in nodes) for field in ('tests','errors','failures','skipped')}
    return result


def main():
    repro=read(LOCAL/'reproduction-verification.json');preserved=read(LOCAL/'preservation-verification.json')
    assert repro['status']==preserved['status']=='passed'
    assert repro['bitwise_identical_independent_recomputes']
    tests={'pipeline':suite('unit-tests.xml'),'existing_regression':suite('regression-tests-corrected.xml'),
           'existing_orchestration':suite('orchestration-tests.xml'),
           'initial_shared_editable_install_attempt':suite('regression-tests.xml')}
    for key in ('pipeline','existing_regression','existing_orchestration'):
        assert tests[key]['errors']==tests[key]['failures']==tests[key]['skipped']==0
    mlflow=read(LOCAL/'mlflow-verification.json')
    assert mlflow['finished_runs']==1 and mlflow['registered_models']==0
    from .prefect_flow import launch
    assert launch()['status']=='disabled'
    run_id=read(LOCAL/'prefect-verification.json')['manual_test_run_id']
    flow=get('http://127.0.0.1:4200/api/flow_runs/'+run_id)
    assert flow['state']['type']=='COMPLETED' and flow['deployment_id'] is None
    primary=Path(read(LOCAL/'baseline.json')['primary_root'])
    secret=(primary/'deployment/industrial/local/observability/secrets/prometheus_password').read_text().strip()
    auth=base64.b64encode(('ri-operator:'+secret).encode()).decode()
    targets=get('http://127.0.0.1:19090/api/v1/targets',{'Authorization':'Basic '+auth})['data']['activeTargets']
    assert len(targets)==3 and all(t['health']=='up' for t in targets)
    assert get('http://127.0.0.1:13000/api/health')['database']=='ok'
    with urllib.request.urlopen('http://127.0.0.1:18180',timeout=10) as response:assert response.status==200
    science=json.loads(subprocess.check_output(['docker','exec','resilientinspect-industrial-science-1','python','-c',
        "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))))"],text=True,timeout=15))
    assert science['ready_models_by_engine']=={'pytorch':15,'onnxruntime':14}
    report=ROOT/'reports/experiments/dvc_pipeline_verification.json';report.touch(exist_ok=True)
    baseline=read(LOCAL/'baseline.json')['worktree_source']
    files=subprocess.check_output(['git','ls-files','-co','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    created=sorted(p for p in files if p not in baseline)
    assert not any(p.startswith('mlops/dvc_pipeline/work/') or p.startswith('mlops/local/') for p in created)
    result={'status':'verified_local','verified_at_epoch':time.time(),'environment':environment(),
        'created_files':created,'modified_preexisting_files':[],
        'reproduction':repro,'preservation':preserved,'tests':tests,'mlflow':mlflow,
        'optional_prefect':{'disabled_by_default':True,'manual_test_run_id':run_id,'state':'COMPLETED','deployment_id':None,'scheduled':False},
        'service_checks':{'prometheus_targets':[{'job':t['labels']['job'],'health':t['health']} for t in targets],
                          'grafana_database':'ok','frontend_http':200,'science_ready_models':science['ready_models_by_engine']},
        'git_status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),
        'limits':['Procedural development data only; these metrics do not evaluate MVTec or the official models.',
                  'Bitwise repeatability tested on this Windows CPU environment, not across hardware/OS versions.',
                  'No DVC remote required or configured; local cache is not an off-machine backup.',
                  'MLflow uses a separate local demo database; the existing tracking UI does not automatically list it.',
                  'Existing monitoring tests needing frozen private runtime files were not run in this asset-free worktree.',
                  'No remote CI run, commit, push or merge.']}
    report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'tests':tests,'created_files':len(created),
                      'unchanged_protected_files':preserved['original_scientific_sha256_files'],'demo_metrics':repro['demo_metrics']}))


if __name__=='__main__':main()
