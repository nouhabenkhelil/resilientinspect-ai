// Real OIDC/browser and operational HTTP checks. Credentials stay in ignored local files.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile,writeFile } from 'node:fs/promises';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const local=new URL('../industrial/local/',import.meta.url);
const clone=process.argv.includes('--recovery');
let folder;
if(clone) folder=JSON.parse(await readFile(new URL('observability/recovery-current.json',local),'utf8')).folder;
const accounts=JSON.parse(await readFile(clone?folder+'/authenticated/config/accounts.json':new URL('accounts.json',local),'utf8')).accounts;
const base=clone?'http://localhost:18680':'http://localhost:18180';
const expected=clone?JSON.parse(await readFile(folder+'/authenticated/business.json','utf8')):null;
const report={at:new Date().toISOString(),base,roles:[],page_errors:[],checks:[]};
const browser=await chromium.launch();
try {
  assert.equal((await fetch(base+'/api/operations')).status,401);
  assert.equal((await fetch(base+'/api/metrics')).status,404);
  for(const label of ['admin','engineer','operator','auditor']) {
    const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
    const page=await context.newPage();
    page.on('pageerror',()=>report.page_errors.push(label));
    await page.goto(base);
    await page.getByRole('link',{name:'Se connecter',exact:true}).click();
    await page.locator('#username').waitFor({timeout:60000});
    assert.match(page.url(),/code_challenge_method=S256/);
    await page.locator('#username').fill(accounts[label].username);
    await page.locator('#password').fill(accounts[label].password);
    await page.locator('#kc-login').click();
    await page.waitForURL(base+'/**',{timeout:60000});
    const session=await (await context.request.get(base+'/api/auth/session')).json();
    assert.equal(session.user.role,accounts[label].role);
    if(expected) assert.ok(expected.users.some(u=>u.id===session.user.id),'Restored ownership identity must survive clone URL adaptation');
    const status=await (await context.request.get(base+'/api/status')).json();
    assert.equal(status.ready_models_by_engine.pytorch,15);
    assert.equal(status.ready_models_by_engine.onnxruntime,14);
    const response=await context.request.get(base+'/api/operations');
    const allowed=['admin','engineer'].includes(label);
    assert.equal(response.status(),allowed?200:403);
    assert.equal((await context.request.get(base+'/api/operations/events')).status(),allowed?200:403);
    if(allowed) {
      const data=await response.json(); assert.ok(data.database_up && data.science_up && data.queue);
      report.snapshot=data;
      await page.goto(base+'/#monitor');
      await page.getByRole('region',{name:'Operations Center'}).waitFor();
      await page.getByRole('region',{name:'Operations Center'}).getByText('15 / 14',{exact:true}).waitFor();
      await page.screenshot({path:new URL(`screenshots/operations-${clone?'recovery-':''}${label}.png`,local).pathname.replace(/^\/(.:)/,'$1'),fullPage:true});
    }
    if(label==='operator') {
      const image=await readFile(new URL('../../data/raw/mvtec_ad/bottle/train/good/002.png',import.meta.url));
      const refused=await context.request.post(base+'/api/predict',{headers:{Origin:base,'X-CSRF-Token':session.csrf_token},
        multipart:{model:'T1',category:'bottle',engine:'onnxruntime',file:{name:'inspection.png',mimeType:'image/png',buffer:image}}});
      assert.equal(refused.status(),503);
      assert.equal((await refused.json()).code,'onnx_unavailable');
      report.t1_bottle_onnx_refused_without_fallback=true;
      const history=await context.request.get(base+'/api/inspections'); assert.equal(history.status(),200);
      const batches=await context.request.get(base+'/api/batches'); assert.equal(batches.status(),200);
      report.operator_history=await history.json(); report.operator_batches=await batches.json();
      if(expected) {
        const owned=expected.inspections.filter(i=>i.owner_id===session.user.id).length;
        assert.equal(report.operator_history.total,owned);
      }
    }
    const csrf={Origin:base,'X-CSRF-Token':session.csrf_token};
    assert.equal((await context.request.post(base+'/api/auth/logout',{headers:csrf})).status(),200);
    assert.equal((await context.request.get(base+'/api/operations')).status(),401);
    report.roles.push({label,role:session.user.role,oidc_pkce:true,operations:response.status(),logout_revoked:true});
    await context.close();
  }
  assert.deepEqual(report.page_errors,[]);
  report.checks.push('Anonymous denied; metrics masked by gateway; actual PKCE/login/logout and four-role matrix; live 15/14 model status');
  await writeFile(new URL(`observability/browser-${clone?'recovery':'live'}.json`,local),JSON.stringify(report,null,2));
  console.log(JSON.stringify({base,roles:report.roles,models:report.snapshot.models,page_errors:report.page_errors,restored_history:clone?report.operator_history.total:undefined}));
} finally { await browser.close(); }
