// Deployed V3 only. Record after real OIDC login, never credentials or cookies.
import { chromium } from '@playwright/test';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const base = 'http://localhost:18180';
const root = fileURLToPath(new URL('../../', import.meta.url));
const output = path.join(root, process.env.MOTION_QA_OUTPUT || 'frontend/reports/screenshots/motion/2026-11-27');
await mkdir(output, { recursive: true });
const report = { origin: base, checkedAt: new Date().toISOString(), checks: [], errors: [], responses: [] };
const browser = await chromium.launch({ headless: true });
let recording;
try {
  const account = JSON.parse(await readFile(path.join(root, 'deployment/industrial/local/accounts.json'), 'utf8')).accounts.admin;
  const auth = await browser.newContext();
  const login = await auth.newPage();
  await login.goto(base);
  await login.getByRole('link', { name: 'Se connecter', exact: true }).click();
  await login.locator('#username').fill(account.username);
  await login.locator('#password').fill(account.password);
  await login.locator('#kc-login').click();
  await login.waitForURL(`${base}/**`);
  await login.getByRole('link', { name: 'Mon profil', exact: true }).waitFor();
  report.browserDefaultReducedMotion = await login.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  report.recordedMotionPreference = 'no-preference';
  const storageState = await auth.storageState(); // Memory only, not a file.
  await auth.close();
  recording = await browser.newContext({ storageState, reducedMotion: 'no-preference', viewport: { width: 1440, height: 900 }, recordVideo: { dir: output, size: { width: 1440, height: 900 } } });
  await recording.addInitScript(() => {
    const evidence = window.__motionEvidence = { samples: [], animations: [], scanning: [], progress: [], resultFrames: [], csvBusy: false };
    let last = 0;
    const started = performance.now();
    function sample(now) {
      if (now - last >= 45) {
        last = now;
        const counter = document.querySelector('.stat-value span[aria-label]');
        if (counter && now - started < 3000) evidence.samples.push({ t: Math.round(now - started), text: counter.textContent, target: counter.getAttribute('aria-label') });
        for (const animation of document.getAnimations()) {
          const name = animation.animationName || animation.transitionProperty;
          if (name && !evidence.animations.includes(name)) evidence.animations.push(name);
        }
        const scan = document.querySelector('.preview-grid.is-analyzing');
        const result = document.querySelector('.result-panel');
        if (result) evidence.resultFrames.push({ t: Math.round(now - started), opacity: getComputedStyle(result).opacity });
        if (scan) evidence.scanning.push({ t: Math.round(now - started), transform: getComputedStyle(scan, '::after').transform });
        const progress = document.querySelector('.batch-progress-track');
        if (progress) evidence.progress.push({ t: Math.round(now - started), value: progress.querySelector('progress').value, max: progress.querySelector('progress').max, transform: getComputedStyle(progress.querySelector('span')).transform });
        if (document.querySelector('button[aria-busy="true"]')) evidence.csvBusy = true;
      }
      if (now - started < 90000) requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  const page = await recording.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', (error) => report.errors.push(error.message));
  page.on('response', async (response) => {
    const url = new URL(response.url());
    if (url.pathname.endsWith('/progress') && response.ok()) {
      const json = await response.json();
      report.responses.push({ path: url.pathname, processed: json.processed, total: json.total, status: json.status });
    }
  });
  await page.goto(base);
  assert.equal(await page.locator('.app-shell').getAttribute('data-motion-revision'), 'visible-v3');
  await page.getByText('API opérationnelle', { exact: true }).waitFor();
  await page.waitForTimeout(1250); // Observe entry/counting; no request is delayed.
  const counterEvidence = await page.evaluate(() => window.__motionEvidence);
  assert.ok(counterEvidence.animations.includes('studio-reveal'));
  const measured = await page.locator('.stat-value span[aria-label]').first().getAttribute('aria-label');
  const values = counterEvidence.samples.filter((sample) => sample.target === measured).map((sample) => Number(sample.text));
  assert.ok(values.some((value) => value > 0 && value < Number(measured)), 'Measured CountUp must have intermediate rendered frames');
  assert.equal(await page.locator('.stat-value span[aria-label]').first().textContent(), measured);
  report.counter = { target: measured, frames: counterEvidence.samples };
  report.checks.push('Real availability CountUp: intermediate frames and exact final value; staggered KPI entrance observed');
  await page.getByRole('button', { name: 'Actualiser le statut API', exact: true }).click();
  await page.waitForTimeout(300);
  assert.equal(await page.locator('.stat-value span[aria-label]').first().textContent(), measured);
  assert.equal(await page.locator('.stat-value span[aria-label]').first().getAttribute('data-counting'), 'false');
  report.checks.push('Unchanged API refresh does not replay CountUp');
  assert.equal(await page.locator('.sidebar nav a span').first().isVisible(), true);
  assert.equal(await page.locator('.app-shell.sidebar-collapsed').count(), 0);
  const card = page.locator('.stat-card').first();
  const rect = await card.boundingBox();
  await page.mouse.move(rect.x + 30, rect.y + 30);
  await page.waitForTimeout(230);
  const first = await card.evaluate((node) => ({ x: node.style.getPropertyValue('--mouse-x'), opacity: getComputedStyle(node, '::before').opacity, transform: getComputedStyle(node).transform }));
  await page.mouse.move(rect.x + 150, rect.y + 80);
  const second = await card.evaluate((node) => node.style.getPropertyValue('--mouse-x'));
  assert.notEqual(first.x, second);
  assert.ok(Number(first.opacity) > .5 && first.transform !== 'none');
  report.spotlight = { first, second };
  report.checks.push('Pointer-following theme accent light and lifted hover verified by computed styles');
  await page.screenshot({ path: path.join(output, 'desktop-motion.png') });
  const summary = page.locator('.official-summary');
  assert.equal(await summary.getAttribute('data-motion-visible'), 'false', 'Below-fold chart must wait for visibility');
  await summary.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('.official-summary')?.dataset.motionVisible === 'true');
  assert.ok(await summary.evaluate((node) => node.getAnimations().some((animation) => animation.playState === 'running')));
  await page.waitForTimeout(600);
  const chartAnimationCount = await summary.evaluate((node) => node.getAnimations().length);
  assert.equal(chartAnimationCount, 0);
  report.checks.push('Below-fold summary waits for viewport; chart bars reveal once and keep official widths');
  await page.getByRole('button', { name: 'Activer le mode clair' }).click();
  await page.waitForTimeout(80);
  assert.ok(await page.evaluate(() => document.getAnimations().some((animation) => animation.transitionProperty === 'background-color')));
  await page.waitForTimeout(350);
  await page.getByRole('button', { name: 'Activer le mode sombre' }).click();
  await page.waitForTimeout(350);
  report.checks.push('Real theme control generates background-colour transitions');
  await page.getByRole('link', { name: 'Smart Inspection', exact: true }).click();
  await page.waitForTimeout(70);
  assert.ok(await page.locator('.page-heading').evaluate((node) => node.getAnimations().some((animation) => animation.playState === 'running')));
  const fixture = path.join(root, 'data/raw/mvtec_ad/bottle/train/good/002.png');
  await page.getByLabel('Fichier image à inspecter').setInputFiles(fixture);
  await page.getByLabel('Modèle d’inspection').selectOption('T2');
  await page.locator('.local-preview').waitFor();
  await page.getByRole('button', { name: 'Analyser l’image', exact: true }).scrollIntoViewIfNeeded();
  const predictionResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/predict' && response.request().method() === 'POST', { timeout: 120000 });
  await page.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
  const prediction = await predictionResponse;
  assert.equal(prediction.status(), 200);
  report.prediction = await prediction.json();
  await page.getByRole('heading', { name: 'Grad-CAM', exact: true }).waitFor({ timeout: 120000 });
  assert.ok(await page.locator('.exact-values').textContent().then((value) => value.includes(String(report.prediction.threshold))));
  const scanning = await page.evaluate(() => window.__motionEvidence.scanning);
  assert.ok(scanning.length > 0 && scanning.some((sample) => sample.transform !== 'none'), 'Scan must be observed during a real in-flight request');
  assert.equal(await page.locator('.is-analyzing').count(), 0);
  report.scanning = scanning;
  await page.locator('.result-panel').scrollIntoViewIfNeeded();
  await page.waitForTimeout(450);
  await page.getByRole('button', { name: 'Carte seule', exact: true }).click();
  await page.waitForTimeout(60);
  assert.ok(await page.locator('.visualization-panel > .explanation > .visual-frame > .zoom-canvas').evaluate((node) => node.getAnimations().length > 0));
  await page.locator('.visualization-panel .viewer-toolbar select').selectOption('1.5');
  await page.waitForTimeout(300);
  assert.equal(await page.locator('.visualization-panel > .explanation > .visual-frame > .zoom-canvas').evaluate((node) => getComputedStyle(node).transform), 'matrix(1.5, 0, 0, 1.5, 0, 0)');
  await page.locator('.visualization-panel .viewer-toolbar select').selectOption('1');
  report.resultFrames = await page.evaluate(() => window.__motionEvidence.resultFrames);
  assert.ok(report.resultFrames.some((frame) => Number(frame.opacity) > 0 && Number(frame.opacity) < 1), 'Returned result must visibly transition when brought into view');
  report.checks.push('Real T2 inference: in-flight scanning, returned decision/score/threshold, view fade and preserved 150% zoom');
  await page.screenshot({ path: path.join(output, 'inspection-motion.png'), fullPage: true });
  await page.getByRole('link', { name: 'Comparison Lab', exact: true }).click();
  await page.getByLabel('Image de comparaison').setInputFiles(fixture);
  // Toggle a real selection to observe the selection feedback, then restore B0/T2.
  const t2 = page.locator('.comparison-models label').filter({ has: page.getByRole('checkbox') }).filter({ hasText: 'T2' });
  await t2.getByRole('checkbox').uncheck();
  await t2.getByRole('checkbox').check();
  assert.ok(await t2.evaluate((node) => node.getAnimations().some((animation) => animation.animationName === 'studio-select')));
  const comparisonResponses = [];
  const collectComparison = async (response) => {
    if (new URL(response.url()).pathname === '/api/predict/visualize' && response.request().method() === 'POST' && response.ok()) {
      const result = await response.json();
      comparisonResponses.push({ model: result.model, anomaly_score: result.anomaly_score, threshold: result.threshold, decision: result.decision });
    }
  };
  page.on('response', collectComparison);
  await page.getByRole('button', { name: 'Comparer les modèles', exact: true }).click();
  await page.locator('.comparison-result').nth(1).waitFor({ timeout: 120000 });
  await page.getByRole('button', { name: 'Comparer les modèles', exact: true }).waitFor({ state: 'visible' });
  await page.locator('.comparison-page > .comparison-results').scrollIntoViewIfNeeded();
  await page.waitForTimeout(650);
  assert.equal(comparisonResponses.length, 2);
  for (const result of comparisonResponses) {
    const card = page.locator('.comparison-result').filter({ has: page.getByRole('heading', { name: result.model, exact: true }) });
    assert.ok((await card.locator('.exact-values').textContent()).includes(String(result.anomaly_score)));
    assert.ok((await card.locator('.exact-values').textContent()).includes(String(result.threshold)));
    assert.equal(await card.getAttribute('data-motion-visible'), 'true');
  }
  report.comparison = comparisonResponses;
  report.checks.push('Real sequential B0/T2 comparison: selection animation, viewport card reveals and unchanged scores/thresholds');
  await page.screenshot({ path: path.join(output, 'comparison-motion.png'), fullPage: true });
  page.off('response', collectComparison);
  await page.getByRole('link', { name: 'Batch Inspection', exact: true }).click();
  await page.waitForFunction(() => { const input = document.querySelector('input[aria-label="Images du lot"]'); return input && !input.disabled; });
  const image = await readFile(fixture);
  await page.getByLabel('Images du lot').setInputFiles([1, 2, 3].map((index) => ({ name: `motion-qa-${index}.png`, mimeType: 'image/png', buffer: image })));
  await page.waitForTimeout(450);
  await page.getByRole('button', { name: 'Démarrer le lot', exact: true }).click();
  await page.locator('.batch-progress-track').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('progress')?.value === 3, undefined, { timeout: 120000 });
  await page.waitForTimeout(450);
  const progress = await page.evaluate(() => window.__motionEvidence.progress);
  assert.ok(progress.some((sample) => sample.value === 3));
  assert.ok(progress.some((sample) => { const a = Number(sample.transform.match(/^matrix\(([^,]+)/)?.[1]); return a > 0 && a < 1; }), 'Visual bar must interpolate between real backend updates');
  assert.ok(report.responses.some((response) => response.processed === 3 && response.total === 3));
  report.progress = progress;
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Exporter CSV', exact: true }).click();
  const csv = await download;
  assert.ok((await readFile(await csv.path(), 'utf8')).includes('motion-qa-1.png'));
  await page.getByText('CSV prêt : le téléchargement a été déclenché.', { exact: true }).waitFor();
  report.checks.push('Real three-image batch: file reveal, genuine 3/3 backend progress, animated visual bar, CSV and completion feedback');
  await page.screenshot({ path: path.join(output, 'batch-motion.png'), fullPage: true });
  report.animations = await page.evaluate(() => window.__motionEvidence.animations);
  const video = page.video();
  await recording.close(); recording = undefined;
  const videoPath = await video.path();
  await copyFile(videoPath, path.join(output, 'motion-proof.webm'));
  report.video = 'motion-proof.webm';
  for (const [name, width, motion] of [['mobile', 390, 'no-preference'], ['reduced', 1440, 'reduce'], ['compact', 1280, 'no-preference']]) {
    const context = await browser.newContext({ storageState, reducedMotion: motion, viewport: { width, height: 900 } });
    const check = await context.newPage();
    await check.goto(base);
    await check.getByText('API opérationnelle', { exact: true }).waitFor();
    if (name === 'mobile') {
      await check.getByRole('button', { name: 'Ouvrir la navigation' }).click();
      await check.waitForTimeout(80);
      assert.ok(await check.locator('.sidebar').evaluate((node) => node.getAnimations().length > 0));
      await check.waitForTimeout(250);
      await check.screenshot({ path: path.join(output, 'mobile-motion.png') });
      await check.keyboard.press('Escape');
      assert.equal(await check.getByRole('button', { name: 'Ouvrir la navigation' }).getAttribute('aria-expanded'), 'false');
      assert.equal(await check.getByRole('button', { name: 'Ouvrir la navigation' }).evaluate((node) => document.activeElement === node), true);
    } else if (name === 'reduced') {
      assert.ok(await check.evaluate(() => [...document.querySelectorAll('*')].every((node) => parseFloat(getComputedStyle(node).animationDuration) <= .00001)));
      const counts = await check.locator('.stat-value span[aria-label]').evaluateAll((nodes) => nodes.every((node) => node.textContent === node.getAttribute('aria-label')));
      assert.ok(counts);
      await check.getByRole('link', { name: 'Smart Inspection', exact: true }).click();
      await check.getByLabel('Fichier image à inspecter').setInputFiles(fixture);
      await check.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
      await check.locator('.is-analyzing').waitFor();
      assert.equal(await check.locator('.is-analyzing').evaluate((node) => getComputedStyle(node, '::after').display), 'none');
      await check.getByRole('heading', { name: 'Résultat de l’inspection', exact: true }).waitFor({ timeout: 120000 });
      await check.locator('.result-panel').scrollIntoViewIfNeeded();
      assert.equal(await check.locator('.result-panel').evaluate((node) => getComputedStyle(node).opacity), '1');
      await check.screenshot({ path: path.join(output, 'reduced-motion.png') });
    } else {
      assert.equal(await check.locator('.app-shell.sidebar-collapsed').count(), 0);
      await check.waitForTimeout(1250); // Capture the settled compact layout too.
      await check.screenshot({ path: path.join(output, 'compact-motion.png') });
    }
    const dimensions = await check.evaluate(() => ({ viewport: innerWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(dimensions.scroll <= dimensions.viewport + 1);
    report.checks.push(`${name}: motion preference, accessible navigation and no global overflow`);
    await context.close();
  }
  assert.deepEqual(report.errors, []);
  report.passed = true;
  console.log(`Motion QA passed: ${report.checks.length} checks; video ${report.video}`);
} catch (error) { report.passed = false; report.failure = error.message; process.exitCode = 1; console.error(error.message); }
finally { if (recording) await recording.close(); await browser.close(); await writeFile(path.join(output, 'verification.json'), JSON.stringify(report, null, 2)); }
