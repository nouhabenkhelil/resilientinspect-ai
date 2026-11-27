"""Real local scraping, scientific proxy, drift and alert trigger/resolution evidence."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from .core import ROOT, DATA, SECRETS, Store, atomic_json
from .configure import api, rules


def query(expr): return api('prometheus','/api/v1/query?'+urllib.parse.urlencode({'query':expr}))['data']['result']


def proxy(path, body=None, source='validation'):
    headers={'Authorization':'Bearer '+(SECRETS/'metrics_token').read_text().strip(),'X-Monitor-Source':source}
    if body is not None: headers['Content-Type']='multipart/form-data; boundary=ri-monitoring-boundary'
    req=urllib.request.Request('http://127.0.0.1:19108/science'+path,data=body,headers=headers)
    try: response=urllib.request.urlopen(req,timeout=120)
    except urllib.error.HTTPError as error: response=error
    with response: return response.status,json.load(response)


def multipart(image,engine='pytorch',model='B0'):
    boundary=b'--ri-monitoring-boundary\r\n'
    body=b''
    for key,value in [('model',model),('category','bottle'),('engine',engine)]:
        body+=boundary+f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    return body+boundary+b'Content-Disposition: form-data; name="file"; filename="inspection.png"\r\nContent-Type: image/png\r\n\r\n'+image+b'\r\n--ri-monitoring-boundary--\r\n'


def inference_checks():
    deadline=time.monotonic()+30
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:19108/health',timeout=3) as response: assert response.status==200
            break
        except Exception:
            if time.monotonic()>deadline: raise
            time.sleep(1)
    for path in ('/metrics','/science/health'):
        try: urllib.request.urlopen('http://127.0.0.1:19108'+path); raise AssertionError('anonymous accepted')
        except urllib.error.HTTPError as error: assert error.code==401
    before=sum(float(r['value'][1]) for r in query('ri_mon_http_requests_total'))
    # Enough actual health requests for each dashboard quantile, without costly inference load.
    for _ in range(110): assert proxy('/health')[0]==200
    with (ROOT/'data/manifests/manifest.csv').open(newline='') as handle:
        examples=[r for r in csv.DictReader(handle) if r['category']=='bottle' and r['split']=='val' and r['label']=='0'][:30]
    assert len(examples)==30
    scores=[]
    for row in examples:
        image=(ROOT/'data/raw/mvtec_ad'/row['image_path']).read_bytes()
        assert hashlib.sha256(image).hexdigest()==row['sha256']
        status,result=proxy('/predict',multipart(image))
        assert status==200 and result['engine']=='pytorch'
        scores.append(result['anomaly_score'])
    status,result=proxy('/predict',multipart(image,'onnxruntime'))
    assert status==200 and result['engine']=='onnxruntime'
    status,result=proxy('/predict',multipart(image,'onnxruntime','T1'))
    assert status==503 and result['code']=='onnx_unavailable'
    status,_=proxy('/predict',b'--ri-monitoring-boundary--\r\n')
    assert status==422
    subprocess.run(['docker','exec','resilientinspect-mlops-monitoring-collector-1','python','-m','mlops.monitoring.drift'],check=True,capture_output=True,timeout=30)
    drift=json.loads((DATA/'drift.json').read_text())
    validation=next(g for g in drift['groups'] if g['model']=='B0' and g['category']=='bottle' and g['engine']=='pytorch' and g['source']=='validation')
    assert validation['window_count']>=30 and validation['status']=='stable'
    time.sleep(12)
    after=sum(float(r['value'][1]) for r in query('ri_mon_http_requests_total'))
    assert after-before>=143
    assert query('ri_mon_http_requests_total{status_class="4xx"}') and query('ri_mon_http_requests_total{status_class="5xx"}')
    targets=api('prometheus','/api/v1/targets')['data']['activeTargets']
    assert len(targets)==3 and all(t['health']=='up' for t in targets)
    code="import json; from mlops.monitoring.core import Store; rows=Store().rows(); print(json.dumps({'rows':len(rows),'fields':list(rows[0])}))"
    store=json.loads(subprocess.check_output(['docker','exec','resilientinspect-mlops-monitoring-collector-1','python','-c',code],text=True,timeout=20))
    values=[dict.fromkeys(store['fields'])]
    assert not any(k in values[0] for k in ('request_id','identity','filename','owner_id','image_sha256'))
    report={'targets':[{'job':t['labels']['job'],'health':t['health']} for t in targets],
        'http_counter_delta':after-before,'actual_validation_predictions':31,'t1_bottle_onnx_refused':True,
        'engines':['pytorch','onnxruntime'],'status_classes':['2xx','4xx','5xx'],'anonymous_denied':True,
        'validation_drift':validation,'store_rows':store['rows'],'privacy_allowlist':True}
    atomic_json(DATA/'inference-verification.json',report)
    print(json.dumps(report))


def demo(action):
    result=subprocess.run(['docker','exec','resilientinspect-mlops-monitoring-collector-1','python','-m','mlops.monitoring.demo',action],capture_output=True,text=True,timeout=30)
    if result.returncode: raise RuntimeError('Demo failed; details withheld')
    return json.loads(result.stdout)


def alert_checks():
    expected={r['alert'] for r in rules()['groups'][0]['rules']}
    stable=demo('stable'); assert stable['groups'][0]['status']=='stable'
    shifted=demo('alerts'); assert shifted['groups'][0]['status']=='drift'
    observed={}; deadline=time.monotonic()+100
    try:
        while time.monotonic()<deadline:
            for row in query('ALERTS{alertname=~"MLOps.*",alertstate="firing",source="synthetic"}'):
                observed[row['metric']['alertname']]=row['metric']
            if expected<=observed.keys(): break
            time.sleep(5)
        assert expected<=observed.keys(), 'Alerts not observed: '+str(expected-observed.keys())
    finally: resolved=demo('resolve')
    deadline=time.monotonic()+40
    while query('ALERTS{alertname=~"MLOps.*",source="synthetic"}') and time.monotonic()<deadline: time.sleep(5)
    assert not query('ALERTS{alertname=~"MLOps.*",source="synthetic"}')
    report={'stable':stable,'shifted':shifted,'fired':[{'rule':name,'labels':observed[name]} for name in sorted(expected)],
        'resolved':sorted(expected),'external_notifications':False,'production_state_overridden':False}
    atomic_json(DATA/'alert-verification.json',report)
    print(json.dumps({'fired':len(expected),'resolved':len(expected),'source':'synthetic'}))


def rule_tests():
    import yaml
    folder=Path(__file__).with_name('rules'); folder.mkdir(exist_ok=True)
    (folder/'alerts.yml').write_text(yaml.safe_dump(rules(),sort_keys=False))
    fixtures=[('MLOpsScienceUnavailable','ri_mon_service_up',0,1,{}),
        ('MLOpsScrapeUnavailable','up',0,1,{'job':'mlops-monitoring'}),
        ('MLOpsHighErrorRate','ri_mon_api_error_ratio',1,0,{}),
        ('MLOpsHighLatency','ri_mon_api_p95_seconds',15,0,{}),
        ('MLOpsHighCPU','ri_mon_host_cpu_ratio',1,0,{}),
        ('MLOpsHighRAM','ri_mon_host_memory_ratio',1,0,{}),
        ('MLOpsModelsNotReady','ri_mon_models_ready',0,15,{'engine':'pytorch'}),
        ('MLOpsScoreDrift','ri_mon_drift_ks_distance',1,0,{}),
        ('MLOpsAnomalyRateDrift','ri_mon_drift_anomaly_rate_delta',1,0,{}),
        ('MLOpsControlStale','ri_mon_control_age_seconds',999,0,{}),
        ('MLOpsControlStale','ri_mon_host_collection_up',0,1,{}),
        ('MLOpsControlStale','ri_mon_drift_report_up',0,1,{})]
    tests=[]
    for name,metric,high,low,labels in fixtures:
        labels={'source':'synthetic',**labels}
        series=metric+'{'+','.join(k+'="'+v+'"' for k,v in labels.items())+'}'
        tests.append({'interval':'10s','input_series':[{'series':series,'values':' '.join([str(high)]*4+[str(low)]*5)}],
            'alert_rule_test':[{'eval_time':'30s','alertname':name,'exp_alerts':[{'exp_labels':{**labels,'severity':'warning','scope':'mlops'},
                'exp_annotations':{'summary':name+' — inspect source label before interpreting; no external notifications'}}]},
                {'eval_time':'70s','alertname':name,'exp_alerts':[]}]})
    (folder/'rule-tests.yml').write_text(yaml.safe_dump({'rule_files':['alerts.yml'],'evaluation_interval':'10s','tests':tests},sort_keys=False))
    image=subprocess.check_output(['docker','inspect','resilientinspect-observability-prometheus-1','--format','{{.Config.Image}}'],text=True).strip()
    result=subprocess.run(['docker','run','--rm','--network','none','--entrypoint','promtool','-v',str(folder.resolve())+':/tests:ro','-w','/tests',image,'test','rules','rule-tests.yml'],capture_output=True,text=True,timeout=60)
    atomic_json(DATA/'rule-verification.json',{'cases':len(tests),'trigger_and_resolution_assertions':len(tests)*2,'exit_code':result.returncode,'output':result.stdout+result.stderr})
    print(result.stdout+result.stderr)
    assert result.returncode==0


if __name__=='__main__':
    from pathlib import Path
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inference','alerts','rules']); args=parser.parse_args()
    {'inference':inference_checks,'alerts':alert_checks,'rules':rule_tests}[args.action]()
