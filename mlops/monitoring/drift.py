"""Read local metadata and produce bounded aggregate JSON/HTML, without images."""
import hashlib
import html
import json
import time
from .core import CONFIG, DATA, KEYS, Store, atomic_json, compare, grouped


def run(store=None):
    reference = DATA / 'reference.json'
    if hashlib.sha256(reference.read_bytes()).hexdigest() != (DATA / 'reference.sha256').read_text().strip(): raise ValueError('reference checksum')
    refs = {tuple(g[k] for k in KEYS[:-1]): g for g in json.loads(reference.read_text())['groups']}
    groups = grouped((store or Store()).rows())
    # Explicit insufficient-data rows for every reference even before first production observation.
    for key in refs: groups.setdefault((*key, 'production'), [])
    report = {'measured_at': time.time(), 'window_hours': CONFIG['window_hours'], 'min_samples': CONFIG['min_samples'],
        'method': 'two-sample empirical KS distance (effect size), plus absolute anomaly-rate difference',
        'threshold_policy': {'ks_distance': CONFIG['ks_distance'], 'anomaly_rate_delta': CONFIG['anomaly_rate_delta'],
                             'chosen_from': 'operational policy; no test-set optimization'},
        'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(), 'groups': []}
    for key, rows in sorted(groups.items()):
        report['groups'].append({**dict(zip(KEYS, key)), **compare(refs.get(key[:-1]), rows)})
    atomic_json(DATA / 'drift.json', report)
    body = '\n'.join('<tr>' + ''.join('<td>' + html.escape(str(g.get(k, '—'))) + '</td>' for k in (*KEYS, 'status', 'window_count', 'ks_distance', 'anomaly_rate_delta')) + '</tr>' for g in report['groups'])
    (DATA / 'drift.html').write_text('<!doctype html><meta charset="utf-8"><title>ResilientInspect drift</title><style>body{font:15px system-ui;margin:2rem}td,th{padding:8px;border:1px solid #ccc}table{border-collapse:collapse}td:nth-child(3){max-width:160px;overflow-wrap:anywhere}</style><h1>Monitoring des scores</h1><p>Référence : validation normale figée. Aucun calcul d’accuracy, AUROC ou F1 sans vérité terrain. Aucun drift des images : caractéristiques non collectées.</p><table><tr>' + ''.join('<th>' + k + '</th>' for k in (*KEYS, 'status', 'window_count', 'ks_distance', 'anomaly_rate_delta')) + '</tr>' + body + '</table>', encoding='utf-8')
    return report


if __name__ == '__main__':
    print(json.dumps({'drift_groups': len(run()['groups'])}))
