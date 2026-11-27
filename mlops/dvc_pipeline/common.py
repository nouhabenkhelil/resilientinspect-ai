"""Explicit inputs, fixed private outputs, deterministic serialization and run receipts."""
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import stat
import sys
import time
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'mlops/dvc_pipeline'
WORK = MODULE / 'work'
LOCAL = ROOT / 'mlops/local/dvc_pipeline'
SCOPE = 'development_demo_only'
PARAM_KEYS = {
    'data': {'seed','image_size','train_samples','calibration_samples','test_normal_samples','test_anomaly_samples'},
    'training': {'seed','epochs','batch_size','learning_rate','channels','cpu_threads'},
    'evaluation': {'normal_quantile'},
}


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    # Stages have no user-selectable output path. Refuse symlinks/junctions into official storage.
    if not path.is_relative_to(WORK) or not path.resolve().is_relative_to(WORK): raise ValueError('Output outside demo work directory')
    for candidate in (path,*path.parents):
        if candidate==ROOT: break
        if candidate.is_symlink() or (candidate.exists() and getattr(candidate.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0)):
            raise ValueError('Linked output path refused')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def params(section):
    config = yaml.safe_load((ROOT/'params.yaml').read_text(encoding='utf-8'))
    result = config.get(section)
    if not isinstance(result,dict) or set(result) != PARAM_KEYS[section]: raise ValueError('Unexpected parameters: '+section)
    return result


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ValueError('Integer outside demo bounds')
    return value


def finite(value, low, high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high: raise ValueError('Invalid finite parameter')
    return value


def environment():
    expected = read(MODULE/'environment.json')
    actual = {'python':sys.version.split()[0], 'packages':{p:importlib.metadata.version(p) for p in expected['packages']},'device':'cpu'}
    if actual['python'] != expected['python'] or actual['packages'] != expected['packages']: raise RuntimeError('Environment differs from declared CPU versions; no automatic dependency change')
    return actual


def git_identity():
    def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=10).strip()
    return {'commit':git('rev-parse','HEAD'),'branch':git('branch','--show-current'),'dirty':bool(git('status','--porcelain'))}


@contextmanager
def execution(stage):
    runtime = environment(); started = time.perf_counter()
    receipt = {'stage':stage,'execution_id':uuid.uuid4().hex,'scope':SCOPE,'environment':runtime,'git':git_identity()}
    try:
        yield receipt
        receipt['status']='completed'
    except Exception:
        receipt['status']='failed'
        raise
    finally:
        receipt['duration_seconds']=time.perf_counter()-started
        LOCAL.mkdir(parents=True,exist_ok=True)
        with (LOCAL/'executions.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(receipt,allow_nan=False)+'\n')


def load_array(name):
    import numpy as np
    path = WORK/'prepared'/name
    manifest = read(WORK/'prepared/manifest.json')
    if sha(path) != manifest['files'][name]: raise ValueError('Prepared array checksum mismatch')
    value = np.load(path,allow_pickle=False)
    if not np.isfinite(value).all(): raise ValueError('Nonfinite prepared input')
    return value
