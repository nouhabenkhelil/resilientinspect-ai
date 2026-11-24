"""Restore into a fresh, uniquely named project; never overwrite serving volumes."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.parse
import yaml
from backup import ROOT, LOCAL, run, sha, unpack

BUSINESS_SQL = "SELECT jsonb_build_object('users',(SELECT jsonb_agg(to_jsonb(u) ORDER BY u.id) FROM users u),'inspections',(SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM inspections i),'batches',(SELECT jsonb_agg(to_jsonb(b) ORDER BY b.id) FROM inspection_batches b),'items',(SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM batch_items i),'releases',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM model_releases r));"


def wait(check, seconds=150):
    until = time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            value=check()
            if value: return value
        except Exception: pass
        time.sleep(2)
    raise RuntimeError('Isolated recovery readiness timed out')


def http(url, data=None, token=None):
    headers={}
    if token: headers['Authorization']='Bearer '+token
    if isinstance(data,dict):
        data=json.dumps(data).encode(); headers['Content-Type']='application/json'
    request=urllib.request.Request(url,data=data,headers=headers)
    with urllib.request.urlopen(request,timeout=8) as response:
        payload=response.read()
        return json.loads(payload) if payload else None


def restore(archive, resume=None):
    began=time.monotonic()
    config=json.loads((LOCAL/'backup-config.json').read_text())
    identity=Path(resume).name if resume else 'resilientinspect-recovery-'+secrets.token_hex(5)
    folder=(ROOT/'deployment/industrial/local'/identity).resolve()
    if not identity.startswith('resilientinspect-recovery-') or folder.parent!=(ROOT/'deployment/industrial/local').resolve(): raise ValueError('Unexpected isolated destination')
    if not resume: folder.mkdir()
    stage=folder/'authenticated'; stage.mkdir(exist_ok=bool(resume))
    manifest=unpack(config,archive,stage)
    if manifest['kind']!='core': raise ValueError('Core backup required')
    expected=json.loads((stage/'business.json').read_text())
    source=yaml.safe_load((ROOT/'deployment/industrial/compose.yml').read_text())
    private={}
    for line in (stage/'config/.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1); private[k]=v.strip().strip('"').strip("'")
    dbpassword=secrets.token_urlsafe(36)
    password=secrets.token_urlsafe(36)
    base='http://localhost:18680'; issuer='http://localhost:18685/realms/resilientinspect'
    env={k:private[k] for k in ('PORTAL_MODE','OIDC_CLIENT_ID','OIDC_CLIENT_SECRET','PORTAL_SESSION_SECRET')}
    env.update(PORTAL_ORIGIN=base, OIDC_ISSUER=issuer,OIDC_INTERNAL_URL='http://idp:8080/realms/resilientinspect',
               DATABASE_URL=f'postgresql+psycopg://ri_app:{password}@postgres:5432/portal', SCIENTIFIC_URL='http://science:8000',
               BATCH_STORAGE_ROOT='/private/images')
    common={'image':'resilientinspect-portal:local','environment':env,'volumes':['images:/private'], 'networks':['recovery','inference'],
            'read_only':True,'tmpfs':['/tmp'],'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'stop_grace_period':'110s','restart':'unless-stopped'}
    services={
      'postgres':{'image':source['services']['postgres']['image'],'environment':{'POSTGRES_USER':'ri_migrator','POSTGRES_PASSWORD':dbpassword,'POSTGRES_DB':'portal'},'volumes':['postgres:/var/lib/postgresql/data'],'networks':['recovery'],'restart':'unless-stopped'},
      'idp':{'image':source['services']['idp']['image'],'command':['start-dev','--hostname=http://localhost:18685'],'volumes':['idp:/opt/keycloak/data'],'ports':['127.0.0.1:18685:8080'],'networks':['recovery'],'mem_limit':'512m','environment':{'JAVA_OPTS_KC_HEAP':'-XX:MaxRAMPercentage=60 -XX:InitialRAMPercentage=30'},'restart':'unless-stopped'},
      'recovery-portal':{**common,'networks':{'recovery':{'aliases':['portal']},'inference':{}}},
      'worker':{**common,'command':['python','-m','portal.batch_worker'],'mem_limit':'256m','environment':{k:v for k,v in env.items() if k in ('DATABASE_URL','SCIENTIFIC_URL','BATCH_STORAGE_ROOT')}},
      'web':{'image':'resilientinspect-industrial-web:local','ports':['127.0.0.1:18680:8080'],'networks':['recovery'],'read_only':True,'tmpfs':['/tmp']},
    }
    doc={'name':identity,'services':services,'networks':{'recovery':{},'inference':{'external':True,'name':'resilientinspect-industrial_inference'}},'volumes':{'postgres':{},'idp':{},'images':{}}}
    compose=folder/'compose.yml'; compose.write_text(yaml.safe_dump(doc,sort_keys=False))
    dc=['docker','compose','-f',str(compose)]
    run(dc+['up','-d','postgres'])
    wait(lambda: subprocess.run(dc+['exec','-T','postgres','pg_isready','-h','127.0.0.1','-U','ri_migrator','-d','portal'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0)
    empty=run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',"SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"]).decode().strip()
    if empty!='0': raise RuntimeError('Refusing to restore into any populated destination, including a previous successful clone')
    sql=f"CREATE ROLE ri_app LOGIN PASSWORD '{password}'; CREATE ROLE ri_observer LOGIN PASSWORD '{secrets.token_urlsafe(36)}';"
    run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-v','ON_ERROR_STOP=1'],data=sql.encode())
    with (stage/'portal.dump').open('rb') as stream:
        result=subprocess.run(dc+['exec','-T','postgres','pg_restore','-U','ri_migrator','-d','portal','--single-transaction','--exit-on-error'],stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT)
        if result.returncode: raise RuntimeError('Isolated PostgreSQL restore failed; private diagnostics withheld')
    actual=json.loads(run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',BUSINESS_SQL]))
    if actual!=expected: raise RuntimeError('Restored business snapshot differs from authenticated source')
    # A volume can only be created here, under this fresh project identity.
    extract="""import os,sys,tarfile
