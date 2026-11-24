// Compare already-observed V3 results with the unchanged V2 scientific service,
// then SELECT their PostgreSQL rows. No V3 inference rerun or SQL mutation.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const local = new URL('./local/', import.meta.url);
const root = fileURLToPath(new URL('../../', import.meta.url));
const observed = JSON.parse(await readFile(new URL('browser-verification.json', local), 'utf8'));
assert.equal(observed.passed, true);
const bytes = await readFile(new URL('../../data/raw/mvtec_ad/bottle/train/good/002.png', import.meta.url));
const report = { date: new Date().toISOString(), comparisons: [], database: [], passed: false };
let step = 'scientific-baseline';
try {
  const metadata = await (await fetch('http://localhost:8001/model/metadata')).json();
  for (const model of ['B0', 'T2']) for (const engine of ['pytorch', 'onnxruntime']) {
    const form = new FormData();
    form.set('model', model); form.set('category', 'bottle'); form.set('engine', engine);
    form.set('file', new Blob([bytes], { type: 'image/png' }), 'inspection.png');
    const response = await fetch('http://localhost:8001/predict', { method: 'POST', body: form, signal: AbortSignal.timeout(120000) });
    assert.equal(response.status, 200);
    const baseline = await response.json();
    const rows = observed.predictions.filter(x => x.model === model && x.engine === engine);
    assert.equal(rows.length, 2);
    const selected = metadata.models.find(x => x.model === model && x.category === 'bottle');
    for (const row of rows) {
      for (const field of ['model', 'engine', 'version', 'threshold', 'decision']) assert.equal(row[field], baseline[field]);
      assert.equal(row.score, baseline.anomaly_score); // Same engine, same runtime and original bytes: exact comparison.
      assert.equal(row.threshold, selected.threshold);
      assert.equal(row.version, selected.checkpoint_sha256);
    }
    report.comparisons.push({ model, engine, v3_responses: rows.length, score: baseline.anomaly_score,
      threshold: baseline.threshold, decision: baseline.decision, checkpoint_sha256: baseline.version,
      calibration_sha256: selected.calibration_sha256, max_absolute_score_error: 0 });
  }
  step = 'postgresql-readonly-binding';
  const code = `import json,os,sys,psycopg
from psycopg.rows import dict_row
data=json.load(sys.stdin)
url=os.environ['DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:', 1)
with psycopg.connect(url, row_factory=dict_row) as db:
 db.execute('SET TRANSACTION READ ONLY')
 rows=db.execute('SELECT i.id::text,i.model,i.category,i.engine,i.status,i.anomaly_score,i.threshold,i.decision,i.upstream_request_id::text AS request_id,i.image_sha256,r.checkpoint_sha256 AS version,r.calibration_sha256 FROM inspections i JOIN model_releases r ON i.release_id=r.id WHERE i.upstream_request_id = ANY(%s::uuid[])', ([x['request_id'] for x in data],)).fetchall()
 print(json.dumps(rows))
`;
  const output = execFileSync('docker', ['compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml',
    'exec', '-T', 'portal', 'python', '-c', code], { cwd: root, input: JSON.stringify(observed.predictions), stdio: ['pipe', 'pipe', 'pipe'], encoding: 'utf8' });
  const rows = JSON.parse(output);
  assert.equal(rows.length, 8);
  for (const row of rows) {
    const expected = observed.predictions.find(x => x.request_id === row.request_id);
    for (const field of ['model', 'engine', 'version', 'threshold', 'decision']) assert.equal(row[field], expected[field]);
    assert.equal(row.anomaly_score, expected.score);
    assert.equal(row.status, 'completed');
    assert.equal(row.image_sha256, null);
    assert.equal(row.calibration_sha256, report.comparisons.find(x => x.model === row.model && x.engine === row.engine).calibration_sha256);
    report.database.push({ id: row.id, request_id: row.request_id, model: row.model, engine: row.engine, exact_result_match: true, no_image_hash: true });
  }
  report.passed = true;
} catch (error) {
  report.failed_step = step;
  report.failure_kind = error.name;
  process.exitCode = 1;
} finally {
  await writeFile(new URL('prediction-verification.json', local), JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify({ passed: report.passed, failed_step: report.failed_step, comparisons: report.comparisons.length, database_rows: report.database.length }));
