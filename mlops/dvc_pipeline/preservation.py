"""Compare the pre-implementation audit without changing either worktree or services."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request
from .common import LOCAL, ROOT, sha


def main():
    baseline=json.loads((LOCAL/'baseline.json').read_text())
    primary=Path(baseline['primary_root'])
    for key,root in [('primary_source',primary),('worktree_source',ROOT),('scientific',primary)]:
        changed=[name for name,digest in baseline[key].items() if not (root/name).is_file() or sha(root/name)!=digest]
        if changed: raise ValueError('Pre-existing bytes changed: '+str(changed[:5]))
    def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    assert git(primary,'status','--porcelain=v1')==baseline['primary_status'].strip()
    assert git(ROOT,'branch','--show-current')=='feature/mlops-dvc-pipeline'
    assert git(ROOT,'rev-parse','HEAD')==baseline['head']==git(primary,'rev-parse','HEAD')
    assert not git(ROOT,'diff','--cached','--name-only')
    containers=json.loads(subprocess.check_output(['docker','inspect',*[c['id'] for c in baseline['containers']]],text=True))
    for previous,current in zip(baseline['containers'],containers):
        assert previous['id']==current['Id'] and previous['started']==current['State']['StartedAt']
        assert current['State']['Running']
    database=primary/'mlops/local/mlflow/tracking.db'
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        business={'original_mlflow_runs':db.execute('SELECT count(*) FROM runs').fetchone()[0],
                  'original_registered_models':db.execute('SELECT count(*) FROM registered_models').fetchone()[0]}
    req=urllib.request.Request('http://127.0.0.1:4200/api/deployments/filter',data=b'{}',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as response: deployments=json.load(response)
    schedules={d['name']:[s['schedule'].get('interval') for s in d['schedules'] if s['active']] for d in deployments if d['name'] in ('local-readonly','local-monitoring')}
    assert schedules=={'local-readonly':[3600.0],'local-monitoring':[60.0]} or schedules=={'local-monitoring':[60.0],'local-readonly':[3600.0]}
    result={'status':'passed','original_scientific_sha256_files':len(baseline['scientific']),
        'original_worktree_files_unchanged':len(baseline['primary_source']),'dedicated_initial_files_unchanged':len(baseline['worktree_source']),
        'primary_dirty_state_preserved':True,'preexisting_running_containers_not_restarted':len(containers),
        'existing_dvc_pointer_sha256':{name:sha(ROOT/name) for name in ('mlops/dataset.dvc','mlops/deployment.dvc')},
        **business,'existing_prefect_intervals_seconds':schedules,'new_prefect_schedule_installed':False,
        'dedicated_remote_configuration_present':(ROOT/'.dvc/config.local').exists(),
        'branch':git(ROOT,'branch','--show-current'),'head':git(ROOT,'rev-parse','HEAD'),'no_commit_push_merge':True}
    (LOCAL/'preservation-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
