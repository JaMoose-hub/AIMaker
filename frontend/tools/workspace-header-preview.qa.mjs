import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./workspace-header-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Actual header and controls, synthetic state, no backend/camera/Pi/model requests',results:[],errors:[]};
let browser;
let currentPage;
const bounds=async locator=>locator.evaluate(node=>node.getBoundingClientRect().toJSON());
async function checkBounds(page,viewport){
  const header=page.locator('.maker-header-integrated');
  const box=await bounds(header);
  assert(box.x>=0&&box.right<=viewport.width+1,'Header exceeds viewport');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Document has horizontal overflow');
  for(const control of await header.locator('.maker-nav button, summary, .pi-global-connect, .runtime-select select').all()){
    if(!await control.isVisible())continue;
    const rect=await bounds(control);
    assert(rect.width>0&&rect.x>=box.x-1&&rect.right<=box.right+1,'Control is clipped or off screen');
    assert(rect.y>=box.y&&rect.bottom<=box.bottom+1,'Control escapes header');
  }
  return box;
}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1352,height:871},{width:1651,height:871},{width:1024,height:768},{width:768,height:871},{width:390,height:844},{width:320,height:700}]){
    for(const locale of ['zh-TW','en']){
      const context=await browser.newContext({viewport,locale});
      const page=await context.newPage();
      currentPage=page;
      const errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
      await page.goto(`${preview.url}?locale=${locale}`,{waitUntil:'networkidle'});
      assert.equal(await page.locator('vite-error-overlay').count(),0);
      assert.equal(await page.locator('.maker-nav button').count(),3);
      const result={viewport,locale,checks:[],header:await checkBounds(page,viewport)};
      report.results.push(result);
      if(viewport.width>700){
        const logo=await bounds(page.locator('.brand-logo')),nav=await bounds(page.locator('.maker-nav'));
        assert(Math.abs((logo.y+logo.height/2)-(nav.y+nav.height/2))<2,'Brand and workflow are not vertically aligned');
        result.checks.push('brand and workflow share one row');
      }
      if(viewport.width>=1352)assert(result.header.height<=114,'Desktop header wastes vertical space');
      result.checks.push('three stages, compact bounded header, no horizontal overflow');
      for(let i=0;i<3;i++){
        await page.locator('.maker-nav button').nth(i).click();
        assert.equal(await page.locator('.maker-nav button[aria-current=step]').count(),1);
        assert.equal(await page.locator('.maker-nav button').nth(i).getAttribute('aria-current'),'step');
        await checkBounds(page,viewport);
      }
      result.checks.push('all three real workflow views switch');
      await page.locator('.maker-model-menu > summary').click();
      assert.equal(await page.locator('.maker-model-menu').getAttribute('open'),'');
      const model=await bounds(page.locator('.maker-model-popover'));
      assert(model.x>=0&&model.right<=viewport.width+1,'Model popover escapes viewport');
      await page.locator('.maker-model-popover select').first().selectOption('gpt-6-luna');
      await page.locator('.maker-model-popover select').nth(1).selectOption('high');
      await page.locator('.maker-model-popover select').nth(1).press('Escape');
      assert.equal(await page.locator('.maker-model-menu').getAttribute('open'),null);
      assert(await page.locator('.maker-model-menu > summary').evaluate(node=>node===document.activeElement));
      await page.locator('.maker-model-menu > summary').click();
      await page.locator('.maker-nav button').first().click();
      assert.equal(await page.locator('.maker-model-menu').getAttribute('open'),null);
      result.checks.push('actual model selection, Escape focus and outside close');
      await page.locator('.pi-execution-menu > summary').click();
      const queue=await bounds(page.locator('.pi-execution-popover'));
      assert(queue.x>=0&&queue.right<=viewport.width+1,'Execution menu escapes viewport');
      await page.locator('.pi-execution-menu > summary').click();
      result.checks.push('actual execution menu bounded and readable');
      await page.locator('.runtime-select:not(.locale-select) select').selectOption('arduino-uno');
      await page.locator('.locale-select select').selectOption(locale==='en'?'zh-TW':'en');
      assert.deepEqual(await page.evaluate(()=>window.__headerQa.events),['controller:arduino-uno',`locale:${locale==='en'?'zh-TW':'en'}`]);
      assert.equal(await page.locator('.runtime-select:not(.locale-select) select').inputValue(),'arduino-uno');
      await checkBounds(page,viewport);
      result.checks.push('controller and language invoke only their original-style callbacks');
      await page.locator('.locale-select select').selectOption(locale);
      await page.screenshot({path:`${artifacts}/header-${viewport.width}-${locale}.png`});
      assert.deepEqual(errors,[]);
      result.checks.push('zero browser errors');
      await context.close();
    }
  }
  for(const width of [1352,390]){
    const viewport={width,height:871};
    const context=await browser.newContext({viewport,locale:'en'});
    const page=await context.newPage();
    currentPage=page;
    await page.goto(`${preview.url}?locale=en&storageError&connectionError&runtimeError`,{waitUntil:'networkidle'});
    await checkBounds(page,viewport);
    for(const selector of ['.maker-save-status[role=alert]','.pi-global-error','.runtime-error']){
      const alert=page.locator(selector);assert(await alert.isVisible());
      assert(await alert.evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Important error text is clipped');
    }
    await page.screenshot({path:`${artifacts}/header-errors-${width}.png`});
    report.results.push({viewport,checks:['storage, connection and runtime warnings remain visible without overflow']});
    await context.close();
  }
  assert(preview.requests.every(path=>['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg'].includes(path)),'Preview contacted a non-asset endpoint');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}
finally{
  await browser?.close();
  await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
