"""Opt-in local demo MLflow store. Never connects to the official 30-run/Registry DB."""
import os
os.environ.setdefault('MLFLOW_DISABLE_TELEMETRY','true')
os.environ.setdefault('MLFLOW_DISABLE_AGENT_HINT','1')
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import mlflow
from mlflow import MlflowClient
from .common import LOCAL, ROOT, SCOPE, WORK, environment, git_identity, read, sha

EXPERIMENT='ResilientInspect-DVC-Pipeline-Demo'


def main():
    environment()
    training=read(WORK/'trained/training.json'); evaluation=read(WORK/'evaluation/report.json')
    if training['model_sha256']!=evaluation['model_sha256'] or sha(WORK/'trained/model.json')!=training['model_sha256']: raise ValueError('Mixed model/evaluation artifacts')
    lock=ROOT/'dvc.lock'
    if not lock.exists(): raise ValueError('Run dvc repro first')
    status=subprocess.run([sys.executable,'-m','dvc','status','dvc.yaml','--json'],cwd=ROOT,
        env={**os.environ,'DVC_SITE_CACHE_DIR':str(ROOT/'.dvc/site-cache')},capture_output=True,text=True,timeout=30)
    if status.returncode or json.loads(status.stdout): raise ValueError('DVC pipeline is not current; reproduce before tracking')
    payload={p:sha(ROOT/p) for p in ('dvc.lock','params.yaml')}
    payload.update({p.relative_to(ROOT).as_posix():sha(p) for p in (WORK/'trained/model.json',WORK/'evaluation/report.json')})
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    directory=LOCAL/'mlflow'; directory.mkdir(parents=True,exist_ok=True)
    uri='sqlite:///'+(directory/'tracking.db').as_posix()
    # Ignore MLFLOW_TRACKING_URI/REGISTRY_URI from the shell, including any official server.
    mlflow.set_tracking_uri(uri); mlflow.set_registry_uri(uri)
    client=MlflowClient(tracking_uri=uri,registry_uri=uri)
    experiment=client.get_experiment_by_name(EXPERIMENT)
    eid=experiment.experiment_id if experiment else client.create_experiment(EXPERIMENT,artifact_location=(directory/'artifacts').as_uri())
    existing=client.search_runs([eid],filter_string=f"tags.`demo.fingerprint` = '{fingerprint}' and attributes.status = 'FINISHED'")
    if existing:
        run_id=existing[0].info.run_id
    else:
        executions=[json.loads(row) for row in (LOCAL/'executions.jsonl').read_text().splitlines()]
        durations={}
        for stage in ('preprocessing','training','evaluation'):
            matches=[r for r in executions if r['stage']==stage and r['status']=='completed']
            if stage=='preprocessing': matches=[r for r in matches if r.get('manifest_sha256')==training['manifest_sha256']]
            else: matches=[r for r in matches if r.get('model_sha256')==training['model_sha256'] and r['parameters']==(training['parameters'] if stage=='training' else evaluation['parameters'])]
            durations[stage]=matches[-1]['duration_seconds'] if matches else None
        identity=git_identity()
        with mlflow.start_run(experiment_id=eid,run_name='procedural-tiny-ae-demo',tags={
            'demo.fingerprint':fingerprint,'scope':SCOPE,'git.commit':identity['commit'],'git.dirty':str(identity['dirty']),
            'dataset':'procedural_grayscale_stripes_v1','promotion':'disabled','dvc.lock.sha256':sha(lock)}) as run:
            manifest=read(WORK/'prepared/manifest.json')
            mlflow.log_params({**{'training.'+k:v for k,v in training['parameters'].items()},
                **{'data.'+k:v for k,v in manifest['data_parameters'].items()},**{'evaluation.'+k:v for k,v in evaluation['parameters'].items()},
                'dataset_manifest_sha256':training['manifest_sha256'],'architecture':training['architecture']})
            mlflow.log_metrics({**evaluation['metrics'],'initial_loss':training['initial_loss'],'final_loss':training['final_loss'],
                **{stage+'_seconds':value for stage,value in durations.items() if value is not None}})
            for name in ('dvc.yaml','dvc.lock','params.yaml','mlops/dvc_pipeline/environment.json','mlops/dvc_pipeline/recipe.json',
                         'mlops/dvc_pipeline/work/prepared/manifest.json','mlops/dvc_pipeline/work/trained/model.json',
                         'mlops/dvc_pipeline/work/trained/training.json','mlops/dvc_pipeline/work/evaluation/report.json'):
                mlflow.log_artifact(str(ROOT/name),artifact_path='demo_evidence')
            run_id=run.info.run_id
    result={'experiment':EXPERIMENT,'run_id':run_id,'scope':SCOPE,'fingerprint':fingerprint,'separate_database':True,
            'registered_models':len(client.search_registered_models()),'finished_runs':len(client.search_runs([eid]))}
    assert result['registered_models']==0
    (LOCAL/'mlflow-verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__': main()
