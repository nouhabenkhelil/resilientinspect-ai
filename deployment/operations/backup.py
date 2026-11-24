"""Encrypted, manifested backups. Live quiescence requires explicit approved-maintenance flag."""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import time
import msvcrt
import sys
import urllib.request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'deployment/industrial/local/observability'
DC = ['docker', 'compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml']
MAGIC = b'RIBKP3\r\n'


def run(args, output=None, data=None, timeout=180):
    try: result = subprocess.run(args, cwd=ROOT, input=data, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,timeout=timeout)
    except subprocess.TimeoutExpired: raise RuntimeError('Docker operation timed out; private diagnostics withheld') from None
    if result.returncode: raise RuntimeError('Backup operation failed; raw diagnostics withheld')
    return result.stdout


def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def encrypt(source, target, key):
    nonce = secrets.token_bytes(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(MAGIC)
    with Path(source).open('rb') as origin, Path(target).open('wb') as out:
        out.write(MAGIC + nonce)
        while chunk := origin.read(1024 * 1024): out.write(cipher.update(chunk))
        out.write(cipher.finalize()); out.write(cipher.tag)


def decrypt(source, target, key):
    size = Path(source).stat().st_size
    with Path(source).open('rb') as origin, Path(target).open('wb') as out:
        if origin.read(8) != MAGIC or size < 36: raise ValueError('Invalid encrypted archive')
        nonce = origin.read(12); origin.seek(-16, 2); tag = origin.read(16); origin.seek(20)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor(); cipher.authenticate_additional_data(MAGIC)
        remaining = size - 36
        while remaining:
            chunk = origin.read(min(1024 * 1024, remaining))
            if not chunk: raise ValueError('Truncated encrypted archive')
            remaining -= len(chunk); out.write(cipher.update(chunk))
        out.write(cipher.finalize())  # No extraction before authentication succeeds.


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with tarfile.open(archive) as packed:
        for member in packed:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '\\' in member.name or ':' in member.name or '..' in name.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe archive member')
            target = destination.joinpath(*name.parts).resolve()
            if not target.is_relative_to(destination): raise ValueError('Archive path escaped destination')
            if member.isdir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with packed.extractfile(member) as origin, target.open('wb') as out: shutil.copyfileobj(origin, out)


@contextmanager
def staging(config):
    parent = (Path(config['backup_root']) / '.staging').resolve(); parent.mkdir(parents=True, exist_ok=True)
    path = parent / secrets.token_hex(16); path.mkdir()
    try: yield path
    finally:
        resolved = path.resolve()
        if resolved.parent != parent or path.is_symlink(): raise RuntimeError('Unsafe staging cleanup target')
        shutil.rmtree(resolved)  # Only this newly created private staging directory; never a Docker volume.


def event(config, event_name, **values):
    row = {'at': datetime.now(timezone.utc).isoformat(), 'event': event_name, **values}
    with (Path(config['backup_root']) / 'operations.jsonl').open('a', encoding='utf-8') as out: out.write(json.dumps(row) + '\n')


def volume_snapshot(volume, target):
    if volume not in {'resilientinspect-industrial_idp-data', 'resilientinspect-industrial_batch-images'}: raise ValueError('Unexpected volume')
    code = "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); t.add('/data',arcname='data'); t.close()"
    with Path(target).open('wb') as out:
        run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '0', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
             '-v', volume + ':/data:ro', 'resilientinspect-portal:local', 'python', '-c', code], output=out)


def await_recovery(services, timeout=150):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        try:
            for service,url in [('web','http://localhost:18180/api/health'),('idp','http://localhost:18585/realms/resilientinspect/.well-known/openid-configuration')]:
                if service in services:
                    with urllib.request.urlopen(url,timeout=4) as response:
                        if response.status!=200: raise RuntimeError('Not ready')
            if 'worker' in services: run(DC+['exec','-T','worker','python','-m','portal.batch_worker','--health'])
            return
        except Exception: time.sleep(2)
    raise RuntimeError('Backup finished, but service recovery did not become healthy')


