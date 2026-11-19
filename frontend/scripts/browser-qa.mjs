// Local headless browser QA explicitly requested for this frontend redesign.
// Real local API only; webcam permission mocks belong to unit tests.
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const base = process.env.UI_TEST_URL || 'http://localhost:18080';
const reports = new URL('../reports/', import.meta.url);
const shots = new URL('screenshots/', reports);
await mkdir(shots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {
  base,
  checked_at: new Date().toISOString(),
  captures: [],
  requests: [],
  errors: [],
  checks: [],
};
try {
  for (const [name, width, height] of [
    ['desktop', 1440, 900],
    ['laptop', 1280, 720],
    ['mobile', 390, 844],
  ]) {
    for (const theme of ['dark', 'light']) {
      const context = await browser.newContext({
        viewport: { width, height },
        reducedMotion: 'reduce',
      });
      await context.addInitScript((theme) => localStorage.setItem('ri.theme', theme), theme);
      const page = await context.newPage();
      page.on('pageerror', (error) => report.errors.push(error.message));
      for (const route of ['dashboard', 'inspection', 'comparison', 'analytics']) {
        await page.goto(`${base}/#${route}`);
        await page.getByText('API opérationnelle', { exact: true }).first().waitFor();
        if (route === 'analytics') {
          await page
            .getByRole('heading', { name: 'AUROC image par catégorie', exact: true })
            .waitFor();
          await page.locator('.recharts-bar-rectangle path').first().waitFor({ state: 'attached' });
          const charts = await page
            .locator('.recharts-wrapper')
            .evaluateAll((nodes) => nodes.map((e) => e.getBoundingClientRect().width));
          assert.ok(charts.length === 3 && charts.every((w) => w > 100), `Empty charts: ${charts}`);
        }
        await page.evaluate(() => document.fonts.ready);
        const dimensions = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          viewport: innerWidth,
        }));
        assert.ok(
          dimensions.scroll <= dimensions.viewport + 1,
          `${name}/${theme}/${route}: overflow ${dimensions.scroll}/${dimensions.viewport}`,
        );
        const filename = `${name}-${theme}-${route}.png`;
        await page.screenshot({
          path: fileURLToPath(new URL(filename, shots)),
          fullPage: true,
          animations: 'disabled',
        });
        report.captures.push({ filename, width, height, theme, route });
        console.log(`Layout OK ${name} ${theme} ${route}`);
      }
      await context.close();
    }
  }
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => report.errors.push(e.message));
  page.on('response', async (response) => {
    if (response.url().includes('/api/predict'))
      report.requests.push({ url: new URL(response.url()).pathname, status: response.status() });
  });
  const fixture = new URL('../../data/raw/mvtec_ad/bottle/train/good/002.png', import.meta.url);
  assert.equal(
    createHash('sha256')
      .update(await readFile(fixture))
      .digest('hex'),
    '7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69',
  );
  await page.goto(`${base}/#inspection`);
  await page.getByText('API opérationnelle', { exact: true }).first().waitFor();
  await page.getByLabel('Fichier image à inspecter').setInputFiles(fileURLToPath(fixture));
  await page.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
  await page
    .getByRole('heading', { name: 'Heatmap de reconstruction', exact: true })
    .waitFor({ timeout: 120000 });
  await page.getByRole('button', { name: 'Côte à côte', exact: true }).click();
  assert.equal(await page.getByAltText('Carte explicative originale').first().isVisible(), true);
  await page.getByRole('button', { name: 'Ouvrir le visualiseur plein écran' }).click();
  assert.equal(await page.getByRole('dialog').isVisible(), true);
  await page.keyboard.press('Escape');
  await page.screenshot({
    path: fileURLToPath(new URL('desktop-real-b0.png', shots)),
    fullPage: true,
  });
  report.checks.push(
    'B0 real prediction, reconstruction error, side-by-side and native full-screen dialog',
  );
  await page.goto(`${base}/#comparison`);
  await page.getByLabel('Image de comparaison').setInputFiles(fileURLToPath(fixture));
  await page.getByRole('button', { name: 'Comparer les modèles', exact: true }).click();
  await page.getByRole('heading', { name: 'Grad-CAM', exact: true }).waitFor({ timeout: 120000 });
  await page
    .getByRole('heading', { name: 'Heatmap de reconstruction', exact: true })
    .waitFor({ timeout: 120000 });
  assert.equal(
    await page.getByRole('heading', { name: 'Résultat de l’inspection', exact: true }).count(),
    2,
  );
  await page.screenshot({
    path: fileURLToPath(new URL('desktop-real-comparison-b0-t2.png', shots)),
    fullPage: true,
  });
  report.checks.push('Comparison B0/T2 real sequential requests and both explanatory maps');
  const history = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('ri.inspections.v2') || '[]'),
  );
  assert.equal(history.length, 3);
  assert.ok(!JSON.stringify(history).includes('base64'));
  await page.goto(`${base}/#history`);
  await page.getByRole('heading', { name: 'Inspections enregistrées', exact: true }).waitFor();
  report.checks.push('3 real inspection metadata entries persisted without image bytes');
  assert.ok(
    report.requests.length === 4 && report.requests.every((r) => r.status === 200),
    JSON.stringify(report.requests),
  );
  assert.deepEqual(report.errors, []);
  report.passed = true;
  await context.close();
} catch (error) {
  report.passed = false;
  report.failure = String(error);
  throw error;
} finally {
  await browser.close();
  await writeFile(
    new URL('browser-verification.json', reports),
    JSON.stringify(report, null, 2) + '\n',
  );
}
