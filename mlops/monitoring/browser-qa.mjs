// Real authenticated Grafana rendering and datasource requests; private evidence only.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const local=new URL('../local/monitoring/',import.meta.url);
const password=(await readFile(new URL('secrets/grafana_password',local),'utf8')).trim();
await mkdir(new URL('runtime/browser/',local),{recursive:true});
const browser=await chromium.launch();
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];page.on('pageerror',()=>errors.push('grafana-page-error'));
const report={at:new Date().toISOString(),dashboards:[],page_errors:errors};
try {
  await page.goto('http://127.0.0.1:13000/login');
  await page.locator('input[name="user"]').fill('ri-admin');
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button',{name:'Log in',exact:true}).click();
  await page.waitForURL(url=>!url.pathname.startsWith('/login'),{timeout:60000});
  for(const key of ['infrastructure','api','models']) {
    const uid='ri-mlops-'+key;
    await page.goto('http://127.0.0.1:13000/d/'+uid+(key==='models'?'?var-source=validation':''));
    const response=await page.request.get('http://127.0.0.1:13000/api/dashboards/uid/'+uid);
    assert.equal(response.status(),200);const data=await response.json();
    assert.equal(await page.getByText('Dashboard not found',{exact:true}).count(),0);
    let measured=0;const panels=[];
    for(const panel of data.dashboard.panels) {
      await page.getByText(panel.title,{exact:true}).first().waitFor({timeout:60000});
      const now=Date.now();
      const request=await page.request.post('http://127.0.0.1:13000/api/ds/query',{data:{from:String(now-30*60*1000),to:String(now),queries:[{
        refId:'A',datasource:{type:'prometheus',uid:'ri-prom'},expr:panel.targets[0].expr.replaceAll('$source','validation'),
        range:true,intervalMs:10000,maxDataPoints:180,format:'time_series'}]}});
      assert.equal(request.status(),200,panel.title);
      const result=(await request.json()).results.A;assert.equal(result.error,undefined,panel.title);
      const actual=(result.frames??[]).some(f=>f.data.values.slice(1).some(v=>v.some(x=>typeof x==='number'&&Number.isFinite(x))));
      measured+=Number(actual);panels.push({title:panel.title,query_ok:true,measured_data:actual});
    }
    assert.ok(measured>=4,'Dashboard must contain actual datasource measurements');
    await page.screenshot({path:new URL('runtime/browser/'+uid+'.png',local).pathname.replace(/^\/(.:)/,'$1'),fullPage:true});
    report.dashboards.push({uid,title:data.dashboard.title,visible_panels:panels.length,panels_with_measurements:measured,panels});
  }
  assert.deepEqual(errors,[]);
  const health=await page.request.get('http://127.0.0.1:13000/api/datasources/uid/ri-prom/health');
  assert.equal((await health.json()).status,'OK');report.datasource_health='OK';
  await writeFile(new URL('runtime/browser-verification.json',local),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {await browser.close();}
