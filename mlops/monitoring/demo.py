"""Expiring synthetic-only alert fixtures and reversible local score drift."""
import hashlib
import hmac
import json
import time
from .core import DATA, KEYS, Store, atomic_json
from .drift import run


def apply(action):
    store=Store()
    reference=next(g for g in json.loads((DATA/'reference.json').read_text())['groups'] if g['model']=='B0' and g['category']=='bottle' and g['engine']=='pytorch')
    identities=['monitoring-demo-v1:'+str(i) for i in range(len(reference['scores']))]
    keys=[hmac.new(store.secret,i.encode(),hashlib.sha256).hexdigest() for i in identities]
    with store.connect() as db: db.executemany('DELETE FROM predictions WHERE event_key=?',[(k,) for k in keys])
    if action in ('stable','shift','alerts'):
        for identity,score in zip(identities,reference['scores']):
            score=1.0 if action in ('shift','alerts') else score
            store.add({**{k:reference[k] for k in KEYS[:-1]},'source':'synthetic','identity':identity,
                'anomaly_score':score,'threshold':reference['threshold'],'decision':'anomaly' if score>reference['threshold'] else 'normal',
                'inference_time_ms':0.0,'timestamp':time.time()})
    atomic_json(DATA/'demo.json',{'expires_at':time.time()+150 if action=='alerts' else 0,'source':'synthetic','event_keys':keys})
    report=run(store)
    return {'action':action,'source':'synthetic','controlled_rows':len(identities),
            'groups':[g for g in report['groups'] if g['source']=='synthetic']}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['stable','shift','alerts','resolve']); args=parser.parse_args()
    print(json.dumps(apply(args.action)))
