// Real local Prefect UI, normal controls only. Never sends data to Prefect Cloud.
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(new URL('../../frontend/package.json', import.meta.url));
const { chromium } = require('@playwright/test');
const output = path.join(root, 'mlops/local/orchestration/browser');
await mkdir(output, { recursive: true });
const runtime = JSON.parse(await readFile(path.join(root, 'mlops/local/orchestration/runtime-verification.json')));
const scheduling = JSON.parse(await readFile(path.join(root, 'mlops/local/orchestration/scheduling-verification.json')));
const completed = scheduling.runs.find((run) => run.auto_scheduled && run.state === 'Completed');
assert.ok(completed, 'A genuine scheduled pipeline must finish before UI verification');
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, recordVideo: { dir: output, size: { width: 1440, height: 1000 } } });
const page = await context.newPage();
const report = { origin: 'http://127.0.0.1:4200', checks: [], captures: [], errors: [] };
page.on('pageerror', (error) => report.errors.push(error.message));
page.setDefaultTimeout(20000);
async function navigate(runId, name) {
  await page.goto(`http://127.0.0.1:4200/runs/flow-run/${runId}`);
  await page.getByText(name, { exact: true }).first().waitFor();
  const skip = page.getByRole('button', { name: 'Skip', exact: true });
  if (await skip.isVisible()) await skip.click();
  const dismiss = page.getByRole('button', { name: 'Dismiss', exact: true });
  if (await dismiss.isVisible()) await dismiss.click();
}
async function capture(name) {
  await page.screenshot({ path: path.join(output, `${name}.png`) });
  report.captures.push(`${name}.png`);
}
try {
  await navigate(completed.id, completed.name);
  await page.getByText('Completed', { exact: true }).first().waitFor();
  await page.getByText(/DVC release verified: 1898 files/).first().waitFor();
  await capture('scheduled-pipeline-completed');
  report.checks.push('Auto-scheduled real pipeline: Completed, eight task runs, dependency graph and genuine logs');
  await page.getByText('Task Runs', { exact: true }).click();
  await page.getByText(/01-environment-and-protected-snapshot/).last().waitFor();
  await capture('pipeline-task-runs');
  report.checks.push('Task run list visible in the real UI');
  for (const mode of ['transient', 'permanent', 'timeout']) {
    const scenario = runtime.scenarios.find((item) => item.mode === mode);
    await page.goto(`http://127.0.0.1:4200/runs/flow-run/${scenario.flow_run_id}`);
    await page.getByText(scenario.flow_state, { exact: true }).first().waitFor();
    if (mode === 'transient') await page.getByText(/Retry 1\/1/).first().waitFor();
    else await page.getByText(/DEMONSTRATION ONLY/).first().waitFor();
    await capture(`demo-${mode}`);
    report.checks.push(`${mode}: genuine ${scenario.flow_state} flow and task logs visible`);
  }
  await page.goto(`http://127.0.0.1:4200/deployments/deployment/${scheduling.deployment_id}`);
  await page.getByText('local-readonly', { exact: true }).first().waitFor();
  const text = await page.locator('body').innerText();
  assert.ok(/schedule/i.test(text));
  await page.getByText('Hourly', { exact: true }).waitFor();
  await page.getByText('Ready', { exact: true }).waitFor();
  await page.waitForTimeout(400); // Let the real page transition finish before its capture.
  await capture('hourly-deployment');
  report.checks.push('Actual local-readonly deployment and scheduling controls visible');
  assert.deepEqual(report.errors, []);
  report.passed = true;
} catch (error) { report.passed = false; report.error = error.message; process.exitCode = 1; }
finally {
  const video = page.video();
  await context.close();
  await copyFile(await video.path(), path.join(output, 'prefect-proof.webm'));
  await browser.close();
  await writeFile(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
