// Read-only consistency of committed real aggregate exports; no source archives on CI.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'src/data', name), 'utf8'));
const experiments = read('experiments.json');
const performance = read('onnx-performance.json');
const models = ['B0', 'A1', 'T0', 'T1', 'T2'];
const categories = ['bottle', 'hazelnut', 'leather'];
const expected = new Set(models.flatMap(m => categories.map(c => `${m}/${c}`)));
const close = (a, b) => assert.ok(Math.abs(a - b) <= 1e-12, `Arithmetic mismatch: ${a} / ${b}`);
const probability = value => assert.ok(value === null || (Number.isFinite(value) && value >= 0 && value <= 1 + Number.EPSILON));
assert.equal(experiments.records.length, 15);
assert.deepEqual(new Set(experiments.records.map(r => `${r.model}/${r.category}`)), expected);
for (const row of experiments.records) {
  assert.equal(row.seed, 42);
  assert.equal(Object.values(row.confusion).reduce((a, b) => a + b, 0), row.images);
  assert.ok(Object.values(row.confusion).every(v => Number.isInteger(v) && v >= 0));
  probability(row.threshold);
  for (const v of Object.values(row.image)) probability(v);
  const { tp, tn, fp, fn } = row.confusion;
  close(row.image.fpr, fp / (fp + tn));
  close(row.image.recall, tp / (tp + fn));
  close(row.image.accuracy, (tp + tn) / row.images);
  close(row.image.f1, 2 * tp / (2 * tp + fp + fn));
  assert.equal(row.pixel === null, row.model.startsWith('T'));
  assert.match(row.protocol_sha256, /^[a-f0-9]{64}$/);
}
for (const macro of experiments.macro) for (const metric of Object.keys(macro.image)) {
  const values = experiments.records.filter(r => r.model === macro.model).map(r => r.image[metric]);
  if (values.every(v => v !== null)) close(macro.image[metric], values.reduce((a, b) => a + b, 0) / 3);
}
for (const source of experiments.sources) {
  assert.match(source.sha256, /^[a-f0-9]{64}$/);
  assert.ok(!source.path.startsWith('/') && !source.path.includes('..') && !source.path.includes('\\') && !source.path.includes(':'));
}
const text = JSON.stringify(experiments);
for (const forbidden of ['image_path', 'sample_id', 'base64', 'best.pt', '/kaggle/', 'C:\\']) assert.ok(!text.includes(forbidden));
assert.equal(performance.status, 'measured');
assert.equal(performance.models.length, 6);
assert.deepEqual(new Set(performance.models.map(r => `${r.model}/${r.category}`)), new Set(['B0', 'T2'].flatMap(m => categories.map(c => `${m}/${c}`))));
for (const row of performance.models) {
  assert.equal(row.parity, 'passed');
  for (const condition of ['score', 'forward']) {
    const stats = row[condition];
    for (const engine of ['pytorch', 'onnxruntime']) {
      const values = stats[engine];
      assert.ok(Object.values(values).every(v => Number.isFinite(v) && v >= 0));
      assert.ok(values.mean_ms > 0 && values.p95_ms >= values.p50_ms);
      close(values.images_per_second, 1000 / values.mean_ms);
    }
    close(stats.speedup_mean, stats.pytorch.mean_ms / stats.onnxruntime.mean_ms);
  }
  assert.ok(Object.values(row.sizes).every(v => Number.isInteger(v) && v > 0));
}
console.log('15 real committed experiment aggregates and 6 measured benchmark aggregates are internally consistent. Archive SHA authenticity/raw measurements are checked by the local artifact-backed path, not asserted by hosted CI.');
