import ast
import hashlib
import os
import subprocess
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
import torch
import yaml
from mlops.dvc_pipeline import common
from mlops.dvc_pipeline.evaluate import metrics
from mlops.dvc_pipeline.model import DemoAutoencoder, load, save, seed_everything
from mlops.dvc_pipeline.preprocess import generate


def test_generated_data_repeats_and_has_independent_content():
    a=generate(16,32,123); b=generate(16,32,123); heldout=generate(16,32,2000123,8)
    assert np.array_equal(a,b) and a.dtype==np.float32 and a.shape==(16,1,32,32)
    digest=lambda values:{hashlib.sha256(v.tobytes()).hexdigest() for v in values}
    assert not digest(a)&digest(heldout)
    assert a.min()>=0 and heldout.max()<=1


def test_tied_auc_and_confusion_are_correct():
    result=metrics(np.array([0,0,1,1]),np.array([.1,.2,.2,.9]),.2)
    assert result['demo_auroc']==.875 and result['demo_accuracy']==.75
    assert result['demo_f1']==pytest.approx(2/3) and result['false_negative']==1


@pytest.mark.parametrize('scores,labels',[(np.array([np.nan,1]),np.array([0,1])),(np.array([0,1]),np.array([0,0]))])
def test_invalid_evaluation_rejected(scores,labels):
    with pytest.raises(ValueError): metrics(labels,scores,.5)


def test_model_roundtrip_and_actual_gradient_update(tmp_path,monkeypatch):
    monkeypatch.setattr(common,'WORK',tmp_path)
    seed_everything(42,1);model=DemoAutoencoder(4)
    original=model.network[0].weight.detach().clone()
    images=torch.from_numpy(generate(8,32,1));optimizer=torch.optim.Adam(model.parameters(),lr=.01)
    loss=((model(images)-images)**2).mean();loss.backward();optimizer.step()
    assert not torch.equal(original,model.network[0].weight)
    path=tmp_path/'model.json';save(path,model,4);loaded=load(path)
    assert all(torch.equal(value,loaded.state_dict()[name]) for name,value in model.state_dict().items())


def test_output_cannot_escape_work_or_follow_link(tmp_path,monkeypatch):
    work=tmp_path/'work';work.mkdir();monkeypatch.setattr(common,'WORK',work)
    with pytest.raises(ValueError):common.write(tmp_path/'official.json',{})
    target=tmp_path/'official';target.mkdir()
    try:(work/'redirect').symlink_to(target,target_is_directory=True)
    except OSError:
        if os.name!='nt': raise
        # Directory junctions need no Windows symlink privilege. Test the actual Windows escape path.
        subprocess.run(['cmd','/c','mklink','/J',str(work/'redirect'),str(target)],check=True,capture_output=True)
    with pytest.raises(ValueError):common.write(work/'redirect/model.json',{})
    assert not (target/'model.json').exists()


def test_every_parameter_is_consumed_and_dependencies_cover_local_imports():
    stages=yaml.safe_load((common.ROOT/'dvc.yaml').read_text())['stages']
    assert list(stages)==['preprocessing','training','evaluation']
    sections={'preprocessing':'data','training':'training','evaluation':'evaluation'}
    files={'preprocessing':'preprocess','training':'train','evaluation':'evaluate'}
    for name,section in sections.items():
        assert stages[name]['params']==[section]
        tree=ast.parse((common.MODULE/(files[name]+'.py')).read_text())
        used={node.slice.value for node in ast.walk(tree) if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name)
              and node.value.id=='config' and isinstance(node.slice,ast.Constant)}
        # Sample counts are accessed through a bounded dictionary loop.
        if name=='preprocessing':used|={'train_samples','calibration_samples','test_normal_samples','test_anomaly_samples'}
        assert used==common.PARAM_KEYS[section]
        deps=stages[name]['deps']
        assert 'mlops/dvc_pipeline/environment.json' in deps
        assert all(not Path(p).is_absolute() and '..' not in Path(p).parts for p in deps)
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.level==1:
                assert 'mlops/dvc_pipeline/'+node.module+'.py' in deps
        outputs=[o if isinstance(o,str) else next(iter(o)) for o in stages[name].get('outs',[])+stages[name].get('metrics',[])]
        assert all(p.startswith('mlops/dvc_pipeline/work/') for p in outputs)


def test_prefect_default_does_not_launch_anything():
    from mlops.dvc_pipeline.prefect_flow import launch
    with patch('subprocess.run',side_effect=AssertionError('Should not execute')):
        assert launch()=={'status':'disabled','training_authorized':False,'scheduled':False}


def test_invalid_demo_parameters_are_bounded():
    for value in (True,0,-1,5000):
        with pytest.raises(ValueError):common.integer(value,1,128)
    for value in (True,float('inf'),float('nan'),-1):
        with pytest.raises(ValueError):common.finite(value,0,1)
