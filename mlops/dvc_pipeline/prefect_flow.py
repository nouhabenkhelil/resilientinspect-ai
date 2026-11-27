"""Optional manual entry point; disabled by default and never registered on a schedule."""
import argparse
import os
from pathlib import Path
import subprocess
from .common import LOCAL, ROOT


def launch(enabled=False,python=None):
    if not enabled: return {'status':'disabled','training_authorized':False,'scheduled':False}
    executable=Path(python or '')
    if not executable.is_file(): raise ValueError('Explicit existing DVC/CPU interpreter required')
    os.environ.setdefault('PREFECT_API_URL','http://127.0.0.1:4200/api')
    os.environ.setdefault('PREFECT_SERVER_ALLOW_EPHEMERAL_MODE','false')
    os.environ.setdefault('PREFECT_HOME',str(LOCAL/'prefect'))
    from prefect import flow,task
    from prefect.cache_policies import NO_CACHE

    @task(retries=0,timeout_seconds=180,cache_policy=NO_CACHE,persist_result=False)
    def reproduce():
        env={**os.environ,'PATH':str(executable.parent)+os.pathsep+os.environ['PATH'],
             'DVC_SITE_CACHE_DIR':str(ROOT/'.dvc/site-cache'),'DVC_NO_ANALYTICS':'true'}
        result=subprocess.run([str(executable),'-m','dvc','repro'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=160)
        if result.returncode: raise RuntimeError('Manual demo reproduction failed; details withheld')
        return {'status':'completed','scope':'development_demo_only','scheduled':False}

    @flow(name='resilientinspect-dvc-demo-manual',timeout_seconds=200,retries=0,persist_result=False)
    def manual_flow(): return reproduce()
    return manual_flow()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--enabled',action='store_true');parser.add_argument('--python');args=parser.parse_args()
    print(launch(args.enabled,args.python))
