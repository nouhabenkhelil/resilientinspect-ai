"""Real, authenticated operational queries. Never print secrets, tokens or raw logs."""
import base64
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request
import yaml
import hashlib
from backup import ROOT,LOCAL,run


def get(base,path,user,password):
    header=base64.b64encode((user+':'+password).encode()).decode()
    with urllib.request.urlopen(urllib.request.Request(base+path,headers={'Authorization':'Basic '+header}),timeout=20) as response:
        return json.load(response)


def main():
    private=LOCAL/'secrets'
    prom=lambda path:get('http://localhost:19090',path,'ri-operator',(private/'prometheus_password').read_text().strip())
    graf=lambda path:get('http://localhost:13000',path,'ri-admin',(private/'grafana_password').read_text().strip())
    targets=prom('/api/v1/targets')['data']['activeTargets']
    assert len(targets)==2 and all(t['health']=='up' for t in targets), 'Real scrape targets are not healthy'
    services={}
    for query in ['ri_database_up','ri_gateway_up','ri_worker_up','ri_science_up','ri_idp_up','ri_batch_pending','ri_batch_running','ri_models_available']:
        data=prom('/api/v1/query?'+urllib.parse.urlencode({'query':query}))
        assert data['status']=='success' and data['data']['result'],query+' has no actual measurements'
        services[query]=data['data']['result']
    dashboards=graf('/api/search?type=dash-db')
    assert len([d for d in dashboards if d['uid'].startswith('ri-')])==6
    queries=0
    for dashboard in dashboards:
        data=graf('/api/dashboards/uid/'+dashboard['uid'])['dashboard']
        for panel in data['panels']:
            for target in panel['targets']:
                result=prom('/api/v1/query?'+urllib.parse.urlencode({'query':target['expr']}))
                assert result['status']=='success'; queries+=1
    for port in [19090,13000]:
        try:
            urllib.request.urlopen('http://localhost:'+str(port)+('/api/v1/targets' if port==19090 else '/api/search'),timeout=5)
            raise AssertionError('Anonymous admin API accepted')
        except urllib.error.HTTPError as error: assert error.code==401
    rules=prom('/api/v1/rules')['data']['groups'][0]['rules']
    assert len(rules)==8 and all(r['health']=='ok' for r in rules)
    # Runtime log audit uses known private values only in memory.
    env={}
    for row in (ROOT/'deployment/industrial/local/.env').read_text().splitlines():
        if '=' in row and not row.startswith('#'):
            key,value=row.split('=',1)
            if any(s in key for s in ['PASSWORD','SECRET']): env[key]=value.strip().strip('"')
    accounts=json.loads((ROOT/'deployment/industrial/local/accounts.json').read_text())
    secrets=[*env.values(),*(p.read_text().strip() for p in private.iterdir() if p.is_file()),*(a['password'] for a in accounts['accounts'].values())]
    logcounts={}
    for service in ['portal','worker']:
        logs=run(['docker','logs','--since','30m','resilientinspect-industrial-'+service+'-1']).decode()
        assert not any(value in logs for value in secrets if len(value)>12),'Sensitive runtime log value detected'
        rows=[json.loads(line) for line in logs.splitlines() if line.startswith('{')]
        assert rows and all('event' in row and 'at' in row for row in rows)
        logcounts[service]=len(rows)
    sql="SELECT json_build_object('observer_can_read_users',has_table_privilege('ri_observer','users','SELECT'),'observer_can_write_items',has_table_privilege('ri_observer','batch_items','UPDATE'),'observer_can_read_items',has_table_privilege('ri_observer','batch_items','SELECT'),'revision',(SELECT version_num FROM alembic_version),'inspections',(SELECT count(*) FROM inspections),'batches',(SELECT count(*) FROM inspection_batches));"
    dc=['docker','compose','--env-file','deployment/industrial/local/.env','-f','deployment/industrial/compose.yml']
    database=json.loads(run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',sql]))
    assert database['observer_can_read_items'] and not database['observer_can_read_users'] and not database['observer_can_write_items']
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'services/portal/portal').glob('*.py')}
    bindings={}
    code="import json,hashlib; from pathlib import Path; print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/app/portal').glob('*.py')}))"
    for container in ['resilientinspect-industrial-portal-1','resilientinspect-industrial-worker-1','resilientinspect-observability-observer-1']:
        observed=json.loads(run(['docker','exec',container,'python','-c',code])); assert observed==source_hashes,'Runtime code differs from final workspace'
        bindings[container]={'code_files':len(observed),'image_id':run(['docker','inspect',container,'--format','{{.Image}}']).decode().strip()}
    proof=json.loads(next((ROOT/'artifacts/onnx').glob('*/*/parity-linux.json')).read_text())['environment']
    versions={}
    code="import json,sys,importlib.metadata as m; print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),**{k:m.version(v) for k,v in {'torch':'torch','numpy':'numpy','scikit_learn':'scikit-learn','torchvision':'torchvision','pillow':'Pillow','onnx':'onnx','onnxruntime':'onnxruntime'}.items()}}))"
    for container in ['resilientinspect-industrial-science-1','resilientinspect-backend-1']:
        observed=json.loads(run(['docker','exec',container,'python','-c',code]))
        assert all(proof[k]==v for k,v in observed.items()),'Scientific library runtime differs from bound proof'
        versions[container]=observed
    report={'targets':[{k:t[k] for k in ['health','scrapeUrl']} for t in targets], 'measured':services,'dashboards':len(dashboards),
      'real_queries_accepted':queries,'rules':[{'name':r['name'],'state':r['state'],'health':r['health']} for r in rules],
      'anonymous_admin_apis_denied':True,'json_log_rows_secret_checked':logcounts,'database':database,'final_runtime_bindings':bindings,'scientific_library_versions_match_proof':versions}
    (LOCAL/'runtime-verification.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report))


if __name__=='__main__': main()
