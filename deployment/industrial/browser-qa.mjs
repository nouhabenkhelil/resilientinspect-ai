// Real local Keycloak + PostgreSQL + inference QA. Credentials/reports stay ignored.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const base = 'http://localhost:18180';
const root = fileURLToPath(new URL('../../', import.meta.url));
const local = new URL('./local/', import.meta.url);
const accounts = JSON.parse(await readFile(new URL('accounts.json', local), 'utf8')).accounts;
const file = new URL('../../data/raw/mvtec_ad/bottle/train/good/002.png', import.meta.url);
const bytes = await readFile(file);
assert.equal(createHash('sha256').update(bytes).digest('hex'), '7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69');
const report = { date: new Date().toISOString(), base, checks: [], predictions: [], errors: [], persistence: null };
let step = 'startup';
const browser = await chromium.launch();
const contexts = [];
await mkdir(new URL('screenshots/', local), { recursive: true });
async function login(label, invalid = false) {
  step = `login:${label}`;
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, reducedMotion: 'reduce' });
  contexts.push(context);
  const page = await context.newPage();
  page.on('pageerror', () => report.errors.push(`browser-error:${label}`));
  await page.goto(base);
  step = `login:${label}:portal-link`;
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  step = `login:${label}:provider-form`;
  await page.locator('#username').fill(accounts[label].username);
  if (invalid) {
    await page.locator('#password').fill('deliberately-invalid-test-password');
    await page.locator('#kc-login').click();
    step = `login:${label}:invalid-password-feedback`;
    await page.getByText(/Invalid username or password/).waitFor();
    report.checks.push('Real Keycloak invalid password refused');
    await page.locator('#username').fill(accounts[label].username);
  }
  await page.locator('#password').fill(accounts[label].password);
  step = `login:${label}:provider-submit`;
  await page.locator('#kc-login').click();
  await page.waitForURL(base + '/**', { timeout: 30000 });
  step = `login:${label}:bff-session`;
  const response = await context.request.get(base + '/api/auth/session');
  assert.equal(response.status(), 200, `OIDC login failed for ${label}`);
  const session = await response.json();
  assert.equal(session.user.role, accounts[label].role);
  const headers = { Origin: base, 'X-CSRF-Token': session.csrf_token };
  const cookies = await context.cookies(base);
  assert.equal(cookies.find(c => c.name === 'ri_portal_session')?.httpOnly, true);
  await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor();
  report.checks.push(`Real OIDC Code/PKCE login and HttpOnly cookie: ${label}`);
  return { context, page, session, headers };
}
async function predict(actor, model, engine) {
  const r = await actor.context.request.post(base + '/api/predict', { headers: actor.headers,
    multipart: { model, category: 'bottle', engine, file: { name: 'inspection.png', mimeType: 'image/png', buffer: bytes } }, timeout: 120000 });
  return r;
}
try {
  assert.equal((await fetch(base + '/api/model/metadata')).status, 401);
  assert.equal((await fetch(base + '/api/health')).status, 200);
  const operator = await login('operator', true);
  step = 'real-models';
  const status = await (await operator.context.request.get(base + '/api/status')).json();
  assert.equal(status.ready_models_by_engine.pytorch, 15);
  assert.equal(status.ready_models_by_engine.onnxruntime, 14);
  report.models = status.ready_models_by_engine;
  const metadata = await (await operator.context.request.get(base + '/api/model/metadata')).json();
  assert.equal(metadata.models.length, 15);
  assert.deepEqual(metadata.models.find(x => x.model === 'T1' && x.category === 'bottle').available_engines, ['pytorch']);
  for (const model of ['B0', 'T2']) for (const engine of ['pytorch', 'onnxruntime']) {
    step = `inspection:${model}:${engine}`;
    await operator.page.goto(base + '/#inspection');
    await operator.page.getByLabel('Modèle d’inspection').selectOption(model);
    await operator.page.getByLabel('Moteur de prédiction').selectOption(engine);
    await operator.page.getByLabel('Fichier image à inspecter').setInputFiles(fileURLToPath(file));
    const prediction = operator.page.waitForResponse(r => r.url().endsWith('/api/predict') && r.request().method() === 'POST', { timeout: 120000 });
    const visualization = operator.page.waitForResponse(r => r.url().endsWith('/api/predict/visualize') && r.request().method() === 'POST', { timeout: 120000 });
    await operator.page.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
    for (const response of [await prediction, await visualization]) {
      assert.equal(response.status(), 200, `Actual inference ${model}/${engine} refused`);
      const data = await response.json();
      assert.equal(data.engine, engine);
      assert.equal(data.version, metadata.models.find(x => x.model === model && x.category === 'bottle').checkpoint_sha256);
      report.predictions.push({ path: new URL(response.url()).pathname, model, engine, score: data.anomaly_score,
        threshold: data.threshold, decision: data.decision, version: data.version, request_id: data.request_id,
        explanation_engine: data.explanation_engine, explanation_score_coherent: data.explanation_score_coherent });
    }
    await operator.page.getByRole('heading', { name: model === 'B0' ? 'Heatmap de reconstruction' : 'Grad-CAM', exact: true }).waitFor();
  }
  step = 'intentional-onnx-rejection';
  const rejected = await predict(operator, 'T1', 'onnxruntime');
  assert.equal(rejected.status(), 503);
  assert.equal((await rejected.json()).code, 'onnx_unavailable');
  report.checks.push('Actual B0/T2 PyTorch/ONNX predictions and visualizations; T1/bottle ONNX 503 without fallback');
  const history = await (await operator.context.request.get(base + '/api/inspections')).json();
  const inspection = history.items.find(x => x.status === 'completed');
  assert.ok(inspection?.id);
  report.inspection_id = inspection.id;
  assert.ok(history.items.some(x => x.status === 'failed'));
  for (const row of history.items) assert.ok(!('visualization' in row) && !('image' in row));
  const second = await login('operator2');
  const auditor = await login('auditor');
  const engineer = await login('engineer');
  const admin = await login('admin');
  step = 'permissions-idor';
  assert.equal((await second.context.request.get(base + '/api/inspections/' + inspection.id)).status(), 404);
  assert.equal((await auditor.context.request.get(base + '/api/inspections/' + inspection.id)).status(), 404);
  assert.equal((await predict(auditor, 'B0', 'pytorch')).status(), 403);
  assert.equal((await operator.context.request.get(base + '/api/admin/users')).status(), 403);
  assert.equal((await operator.context.request.get(base + '/api/readiness')).status(), 403);
  assert.equal((await engineer.context.request.get(base + '/api/readiness')).status(), 200);
  const grant = `${base}/api/admin/inspections/${inspection.id}/grants/${auditor.session.user.id}`;
  assert.equal((await admin.context.request.post(grant, { headers: admin.headers })).status(), 200);
  assert.equal((await auditor.context.request.get(base + '/api/inspections/' + inspection.id)).status(), 200);
  assert.equal((await second.context.request.post(base + '/api/predict', { multipart: { model: 'B0' } })).status(), 403);
  assert.equal((await second.context.request.post(base + '/api/predict', { headers: second.headers,
    multipart: { model: 'B0', category: 'bottle', file: { name: 'bad.png', mimeType: 'image/png', buffer: Buffer.from('invalid') } } })).status(), 400);
  report.checks.push('Four real roles; IDOR 404; explicit admin read grant; auditor write 403; CSRF and invalid upload refused');
  step = 'comparison';
  await engineer.page.goto(base + '/#comparison');
  await engineer.page.getByLabel('Image de comparaison').setInputFiles(fileURLToPath(file));
  await engineer.page.getByText('Comparaison technique des moteurs · même architecture', { exact: true }).click();
  await engineer.page.getByRole('button', { name: 'Comparer PyTorch et ONNX', exact: true }).click();
  await engineer.page.getByText('ONNX Runtime', { exact: true }).waitFor({ timeout: 120000 });
  assert.equal(await engineer.page.getByRole('heading', { name: 'Résultat de l’inspection', exact: true }).count(), 2);
  report.checks.push('Authenticated Comparison Lab executes both real engines');
  for (const [hash, selector] of [['analytics', '.performance-engineering .recharts-bar-rectangle path'], ['monitor', '.monitor-page'], ['history', '.portal-history'], ['profile', '.portal-profile']]) {
    step = `navigation:${hash}`;
    await engineer.page.goto(base + '/#' + hash);
    if (hash === 'monitor') await engineer.page.getByRole('heading', { name: 'Versions et provenance', exact: true }).waitFor();
    else await engineer.page.locator(selector).first().waitFor({ state: hash === 'analytics' ? 'attached' : 'visible' });
  }
  await admin.page.goto(base + '/#admin');
  await admin.page.getByText(accounts.operator.username + '@example.invalid', { exact: true }).waitFor();
  await auditor.page.goto(base + '/#audit');
  await auditor.page.getByRole('heading', { name: 'Événements d’audit accessibles', exact: true }).waitFor();
  await auditor.page.goto(base + '/#inspection');
  await auditor.page.getByText('ACCÈS 403', { exact: true }).waitFor();
  await operator.page.goto(base + '/#history');
  await operator.page.locator('.portal-history').waitFor();
  await operator.page.reload();
  await operator.page.locator('.portal-history tbody tr').first().waitFor();
  await operator.page.screenshot({ path: fileURLToPath(new URL('screenshots/history-desktop.png', local)), fullPage: true });
  await operator.page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await operator.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await operator.page.screenshot({ path: fileURLToPath(new URL('screenshots/history-mobile.png', local)), fullPage: true });
  report.checks.push('Authenticated analytics/performance, monitor, persistent history, profile, administration, audit, 403 and mobile layout');
  if (process.argv.includes('--restart-postgres')) {
    step = 'postgres-persistence';
    execFileSync('docker', ['compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml', 'restart', 'postgres'], { cwd: root, stdio: 'pipe' });
    let retained = false;
    for (let i = 0; i < 30; i++) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      const r = await operator.context.request.get(base + '/api/inspections/' + inspection.id);
      if (r.status() === 200) { retained = (await r.json()).version === inspection.version; break; }
    }
    assert.equal(retained, true);
    report.persistence = { postgres_restarted: true, inspection_retained: true, session_retained: true };
  }
  step = 'revoke-logout';
  assert.equal((await admin.context.request.post(base + `/api/admin/users/${second.session.user.id}/revoke-sessions`, { headers: admin.headers })).status(), 200);
  assert.equal((await second.context.request.get(base + '/api/auth/session')).status(), 401);
  await second.page.reload();
  await second.page.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  await operator.page.goto(base + '/#profile');
  await operator.page.getByRole('button', { name: 'Déconnexion', exact: true }).click();
  await operator.page.waitForURL(url => url.port === '18585');
  const confirm = operator.page.locator('#kc-logout');
  if (await confirm.count()) await confirm.click();
  assert.equal((await operator.context.request.get(base + '/api/auth/session')).status(), 401);
  report.checks.push('Real session revocation and UI 401; BFF logout revoked and Keycloak end-session reached');
  assert.deepEqual(report.errors, []);
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failed_step = step;
  report.failure_kind = error.name;
  report.failure_operation = String(error.message).split('\n')[0].replace(/https?:\/\/\S+/g, '[url]');
  for (const context of contexts) {
    const page = context.pages()[0];
    if (page) await page.screenshot({ path: fileURLToPath(new URL('screenshots/failure.png', local)), fullPage: true }).catch(() => {});
  }
  console.error(`Industrial QA failed at ${step}; private evidence retained without credentials.`);
  process.exitCode = 1;
} finally {
  await writeFile(new URL('browser-verification.json', local), JSON.stringify(report, null, 2) + '\n');
  for (const c of contexts) await c.close();
  await browser.close();
}
console.log(JSON.stringify({ passed: report.passed, failed_step: report.failed_step, predictions: report.predictions.length, checks: report.checks.length }));