@contextmanager
def backup_lock(config):
    with (Path(config['backup_root']) / '.backup.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError: raise RuntimeError('Another backup process owns the maintenance lock') from None
        try: yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def create(config, kind, approved=False):
    with backup_lock(config): return create_locked(config, kind, approved)


def create_locked(config, kind, approved=False):
    if kind == 'core' and not approved: raise ValueError('Explicit live-maintenance approval required')
    began = time.monotonic(); identity = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3)
    root = Path(config['backup_root']).resolve(); key = Path(config['key_file']).read_bytes()
    if len(key) != 32: raise ValueError('A separate 256-bit backup key is required')
    event(config, 'backup.started', kind=kind, id=identity)
    stopped = []; downtime=None
    with staging(config) as stage:
        try:
            if kind == 'core':
                for service in ('web', 'portal', 'worker', 'idp'):
                    cid = run(DC + ['ps', '-q', service]).decode().strip()
                    if cid: stopped.append(service)
                if stopped:
                    outage_start=time.monotonic()
                    run(DC + ['stop', '-t', '110', *stopped])
                with (stage / 'portal.dump').open('wb') as out:
                    run(DC + ['exec', '-T', 'postgres', 'pg_dump', '-U', 'ri_migrator', '-d', 'portal', '-Fc'], output=out)
                snapshot_sql = "SELECT jsonb_build_object('users',(SELECT jsonb_agg(to_jsonb(u) ORDER BY u.id) FROM users u),'inspections',(SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM inspections i),'batches',(SELECT jsonb_agg(to_jsonb(b) ORDER BY b.id) FROM inspection_batches b),'items',(SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM batch_items i),'releases',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM model_releases r));"
                (stage / 'business.json').write_bytes(run(DC + ['exec', '-T', 'postgres', 'psql', '-U', 'ri_migrator', '-d', 'portal', '-qAtc', snapshot_sql]))
                volume_snapshot('resilientinspect-industrial_idp-data', stage / 'keycloak.tar')
                volume_snapshot('resilientinspect-industrial_batch-images', stage / 'images.tar')
                config_dir = stage / 'config'; config_dir.mkdir()
                for name in ('.env', 'realm.json', 'accounts.json'):
                    shutil.copy2(ROOT / 'deployment/industrial/local' / name, config_dir / name)
                observability=config_dir/'observability'; observability.mkdir()
                shutil.copytree(LOCAL/'secrets',observability/'secrets')
                for name in ('prometheus-web.yml','datasource.yml','backup-config.json','.env'):
                    shutil.copy2(LOCAL/name,observability/name)
                # Reconstruct dirty operational sources without collecting datasets, weights or secrets.
                (config_dir/'workspace.patch').write_bytes(run(['git','diff','--binary','HEAD']))
                runtime={}
                for service in ('postgres','idp','science','portal','worker','web'):
                    cid=run(DC+['ps','-a','-q',service]).decode().strip()
                    details=json.loads(run(['docker','inspect',cid]))[0]
                    runtime[service]={'image_id':details['Image'],'image_reference':details['Config']['Image']}
                (config_dir/'runtime-images.json').write_text(json.dumps(runtime,indent=2))
                sources=config_dir/'operational-sources'
                for relative in ('services/portal','deployment/operations','frontend/src/portal','deployment/industrial/compose.yml','frontend/nginx.portal.conf'):
                    origin=ROOT/relative; target=sources/relative; target.parent.mkdir(parents=True,exist_ok=True)
                    if origin.is_dir(): shutil.copytree(origin,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                    else: shutil.copy2(origin,target)
            else:
                # MLflow/DVC have a different, weekly cycle; no application outage required.
                mlflow_root = Path(config['mlflow_root']).resolve()
                with closing(sqlite3.connect(f'file:{(mlflow_root / "tracking.db").as_posix()}?mode=ro', uri=True)) as original:
                    with closing(sqlite3.connect(stage / 'tracking.db')) as copy: original.backup(copy)
                for label, source in [('mlflow-artifacts', mlflow_root / 'artifacts'), ('dvc-store', Path(config['dvc_root']))]:
                    before = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
                    with tarfile.open(stage / (label + '.tar'), 'w') as archive: archive.add(source, arcname='data')
                    if before != {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}: raise RuntimeError('MLOps store changed during snapshot')
                    (stage / (label + '-files.json')).write_text(json.dumps(before))
                shutil.copy2(ROOT / 'mlops/release-manifest.json', stage / 'release-manifest.json')
        finally:
            # Start the exact existing containers, without Compose starting migration dependencies.
            if stopped:
                for service in reversed(stopped):
                    cid=run(DC+['ps','-a','-q',service]).decode().strip()
                    if not cid: raise RuntimeError('Previously running service container disappeared')
                    run(['docker','start',cid])
                await_recovery(stopped)
                downtime=round(time.monotonic()-outage_start,3)
        entries = {p.relative_to(stage).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in stage.rglob('*') if p.is_file()}
        inner = {'schema': 1, 'kind': kind, 'id': identity, 'git_head': run(['git', 'rev-parse', 'HEAD']).decode().strip(), 'files': entries}
        (stage / 'manifest.json').write_text(json.dumps(inner, indent=2))
        plain = stage / 'archive.tar'
        with tarfile.open(plain, 'w') as archive:
            for name in [*entries, 'manifest.json']: archive.add(stage / name, arcname=name, recursive=False)
        target = root / f'{kind}-{identity}.ri3'
        encrypt(plain, target, key)
        metadata = {'schema': 1, 'kind': kind, 'id': identity, 'archive': target.name, 'sha256': sha(target), 'bytes': target.stat().st_size,
                    'finished_at': datetime.now(timezone.utc).isoformat(), 'duration_seconds': round(time.monotonic() - began, 3), 'service_recovery_seconds':downtime}
        target.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
    event(config, 'backup.completed', **metadata)
    rotate(config,kind)
    (LOCAL / 'backup-status.json').write_text(json.dumps(metadata))
    return metadata


def rotate(config,kind):
    # Rotation is confined to our own, validated archive/manifest pairs under the configured private root.
    root=Path(config['backup_root']).resolve()
    records = sorted(root.glob(kind + '-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for record in records[config['keep_' + kind]:]:
        data = json.loads(record.read_text()); archive = root / data['archive']
        if not re.fullmatch(kind+r'-\d{8}T\d{6}Z-[a-f0-9]{6}',record.stem) or archive.stem!=record.stem or data['kind']!=kind or archive.parent != root or archive.suffix != '.ri3': raise ValueError('Unsafe rotation member')
        if sha(archive) != data['sha256']: raise ValueError('Rotation integrity mismatch')
        archive.unlink(); record.unlink(); event(config, 'backup.rotated', id=data['id'], kind=kind)


def unpack(config, archive, destination):
    archive = Path(archive).resolve(); metadata = json.loads(archive.with_suffix('.json').read_text())
    if sha(archive) != metadata['sha256']: raise ValueError('Encrypted archive SHA256 mismatch')
    plain = Path(destination) / 'authenticated.tar'
    decrypt(archive, plain, Path(config['key_file']).read_bytes())
    safe_extract(plain, destination); plain.unlink()
    manifest = json.loads((Path(destination) / 'manifest.json').read_text())
    for name, entry in manifest['files'].items():
        path = Path(destination) / name
        if not path.resolve().is_relative_to(Path(destination).resolve()) or sha(path) != entry['sha256']: raise ValueError('Restored file integrity mismatch')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['core', 'mlops', 'daemon'])
    parser.add_argument('--approved-maintenance', action='store_true')
    args = parser.parse_args(); config = json.loads((LOCAL / 'backup-config.json').read_text())
    if args.action != 'daemon': print(json.dumps(create(config, args.action, args.approved_maintenance))); return
    if not args.approved_maintenance: raise SystemExit('Recurring live-maintenance approval required')
    (LOCAL/'daemon.json').write_text(json.dumps({'pid':os.getpid(),'started_at':datetime.now(timezone.utc).isoformat(),
        'python':sys.executable,'core_hours':config['core_interval_hours'],'mlops_days':config['mlops_interval_days']}))
    event(config,'daemon.started',pid=os.getpid())
    while True:
        for kind, seconds in [('core', config['core_interval_hours'] * 3600), ('mlops', config['mlops_interval_days'] * 86400)]:
            records = list(Path(config['backup_root']).glob(kind + '-*.json'))
            if not records or time.time() - max(p.stat().st_mtime for p in records) >= seconds:
                try: create(config, kind, approved=True)
                except Exception: event(config, 'backup.failed', kind=kind)
        time.sleep(60)


if __name__ == '__main__': main()
