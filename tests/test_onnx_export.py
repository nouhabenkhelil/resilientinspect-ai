"""Real small ONNX graphs for contracts; fixtures never count as scientific parity."""
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import torch

from backend.app.config import Settings
from backend.app.models import LoadedModel, ModelStore
from backend.app.schemas import ModelMetadata
from backend.app.inference import predict
from backend.app.errors import APIError
from resilientinspect.models.autoencoder import ConvAutoencoder
from resilientinspect.data.dataset import letterbox_pair
from PIL import Image
from resilientinspect.export import onnx_runtime as runtime, onnx_cli
from test_backend_api import client, store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph(tmp_path_factory):
    torch.set_num_threads(2)
    directory = tmp_path_factory.mktemp("onnx_graph")
    checkpoint = directory / "best.pt"
    network = ConvAutoencoder().eval().requires_grad_(False)
    torch.save(network.state_dict(), checkpoint)
    meta = ModelMetadata(model="B0", category="bottle", version=runtime._sha256(checkpoint),
        checkpoint_sha256=runtime._sha256(checkpoint), calibration_sha256="a"*64, threshold=.2,
        normalization="RGB [0,1]",score="fixture",explanation="reconstruction_error",serving_environment={})
    loaded = LoadedModel(network,meta)
    return directory,checkpoint,loaded


def test_real_static_export_checker_session_and_fp32_parity(graph,monkeypatch):
    directory,checkpoint,loaded=graph
    monkeypatch.setattr(runtime,"artifact_directory",lambda *args: directory)
    with pytest.warns((DeprecationWarning, torch.jit.TracerWarning)):
        onnx_cli.export(ROOT,loaded,checkpoint)
    runtime.verify_artifact(ROOT,loaded.metadata)
    session=runtime.session(directory/"model.onnx")
    tensor=torch.rand(1,3,256,256)
    with torch.inference_mode(): expected=loaded.network(tensor).numpy()
    actual=session.run(None,{"images":tensor.numpy()})[0]
    assert session.get_providers()==["CPUExecutionProvider"]
    np.testing.assert_allclose(actual,expected,atol=1e-4,rtol=1e-4)
    assert actual.shape==(1,3,256,256) and actual.dtype==np.float32


def test_graph_hash_and_source_calibration_cannot_be_substituted(graph,monkeypatch):
    directory,_,loaded=graph
    monkeypatch.setattr(runtime,"artifact_directory",lambda *args: directory)
    changed=loaded.metadata.model_copy(update={"calibration_sha256":"b"*64})
    with pytest.raises(ValueError,match="binding"):
        runtime.verify_artifact(ROOT,changed)
    graph_path=directory/"model.onnx"
    original=graph_path.read_bytes()
    graph_path.write_bytes(original+b"tampered")
    try:
        with pytest.raises(ValueError,match="SHA256"):
            runtime.verify_artifact(ROOT,loaded.metadata)
    finally: graph_path.write_bytes(original)


def test_missing_failed_or_unbound_parity_refused(graph,monkeypatch):
    directory,_,loaded=graph
    monkeypatch.setattr(runtime,"artifact_directory",lambda *args: directory)
    path=directory/"parity-windows.json"
    runtime.write_json(path,{"status":"failed"})
    with pytest.raises(ValueError,match="parity"):
        runtime.admit(ROOT,loaded.metadata)
    path.write_text('{}')
    with pytest.raises(ValueError,match="SHA256"):
        runtime.admit(ROOT,loaded.metadata)


def test_score_policy_and_nonfinite_outputs():
    assert runtime.score_parity(.2,.20000001,.2)["decision_passed"]
    assert not runtime.score_parity(.1,.3,.2)["decision_passed"]
    sample=letterbox_pair(Image.new('RGB',(100,80)),Image.new('L',(100,80)),(256,256))
    with pytest.raises(ValueError,match="output"):
        runtime.score_output(np.full((1,),np.nan,dtype=np.float32),sample,"T2")


def test_cache_reuses_and_bounds_sessions(monkeypatch):
    monkeypatch.setattr(runtime,"session",lambda path: object())
    cache=runtime.SessionCache(2)
    first=cache.get("a")
    assert cache.get("a") is first
    cache.get("b");cache.get("c")
    assert len(cache.items)==2 and "a" not in cache.items


def test_benchmark_statistics_and_minimum_measurement_contract(graph):
    result=onnx_cli.stats([1.,2.,3.])
    assert result['mean_ms']==2 and result['p50_ms']==2
    assert result['p95_ms']==pytest.approx(2.9) and result['images_per_second']==500
    _,checkpoint,loaded=graph
    with pytest.raises(ValueError,match='100'):
        onnx_cli.benchmark(ROOT,ROOT/'data/raw/mvtec_ad',loaded,checkpoint,iterations=99)


def test_optional_onnx_failure_does_not_remove_pytorch_models(store,monkeypatch):
    monkeypatch.setattr(runtime,"admit",lambda *args: (_ for _ in ()).throw(ValueError('invalid graph')))
    store.load_optional_engines()
    assert len(store.models)==15
    assert all(m.metadata.available_engines==['pytorch'] for m in store.models.values())


def test_api_legacy_default_and_no_silent_fallback(client):
    from test_backend_api import image_bytes
    files={"file":('input.png',image_bytes(),'image/png')}
    old=client.post('/predict',data={"model":"B0","category":"bottle"},files=files)
    assert old.status_code==200 and old.json()['engine']=='pytorch'
    refused=client.post('/predict',data={"model":"B0","category":"bottle","engine":"onnxruntime"},files=files)
    assert refused.status_code==503 and refused.json()['code']=='onnx_unavailable'
    invalid=client.post('/predict',data={"model":"B0","category":"bottle","engine":"gpu"},files=files)
    assert invalid.status_code==422


def test_onnx_transfer_visualization_declares_pytorch_and_checks_coherence(store):
    loaded=store.models['T2','bottle']
    sample=letterbox_pair(Image.new('RGB',(91,43),(40,100,150)),Image.new('L',(91,43)),(256,256))
    with torch.inference_mode():
        reference=loaded.network(runtime.inputs(sample,'T2')).numpy()
    class Cache:
        def get(self,path):return self
        def run(self,*args):return [reference]
    loaded.onnx_path=Path('unit.onnx');loaded.onnx_cache=Cache()
    try:
        response=predict(loaded,sample,uuid4(),engine='onnxruntime',visualize=True)
        assert response.engine=='onnxruntime' and response.explanation_engine=='pytorch'
        assert response.explanation_score_coherent is True
        assert response.visualization.coordinate_space=='letterbox_256'
        assert response.visualization.is_segmentation is False
        reference[:]=reference+5
        with pytest.raises(APIError) as exc:
            predict(loaded,sample,uuid4(),engine='onnxruntime',visualize=True)
        assert exc.value.code=='explanation_divergence'
    finally:
        loaded.onnx_path=None;loaded.onnx_cache=None
