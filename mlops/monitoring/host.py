"""Windows host psutil + read-only Docker CLI stats. Never mount docker.sock."""
import json
import re
import subprocess
import time
import psutil
from .core import DATA, atomic_json


def command(args):
    return subprocess.check_output(args, text=True, timeout=25, stderr=subprocess.DEVNULL)


def byte_value(value):
    match=re.fullmatch(r'([\d.]+)([kKMGT]?i?B)',value.strip())
    if not match: raise ValueError('Docker memory unit')
    number, unit=match.groups()
    power={'B':0,'kB':1,'KB':1,'KiB':1,'MB':2,'MiB':2,'GB':3,'GiB':3,'TB':4,'TiB':4}[unit]
    return float(number)*(1024 if 'i' in unit else 1000)**power


def collect():
    memory=psutil.virtual_memory()
    result={'measured_at':time.time(),'scope':'Windows host; per-container Docker Desktop CPU uses one core = 100%',
            'cpu_ratio':psutil.cpu_percent(interval=1)/100,'memory_ratio':memory.percent/100,
            'memory_used_bytes':memory.used,'memory_total_bytes':memory.total,'containers':[]}
    items=[json.loads(s) for s in command(['docker','ps','-a','--format','{{json .}}']).splitlines()]
    names=[i['Names'] for i in items if i['Names'].startswith(('resilientinspect-industrial-','resilientinspect-observability-','resilientinspect-mlops-monitoring-'))]
    stats={}
    if names:
        stats={r['Name']:r for r in [json.loads(s) for s in command(['docker','stats','--no-stream','--format','{{json .}}',*names]).splitlines()]}
    for item in items:
        if item['Names'] not in names: continue
        row={'container':item['Names'],'up':int(item['State']=='running')}
        if item['Names'] in stats:
            sample=stats[item['Names']]; used,limit=sample['MemUsage'].split('/')
            row.update(cpu_ratio=float(sample['CPUPerc'].rstrip('%'))/100,memory_bytes=byte_value(used),memory_limit_bytes=byte_value(limit))
        result['containers'].append(row)
    atomic_json(DATA/'host.json',result)
    return result


if __name__=='__main__': print(json.dumps({'host_collected':True,'containers':len(collect()['containers'])}))
