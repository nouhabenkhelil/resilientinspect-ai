import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const base = process.env.UI_TEST_URL || 'http://localhost:18080';
const output = new URL('../reports/', import.meta.url);
await mkdir(new URL('screenshots/', output), { recursive: true });
const report = { base, checks: [], responses: [], errors: [] };
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce',
  });
  page.on('pageerror', (e) => report.errors.push(e.message));
  const file = new URL('../../data/raw/mvtec_ad/bottle/train/good/002.png', import.meta.url);
  assert.equal(
    createHash('sha256')
      .update(await readFile(file))
      .digest('hex'),
    '7de0414f1744aaf5cec488928ee3b761509e4bad4f607dc4f6d41ad7862dab69',
  );
  await page.goto(`${base}/#inspection`);
  await page.getByText('API opérationnelle', { exact: true }).first().waitFor();
  const health = await (await page.request.get(`${base}/api/health`)).json();
  assert.equal(health.ready_models, 15);
  for (const model of ['B0', 'T2']) {
    await page.getByLabel('Modèle d’inspection').selectOption(model);
    await page.getByLabel('Moteur de prédiction').selectOption('onnxruntime');
    await page.getByLabel('Fichier image à inspecter').setInputFiles(fileURLToPath(file));
    const prediction = page.waitForResponse(
      (r) => r.url().endsWith('/api/predict') && r.request().method() === 'POST',
    );
    const visual = page.waitForResponse(
      (r) => r.url().endsWith('/api/predict/visualize') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Analyser l’image', exact: true }).click();
    for (const response of [await prediction, await visual]) {
      assert.equal(response.status(), 200);
      const body = await response.json();
      assert.equal(body.engine, 'onnxruntime');
      report.responses.push({
        path: new URL(response.url()).pathname,
        status: response.status(),
        model: body.model,
        engine: body.engine,
        score: body.anomaly_score,
        threshold: body.threshold,
        explanation_engine: body.explanation_engine,
        coherent: body.explanation_score_coherent,
      });
      if (body.visualization) {
        assert.equal(body.explanation_engine, model === 'B0' ? 'onnxruntime' : 'pytorch');
        if (model === 'T2') assert.equal(body.explanation_score_coherent, true);
      }
    }
    await page
      .getByRole('heading', {
        name: model === 'B0' ? 'Heatmap de reconstruction' : 'Grad-CAM',
        exact: true,
      })
      .waitFor();
    await page.screenshot({
      path: fileURLToPath(new URL(`screenshots/onnx-${model}.png`, output)),
      fullPage: true,
    });
    report.checks.push(`Real ${model} ONNX prediction and correct explanation engine`);
  }
  await page.goto(`${base}/#comparison`);
  await page.getByLabel('Image de comparaison').setInputFiles(fileURLToPath(file));
  await page.getByText('Comparaison technique des moteurs · même architecture',{exact:true}).click();
  await page.getByRole('button',{name:'Comparer PyTorch et ONNX',exact:true}).click();
  await page.getByText('ONNX Runtime',{exact:true}).waitFor({timeout:120000});
  assert.equal(await page.getByRole('heading',{name:'Résultat de l’inspection',exact:true}).count(),2);
  report.checks.push('Technical engine comparison executes both actual engines sequentially');
  await page.goto(`${base}/#analytics`);
  await page.getByRole('heading', { name: 'PyTorch / ONNX Runtime', exact: true }).waitFor();
  await page
    .locator('.performance-engineering .recharts-bar-rectangle path')
    .first()
    .waitFor({ state: 'attached' });
  await page.getByLabel('Métrique du benchmark').selectOption('p95_ms');
  await page.screenshot({
    path: fileURLToPath(new URL('screenshots/onnx-performance.png', output)),
    fullPage: true,
  });
  report.checks.push('Measured p50/p95/throughput benchmark charts and tables rendered');
  await page.goto(`${base}/#monitor`);
  await page.getByText('PyTorch / ONNX validés', { exact: true }).waitFor();
  assert.deepEqual(report.errors, []);
  report.passed = true;
} catch (e) {
  report.passed = false;
  report.error = String(e);
  throw e;
} finally {
  await browser.close();
  await writeFile(
    new URL('onnx-browser-verification.json', output),
    JSON.stringify(report, null, 2) + '\n',
  );
}
