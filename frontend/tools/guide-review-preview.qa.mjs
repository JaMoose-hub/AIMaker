import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {startPreview,fixtureRequestAllowed} from './wiring-ai-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./guide-review-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Real guide/test components with synthetic records; no camera/Pi/model/production storage',results:[],errors:[]};
let browser,currentPage;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:1352,height:871},{width:390,height:844},{width:320,height:700}])for(const locale of ['zh-TW','en']){
    const context=await browser.newContext({viewport,locale});
    const page=await context.newPage();currentPage=page;
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    await page.goto(`${preview.url}?scenario=review`,{waitUntil:'networkidle'});
    assert.equal(await page.locator('vite-error-overlay').count(),0);
    const review=page.locator('.guide-module-review'),card=page.locator('.guide-panel-body > .component-test-card');
    assert.equal(await review.locator('strong').innerText(),'4 / 4');
    const metrics=await review.evaluate(element=>{
      const box=node=>node.getBoundingClientRect().toJSON();
      return {review:box(element),label:box(element.querySelector('span')),count:box(element.querySelector('strong')),description:box(element.querySelector('p'))};
    });
    assert(metrics.review.height<=90,'Manual record remains too tall');
    assert(Math.abs(metrics.label.y+metrics.label.height/2-metrics.count.y-metrics.count.height/2)<2,'Count and label are not aligned');
    assert(metrics.description.y>=metrics.label.bottom-1,'Explanation overlaps the count/title');
    const before=await page.locator('#qa-guide-state').textContent();
    const baseline=await page.addStyleTag({content:'.app.maker-layout .guide-module-review{grid-template-columns:1fr;gap:8px;padding:14px;}.app.maker-layout .guide-module-review>strong{font-size:28px;line-height:inherit;}.app.maker-layout .guide-module-review>p{font-size:13px;line-height:1.7;}'});
    metrics.previousHeight=(await review.boundingBox()).height;
    await baseline.evaluate(node=>node.remove());
    assert(metrics.review.height<metrics.previousHeight*.7,'Record height was not materially reduced');
    const action=card.locator('.component-test-debug-action');
    assert.equal(await action.count(),1);
    assert.equal(await card.locator('header .component-test-result-row .component-test-debug-action').count(),1);
    const resultRow=await card.locator('.component-test-result-row').boundingBox();
    const result=await card.locator('.test-outcome').boundingBox(),button=await action.boundingBox();
    assert(button.x>=result.x+result.width-1,'Troubleshooting should sit beside the result');
    assert(Math.abs(result.y+result.height/2-button.y-button.height/2)<2,'Result/action baseline is not aligned');
    assert(button.width<resultRow.width*.6,'Troubleshooting still occupies a full row');
    assert((await card.innerText()).includes(locale==='en'?'saved history, not current wiring evidence':'先前保存，非目前接線證據'));
    assert.equal(await card.locator('.test-actions button').count(),2,'Retest/review controls are missing');
    assert((await card.innerText()).includes(locale==='en'?'Power off before rewiring':'改接線前斷電'));
    assert.deepEqual(await page.evaluate(()=>window.__wiringQa.events),[]);
    assert.equal(await page.locator('#qa-guide-state').textContent(),before);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await review.screenshot({path:`${artifacts}/${viewport.width}-${locale}-record.png`});
    await card.screenshot({path:`${artifacts}/${viewport.width}-${locale}-result.png`});
    await page.screenshot({path:`${artifacts}/${viewport.width}-${locale}-workspace.png`,fullPage:true});
    await action.focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('.wiring-workspace-tabs > button[aria-selected=true]').innerText(),locale==='en'?'AI assistant':'AI 協作');
    assert.deepEqual(await page.evaluate(()=>window.__wiringQa.debugNavigations),[{componentId:'hc-sr04',runId:'qa-hc-sr04',symptom:'wiring_changed'}]);
    assert.deepEqual(JSON.parse(await page.locator('#qa-guide-state').textContent()).confirmed,JSON.parse(before).confirmed);
    assert.deepEqual(await page.evaluate(()=>window.__wiringQa.events),[],'Navigation started a model/hardware request');
    assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),[]);
    assert.deepEqual(errors,[]);
    report.results.push({viewport,locale,metrics,checks:['compact aligned manual record, over 30% shorter','result and troubleshoot share a row','history, retest/review and safety reminder preserved','keyboard troubleshooting passes exact component/run/reason','no confirmation changes, hardware/model requests, browser errors or document overflow']});
    await context.close();
  }
  for(const width of [1352,390])for(const scenario of ['partial-review','review']){
    const context=await browser.newContext({viewport:{width,height:871},locale:'zh-TW'});
    const page=await context.newPage();currentPage=page;
    await page.goto(`${preview.url}?scenario=${scenario}&outcome=passed`,{waitUntil:'networkidle'});
    const review=page.locator('.guide-module-review');
    assert.equal(await review.locator('strong').innerText(),scenario==='partial-review'?'2 / 4':'4 / 4');
    if(scenario==='partial-review'){
      assert((await review.innerText()).includes('暫停總覽'));
      assert.equal(await page.locator('.component-test-card').count(),0);
    }else{
      assert((await page.locator('.test-outcome').innerText()).includes('功能通過'));
      assert.equal(await page.locator('.component-test-debug-action').count(),0);
    }
    assert.deepEqual(await page.evaluate(()=>window.__wiringQa.events),[]);
    report.results.push({width,scenario,checks:['paused/complete records remain accurate; partial wires never offer a test; passed results do not gain a troubleshoot action']});
    await context.close();
  }
  assert(preview.requests.every(fixtureRequestAllowed),'Preview contacted a non-fixture endpoint');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();await new Promise(done=>preview.server.close(done));
  report.requests=preview.requests;
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
