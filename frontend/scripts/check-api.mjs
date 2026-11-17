// Test d’intégration réel. Aucun mock, fichier MVTec ou checkpoint côté frontend.
import assert from 'node:assert/strict';
import { deflateSync } from 'node:zlib';
import { mkdir, writeFile } from 'node:fs/promises';

const base = (process.env.API_TEST_URL || 'http://127.0.0.1:5173/api').replace(/\/+$/, '');
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(kind, data) {
  const content = Buffer.concat([Buffer.from(kind), data]);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(content));
  return Buffer.concat([size, content, checksum]);
}
function syntheticPng() {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(173, 0);
  header.writeUInt32BE(89, 4);
  header[8] = 8;
  header[9] = 2;
  const rows = Buffer.alloc(89 * (173 * 3 + 1));
  for (let y = 0; y < 89; y++)
    for (let x = 0; x < 173; x++) {
      const offset = y * (173 * 3 + 1) + 1 + x * 3;
      rows[offset] = 61;
      rows[offset + 1] = 110;
      rows[offset + 2] = 170;
    }
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
async function get(path) {
  const response = await fetch(`${base}${path}`, { signal: AbortSignal.timeout(15_000) });
  const body = await response.json();
  assert.ok(
    response.ok || (path === '/health' && response.status === 503 && body.status === 'degraded'),
  );
  return body;
}
const health = await get('/health');
assert.equal(health.device, 'cpu');
const metadata = await get('/model/metadata');
assert.ok(metadata.models.length > 0, 'Aucun modèle réellement disponible');
assert.equal(health.ready_models, metadata.models.length);
const file = new File([syntheticPng()], 'synthetic-inspection.png', { type: 'image/png' });
const calls = [];
for (const model of metadata.models) {
  let previous;
  for (const path of ['/predict', '/predict/visualize']) {
    const form = new FormData();
    form.append('file', file);
    form.append('category', model.category);
    form.append('model', model.model);
    const response = await fetch(`${base}${path}`, {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(120_000),
    });
    const result = await response.json();
    assert.equal(response.status, 200, JSON.stringify(result));
    assert.equal(result.category, model.category);
    assert.equal(result.model, model.model);
    assert.equal(result.threshold, model.threshold);
    assert.equal(result.version, model.version);
    assert.equal(result.decision, result.anomaly_score > result.threshold ? 'anomaly' : 'normal');
    assert.ok(Number.isFinite(result.inference_time_ms) && result.inference_time_ms >= 0);
    assert.match(result.request_id, /^[0-9a-f-]{36}$/);
    assert.equal(response.headers.get('x-request-id'), result.request_id);
    if (previous) assert.equal(result.anomaly_score, previous.anomaly_score);
    if (path.endsWith('/visualize')) {
      const visual = result.visualization;
      assert.equal(visual.kind, model.explanation);
      assert.equal(visual.is_segmentation, false);
      assert.equal(visual.coordinate_space, 'letterbox_256');
      assert.deepEqual(visual.original_height_width, [89, 173]);
      assert.equal(
        visual.scale,
        model.explanation === 'gradcam' ? 'relative_per_image_0_1' : 'absolute_l1_0_1',
      );
      for (const name of ['image', 'heatmap', 'overlay']) {
        const png = Buffer.from(visual[`${name}_png_base64`], 'base64');
        assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
        assert.equal(png.readUInt32BE(16), 256);
        assert.equal(png.readUInt32BE(20), 256);
      }
    }
    calls.push({
      path,
      model: result.model,
      category: result.category,
      decision: result.decision,
      score: result.anomaly_score,
      threshold: result.threshold,
      inference_time_ms: result.inference_time_ms,
      request_id: result.request_id,
      status: response.status,
    });
    previous = result;
    console.log(`${response.status} ${path} ${model.model}/${model.category}`);
  }
}
const invalid = new FormData();
invalid.append('file', new File(['bad'], 'invalid.gif'));
invalid.append('category', 'bottle');
invalid.append('model', 'B0');
const rejected = await fetch(`${base}/predict`, {
  method: 'POST',
  body: invalid,
  signal: AbortSignal.timeout(15_000),
});
assert.equal(rejected.status, 415);
const error = await rejected.json();
assert.equal(error.code, 'unsupported_extension');
assert.ok(error.request_id);
const report = {
  checked_at: new Date().toISOString(),
  base_url: base,
  synthetic_image: '173 × 89 RGB PNG generated in memory',
  health,
  combinations: metadata.models.length,
  calls,
  invalid_file_status: rejected.status,
};
await mkdir(new URL('../reports/', import.meta.url), { recursive: true });
await writeFile(
  new URL('../reports/api-verification.json', import.meta.url),
  JSON.stringify(report, null, 2) + '\n',
);
console.log(
  `Intégration réelle réussie : ${calls.length} POST, ${metadata.models.length} couples, validation HTTP 415.`,
);
