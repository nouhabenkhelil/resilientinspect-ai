"""Read-only final state, baseline preservation and durable recovery timings."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from uuid import UUID
import yaml
from backup import ROOT,LOCAL,run,sha


def main():
    fault_path=LOCAL/'fault-verification.json'; fault=json.loads(fault_path.read_text())
    folder=Path(json.loads((LOCAL/'recovery-current.json').read_text())['folder'])
    item=str(UUID(fault['real_recovered_image']['item_id']))
    query=f"SELECT extract(epoch FROM (max(created_at) FILTER (WHERE kind='item.completed')-max(created_at) FILTER (WHERE kind='item.recovered'))) FROM batch_events WHERE item_id='{item}';"
    if 'recovered_event_to_completed_seconds' not in fault:
        fault['recovered_event_to_completed_seconds']=float(run(['docker','compose','-f',str(folder/'compose.yml'),'exec','-T','postgres','psql','-U','ri_migrator','-d','portal','-qAtc',query]))
    fault_path.write_text(json.dumps(fault,indent=2))
    report={'at':datetime.now(timezone.utc).isoformat(),'services':[],'preexisting_exact':[],'backups':[]}
    baseline=json.loads((ROOT/'deployment/industrial/local/sprint3-baseline/index.json').read_text())
    for entry in baseline['files']:
        if entry['path'] not in ('frontend/nginx.portal.conf','services/portal/migrations/env.py','services/portal/portal/app.py'):
            assert sha(ROOT/entry['path'])==entry['sha256'],'Preexisting bytes changed'
            report['preexisting_exact'].append(entry['path'])
    for name in ['resilientinspect-industrial-'+s+'-1' for s in ['postgres','idp','science','portal','worker','web']]+['resilientinspect-observability-'+s+'-1' for s in ['observer','prometheus','grafana']]+['resilientinspect-backend-1','resilientinspect-frontend-1']:
        data=json.loads(run(['docker','inspect',name]))[0]
        assert data['State']['Running'],name+' is not running'
        health=data['State'].get('Health',{}).get('Status')
        if health: assert health=='healthy',name+' is not healthy'
        bindings=[{'ip':x['HostIp'],'port':x['HostPort']} for values in (data['HostConfig']['PortBindings'] or {}).values() for x in values or []]
        assert all(x['ip']=='127.0.0.1' for x in bindings)
        report['services'].append({'name':name,'state':data['State']['Status'],'health':health,'ports':bindings,'image_id':data['Image'],'restart':data['HostConfig']['RestartPolicy']['Name']})
    config=json.loads((LOCAL/'backup-config.json').read_text())
    report['recovery_containers_stopped']=not bool(run(['docker','ps','-q','--filter','label=com.docker.compose.project='+folder.name]).strip())
    assert report['recovery_containers_stopped'],'Recovery workload still running after validation'
    report['retained_recovery_volumes']=[name for name in run(['docker','volume','ls','--format','{{.Name}}']).decode().splitlines() if name.startswith(folder.name+'_')]
    assert len(report['retained_recovery_volumes'])==3
    for kind in ['core','mlops']:
        path=max(Path(config['backup_root']).glob(kind+'-*.json'),key=lambda p:p.stat().st_mtime)
        data=json.loads(path.read_text()); assert sha(path.with_suffix('.ri3'))==data['sha256']
        data['next_due_utc']=(datetime.fromtimestamp(path.stat().st_mtime,tz=timezone.utc)+timedelta(hours=config['core_interval_hours'] if kind=='core' else 24*config['mlops_interval_days'])).isoformat()
        report['backups'].append(data)
    tracked=run(['git','diff','--name-only','HEAD']).decode().splitlines()
    untracked=run(['git','ls-files','--others','--exclude-standard']).decode().splitlines()
    candidates=sorted(set(tracked+untracked)); report['git_candidates']=candidates
    (LOCAL/'publish-files.txt').write_text('\n'.join(candidates)+'\n')
    (LOCAL/'final-state.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'services':len(report['services']),'all_running_and_checked':True,'preexisting_exact':report['preexisting_exact'],
       'candidate_files':len(candidates),'recovered_event_to_completed_seconds':fault['recovered_event_to_completed_seconds'],
       'next_due':{b['kind']:b['next_due_utc'] for b in report['backups']}}))


if __name__=='__main__':main()
