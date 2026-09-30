import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './wiring-ai-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./wiring-ai-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview();
const report={fixture:'Real VideoView / overlays with synthetic image and packets; no production camera/Pi/model/storage',results:[],errors:[]};
let browser;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:390,height:844}]){
    const context=await browser.newContext({viewport,locale:'zh-TW'}),page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    await page.goto(`${preview.url}?scenario=overlay`,{waitUntil:'networkidle'});
    assert((await page.locator('body').innerText()).includes('疊圖篩選隔離 QA'));
    assert.equal(await page.locator('vite-error-overlay').count(),0);
    const result={viewport,checks:[]};
    const ids=()=>page.locator('.component-overlay-svg').evaluateAll(nodes=>nodes.map(node=>node.dataset.componentId));
    await page.evaluate(()=>{window.__qaOverlayCamera=document.querySelector('.video-img');});
    const board=await page.locator('.overlay-svg .board-outline').getAttribute('points');
    assert.deepEqual(await ids(),['hc-sr04']);
    assert.equal(await page.locator('.component-overlay-svg text').filter({hasText:/^CS$/}).count(),0);
    assert.equal(await page.evaluate(()=>window.__overlayQa.frame.components.length),2);
    result.checks.push('Review/AI without an active pin displays Pi + HC only despite an overlapping TFT pose');
    await page.screenshot({path:`${artifacts}/${viewport.width}-hc-overlay-scope.png`,fullPage:true});
    await page.getByRole('button',{name:'開始 TRIG 步驟',exact:true}).click();
    assert.deepEqual(await ids(),['hc-sr04']);
    assert.equal(await page.locator('[data-guide-connection="GPIO17:TRIG"]').count(),1);
    result.checks.push('Active TRIG retains the correct same-frame connection with no TFT markers');
    await page.getByRole('button',{name:'選 TFT',exact:true}).click();
    assert.deepEqual(await ids(),['mrd-tf240-8p-cs']);
    assert.equal(await page.locator('[data-guide-connection]').count(),0);
    assert.equal(await page.locator('.overlay-svg .board-outline').getAttribute('points'),board);
    result.checks.push('Module switch removes the old HC guide immediately while Pi geometry remains unchanged');
    await page.getByRole('button',{name:'接線完成',exact:true}).click();
    await page.getByRole('button',{name:'選 HC-SR04+',exact:true}).click();
    await page.getByRole('button',{name:'只留下 TFT 偵測',exact:true}).click();
    assert.deepEqual(await ids(),[]);
    assert.equal(await page.locator('.overlay-svg .board-outline').getAttribute('points'),board);
    result.checks.push('Missing HC cannot substitute a TFT box or pin labels; Pi stays visible');
    await page.getByRole('button',{name:'恢復 HC 偵測',exact:true}).click();
    assert.deepEqual(await ids(),['hc-sr04']);
    await page.getByRole('button',{name:'要求 TFT 取景',exact:true}).click();
    assert.deepEqual(await ids(),['mrd-tf240-8p-cs']);
    assert(await page.locator('.debug-capture-overlay').isVisible());
    await page.getByRole('button',{name:'結束取景',exact:true}).click();
    assert.deepEqual(await ids(),['hc-sr04']);
    result.checks.push('Explicit capture focuses its own component and returns to the selected module afterward');
    assert(await page.evaluate(()=>window.__qaOverlayCamera===document.querySelector('.video-img')));
    assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),[]);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.deepEqual(errors,[]);
    result.checks.push('Same camera DOM; no API requests, console errors, storage writes or horizontal overflow');
    report.results.push(result);await context.close();
  }
}catch(error){report.errors.push(error.stack);throw error;}
finally{
  await writeFile(`${artifacts}/overlay-scope-report.json`,JSON.stringify({...report,requests:preview.requests},null,2));
  await browser?.close();await new Promise(resolve=>preview.server.close(resolve));
  console.log(JSON.stringify(report,null,2));
}
