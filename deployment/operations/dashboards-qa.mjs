import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {chromium}=require('@playwright/test');
const local=new URL('../industrial/local/',import.meta.url);
const password=(await readFile(new URL('observability/secrets/grafana_password',local),'utf8')).trim();
const browser=await chromium.launch();
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[]; page.on('pageerror',()=>errors.push('grafana-browser-error'));
const report={at:new Date().toISOString(),dashboards:[]};
try {
  await page.goto('http://localhost:13000/login',{timeout:60000});
  await page.locator('input[name="user"]').fill('ri-admin');
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button',{name:'Log in',exact:true}).click();
  await page.waitForURL(url=>!url.pathname.startsWith('/login'),{timeout:60000});
  for(const key of ['health','api','batches','processing','database','engines']) {
    await page.goto('http://localhost:13000/d/ri-'+key,{timeout:60000});
    await page.getByRole('main').waitFor();
    await page.getByText('Dashboard not found',{exact:true}).count().then(n=>assert.equal(n,0));
    // Query the live provisioned definition with this browser's authenticated cookie.
    const definition=await page.request.get('http://localhost:13000/api/dashboards/uid/ri-'+key);
    assert.equal(definition.status(),200);
    const data=await definition.json();
    for(const panel of data.dashboard.panels) {
      await page.getByText(panel.title,{exact:true}).first().waitFor({timeout:60000});
    }
    await page.screenshot({path:new URL('screenshots/grafana-'+key+'.png',local).pathname.replace(/^\/(.:)/,'$1'),fullPage:true});
    report.dashboards.push({uid:'ri-'+key,title:data.dashboard.title,visible_panels:data.dashboard.panels.length});
  }
  assert.deepEqual(errors,[]); report.errors=errors;
  await writeFile(new URL('observability/grafana-browser.json',local),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {await browser.close();}
