import math
import time
import pytest
from mlops.monitoring.core import Store, sanitize, compare, ks_distance
from mlops.monitoring.configure import rules
from mlops.monitoring.host import byte_value


def row(**kwargs):
    return {'identity':'private-request-uuid','model':'B0','category':'bottle','engine':'pytorch','version':'a'*64,
            'source':'production','anomaly_score':.2,'threshold':.5,'decision':'normal','inference_time_ms':12.,'timestamp':time.time(),**kwargs}


def test_privacy_and_deduplication(tmp_path):
    store=Store(tmp_path/'events.sqlite',b'private-test-key')
    item=row(filename='secret.png',user='person@example.com',image='base64-secret')
    store.add(item); store.add(item)
    data=store.rows()
    assert len(data)==1
    assert not {'identity','filename','user','image'} & data[0].keys()
    assert 'private-request-uuid' not in str(data)
    store.add(row(source='validation')); store.add(row(source='production'))
    assert store.rows()[0]['source']=='validation'
    assert Store(tmp_path/'events.sqlite',b'private-test-key').rows()==store.rows()


@pytest.mark.parametrize('changes',[{'anomaly_score':float('nan')},{'anomaly_score':float('inf')},{'anomaly_score':-1},
    {'anomaly_score':1.1},{'source':'test'},{'engine':'unknown'},{'version':'a/path'},{'decision':'anomaly'},
    {'inference_time_ms':-1},{'timestamp':time.time()+1000},{'model':'arbitrary'},{'threshold':True}])
def test_invalid_metadata_rejected(changes):
    with pytest.raises(ValueError): sanitize(row(**changes),b'key')


def test_retention_removes_old_only(tmp_path):
    store=Store(tmp_path/'events.sqlite',b'key')
    store.add(row(identity='old',timestamp=time.time()-8*86400)); store.add(row(identity='new'))
    assert store.prune()==1
    with store.connect() as db: assert db.execute('SELECT count(*) FROM predictions').fetchone()[0]==1


def test_distribution_ties_and_shift():
    assert ks_distance([0,0,1],[0,0,1])==0
    assert ks_distance([0]*30,[1]*30)==1
    reference={'scores':[.2]*40,'threshold':.5}
    assert compare(reference,[row() for _ in range(40)])['status']=='stable'
    shifted=compare(reference,[row(anomaly_score=1,decision='anomaly') for _ in range(40)])
    assert shifted['status']=='drift' and shifted['score_drift'] and shifted['anomaly_rate_drift']
    assert compare(reference,[row()])['status']=='insufficient_data'
    assert compare(None,[row()]*40)['status']=='missing_reference'
    assert compare(reference,[row(threshold=.6)]*40)['status']=='invalid_data'
    assert compare(reference,[row(anomaly_score=math.nan)]*40)['status']=='invalid_data'


def test_model_release_groups_are_separate(tmp_path):
    from mlops.monitoring.core import grouped
    store=Store(tmp_path/'events.sqlite',b'key')
    for n,change in enumerate([{}, {'engine':'onnxruntime'}, {'model':'A1'}, {'category':'leather'}, {'version':'b'*64}, {'source':'synthetic'}]):
        store.add(row(identity=str(n),**change))
    assert len(grouped(store.rows()))==6


def test_rules_and_units():
    generated=rules()['groups'][0]['rules']
    assert len(generated)==10 and len({r['alert'] for r in generated})==10
    assert all(r['for']=='20s' for r in generated)
    assert byte_value('1.5MiB')==1.5*1024**2
    assert byte_value('100kB')==100000


def test_reference_matches_archived_validation_without_test():
    from mlops.monitoring.reference import freeze
    refs=freeze()['groups']
    assert len(refs)==29
    assert all(len(g['scores'])>=30 for g in refs)
    assert not any(g['model']=='T1' and g['category']=='bottle' and g['engine']=='onnxruntime' for g in refs)
