// Real local OIDC/browser/worker QA. Private images, credentials and reports stay ignored.
// Explicitly tests interruption of ONLY the new worker. Never restarts PostgreSQL/Keycloak.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const root = fileURLToPath(new URL('../../', import.meta.url));
const local = new URL('./local/', import.meta.url), base = 'http://localhost:18180';
const accounts = JSON.parse(await readFile(new URL('accounts.json', local), 'utf8')).accounts;
const manifest = JSON.parse(await readFile(new URL('../../mlops/release-manifest.json', import.meta.url), 'utf8'));
const sources = manifest.entries.filter(x => x.path.startsWith('data/raw/mvtec_ad/bottle/train/good/') && x.path.endsWith('.png')).sort((a, b) => a.path.localeCompare(b.path)).slice(0, 10);
assert.equal(sources.length, 10);
const files = [];
for (const source of sources) {
  const buffer = await readFile(new URL('../../' + source.path, import.meta.url));
  assert.equal(createHash('sha256').update(buffer).digest('hex'), source.sha256);
  files.push({ name: source.path.split('/').at(-1), buffer, sha256: source.sha256 });
}
const stateUrl = new URL('batch-qa-state.json', local);
let state = { jobs: {}, baselines: {}, source_sha256: files.map(f => f.sha256) };
try { state = JSON.parse(await readFile(stateUrl, 'utf8')); assert.deepEqual(state.source_sha256, files.map(f => f.sha256)); } catch (e) { if (e.code !== 'ENOENT') throw e; }
async function checkpoint() { await writeFile(stateUrl, JSON.stringify(state, null, 2) + '\n'); }
const report = { date: new Date().toISOString(), checks: [], jobs: [], errors: [], passed: false };
let step = 'startup', workerStopped = false;
const browser = await chromium.launch(), contexts = [];
await mkdir(new URL('screenshots/', local), { recursive: true });
function docker(...args) { return execFileSync('docker', ['compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml', ...args], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'], encoding: 'utf8' }); }
function legacySnapshot() { return docker('exec', '-T', 'postgres', 'psql', '-U', 'ri_migrator', '-d', 'portal', '-qAtc', 'SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM inspections i;').trim(); }
async function login(label) {
  step = 'login:' + label;
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, reducedMotion: 'reduce' }); contexts.push(context);
  const page = await context.newPage(); page.on('pageerror', () => report.errors.push('browser-error:' + label));
  await page.goto(base); await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  await page.locator('#username').fill(accounts[label].username); await page.locator('#password').fill(accounts[label].password); await page.locator('#kc-login').click();
  await page.waitForURL(base + '/**'); await page.getByRole('link', { name: 'Batch Inspection', exact: true }).waitFor();
  const response = await context.request.get(base + '/api/auth/session'); assert.equal(response.status(), 200);
  const session = await response.json(); assert.equal(session.user.role, accounts[label].role);
  return { context, page, headers: { Origin: base, 'X-CSRF-Token': session.csrf_token }, label };
}
async function upload(actor, model, engine, key, names) {
  // Playwright's object multipart cannot represent repeated file fields. Use native FormData in the page.
  return actor.page.evaluate(async ({ model, engine, key, headers, entries }) => {
    const form = new FormData(); form.set('model', model); form.set('category', 'bottle'); form.set('engine', engine);
    for (const entry of entries) {
      const bytes = Uint8Array.from(atob(entry.base64), c => c.charCodeAt(0));
      form.append('files', new File([bytes], entry.name, { type: 'image/png' }));
    }
    const response = await fetch('/api/batches', { method: 'POST', headers: { ...headers, 'Idempotency-Key': key }, body: form });
    return { status: response.status, body: await response.json() };
  }, { model, engine, key, headers: actor.headers, entries: files.map((f, i) => ({ name: names?.[i] || f.name, base64: f.buffer.toString('base64') })) });
}
async function waitBatch(actor, id, timeout = 180000) {
  const until = Date.now() + timeout, observed = [];
  while (Date.now() < until) {
    const r = await actor.context.request.get(`${base}/api/batches/${id}/progress`); assert.equal(r.status(), 200);
    const b = await r.json(); if (!observed.includes(b.processed)) observed.push(b.processed);
    assert.equal(b.processed, b.normal_count + b.anomaly_count + b.error_count + b.cancelled_count);
    if (['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(b.status)) return { batch: b, observed };
    await new Promise(resolve => setTimeout(resolve, 800));
  }
  throw new Error('Batch completion timeout');
}
async function baseline(model, engine, file) {
  const key = `${model}/${engine}/${file.sha256}`;
  if (!state.baselines[key]) {
    const form = new FormData(); form.set('model', model); form.set('category', 'bottle'); form.set('engine', engine);
    form.set('file', new Blob([file.buffer], { type: 'image/png' }), file.name);
    const r = await fetch('http://localhost:8001/predict', { method: 'POST', body: form, signal: AbortSignal.timeout(120000) });
    assert.equal(r.status, 200); state.baselines[key] = await r.json(); await checkpoint();
  }
  return state.baselines[key];
}
async function verifyJob(actor, id, model, engine, timeout) {
  const { batch, observed } = await waitBatch(actor, id, timeout); assert.equal(batch.status, 'completed'); assert.equal(batch.total, 10);
  const response = await actor.context.request.get(`${base}/api/batches/${id}/items?limit=50`); assert.equal(response.status(), 200);
  const items = (await response.json()).items; assert.equal(items.length, 10);
  for (const item of items) {
    const file = files[item.position - 1]; assert.equal(item.file_sha256, file.sha256); assert.equal(item.status, 'completed');
    const expected = await baseline(model, engine, file);
    for (const field of ['engine', 'anomaly_score', 'threshold', 'decision', 'version']) assert.equal(item[field], expected[field]);
  }
  report.jobs.push({ id, model, engine, total: 10, completed: batch.processed, normal: batch.normal_count, anomaly: batch.anomaly_count,
    observed_progress: observed, max_absolute_score_error_vs_individual: 0, max_attempts: Math.max(...items.map(i => i.attempts)) });
  return items;
}
try {
  const beforeLegacy = legacySnapshot();
  assert.equal((await fetch(base + '/api/batches')).status, 401);
  assert.equal((await fetch(base + '/api/batches', { method: 'POST' })).status, 401);
  const actors = {};
  for (const name of ['operator', 'engineer', 'operator2', 'auditor', 'admin']) actors[name] = await login(name);
  const health = await (await actors.operator.context.request.get(base + '/api/status')).json();
  assert.deepEqual(health.ready_models_by_engine, { pytorch: 15, onnxruntime: 14 }); report.models = health.ready_models_by_engine;
  const plan = [['B0', 'pytorch', 'operator'], ['B0', 'onnxruntime', 'operator'], ['T2', 'pytorch', 'engineer'], ['T2', 'onnxruntime', 'engineer']];
  for (const [model, engine, name] of plan) {
    step = `real-batch:${model}:${engine}`; const actor = actors[name], key = `${model}/${engine}`;
    if (!state.jobs[key]) {
      if (key === 'B0/pytorch') {
        await actor.page.goto(base + '/#batch');
        await actor.page.getByLabel('Images du lot').setInputFiles(files.map(f => ({ name: f.name, mimeType: 'image/png', buffer: f.buffer })));
        await actor.page.getByRole('button', { name: 'Démarrer le lot', exact: true }).waitFor();
        const created = actor.page.waitForResponse(r => r.url().endsWith('/api/batches') && r.request().method() === 'POST');
        await actor.page.getByRole('button', { name: 'Démarrer le lot', exact: true }).click();
        const response = await created; assert.equal(response.status(), 202);
        state.jobs[key] = { id: (await response.json()).id, owner: name }; await checkpoint();
      } else {
        const submission = randomUUID(), result = await upload(actor, model, engine, submission); assert.equal(result.status, 202);
        state.jobs[key] = { id: result.body.id, owner: name, submission }; await checkpoint();
        const replay = await upload(actor, model, engine, submission); assert.equal(replay.status, 200); assert.equal(replay.body.id, result.body.id);
      }
    }
    await verifyJob(actor, state.jobs[key].id, model, engine);
  }
  report.checks.push('40 real batch results on 10 distinct SHA256-verified images; exact match to 40 individual scientific responses');
  const first = state.jobs['B0/pytorch'].id, owner = actors.operator;
  const items = (await (await owner.context.request.get(`${base}/api/batches/${first}/items`)).json()).items;
  step = 'rbac-idor';
  for (const actor of [actors.operator2, actors.auditor]) for (const path of ['', '/progress', '/items', '/events', '/errors', '/export.csv', `/items/${items[0].id}/image`]) {
    assert.equal((await actor.context.request.get(`${base}/api/batches/${first}${path}`)).status(), 404);
  }
  assert.equal((await actors.admin.context.request.get(`${base}/api/batches/${first}`)).status(), 200);
  assert.equal((await actors.auditor.context.request.post(`${base}/api/batches/${first}/cancel`, { headers: actors.auditor.headers })).status(), 403);
  assert.equal((await actors.operator2.context.request.post(`${base}/api/batches/${first}/cancel`, { headers: actors.operator2.headers })).status(), 404);
  assert.equal((await actors.auditor.context.request.post(base + '/api/batches', { headers: actors.auditor.headers })).status(), 403);
  assert.equal((await owner.context.request.post(base + '/api/batches')).status(), 403);
  assert.equal((await fetch(`${base}/api/batches/${first}/items/${items[0].id}/image`)).status, 401);
  report.checks.push('Real role checks, owner-scoped IDOR across detail/progress/items/errors/events/CSV/private images, auditor mutation 403, CSRF 403, anonymous 401');
  step = 'ui-results-csv-explanation';
  await owner.page.goto(base + '/#batch'); await owner.page.getByRole('button', { name: `Ouvrir le lot ${first}`, exact: true }).click();
  await owner.page.waitForFunction(() => document.querySelector('progress')?.value === 10);
  await owner.page.getByLabel('Filtre des résultats du lot').selectOption('normal');
  await owner.page.getByRole('button', { name: 'Expliquer', exact: true }).first().waitFor();
  const explanation = owner.page.waitForResponse(r => r.url().endsWith('/explanation'));
  await owner.page.getByRole('button', { name: 'Expliquer', exact: true }).first().click();
  const explained = await explanation; assert.equal(explained.status(), 200); assert.equal((await explained.json()).anomaly_score, items[0].anomaly_score);
  await owner.page.locator('.visual-frame img').first().waitFor();
  await owner.page.getByLabel('Filtre des résultats du lot').selectOption('anomaly'); await owner.page.getByText('Aucune image pour ce filtre.', { exact: true }).waitFor();
  await owner.page.getByLabel('Filtre des résultats du lot').selectOption('error'); await owner.page.getByText('Aucune image pour ce filtre.', { exact: true }).waitFor();
  await owner.page.getByLabel('Filtre des résultats du lot').selectOption('all');
  const csv = await owner.context.request.get(`${base}/api/batches/${first}/export.csv`); assert.equal(csv.status(), 200);
  assert.equal((await csv.text()).trim().split('\r\n').length, 11);
  const download = owner.page.waitForEvent('download'); await owner.page.getByRole('button', { name: 'Exporter CSV', exact: true }).click(); assert.ok((await download).suggestedFilename().endsWith('.csv'));
  await owner.page.screenshot({ path: fileURLToPath(new URL('screenshots/batch-desktop.png', local)), fullPage: true });
  await owner.page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await owner.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await owner.page.screenshot({ path: fileURLToPath(new URL('screenshots/batch-mobile.png', local)), fullPage: true });
  report.checks.push('Real upload UI, server progress, filters, explanation, CSV download, desktop/mobile layout');
  step = 'cancel-pending';
  if (!state.jobs.cancel) {
    docker('stop', 'worker'); workerStopped = true;
    const result = await upload(owner, 'B0', 'pytorch', randomUUID(), files.map((f, i) => i === 0 ? '../../=SUM(1).png' : f.name)); assert.equal(result.status, 202);
    state.jobs.cancel = { id: result.body.id, owner: 'operator' }; await checkpoint();
    const cancelled = await owner.context.request.post(`${base}/api/batches/${result.body.id}/cancel`, { headers: owner.headers }); assert.equal(cancelled.status(), 200);
    assert.equal((await cancelled.json()).cancelled_count, 10);
  }
  const cancelCsv = await owner.context.request.get(`${base}/api/batches/${state.jobs.cancel.id}/export.csv`);
  assert.ok((await cancelCsv.text()).includes("'=SUM(1).png")); assert.ok(!(await cancelCsv.text()).includes('../'));
  report.cancelled_images = 10;
  step = 'crash-recovery';
  if (!state.jobs.crash) {
    if (!workerStopped) { docker('stop', 'worker'); workerStopped = true; }
    const result = await upload(actors.engineer, 'T2', 'pytorch', randomUUID()); assert.equal(result.status, 202);
    state.jobs.crash = { id: result.body.id, owner: 'engineer' }; await checkpoint();
  }
  docker('up', '-d', '--no-deps', 'worker'); workerStopped = false;
  if (!state.crash_observed) {
    for (let i = 0; i < 100; i++) {
      const rows = (await (await actors.engineer.context.request.get(`${base}/api/batches/${state.jobs.crash.id}/items?limit=50`)).json()).items;
      if (rows.some(x => x.status === 'running')) {
        docker('kill', '-s', 'SIGKILL', 'worker'); workerStopped = true;
        const persisted = (await (await actors.engineer.context.request.get(`${base}/api/batches/${state.jobs.crash.id}/items?limit=50`)).json()).items;
        assert.ok(persisted.some(x => x.status === 'running')); state.crash_observed = true; await checkpoint(); break;
      }
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    assert.equal(state.crash_observed, true);
    docker('up', '-d', '--no-deps', 'worker'); workerStopped = false;
  }
  const recovered = await verifyJob(actors.engineer, state.jobs.crash.id, 'T2', 'pytorch', 240000);
  assert.ok(recovered.some(x => x.attempts >= 2));
  const events = (await (await actors.engineer.context.request.get(`${base}/api/batches/${state.jobs.crash.id}/events?limit=100`)).json()).items;
  assert.ok(events.some(x => x.kind === 'item.recovered'));
  assert.equal(new Set(recovered.map(x => x.id)).size, 10);
  report.checks.push('Pending cancellation, sanitized filename/CSV formula protection, real SIGKILL worker crash, durable lease recovery and bounded retry with one committed result per item');
  step = 'reconnect-and-nonregression';
  const fresh = await login('operator');
  assert.equal((await fresh.context.request.get(`${base}/api/batches/${first}`)).status(), 200);
  assert.equal(legacySnapshot(), beforeLegacy); report.sprint1_inspections_preserved = JSON.parse(beforeLegacy).length;
  const rejected = await upload(actors.engineer, 'T1', 'onnxruntime', randomUUID());
  assert.equal(rejected.status, 503); assert.equal(rejected.body.code, 'onnx_unavailable');
  assert.equal((await fetch('http://localhost:18080')).status, 200); assert.equal((await fetch(base)).status, 200);
  assert.deepEqual(report.errors, []);
  report.distinct_real_images = files.length; report.completed_batch_items = report.jobs.reduce((n, j) => n + j.completed, 0);
  report.individual_reference_responses = Object.keys(state.baselines).length;
  report.passed = true;
} catch (error) {
  report.failed_step = step; report.failure_kind = error.name;
  report.failure_operation = String(error.message).split('\n')[0].replace(/https?:\/\/\S+/g, '[url]');
  console.error('Batch QA failed at ' + step + '; private evidence retained without credentials.'); process.exitCode = 1;
  for (const c of contexts) if (c.pages()[0]) await c.pages()[0].screenshot({ path: fileURLToPath(new URL('screenshots/batch-failure.png', local)), fullPage: true }).catch(() => {});
} finally {
  if (workerStopped) { try { docker('up', '-d', '--no-deps', 'worker'); } catch { report.worker_restore_failed = true; } }
  await writeFile(new URL('batch-browser-verification.json', local), JSON.stringify(report, null, 2) + '\n');
  for (const context of contexts) await context.close(); await browser.close();
}
console.log(JSON.stringify({ passed: report.passed, failed_step: report.failed_step, completed_batch_items: report.completed_batch_items, checks: report.checks.length }));
