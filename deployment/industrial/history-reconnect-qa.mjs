// Authorized fresh OIDC login, read-only history checks and anonymous inference denial.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const local = new URL('./local/', import.meta.url);
const account = JSON.parse(await readFile(new URL('accounts.json', local), 'utf8')).accounts.operator;
const previous = JSON.parse(await readFile(new URL('browser-verification.json', local), 'utf8'));
assert.equal(previous.passed, true);
const base = 'http://localhost:18180';
const report = { date: new Date().toISOString(), anonymous_inference: [], passed: false };
const browser = await chromium.launch();
let step = 'anonymous-inference';
try {
  for (const route of ['/predict', '/predict/visualize']) {
    const response = await fetch(base + '/api' + route, { method: 'POST' });
    assert.equal(response.status, 401);
    report.anonymous_inference.push({ route, status: response.status });
  }
  step = 'reconnect-oidc';
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const page = await context.newPage();
  await page.goto(base);
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  const authorization = new URL(page.url());
  assert.equal(authorization.port, '18585');
  assert.equal(authorization.searchParams.get('response_type'), 'code');
  assert.equal(authorization.searchParams.get('code_challenge_method'), 'S256');
  assert.ok(authorization.searchParams.get('state')?.length >= 32);
  assert.ok(authorization.searchParams.get('nonce')?.length >= 32);
  assert.ok(authorization.searchParams.get('code_challenge')?.length >= 43);
  report.oidc = { response_type: 'code', pkce_method: 'S256', state_nonce_present: true };
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(base + '/**');
  await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor();
  const profile = await (await context.request.get(base + '/api/auth/session')).json();
  const inspection = await context.request.get(base + '/api/inspections/' + previous.inspection_id);
  assert.equal(inspection.status(), 200);
  const row = await inspection.json();
  assert.equal(row.owner_id, profile.user.id);
  assert.ok(previous.predictions.some(x => x.request_id === row.request_id && x.score === row.anomaly_score));
  const history = await (await context.request.get(base + '/api/inspections?limit=100')).json();
  for (const result of previous.predictions) assert.ok(history.items.some(x => x.request_id === result.request_id && x.status === 'completed'));
  report.reconnection = { inspection_id: row.id, owner_matched: true, retained_completed_inspections: previous.predictions.length, accessible_total: history.total };
  const cookies = await context.cookies(base);
  const session = cookies.find(c => c.name === 'ri_portal_session');
  assert.equal(session.httpOnly, true);
  assert.equal(session.sameSite, 'Lax');
  report.browser_storage = await page.evaluate(() => ({
    session_cookie_visible_to_js: document.cookie.includes('ri_portal_session'),
    sensitive_storage_keys: [...Object.keys(localStorage), ...Object.keys(sessionStorage)].filter(k => /token|session|csrf|auth|inspection/i.test(k)),
  }));
  assert.equal(report.browser_storage.session_cookie_visible_to_js, false);
  assert.deepEqual(report.browser_storage.sensitive_storage_keys, []);
  await page.goto(base + '/#history');
  await page.locator('.portal-history tbody tr').first().waitFor();
  report.history_ui_after_fresh_login = true;
  report.passed = true;
} catch (error) {
  report.failed_step = step;
  report.failure_kind = error.name;
  process.exitCode = 1;
} finally {
  await browser.close();
  await writeFile(new URL('history-reconnect-verification.json', local), JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify({ passed: report.passed, failed_step: report.failed_step, anonymous_inference: report.anonymous_inference, retained: report.reconnection?.retained_completed_inspections }));
