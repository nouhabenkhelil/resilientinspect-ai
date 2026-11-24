// Keeps one real browser session in memory across the separately approved restart.
// This script never restarts Docker, changes SQL directly or creates an inspection.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const local = new URL('./local/', import.meta.url);
const account = JSON.parse(await readFile(new URL('accounts.json', local), 'utf8')).accounts.operator;
const base = 'http://localhost:18180';
const report = { started: new Date().toISOString(), passed: false };
const browser = await chromium.launch();
const sensitive = [];
let step = 'login-before-restart';
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === '/api/auth/callback') for (const key of ['code', 'state']) {
      const value = url.searchParams.get(key); if (value) sensitive.push(value);
    }
  });
  await page.goto(base);
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  for (const cookie of await context.cookies(base + '/api/auth/login')) if (cookie.name === 'ri_oidc_flow') sensitive.push(cookie.value);
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(base + '/**');
  await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor();
  const beforeProfile = await (await context.request.get(base + '/api/auth/session')).json();
  sensitive.push(beforeProfile.csrf_token);
  for (const cookie of await context.cookies(base)) if (cookie.name === 'ri_portal_session') sensitive.push(cookie.value);
  const before = await (await context.request.get(base + '/api/inspections?limit=100')).json();
  assert.ok(before.items.length >= 9);
  await page.close();
  await writeFile(new URL('persistence-ready.json', local), JSON.stringify({ ready: true, date: new Date().toISOString(), accessible_inspections: before.items.length }) + '\n');
  console.log('Persistence session ready; waiting for separately approved PostgreSQL restart.');
  step = 'wait-approved-restart';
  const deadline = Date.now() + 180000;
  let restart;
  while (Date.now() < deadline) {
    try {
      const candidate = JSON.parse((await readFile(new URL('restart-verification.json', local), 'utf8')).replace(/^\uFEFF/, ''));
      if (candidate.passed && candidate.date > report.started) { restart = candidate; break; }
    } catch { /* No result marker until the approved restart completes. */ }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert.ok(restart?.postgres_restarted);
  step = 'same-session-after-restart';
  const profileResponse = await context.request.get(base + '/api/auth/session');
  assert.equal(profileResponse.status(), 200);
  const afterProfile = await profileResponse.json();
  assert.equal(afterProfile.user.id, beforeProfile.user.id);
  const after = await (await context.request.get(base + '/api/inspections?limit=100')).json();
  assert.equal(after.total, before.total);
  for (const row of before.items) {
    const response = await context.request.get(base + '/api/inspections/' + row.id);
    assert.equal(response.status(), 200);
    assert.deepEqual(await response.json(), row);
  }
  const status = await (await context.request.get(base + '/api/status')).json();
  assert.deepEqual(status.ready_models_by_engine, { pytorch: 15, onnxruntime: 14 });
  const resumed = await context.newPage();
  await resumed.goto(base + '/#history');
  await resumed.locator('.portal-history tbody tr').first().waitFor();
  assert.equal((await fetch('http://localhost:18080')).status, 200);
  assert.equal((await fetch(base)).status, 200);
  report.same_server_session_retained = true;
  report.accessible_inspections_retained = before.items.length;
  report.all_database_inspections_preserved = restart.inspections_preserved;
  report.history_ui_after_restart = true;
  report.models = status.ready_models_by_engine;
  report.coexistence_http = { v2: 200, v3: 200 };
  step = 'dynamic-secret-log-scan';
  const logs = execFileSync('docker', ['compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml',
    'logs', '--no-color', '--no-log-prefix'], { cwd: fileURLToPath(new URL('../../', import.meta.url)), stdio: ['pipe', 'pipe', 'pipe'], encoding: 'utf8' });
  assert.ok(sensitive.length >= 5);
  assert.equal(sensitive.filter(value => value.length >= 16 && logs.includes(value)).length, 0);
  report.dynamic_secret_log_scan = { known_values_checked: sensitive.length, matches: 0, scope: 'Real OIDC code/state, flow cookie, opaque session cookie and CSRF token; no values persisted' };
  report.passed = true;
} catch (error) {
  report.failed_step = step;
  report.failure_kind = error.name;
  process.exitCode = 1;
} finally {
  report.finished = new Date().toISOString();
  await browser.close();
  await writeFile(new URL('post-restart-verification.json', local), JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify(report));
