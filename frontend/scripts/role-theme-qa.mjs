// Only the deployed industrial V3; genuine sessions, no asset/API interception.
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const base = 'http://localhost:18180';
const root = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(root, 'frontend/reports/role-theme/2026-11-27');
const accounts = JSON.parse(await readFile(path.join(root, 'deployment/industrial/local/accounts.json'), 'utf8')).accounts;
const report = { origin: base, checkedAt: new Date().toISOString(), checks: [], captures: [], roles: {}, errors: [] };
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
let videoContext;
const labels = { admin: 'Administrateur', ai_engineer: 'Ingénieur IA', operator: 'Opérateur', auditor: 'Auditeur' };
function track(page) { page.setDefaultTimeout(20000); page.on('pageerror', (error) => report.errors.push(error.message)); }
async function login(page, role, start = true) {
  if (start) await page.goto(base);
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  const account = accounts[role === 'ai_engineer' ? 'engineer' : role];
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(`${base}/**`);
  await page.getByText('API opérationnelle', { exact: true }).waitFor();
  await page.locator(`.app-shell[data-role="${role}"]`).waitFor();
  assert.equal(await page.locator('.app-shell').getAttribute('data-visual-revision'), 'role-themes-v3');
  const session = await (await page.request.get(`${base}/api/auth/session`)).json();
  assert.equal(session.user.role, role);
  return { role: session.user.role, permissions: session.user.permissions };
}
async function theme(page, value) {
  if (await page.locator('html').getAttribute('data-theme') !== value) {
    await page.getByRole('button', { name: value === 'light' ? 'Activer le mode clair' : 'Activer le mode sombre' }).click();
  }
  await page.waitForTimeout(350);
}
async function capture(page, name) {
  await page.screenshot({ path: path.join(output, `${name}.png`) });
  report.captures.push(`${name}.png`);
}
async function palette(page) {
  return page.locator('.app-shell').evaluate((node) => {
    const style = getComputedStyle(node);
    return Object.fromEntries(['--bg', '--surface', '--accent', '--accent2', '--normal', '--anomaly', '--warning', '--chart-b0', '--chart-t2'].map((key) => [key, style.getPropertyValue(key).trim()]));
  });
}
try {
  for (const role of ['admin', 'ai_engineer', 'operator', 'auditor']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'no-preference' });
    const page = await context.newPage(); track(page);
    const session = await login(page, role);
    report.roles[role] = { session, palettes: {}, responsive: [] };
    await page.waitForTimeout(1500);
    const nav = page.getByRole('navigation', { name: 'Navigation principale' });
    const expected = {
      admin: ['Smart Inspection', 'Comparison Lab', 'System Monitor', 'Administration', 'Audit'],
      ai_engineer: ['Smart Inspection', 'Comparison Lab', 'System Monitor'],
      operator: ['Smart Inspection', 'Comparison Lab'], auditor: ['Audit'],
    }[role];
    for (const name of ['Smart Inspection', 'Comparison Lab', 'System Monitor', 'Administration', 'Audit']) {
      assert.equal(await nav.getByRole('link', { name, exact: true }).count(), expected.includes(name) ? 1 : 0);
    }
    assert.equal(await page.getByRole('button', { name: 'Nouvelle inspection', exact: true }).count(), role === 'auditor' ? 0 : 1);
    assert.ok((await page.locator('.sidebar-account').textContent()).includes(labels[role]));
    assert.equal(await page.locator('.app-shell.sidebar-collapsed').count(), 0);
    for (const mode of ['dark', 'light']) {
      await theme(page, mode);
      report.roles[role].palettes[mode] = await palette(page);
      if (['admin', 'ai_engineer'].includes(role)) await capture(page, `${role}-dashboard-${mode}`);
    }
    if (['admin', 'ai_engineer'].includes(role)) {
      for (const width of [390, 768, 1280, 1440, 1920]) {
        await page.setViewportSize({ width, height: 1000 });
        for (const mode of ['dark', 'light']) {
          await theme(page, mode);
          const geometry = await page.evaluate(() => {
            const svg = document.querySelector('.industrial-hero-art svg');
            const box = svg.getBoundingClientRect();
            const action = document.querySelector('.hero-copy .primary').getBoundingClientRect();
            return { viewport: innerWidth, scroll: document.documentElement.scrollWidth, ratio: box.width / box.height,
              heroWidth: box.width, heroLeft: box.left, heroRight: box.right, heroTop: box.top, buttonBottom: action.bottom };
          });
          assert.ok(geometry.scroll <= width + 1, `${role}/${mode}/${width}: overflow`);
          assert.ok(Math.abs(geometry.ratio - 600 / 420) < .01, 'SVG aspect ratio');
          assert.ok(geometry.heroWidth > 200 && geometry.heroLeft >= 0 && geometry.heroRight <= width + 1, 'Hero visible and bounded');
          if (width === 390) assert.ok(geometry.heroTop >= geometry.buttonBottom, 'Mobile hero stacks below usable actions');
          report.roles[role].responsive.push({ width, mode, ...geometry });
          if (width === 390) await capture(page, `${role}-mobile-390-${mode}`);
        }
      }
      if (role === 'admin') {
        await page.setViewportSize({ width: 1920, height: 1100 }); await theme(page, 'dark');
        await page.locator('.industrial-hero').screenshot({ path: path.join(output, 'industrial-hero-large.png') });
        report.captures.push('industrial-hero-large.png');
      }
      await page.setViewportSize({ width: 390, height: 1000 });
      await page.getByRole('button', { name: 'Ouvrir la navigation' }).click();
      const drawer = page.getByRole('dialog', { name: 'Navigation du studio' });
      await drawer.waitFor();
      await page.keyboard.press('Shift+Tab');
      assert.ok(await drawer.evaluate((node) => node.contains(document.activeElement)));
      await page.keyboard.press('Tab');
      assert.ok(await drawer.evaluate((node) => node.contains(document.activeElement)));
      await capture(page, `${role}-mobile-drawer`);
      await page.keyboard.press('Escape');
      assert.equal(await page.getByRole('button', { name: 'Ouvrir la navigation' }).evaluate((node) => document.activeElement === node), true);
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.getByRole('link', { name: 'System Monitor', exact: true }).click();
      await page.getByRole('heading', { name: 'Des mesures, au présent.', exact: true }).waitFor();
      await page.getByRole('link', { name: 'Historique', exact: true }).click();
      const history = await (await page.request.get(`${base}/api/inspections?limit=100&offset=0`)).json();
      assert.ok(Array.isArray(history.items));
      if (history.items.length) {
        await page.getByRole('button', { name: 'Détails', exact: true }).first().click();
        await page.getByRole('heading', { name: 'Détails de l’inspection', exact: true }).waitFor();
      }
      report.roles[role].persistentHistoryRows = history.items.length;
    }
    if (role !== 'admin') {
      await page.goto(`${base}/#admin`);
      await page.getByText('ACCÈS 403', { exact: true }).waitFor();
      assert.equal((await page.request.get(`${base}/api/admin/users`)).status(), 403);
    }
    report.checks.push(`${role}: real authenticated identity, role label, unchanged navigation/RBAC and two palettes`);
    if (['admin', 'ai_engineer'].includes(role)) report.checks.push(`${role}: five widths x two modes; intact SVG, keyboard drawer, real operations and persistent history`);
    await context.close();
  }
  for (const mode of ['dark', 'light']) {
    const admin = report.roles.admin.palettes[mode], engineer = report.roles.ai_engineer.palettes[mode];
    assert.notEqual(admin['--bg'], engineer['--bg']); assert.notEqual(admin['--accent'], engineer['--accent']);
    for (const key of ['--normal', '--anomaly', '--warning', '--chart-b0', '--chart-t2']) assert.equal(admin[key], engineer[key]);
    assert.equal(report.roles.operator.palettes[mode]['--bg'], report.roles.auditor.palettes[mode]['--bg']);
  }
  report.checks.push('Admin/engineer identities differ; scientific semantic/chart colours agree; operator/auditor remain neutral');
  // Real end-session, then a different real account in the SAME browser context.
  const switching = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'no-preference' });
  const sessionPage = await switching.newPage(); track(sessionPage);
  await login(sessionPage, 'admin'); await theme(sessionPage, 'light');
  await sessionPage.getByRole('link', { name: 'Ouvrir mon profil', exact: true }).click();
  await sessionPage.getByRole('button', { name: 'Déconnexion', exact: true }).click();
  await sessionPage.waitForURL(/localhost:18585.*logout/);
  if (await sessionPage.locator('#kc-logout').isVisible()) await sessionPage.locator('#kc-logout').click();
  await sessionPage.waitForURL(`${base}/**`);
  await sessionPage.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  assert.equal(await sessionPage.locator('[data-role]').count(), 0);
  assert.equal((await sessionPage.request.get(`${base}/api/auth/session`)).status(), 401);
  await login(sessionPage, 'ai_engineer', false);
  assert.equal(await sessionPage.locator('html').getAttribute('data-theme'), 'light');
  assert.equal(await sessionPage.locator('.app-shell').getAttribute('data-role'), 'ai_engineer');
  await capture(sessionPage, 'same-session-engineer-after-admin-logout');
  const storage = await switching.storageState(); // Memory only; never saved to disk.
  report.checks.push('Real admin logout -> no private role + 401 -> engineer login in the same context; light preference preserved');
  await switching.close();
  const reduced = await browser.newContext({ storageState: storage, reducedMotion: 'reduce', viewport: { width: 1440, height: 1000 } });
  const reducedPage = await reduced.newPage(); track(reducedPage);
  await reducedPage.goto(base); await reducedPage.locator('.industrial-hero-art svg').waitFor();
  assert.ok(await reducedPage.locator('.hero-node-pulse, .hero-scan-line, .industrial-hero-art').evaluateAll((nodes) => nodes.every((node) => getComputedStyle(node).animationName === 'none')));
  assert.equal(await reducedPage.locator('.industrial-hero-art svg').isVisible(), true);
  await capture(reducedPage, 'reduced-motion-static-hero');
  await reduced.close();
  report.checks.push('Reduced motion keeps the complete SVG visible with all decorative hero animation disabled');
  const anonymous = await browser.newContext(); const anonymousPage = await anonymous.newPage(); track(anonymousPage);
  await anonymousPage.goto(base);
  await anonymousPage.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  assert.equal(await anonymousPage.locator('[data-role]').count(), 0);
  assert.equal((await anonymousPage.request.get(`${base}/api/auth/session`)).status(), 401);
  await anonymous.close();
  report.checks.push('Anonymous 401 never renders a private role theme');
  // Record only AFTER authentication. No login form, cookies or credentials in video.
  videoContext = await browser.newContext({ storageState: storage, reducedMotion: 'no-preference', viewport: { width: 1440, height: 1000 }, recordVideo: { dir: output, size: { width: 1440, height: 1000 } } });
  const videoPage = await videoContext.newPage(); track(videoPage);
  await videoPage.addInitScript(() => {
    const samples = window.__heroFrameIntervals = [];
    let previous;
    const start = performance.now();
    function frame(now) {
      if (previous !== undefined) samples.push(now - previous);
      previous = now;
      if (now - start < 6000) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
  await videoPage.goto(base);
  await videoPage.locator('.industrial-hero-art svg').waitFor();
  await videoPage.waitForTimeout(1700);
  assert.ok(await videoPage.locator('.hero-scan-line').evaluate((node) => node.getAnimations().length > 0));
  const card = await videoPage.locator('.stat-card').first().boundingBox();
  await videoPage.mouse.move(card.x + 30, card.y + 30); await videoPage.waitForTimeout(350);
  await videoPage.mouse.move(card.x + 150, card.y + 80); await videoPage.waitForTimeout(300);
  await theme(videoPage, 'dark'); await videoPage.waitForTimeout(400);
  await videoPage.getByRole('link', { name: 'Smart Inspection', exact: true }).click();
  await videoPage.waitForTimeout(400);
  await videoPage.getByRole('link', { name: 'Control Center', exact: true }).click();
  await videoPage.waitForTimeout(2500);
  report.frameIntervals = await videoPage.evaluate(() => {
    const samples = window.__heroFrameIntervals.slice().sort((a, b) => a - b);
    return { frames: samples.length, medianMs: samples[Math.floor(samples.length * .5)], p95Ms: samples[Math.floor(samples.length * .95)] };
  });
  const video = videoPage.video();
  await videoContext.close(); videoContext = undefined;
  await copyFile(await video.path(), path.join(output, 'role-theme-proof.webm'));
  report.video = 'role-theme-proof.webm';
  report.checks.push('Browser video observes real hero scan/nodes, CountUp, role-coloured hover, theme and navigation');
  assert.deepEqual(report.errors, []);
  report.passed = true;
  console.log(`Role theme QA passed: ${report.checks.length} checks, ${report.captures.length} captures, no page errors.`);
} catch (error) {
  report.passed = false; report.failure = error.message; console.error(error.message); process.exitCode = 1;
} finally {
  if (videoContext) await videoContext.close();
  await browser.close();
  await writeFile(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
}
