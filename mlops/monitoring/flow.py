"""Separate Prefect flow. Only host measurements and local drift reports; no training."""
import asyncio
import json
import os
import subprocess
import sys
from .core import ROOT

os.environ.setdefault('PREFECT_API_URL','http://127.0.0.1:4200/api')
os.environ.setdefault('PREFECT_SERVER_ALLOW_EPHEMERAL_MODE','false')
os.environ.setdefault('PREFECT_HOME',str(ROOT/'mlops/local/prefect'))
from prefect import flow, task
from prefect.cache_policies import NO_CACHE


@task(retries=1,retry_delay_seconds=2,timeout_seconds=50,cache_policy=NO_CACHE,persist_result=False)
async def bounded_measurement(kind):
    args = [str(ROOT/'.venv-monitoring/Scripts/python.exe'),'-m','mlops.monitoring.host'] if kind=='host' else [
        'docker','exec','resilientinspect-mlops-monitoring-collector-1','python','-m','mlops.monitoring.drift']
    def invoke():
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=40)
        if result.returncode: raise RuntimeError('Monitoring '+kind+' failed; details withheld')
        return json.loads(result.stdout)
    return await asyncio.to_thread(invoke)


@flow(name='resilientinspect-monitoring-drift',retries=0,timeout_seconds=100,persist_result=False,log_prints=False)
async def monitoring_flow():
    host=await bounded_measurement('host')
    drift=await bounded_measurement('drift')
    return {'host':host,'drift':drift}


if __name__=='__main__':
    if '--serve' in sys.argv:
        from prefect.schedules import Interval
        monitoring_flow.serve(name='local-monitoring',schedule=Interval(60,timezone='Africa/Lagos'),limit=1,
            pause_on_shutdown=True,tags=['local','monitoring','no-training'])
    else: asyncio.run(monitoring_flow())
