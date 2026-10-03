// Real execution menu, simulated Pi only. No production origin/hardware access.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./stop-project-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0),origin=new URL(preview.url).origin;
const report={scope:'Real execution UI; in-memory owner-bound stop responses; no Pi/camera/cloud/production storage.',checks:[],errors:[],denied:[]};
let browser,page;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const width of [1651,1352,390,320])for(const locale of ['zh-TW','en']){
    const context=await browser.newContext({viewport:{width,height:width<500?844:871}});
    await context.addInitScript(value=>localStorage.setItem('boardvision.locale.v1',value),locale);
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      if(u.origin===origin&&['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'].includes(u.pathname))return route.continue();
      report.denied.push(u.href);return route.abort();
    });
    page=await context.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
    await page.goto(`${preview.url}?executionStop=running&locale=${locale}`,{waitUntil:'networkidle'});
    assert(await page.locator('body').innerText());
    assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
    const draft=page.locator('.maker-composer textarea');await draft.fill('Keep my unsent draft');
    const storageBefore=await page.evaluate(()=>JSON.stringify(localStorage));
    const historyBefore=await page.locator('.maker-message').allTextContents();
    await page.locator('.pi-execution-menu > summary').click();
    const stop=page.getByRole('button',{name:locale==='en'?'Stop project':'停止作品',exact:true});
    const confirm=page.getByRole('button',{name:locale==='en'?'Confirm stop':'確認停止',exact:true});
    const cancel=page.getByRole('button',{name:locale==='en'?'Cancel':'取消',exact:true});
    assert(await stop.isEnabled());await stop.click();
    assert.deepEqual(await page.evaluate(()=>window.__stopProjectQa.events),[]);
    await cancel.click();assert.equal(await confirm.count(),0);
    assert.deepEqual(await page.evaluate(()=>window.__stopProjectQa.events),[]);
    await stop.click();await page.evaluate(()=>window.__stopProjectQa.changeOwner());
    await confirm.waitFor();assert(await confirm.isDisabled());await cancel.click();
    await stop.click();await confirm.click();
    await page.locator('.pi-current-owner').filter({hasText:locale==='en'?'Project stopped':'作品已停止'}).waitFor();
    assert.deepEqual(await page.evaluate(()=>window.__stopProjectQa.events),[{path:'/api/pi/stop',body:{owner:'program:offline-replacement'}}]);
    assert(await stop.isDisabled());assert.equal(await draft.inputValue(),'Keep my unsent draft');
    assert.deepEqual(await page.locator('.maker-message').allTextContents(),historyBefore);
    assert.equal(await page.evaluate(()=>JSON.stringify(localStorage)),storageBefore);
    const bounds=await page.locator('.pi-execution-popover').boundingBox();
    assert(bounds.x>=0&&bounds.x+bounds.width<=width+1,'Popover stays within the viewport');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:`${artifacts}/stop-${width}-${locale}.png`,fullPage:true});
    report.checks.push({width,locale,case:'success',checks:['confirmation and cancel','changed-owner disabled','exact owner request','verified stopped status','draft/history/storage retained','no overflow']});
    for(const scenario of ['queue','test','unknown','failure','old']){
      await page.goto(`${preview.url}?executionStop=${scenario}&locale=${locale}`,{waitUntil:'networkidle'});
      await page.locator('.pi-execution-menu > summary').click();
      if(['queue','test','unknown'].includes(scenario)){
        assert(await stop.isDisabled());assert.deepEqual(await page.evaluate(()=>window.__stopProjectQa.events),[]);
      }else{
        await stop.click();await confirm.click();
        await page.locator('.pi-project-control [role=alert]').waitFor();
        assert((await page.locator('.pi-current-owner').innerText()).includes(locale==='en'?'Project running':'作品程式執行中'));
        assert.equal((await page.evaluate(()=>window.__stopProjectQa.events)).length,1);
        if(scenario==='old')assert((await page.locator('.pi-project-control [role=alert]').innerText()).includes(locale==='en'?'Restart':'重啟'));
      }
      report.checks.push({width,locale,case:scenario});
    }
    assert.deepEqual(errors,[]);await context.close();
  }
  assert.deepEqual(report.denied,[]);
}catch(e){report.errors.push(e.stack);process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});}
finally{await browser?.close();await new Promise(done=>preview.server.close(done));await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
