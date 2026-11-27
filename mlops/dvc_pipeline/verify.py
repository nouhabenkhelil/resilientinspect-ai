"""Real DVC incremental execution and byte-for-byte repeatability proof."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml
from .common import LOCAL, MODULE, ROOT, WORK, environment, read, sha


def child_env():
    return {**os.environ,'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'],
            'DVC_SITE_CACHE_DIR':str(ROOT/'.dvc/site-cache'),'DVC_NO_ANALYTICS':'true',
            'MLFLOW_DISABLE_TELEMETRY':'true','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}


def events():
    path=LOCAL/'executions.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def hashes(): return {p.relative_to(WORK).as_posix():sha(p) for p in WORK.rglob('*') if p.is_file()}


def mtimes(): return {p.relative_to(WORK).as_posix():p.stat().st_mtime_ns for p in WORK.rglob('*') if p.is_file()}


def dvc(name,*args):
    before=len(events()); start=time.perf_counter()
    result=subprocess.run([sys.executable,'-m','dvc',*args],cwd=ROOT,env=child_env(),capture_output=True,text=True,timeout=180)
    log=LOCAL/(name+'.log'); log.parent.mkdir(parents=True,exist_ok=True);log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode: raise RuntimeError('DVC failed: '+name+'; inspect local log')
    return {'command':'dvc '+' '.join(args),'exit_code':result.returncode,'duration_seconds':time.perf_counter()-start,
            'executed_stages':[row['stage'] for row in events()[before:]],'output':result.stdout+result.stderr}


def main():
    runtime=environment(); LOCAL.mkdir(parents=True,exist_ok=True)
    params_path=ROOT/'params.yaml'; model_path=MODULE/'model.py'
    original_params=params_path.read_bytes(); original_model=model_path.read_bytes()
    config=yaml.safe_load(original_params)
    # No reset, checkout, pull, gc, add or official-pointer commands occur here.
    cases={}
    try:
        cases['dag']=dvc('dag','dag')
        assert all(name in cases['dag']['output'] for name in ('preprocessing','training','evaluation'))
        cases['reference_recompute']=dvc('reference-recompute','repro','--force','--no-run-cache')
        assert cases['reference_recompute']['executed_stages']==['preprocessing','training','evaluation']
        baseline=hashes(); times=mtimes()
        cases['unchanged']=dvc('unchanged','repro')
        assert cases['unchanged']['executed_stages']==[] and hashes()==baseline and mtimes()==times
        config['training']['seed']+=1
        params_path.write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf-8')
        cases['training_seed_change']=dvc('training-seed-change','repro')
        assert cases['training_seed_change']['executed_stages']==['training','evaluation']
        assert sha(WORK/'trained/model.json')!=baseline['trained/model.json']
        assert sha(WORK/'prepared/manifest.json')==baseline['prepared/manifest.json']
        model_hash=sha(WORK/'trained/model.json')
        config['evaluation']['normal_quantile']=.9
        params_path.write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf-8')
        cases['evaluation_parameter_change']=dvc('evaluation-parameter-change','repro')
        assert cases['evaluation_parameter_change']['executed_stages']==['evaluation']
        assert sha(WORK/'trained/model.json')==model_hash
        params_path.write_bytes(original_params)
        cases['restore_parameters']=dvc('restore-parameters','repro')
        assert hashes()==baseline
        model_path.write_bytes(original_model+b'\n# Temporary dependency verification; restored by verify.py.\n')
        cases['model_dependency_change']=dvc('model-dependency-change','repro')
        assert cases['model_dependency_change']['executed_stages']==['training','evaluation']
        model_path.write_bytes(original_model)
        cases['restore_dependency']=dvc('restore-dependency','repro')
        cases['independent_recompute']=dvc('independent-recompute','repro','--force','--no-run-cache')
        assert cases['independent_recompute']['executed_stages']==['preprocessing','training','evaluation']
        assert hashes()==baseline,'Independent execution produced different output bytes'
        cases['final_unchanged']=dvc('final-unchanged','repro')
        assert cases['final_unchanged']['executed_stages']==[]
        cases['status']=dvc('pipeline-status','status','dvc.yaml','--json')
        assert json.loads(cases['status']['output'])=={}
        training=read(WORK/'trained/training.json')
        assert training['optimizer_steps']>0 and training['weight_delta_squared']>0 and training['final_loss']<training['initial_loss']
        proof={'status':'passed','environment':runtime,'cases':cases,'output_sha256':baseline,
               'bitwise_identical_independent_recomputes':True,'duration_receipts_outside_cached_outputs':True,
               'training':training,'demo_metrics':read(WORK/'evaluation/metrics.json'),
               'existing_release_pointers_retrieved':False,'remote_required':False}
        (LOCAL/'reproduction-verification.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
        print(json.dumps({'status':'passed','executed_stages_by_case':{k:v['executed_stages'] for k,v in cases.items()},
                          'identical_output_files':len(baseline),'demo_metrics':proof['demo_metrics']}))
    finally:
        params_path.write_bytes(original_params);model_path.write_bytes(original_model)


if __name__=='__main__': main()
