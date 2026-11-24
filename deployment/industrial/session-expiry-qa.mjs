// Natural inactivity expiry. No clock changes, SQL writes, restart or data reset.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const local = new URL('./local/', import.meta.url);
const account = JSON.parse(await readFile(new URL('accounts.json', local), 'utf8')).accounts.engineer;
const base = 'http://localhost:18180';
const report = { started: new Date().toISOString(), method: 'Natural 600-second inactivity, no database/clock modification', passed: false };
const browser = await chromium.launch();
let step = 'oidc-login';
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(base);
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(base + '/**');
  await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor();
  await page.close(); // Stop frontend health polling, which otherwise counts as activity.
  const response = await context.request.get(base + '/api/auth/session');
  assert.equal(response.status(), 200);
  const cookie = (await context.cookies(base)).find(c => c.name === 'ri_portal_session');
  assert.ok(cookie?.value && cookie.httpOnly);
  report.authenticated_before_wait = true;
  const began = Date.now();
  step = 'natural-idle-wait';
  console.log('Natural session-expiry check started; no requests for 605 seconds.');
  while (Date.now() - began < 605000) {
    await new Promise(resolve => setTimeout(resolve, Math.min(30000, 605000 - (Date.now() - began))));
  }
  step = 'server-expiry';
  // Present the original opaque identifier even if a client would discard it.
  // A 401 must come from server session validation, not merely a missing cookie.
  const expired = await context.request.get(base + '/api/auth/session', { headers: { Cookie: `${cookie.name}=${cookie.value}` } });
  report.waited_seconds = Math.floor((Date.now() - began) / 1000);
  report.status = expired.status();
  report.code = (await expired.json()).code;
  assert.equal(report.status, 401);
  assert.equal(report.code, 'session_expired');
  const resumed = await context.newPage();
  await resumed.goto(base + '/#profile');
  await resumed.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  report.login_screen_after_expiry = true;
  report.passed = true;
} catch (error) {
  report.failed_step = step;
  report.failure_kind = error.name;
  process.exitCode = 1;
} finally {
  report.finished = new Date().toISOString();
  await browser.close();
  await writeFile(new URL('session-expiry-verification.json', local), JSON.stringify(report, null, 2) + '\n');
}
console.log(JSON.stringify(report));