from pathlib import PurePosixPath,Path
t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|')
for m in t:
 p=PurePosixPath(m.name)
 if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='data' or not(m.isdir() or m.isfile()) or m.uid not in (0,1000,10002): raise ValueError('Unsafe volume member')
 target=Path('/'+str(p))
 if m.isdir(): target.mkdir(parents=True,exist_ok=True)
 else:
  target.parent.mkdir(parents=True,exist_ok=True)
  with t.extractfile(m) as src,target.open('wb') as dst:
   import shutil; shutil.copyfileobj(src,dst)
 os.chmod(target,m.mode & 0o777); os.chown(target,m.uid,m.gid)
"""
    for label,filename in [('images','images.tar'),('idp','keycloak.tar')]:
        volume=identity+'_'+label
        run(['docker','volume','create',volume])
        with (stage/filename).open('rb') as stream:
            result=subprocess.run(['docker','run','--rm','-i','--network','none','--read-only','--user','0','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','--cap-add','CHOWN','--cap-add','FOWNER','-v',volume+':/data','resilientinspect-portal:local','python','-c',extract],stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if result.returncode: raise RuntimeError('Isolated private-volume restore failed')
    inventory={i['file_ref'].replace('-',''):i['file_sha256'] for i in expected['items'] if not i['file_deleted_at']}
    verify="import hashlib,json; from pathlib import Path; print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/data/images').iterdir() if p.is_file()}))"
    hashes=json.loads(run(['docker','run','--rm','--network','none','--read-only','--user','0','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','-v',identity+'_images:/data:ro','resilientinspect-portal:local','python','-c',verify]))
    if hashes!=inventory: raise RuntimeError('Restored private images differ from PostgreSQL SHA256 inventory')
    (folder/'integrity.json').write_text(json.dumps({'business_exact_before_url_adaptation':True,'private_images_sha256_verified':len(hashes)}))
    # Only clone URLs change; original immutable scientific releases/results stay exact.
    run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-v','ON_ERROR_STOP=1'],data=b"UPDATE users SET issuer='http://localhost:18685/realms/resilientinspect' WHERE issuer='http://localhost:18585/realms/resilientinspect';")
    run(dc+['up','-d','idp'])
    finish(folder,archive)


def finish(folder,archive):
    folder=Path(folder).resolve(); identity=folder.name
    if folder.parent!=(ROOT/'deployment/industrial/local').resolve() or not identity.startswith('resilientinspect-recovery-'): raise ValueError('Unexpected isolated project')
    stage=folder/'authenticated'; compose=folder/'compose.yml'
    doc=yaml.safe_load(compose.read_text()); env=doc['services']['recovery-portal']['environment']
    base=env['PORTAL_ORIGIN']; issuer=env['OIDC_ISSUER']
    dc=['docker','compose','-f',str(compose)]
    expected=json.loads((stage/'business.json').read_text())
    actual=json.loads(run(dc+['exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',BUSINESS_SQL]))
    # Recheck the completed acquisition, normalizing only the declared clone issuer.
    for user in actual['users']:
        if user['issuer']==issuer: user['issuer']='http://localhost:18585/realms/resilientinspect'
    if actual!=expected: raise RuntimeError('Existing restored business data changed before validation')
    verify="import hashlib,json; from pathlib import Path; print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/data/images').iterdir() if p.is_file()}))"
    hashes=json.loads(run(['docker','run','--rm','--network','none','--read-only','--user','0','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','-v',identity+'_images:/data:ro','resilientinspect-portal:local','python','-c',verify]))
    if hashes!={i['file_ref'].replace('-',''):i['file_sha256'] for i in expected['items'] if not i['file_deleted_at']}: raise RuntimeError('Restored image hash mismatch')
    wait(lambda:http(issuer+'/.well-known/openid-configuration'),300)
    accounts=json.loads((stage/'config/accounts.json').read_text())
    admin=accounts['provider_administrator']
    form=urllib.parse.urlencode({'grant_type':'password','client_id':'admin-cli','username':admin['username'],'password':admin['password']}).encode()
    token=http('http://localhost:18685/realms/master/protocol/openid-connect/token',form)['access_token']
    api='http://localhost:18685/admin/realms/resilientinspect/clients'
    clients=http(api+'?clientId='+urllib.parse.quote(env['OIDC_CLIENT_ID']),token=token)
    client=http(api+'/'+clients[0]['id'],token=token)
    client['redirectUris']=[base+'/api/auth/callback']; client['webOrigins']=[base]
    client['attributes']['post.logout.redirect.uris']=base+'/*'
    request=urllib.request.Request(api+'/'+client['id'],data=json.dumps(client).encode(),method='PUT',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=10): pass
    run(dc+['up','-d','recovery-portal','web'])
    wait(lambda:http(base+'/api/health'))
    report={'project':identity,'compose':str(compose),'source_archive':Path(archive).name,'business_exact_before_url_adaptation':True,
            'users':len(expected['users']),'inspections':len(expected['inspections']),'batches':len(expected['batches']),'items':len(expected['items']),
            'private_images_sha256_verified':len(hashes),'duration_ready_seconds':round(time.time()-folder.stat().st_birthtime,3),
            'base':base,'issuer':issuer,'worker_started':False,'retained_volumes':[identity+'_'+name for name in ('postgres','idp','images')]}
    (folder/'report.json').write_text(json.dumps(report,indent=2))
    (LOCAL/'recovery-current.json').write_text(json.dumps({'folder':str(folder)}))
    print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('archive'); parser.add_argument('--resume-empty-project'); parser.add_argument('--finish-existing-project'); args=parser.parse_args()
    if args.finish_existing_project: finish(ROOT/'deployment/industrial/local'/args.finish_existing_project,args.archive)
    else: restore(args.archive,args.resume_empty_project)
