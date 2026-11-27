"""Privacy allowlist, persistent deduplication and window statistics."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import tempfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv('MONITOR_DATA', ROOT / 'mlops/local/monitoring/runtime'))
SECRETS = Path(os.getenv('MONITOR_SECRETS', ROOT / 'mlops/local/monitoring/secrets'))
CONFIG = json.loads(Path(__file__).with_name('config.json').read_text())
SOURCES = ('production', 'validation', 'synthetic', 'historical')
KEYS = ('model', 'category', 'version', 'engine', 'source')


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,suffix='.tmp',delete=False) as handle:
        handle.write(json.dumps(value, indent=2, allow_nan=False)); tmp=Path(handle.name)
    try: tmp.replace(path)
    finally: tmp.unlink(missing_ok=True)


def sanitize(row, secret):
    """Only returned fields can reach SQLite. No image/file/user/request UUID retained."""
    if row.get('model') not in ('B0', 'A1', 'T0', 'T1', 'T2'): raise ValueError('model')
    if row.get('category') not in ('bottle', 'hazelnut', 'leather'): raise ValueError('category')
    if row.get('engine') not in ('pytorch', 'onnxruntime'): raise ValueError('engine')
    if row.get('source') not in SOURCES: raise ValueError('source')
    if not re.fullmatch('[0-9a-f]{64}', str(row.get('version', ''))): raise ValueError('version')
    if row.get('decision') not in ('normal', 'anomaly'): raise ValueError('decision')
    for name in ('anomaly_score', 'threshold', 'inference_time_ms', 'timestamp'):
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value): raise ValueError(name)
        if name in ('anomaly_score', 'threshold') and not 0 <= value <= 1: raise ValueError(name)
        if name == 'inference_time_ms' and value < 0: raise ValueError(name)
    if row['decision'] != ('anomaly' if row['anomaly_score'] > row['threshold'] else 'normal'): raise ValueError('decision mismatch')
    if row['timestamp'] > time.time() + 60 or row['timestamp'] < 0: raise ValueError('timestamp')
    identity = row.get('identity')
    if not isinstance(identity, str) or not 1 <= len(identity) <= 160: raise ValueError('identity')
    return {'event_key': hmac.new(secret, identity.encode(), hashlib.sha256).hexdigest(),
            **{k: row[k] for k in (*KEYS, 'decision', 'anomaly_score', 'threshold', 'inference_time_ms', 'timestamp')}}


class Store:
    def __init__(self, path=None, secret=None):
        self.path = Path(path or os.getenv('MONITOR_STORE', DATA / 'predictions.sqlite3')); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = secret or (SECRETS / 'hmac_key').read_bytes()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS predictions (
                event_key TEXT PRIMARY KEY, model TEXT, category TEXT, version TEXT, engine TEXT, source TEXT,
                decision TEXT, anomaly_score REAL, threshold REAL, inference_time_ms REAL, timestamp REAL)''')
            db.execute('CREATE INDEX IF NOT EXISTS timestamp_idx ON predictions(timestamp)')
        if os.name!='nt': self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5); db.row_factory = sqlite3.Row
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db: yield db
        finally: db.close()

    def add(self, row):
        item = sanitize(row, self.secret)
        with self.connect() as db:
            # Explicit proxy provenance wins over generic SQL ingestion of the same upstream request.
            db.execute('''INSERT INTO predictions VALUES (:event_key,:model,:category,:version,:engine,:source,
                :decision,:anomaly_score,:threshold,:inference_time_ms,:timestamp)
                ON CONFLICT(event_key) DO UPDATE SET source=excluded.source
                WHERE predictions.source IN ('historical','production') AND excluded.source IN ('validation','synthetic')''', item)

    def prune(self, now=None):
        with self.connect() as db:
            count=db.execute('DELETE FROM predictions WHERE timestamp < ?', ((now or time.time()) - CONFIG['retention_days'] * 86400,)).rowcount
        if count:
            with self.connect() as db: db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return count

    def rows(self, now=None):
        with self.connect() as db:
            if self.path == Path(os.getenv('MONITOR_STORE', DATA/'predictions.sqlite3')):
                try:
                    demo=json.loads((DATA/'demo.json').read_text())
                    if 0 < demo.get('expires_at',0) < time.time():
                        db.executemany('DELETE FROM predictions WHERE event_key=?',[(k,) for k in demo.get('event_keys',[])])
                except (OSError,ValueError): pass
            return [dict(r) for r in db.execute('SELECT * FROM predictions WHERE timestamp >= ? ORDER BY timestamp',
                ((now or time.time()) - CONFIG['window_hours'] * 3600,))]


def grouped(rows):
    groups = {}
    for row in rows: groups.setdefault(tuple(row[k] for k in KEYS), []).append(row)
    return groups


def ks_distance(a, b):
    """Two empirical CDFs, including ties. Effect size only, no p-value claim."""
    from bisect import bisect_right
    if not a or not b: raise ValueError('empty distribution')
    a, b = sorted(a), sorted(b)
    return max(abs(bisect_right(a, x) / len(a) - bisect_right(b, x) / len(b)) for x in sorted(set(a + b)))


def compare(reference, rows, min_samples=None):
    minimum = min_samples or CONFIG['min_samples']
    result = {'reference_count': len(reference.get('scores', [])) if reference else 0, 'window_count': len(rows),
              'input_feature_drift': 'unavailable: image features are not collected', 'ground_truth_metrics': 'unavailable'}
    if not reference: return {**result, 'status': 'missing_reference'}
    scores = [r['anomaly_score'] for r in rows]
    threshold = reference['threshold']
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in scores + reference['scores']) or any(r['threshold'] != threshold for r in rows):
        return {**result, 'status': 'invalid_data'}
    if result['reference_count'] < minimum or len(rows) < minimum: return {**result, 'status': 'insufficient_data'}
    distance = ks_distance(reference['scores'], scores)
    reference_rate = sum(v > threshold for v in reference['scores']) / result['reference_count']
    window_rate = sum(r['decision'] == 'anomaly' for r in rows) / len(rows)
    return {**result, 'status': 'drift' if distance > CONFIG['ks_distance'] or abs(window_rate - reference_rate) > CONFIG['anomaly_rate_delta'] else 'stable',
            'ks_distance': distance, 'reference_anomaly_rate': reference_rate, 'window_anomaly_rate': window_rate,
            'anomaly_rate_delta': abs(window_rate - reference_rate), 'score_drift': distance > CONFIG['ks_distance'],
            'anomaly_rate_drift': abs(window_rate - reference_rate) > CONFIG['anomaly_rate_delta']}
