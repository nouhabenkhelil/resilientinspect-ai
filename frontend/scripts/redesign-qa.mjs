// Real deployed V3 only: no asset interception or preview server.
// Optional A/B captures replay only hash-verified historical GET records.
// All functional tests run with live API requests after those routes are removed.
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createHash } from 'node:crypto';

const base = 'http://localhost:18180';
const root = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(root, 'frontend/reports/screenshots/restore');
const accounts = JSON.parse(await readFile(path.join(root, 'deployment/industrial/local/accounts.json'), 'utf8')).accounts;
const before = process.argv.includes('--before');
const compare = process.argv.includes('--compare');
const servedHtml = await (await fetch(base)).text();
const report = { origin: base, checkedAt: new Date().toISOString(), assets: 'real existing Docker web service; no asset interception; functional tests use live API', servedIndexSha256: createHash('sha256').update(servedHtml).digest('hex'), scripts: [...servedHtml.matchAll(/src="(\/assets\/[^\"]+\.js)"/g)].map((match) => match[1]), checks: [], captures: [], errors: [] };
const flowsOnly = process.argv.includes('--flows-only');
const accessOnly = process.argv.includes('--access-only');
const browser = await chromium.launch({ headless: true });
await mkdir(output, { recursive: true });
async function contextFor(theme = 'dark', width = 1440) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
  await context.addInitScript((value) => { if (!localStorage.getItem('ri.theme')) localStorage.setItem('ri.theme', value); }, theme);
  return context;
}
async function login(context, role = 'admin') {
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', (error) => report.errors.push(error.message));
  await page.goto(base);
  await page.getByRole('link', { name: 'Se connecter', exact: true }).click();
  const account = accounts[role === 'ai_engineer' ? 'engineer' : role];
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(`${base}/**`);
  await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor({ state: 'attached' });
  await page.getByText('API opérationnelle', { exact: true }).waitFor({ state: 'attached' });
  if (!before) assert.equal(await page.locator('[data-ui-revision="restore-v3"]').count(), 1, 'Restored build must be served by Docker');
  report.checks.push(`Real OIDC login: ${role}`);
  return page;
}
async function navigate(page, id) {
  await page.evaluate((value) => { window.location.hash = value; }, id);
  await page.locator('main .page-heading').waitFor();
  await page.waitForFunction((value) => document.title.startsWith(value), ({ dashboard: 'Control Center', inspection: 'Smart Inspection', batch: 'Batch Inspection', comparison: 'Comparison Lab', analytics: 'Model Analytics', monitor: 'System Monitor', history: 'Historique', profile: 'Mon profil', admin: 'Administration', audit: 'Audit' })[id]);
  if (id === 'analytics') await page.getByRole('heading', { name: 'AUROC image par catégorie', exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
}
async function capture(page, name) {
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true, animations: 'disabled' });
  report.captures.push(`${name}.png`);
}
async function resultLayouts(page, name) {
  for (const width of [375, 430, 768, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
        await page.getByRole('button', { name: theme === 'light' ? 'Activer le mode clair' : 'Activer le mode sombre' }).click();
      }
      const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
      assert.ok(dimensions.scroll <= width + 1, `${name}/${width}/${theme}: ${JSON.stringify(dimensions)}`);
      const images = await page.locator('.visual-frame:not(.viewer-dialog .visual-frame) img').evaluateAll((nodes) => nodes.map((node) => ({ natural: node.naturalWidth / node.naturalHeight, rendered: node.getBoundingClientRect().width / node.getBoundingClientRect().height })));
      assert.ok(images.length && images.every((image) => Math.abs(image.natural - image.rendered) < 0.01), `${name}: scientific image aspect ratio`);
      if (width === 375 || width === 1440) await capture(page, `after-result-${name}-${width}-${theme}`);
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  report.checks.push(`Real ${name} result: 6 widths x 2 themes, no global overflow, scientific image aspect ratios preserved`);
}
async function pairedCaptures(page) {
  const data = {};
  let historicalRoute;
  for (const endpoint of ['/api/inspections?limit=100&status=completed', '/api/batches?limit=10&offset=0']) {
    const response = await page.request.get(`${base}${endpoint}`);
    assert.equal(response.status(), 200);
    const json = await response.json();
    data[endpoint] = createHash('sha256').update(JSON.stringify({ items: json.items, total: json.total })).digest('hex');
  }
  if (!before) {
    const reference = JSON.parse(await readFile(path.join(output, 'before.json'), 'utf8'));
    report.currentDataHashes = { ...data };
    if (JSON.stringify(data) !== JSON.stringify(reference.comparisonDataHashes)) {
      // New records can arrive during an interrupted session. Reconstruct the
      // original dataset using its timestamp, and accept it only if every byte
      // of the normalized record set matches the hash saved before deployment.
      const payloads = {};
      for (const endpoint of Object.keys(data)) {
        const source = endpoint.includes('/batches') ? '/api/batches?limit=50&offset=0' : endpoint;
        const response = await page.request.get(`${base}${source}`);
        assert.equal(response.status(), 200);
        const json = await response.json();
        const older = json.items.filter((item) => Date.parse(item.created_at) <= Date.parse(reference.checkedAt));
        const payload = { items: endpoint.includes('/batches') ? older.slice(0, 10) : older, total: older.length };
        data[endpoint] = createHash('sha256').update(JSON.stringify(payload)).digest('hex');
        assert.equal(data[endpoint], reference.comparisonDataHashes[endpoint], 'Historical data must exactly match the original records');
        payloads[endpoint] = payload;
      }
      historicalRoute = (url) => url.origin === base && Object.hasOwn(payloads, url.pathname + url.search);
      await page.route(historicalRoute, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payloads[new URL(route.request().url()).pathname + new URL(route.request().url()).search]) }));
      await page.reload();
      await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor({ state: 'attached' });
      report.comparisonMethod = 'B captures only: replay of historical records reconstructed from the live API and matching the original SHA256; no fabricated values or asset substitution';
    } else report.comparisonMethod = 'Identical live records, no replay';
    assert.deepEqual(data, reference.comparisonDataHashes, 'A/B must show the same genuine records');
    assert.notEqual(report.servedIndexSha256, reference.servedIndexSha256, 'Docker must serve a different compiled frontend');
  }
  report.comparisonDataHashes = data;
  for (const width of [430, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.getByRole('button', { name: theme === 'light' ? 'Activer le mode clair' : 'Activer le mode sombre' }).click();
      for (const id of ['dashboard', 'inspection', 'batch']) {
        await navigate(page, id);
        if (id === 'batch') await page.getByRole('button', { name: /^Ouvrir le lot / }).first().waitFor();
        await capture(page, `${before ? 'A' : 'B'}-${width}-${theme}-${id}`);
      }
    }
  }
  if (historicalRoute) {
    await page.unroute(historicalRoute);
    await page.reload();
    await page.getByRole('link', { name: 'Mon profil', exact: true }).waitFor({ state: 'attached' });
  }
  report.checks.push('A/B: 18 captures, identical viewport/theme and genuine inspection/batch record hashes');
}
try {
  const context = await contextFor();
  const page = await login(context);
  if (before) {
    await pairedCaptures(page);
    report.passed = true;
    console.log('Previous V3 captured directly from Docker; no inference or batch created.');
  } else {
  if (compare) await pairedCaptures(page);
  const pages = ['dashboard', 'inspection', 'batch', 'comparison', 'analytics', 'monitor', 'history', 'profile', 'admin', 'audit'];
  for (const width of flowsOnly || accessOnly ? [] : [375, 430, 768, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ['dark', 'light']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
        await page.getByRole('button', { name: theme === 'light' ? 'Activer le mode clair' : 'Activer le mode sombre' }).click();
      }
      for (const id of pages) {
        await navigate(page, id);
        // Wait for service/list requests, but polling intentionally remains active.
        await page.waitForTimeout(150);
        const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
        assert.ok(dimensions.scroll <= dimensions.width + 1, `${width}/${theme}/${id}: overflow ${JSON.stringify(dimensions)}`);
        if (width >= 1280) {
          assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('sidebar-collapsed')), false, 'Desktop must be expanded by default');
          const labels = await page.locator('.sidebar nav a > span').evaluateAll((nodes) => nodes.map((node) => ({ display: getComputedStyle(node).display, width: node.getBoundingClientRect().width })));
          assert.ok(labels.length === 10 && labels.every((label) => label.display !== 'none' && label.width > 20), 'Desktop navigation labels must be visible');
        }
        if (id === 'analytics') {
          const charts = await page.locator('.recharts-wrapper').evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width));
          assert.ok(charts.length >= 3 && charts.every((w) => w > 100), `Charts ${charts}`);
        }
        await capture(page, `after-${width}-${theme}-${id}`);
      }
      report.checks.push(`No global overflow, 10 pages: ${width}px / ${theme}`);
      console.log(`Layouts checked: ${width}px ${theme}`);
    }
  }
  await page.setViewportSize({ width: 390, height: 900 });
  await navigate(page, 'dashboard');
  await page.getByRole('button', { name: 'Ouvrir la navigation' }).click();
  const drawer = page.getByRole('dialog', { name: 'Navigation du studio' });
  await drawer.waitFor();
  assert.ok(await page.getByRole('button', { name: 'Fermer la navigation', exact: true }).evaluate((node) => node === document.activeElement));
  await page.keyboard.press('Shift+Tab');
  assert.ok(await drawer.evaluate((node) => node.contains(document.activeElement)));
  await page.keyboard.press('Tab');
  assert.ok(await page.getByRole('button', { name: 'Fermer la navigation', exact: true }).evaluate((node) => node === document.activeElement));
  await capture(page, 'after-mobile-drawer');
  await page.keyboard.press('Escape');
  assert.ok(await page.getByRole('button', { name: 'Ouvrir la navigation' }).evaluate((node) => node === document.activeElement));
  assert.equal(await page.locator('.main-shell').getAttribute('inert'), null);
  assert.equal(await page.evaluate(() => document.body.style.overflow), '');
  report.checks.push('Mobile keyboard: initial focus, Shift+Tab/Tab trap, Escape, restored focus and body scroll');
  const motion = await page.evaluate(() => [...document.querySelectorAll('*')].every((node) => getComputedStyle(node).animationDuration.split(',').every((value) => parseFloat(value) <= 0.00001)));
  assert.ok(motion, 'Reduced motion must stop continuous animations');
  report.checks.push('Reduced motion: every rendered animation <= 0.01ms');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Réduire la navigation' }).click();
  assert.ok(await page.locator('.app-shell').evaluate((node) => node.classList.contains('sidebar-collapsed')));
  await page.getByRole('button', { name: 'Déployer la navigation' }).click();
  await page.getByRole('button', { name: 'Mode démonstration' }).click();
  assert.equal(await page.locator('.app-shell').evaluate((node) => node.classList.contains('sidebar-collapsed')), false, 'Demo mode must not force icon-only navigation');
  await page.getByRole('button', { name: 'Mode démonstration' }).click();
  const initialTheme = await page.locator('html').getAttribute('data-theme');
  await page.getByRole('button', { name: initialTheme === 'dark' ? 'Activer le mode clair' : 'Activer le mode sombre' }).click();
  assert.notEqual(await page.locator('html').getAttribute('data-theme'), initialTheme);
  await page.reload();
  assert.notEqual(await page.locator('html').getAttribute('data-theme'), initialTheme);
  report.checks.push('Desktop collapse/expand and theme toggle persisted after reload');

  if (!accessOnly) {
  const fixture = path.join(root, 'data/raw/mvtec_ad/bottle/train/good/002.png');
  const bytes = await readFile(fixture);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), '7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69');
  report.predictions = [];
  await navigate(page, 'inspection');
  await page.getByLabel('Fichier image à inspecter').setInputFiles(fixture);
  for (const engine of ['pytorch', 'onnxruntime']) {
    await page.getByLabel('Moteur de prédiction', { exact: true }).selectOption(engine);
    const response = page.waitForResponse((res) => new URL(res.url()).pathname === '/api/predict' && res.request().method() === 'POST', { timeout: 120000 });
    await page.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
    const received = await response;
    assert.equal(received.status(), 200);
    const result = await received.json();
    assert.equal(result.engine, engine);
    await page.getByRole('heading', { name: 'Heatmap de reconstruction', exact: true }).waitFor({ timeout: 120000 });
    await page.getByText('Valeurs exactes de l’API', { exact: true }).click();
    const values = await page.locator('.exact-values').innerText();
    assert.ok(values.includes(String(result.anomaly_score)) && values.includes(String(result.threshold)));
    await page.getByText('Valeurs exactes de l’API', { exact: true }).click();
    assert.equal(await page.getByRole('heading', { name: result.decision === 'normal' ? 'Normal' : 'Anormal', exact: true }).count(), 1);
    report.predictions.push({ model: result.model, category: result.category, engine, decision: result.decision, anomaly_score: result.anomaly_score, threshold: result.threshold });
    await capture(page, `after-real-single-${engine}`);
    console.log(`Real inspection checked: ${engine}`);
  }
  await page.getByRole('button', { name: 'Côte à côte', exact: true }).click();
  assert.ok(await page.getByAltText('Carte explicative originale').first().isVisible());
  await page.getByRole('button', { name: 'Ouvrir le visualiseur plein écran' }).click();
  await page.getByRole('dialog').waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(), 0);
  report.checks.push('Real B0 PyTorch + ONNX inference, exact API score/threshold, heatmap, side-by-side and fullscreen Escape');
  await resultLayouts(page, 'single');
  await navigate(page, 'comparison');
  await page.getByLabel('Image de comparaison').setInputFiles(fixture);
  await page.getByRole('button', { name: 'Comparer les modèles', exact: true }).click();
  await page.getByRole('heading', { name: 'Grad-CAM', exact: true }).waitFor({ timeout: 120000 });
  await page.getByRole('heading', { name: 'Heatmap de reconstruction', exact: true }).waitFor({ timeout: 120000 });
  assert.equal(await page.getByRole('heading', { name: 'Résultat de l’inspection', exact: true }).count(), 2);
  await capture(page, 'after-real-comparison');
  report.checks.push('Real sequential B0/T2 comparison and both scientific explanations');
  await resultLayouts(page, 'comparison');

  await navigate(page, 'batch');
  const existing = page.getByRole('button', { name: /^Ouvrir le lot / }).first();
  await existing.waitFor();
  await existing.click();
  await page.getByRole('progressbar', { name: 'Progression réelle du lot' }).waitFor();
  await page.locator('.batch-detail .table-scroll tbody tr').first().waitFor();
  report.checks.push('Existing PostgreSQL batch opened: real persisted progress and image results visible');
  // Native DataTransfer exercises the redesigned multi-file drop target.
  const transfer = await page.evaluateHandle((data) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array(data)], 'redesign-qa-002.png', { type: 'image/png' }));
    transfer.items.add(new File([new Uint8Array(data)], 'redesign-qa-002-copy.png', { type: 'image/png' }));
    return transfer;
  }, Array.from(bytes));
  await page.locator('.batch-drop').dispatchEvent('drop', { dataTransfer: transfer });
  await page.getByRole('button', { name: 'Démarrer le lot', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Démarrer le lot', exact: true }).click();
  await page.getByRole('progressbar', { name: 'Progression réelle du lot' }).waitFor({ timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('progress')?.value === 2, undefined, { timeout: 120000 });
  await page.getByText('1. redesign-qa-002.png', { exact: true }).waitFor();
  await page.getByText('2. redesign-qa-002-copy.png', { exact: true }).waitFor();
  await page.getByLabel('Filtre des résultats du lot').selectOption('normal');
  await page.getByText('1. redesign-qa-002.png', { exact: true }).waitFor();
  await page.getByLabel('Filtre des résultats du lot').selectOption('anomaly');
  await page.getByText('Aucune image pour ce filtre.', { exact: true }).waitFor();
  await page.getByLabel('Filtre des résultats du lot').selectOption('error');
  await page.getByText('Aucune image pour ce filtre.', { exact: true }).waitFor();
  await page.getByLabel('Filtre des résultats du lot').selectOption('all');
  await page.getByText('1. redesign-qa-002.png', { exact: true }).waitFor();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Exporter CSV', exact: true }).click();
  const csv = await download;
  assert.ok((await readFile(await csv.path(), 'utf8')).includes('redesign-qa-002.png'));
  await page.getByRole('button', { name: 'Expliquer', exact: true }).first().click();
  await page.getByRole('heading', { name: 'Heatmap de reconstruction', exact: true }).waitFor({ timeout: 120000 });
  await capture(page, 'after-real-batch');
  report.checks.push('Real batch: two PNG drag/drop, upload, worker progress 2/2, filters, CSV bytes, retained-image explanation');
  await resultLayouts(page, 'batch');
  await navigate(page, 'history');
  await page.getByRole('button', { name: 'Détails', exact: true }).first().click();
  await page.getByRole('heading', { name: 'Détails de l’inspection', exact: true }).waitFor();
  report.checks.push('Persistent history opens real inspection details');
  }
  await page.getByRole('link', { name: 'Ouvrir mon profil', exact: true }).click();
  await page.getByRole('button', { name: 'Déconnexion', exact: true }).click();
  // Keycloak can require explicit end-session confirmation when no id_token_hint
  // is sent by the existing BFF. Follow the real IdP screen, never bypass it.
  await page.waitForURL(/localhost:18585.*logout/);
  if (await page.locator('#kc-logout').isVisible()) await page.locator('#kc-logout').click();
  await page.waitForURL(`${base}/**`);
  await page.reload();
  await page.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  report.checks.push('Real logout returns to portal login');
  await context.close();

  for (const role of ['ai_engineer', 'operator', 'auditor']) {
    const roleContext = await contextFor();
    const rolePage = await login(roleContext, role);
    const nav = rolePage.getByRole('navigation', { name: 'Navigation principale' });
    const expected = {
      ai_engineer: ['Smart Inspection', 'Comparison Lab', 'System Monitor'],
      operator: ['Smart Inspection', 'Comparison Lab'],
      auditor: ['Audit'],
    }[role];
    for (const name of ['Smart Inspection', 'Comparison Lab', 'System Monitor', 'Administration', 'Audit']) {
      assert.equal(await nav.getByRole('link', { name, exact: true }).count(), expected.includes(name) ? 1 : 0, `${role}: ${name}`);
    }
    assert.equal(await rolePage.getByRole('button', { name: 'Nouvelle inspection', exact: true }).count(), role === 'auditor' ? 0 : 1);
    await navigate(rolePage, 'admin');
    await rolePage.getByText('ACCÈS 403', { exact: true }).waitFor();
    assert.equal((await rolePage.request.get(`${base}/api/admin/users`)).status(), 403);
    await navigate(rolePage, 'batch');
    await rolePage.getByRole('heading', { name: 'Historique des lots', exact: true }).waitFor();
    assert.equal(await rolePage.getByRole('button', { name: 'Démarrer le lot', exact: true }).count(), role === 'auditor' ? 0 : 1);
    await capture(rolePage, `after-role-${role}`);
    report.checks.push(`Role ${role}: authorized nav/dashboard/batch actions; direct #admin denied; real GET /api/admin/users = 403`);
    await roleContext.close();
  }
  const anonymous = await contextFor();
  assert.equal((await anonymous.request.get(`${base}/api/auth/session`)).status(), 401);
  const loginPage = await anonymous.newPage();
  await loginPage.goto(base);
  await loginPage.getByRole('link', { name: 'Se connecter', exact: true }).waitFor();
  assert.equal(await loginPage.locator('.sidebar').count(), 0);
  await capture(loginPage, 'after-real-401-login');
  report.checks.push('Anonymous session = real 401; portal login exposes no authenticated workspace');
  await anonymous.close();
  assert.deepEqual(report.errors, []);
  report.passed = true;
  console.log(`QA passed: ${report.checks.length} checks, ${report.captures.length} captures, no page errors.`);
  }
} catch (error) {
  report.passed = false;
  report.failure = error.message;
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, before ? 'before.json' : accessOnly ? 'access.json' : flowsOnly ? 'flows.json' : 'after.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
