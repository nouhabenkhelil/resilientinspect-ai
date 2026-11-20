// Real local Chromium navigation. Screenshots stay in ignored mlops/local.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('playwright');
const runs = JSON.parse(await fs.readFile(path.join(root, 'reports/experiments/mlops_runs.json'), 'utf8'));
const row = runs.models.find(r => r.model === 'T2' && r.category === 'bottle');
const base = process.env.MLFLOW_UI_URL || 'http://127.0.0.1:5000';
const directory = path.join(root, 'mlops/local/screenshots');
await fs.mkdir(directory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const screens = [];
page.on('pageerror', error => errors.push(String(error)));
page.setDefaultTimeout(30_000);
async function contains(text) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible' });
  assert.ok((await page.locator('body').innerText()).includes(text));
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(directory, `${name}.png`), fullPage: true });
  screens.push(name);
}
try {
  await page.goto(base);
  await page.getByText('Model training', { exact: true }).click();
  await page.getByRole('link', { name: 'Experiments', exact: true }).click();
  for (const name of ['Historical-A1', 'Historical-B0', 'Archived-Transfer-Imported', 'Technical-ONNX-Benchmark', 'Registry-Packaging']) await contains(name);
  await screenshot('experiments');
  const response = await page.request.get(`${base}/api/2.0/mlflow/runs/get`, { params: { run_id: row.run_id } });
  assert.equal(response.status(), 200);
  const { run } = await response.json();
  await page.goto(`${base}/#/experiments/${run.info.experiment_id}/runs/${row.run_id}`);
  for (const text of ['official_test.image.auroc', 'training.batch_size', 'retrospective_archive_import', row.checkpoint_sha256]) await contains(text);
  await screenshot('run-metrics-parameters');
  await page.getByText('Artifacts', { exact: true }).click();
  await contains('frozen_evidence');
  await page.getByText('frozen_evidence', { exact: true }).click();
  await contains('best.pt');
  await contains('calibration.json');
  await screenshot('run-artifacts');
  await page.getByRole('link', { name: 'Model registry', exact: true }).click();
  for (const category of ['bottle', 'hazelnut', 'leather']) await contains(`ResilientInspect-T2-${category}`);
  // MLflow opens an onboarding modal on the first registry visit.
  if (await page.getByRole('dialog').isVisible()) await page.keyboard.press('Escape');
  await contains('demo_candidate');
  await screenshot('registry');
  await page.locator('a[href="#/models/ResilientInspect-T2-bottle/versions/1"]').first().click();
  for (const text of ['demo_candidate', row.checkpoint_sha256, row.calibration_sha256, row.protocol_sha256]) await contains(text);
  await screenshot('registry-version');
  assert.deepEqual(errors, []);
  const result = { status: 'passed', engine: 'Chromium', mlflow_version: '3.16.1', screens,
    real_run_id: row.run_id, real_registry_model: 'ResilientInspect-T2-bottle', real_registry_version: '1',
    parameters_metrics_artifacts_visible: true, three_registry_models_visible: true, alias_visible: true, page_errors: errors };
  await fs.writeFile(path.join(root, 'reports/experiments/mlops_browser.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
} finally { await browser.close(); }
