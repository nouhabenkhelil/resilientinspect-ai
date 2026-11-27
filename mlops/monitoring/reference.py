"""Freeze only archived validation-normal scores; never read official test images."""
import hashlib
import csv
import json
from .core import ROOT, DATA, atomic_json


def freeze():
    target = DATA / 'reference.json'
    if target.exists():
        expected = (DATA / 'reference.sha256').read_text().strip()
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected: raise ValueError('reference checksum')
        return json.loads(target.read_text())
    groups = []
    for folder in sorted((ROOT / 'artifacts/onnx').glob('*/*')):
        meta_path, proof_path = folder / 'metadata.json', folder / 'parity-windows.json'
        if not meta_path.exists() or not proof_path.exists(): continue
        for path in (meta_path, proof_path):
            expected = path.with_suffix('.sha256').read_text().strip().split()[0]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected: raise ValueError('archived proof checksum')
        meta, proof = json.loads(meta_path.read_text()), json.loads(proof_path.read_text())
        if proof['test_executed'] or proof['metadata_sha256'] != hashlib.sha256(meta_path.read_bytes()).hexdigest(): raise ValueError('reference provenance')
        rows = [r for r in proof['rows'] if r['kind'] == 'normal' and r['label'] == 0]
        # Frozen split membership is audited; sample paths stay in the original private proof only.
        manifest_path = ROOT / 'data/manifests/manifest.csv'
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != proof['manifest_sha256']: raise ValueError('manifest checksum')
        with manifest_path.open(newline='', encoding='utf-8') as handle:
            manifest = list(csv.DictReader(handle))
        validation = {r['image_path'] for r in manifest if r['split']=='val' and r['category']==meta['category']}
        for row in rows:
            if '/train/good/' not in row['sample_id'] or '/test/' in row['sample_id']: raise ValueError('reference split')
            if row['sample_id'].removeprefix('normal:') not in validation: raise ValueError('not frozen validation membership')
        for engine, field in [('pytorch', 'pytorch_score'), ('onnxruntime', 'onnx_score')]:
            if engine == 'onnxruntime' and proof['status'] != 'passed': continue
            groups.append({'model': meta['model'], 'category': meta['category'], 'version': meta['checkpoint_sha256'],
                'engine': engine, 'threshold': meta['threshold'], 'scores': [r[field] for r in rows],
                'provenance': {'split': 'frozen validation normals from train/good; no test',
                    'proof_sha256': hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                    'metadata_sha256': hashlib.sha256(meta_path.read_bytes()).hexdigest()}})
    if len(groups) != 29: raise ValueError(f'Expected 15 PyTorch / 14 ONNX references, got {len(groups)}')
    value = {'policy': 'validation_normal_ecdf_v1', 'groups': groups,
             'scope': 'Normal validation baseline; production shifts can reflect product mix, not necessarily model failure.'}
    atomic_json(target, value)
    (DATA / 'reference.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest())
    return value


if __name__ == '__main__':
    print(json.dumps({'reference_groups': len(freeze()['groups'])}))
