// Real cards, conversation and circuit canvas on an isolated origin. No production access.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,fixtureRequestAllowed} from './wiring-ai-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./diagram-workspace-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Actual AI cards, main diagram, conversation and catalog; synthetic snapshots/photos and hook state only',results:[],errors:[],deniedRequests:[]};
let browser,currentPage;
try {
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:1352,height:871},{width:390,height:844},{width:320,height:700}]) {
    for(const locale of ['zh-TW','en']) {
      const context=await browser.newContext({viewport,locale});
      await context.addInitScript(value=>localStorage.setItem('boardvision.locale.v1',value),locale);
      await context.route('**/*',route=>{
        const url=new URL(route.request().url());
        if(url.origin===new URL(preview.url).origin&&fixtureRequestAllowed(url.pathname+url.search))return route.continue();
        report.deniedRequests.push(url.href);return route.abort();
      });
      const page=await context.newPage();currentPage=page;
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
      await page.goto(`${preview.url}?scenario=diagram-link`,{waitUntil:'networkidle'});
      assert(await page.evaluate(()=>document.body.innerText.trim().length>0));
      assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
      const tr=(zh,en)=>locale==='en'?en:zh;
      const aiTab=page.getByRole('tab',{name:tr('AI 協作','AI assistant'),exact:true});
      const current=page.locator('.ai-diagram-card').filter({hasText:tr('設計接法 · v2','Designed wiring · v2')});
      const old=page.locator('.ai-diagram-card').filter({hasText:tr('設計接法 · v1','Designed wiring · v1')});
      const openName=tr('在左側查看接法','View wiring on the left');
      const left=page.locator('#current-step-diagram');
      const draft=page.locator('.ai-debug-entry textarea');
      await draft.fill(tr('保留這段草稿；我要比較這兩條線。','Keep this draft while I compare the wires.'));
      const initialDraft=await draft.inputValue();
      const guideBefore=await page.locator('#qa-guide-state').textContent();
      const bindingBefore=await page.locator('#qa-view-binding').textContent();
      const conversationBefore=await page.locator('.ai-debug-message > p').allTextContents();
      await page.evaluate(()=>{window.__cameraBeforeLink=document.querySelector('.video-shell');});
      assert.equal(await current.locator('svg,dialog,.maker-circuit').count(),0);
      assert.equal(await old.locator('svg,dialog,.maker-circuit').count(),0);
      assert.equal(await current.locator('.ai-evidence-actions button').count(),1);
      await current.getByRole('button',{name:openName}).click();
      assert(await left.isVisible());
      assert.equal(await page.locator('.video-shell').isVisible(),false);
      assert.equal(await aiTab.getAttribute('aria-selected'),'true');
      assert.equal(await left.locator('[data-circuit-wire="hc-sr04:trig"].active').count(),1);
      assert.match(await left.locator('h2').innerText(),/TRIG.*Pin 11/);
      assert(await left.locator('.diagram-inspection-heading').getByText(tr('目前版本 · 僅供檢視','Current version · read only'),{exact:true}).isVisible());
      assert.equal(await draft.inputValue(),initialDraft);
      assert.equal(await page.locator('#qa-guide-state').textContent(),guideBefore);
      assert.equal(await page.locator('#qa-view-binding').textContent(),bindingBefore);
      assert.deepEqual(await page.locator('.ai-debug-message > p').allTextContents(),conversationBefore);
      if(viewport.width<=960)assert(await left.evaluate(node=>node.getBoundingClientRect().top<innerHeight),'Narrow-screen link did not reveal the main canvas');
      const canvas=await left.locator('.circuit-viewport').evaluate(node=>({height:node.clientHeight,scrollHeight:node.scrollHeight,width:node.clientWidth,scrollWidth:node.scrollWidth}));
      assert(canvas.height>120&&canvas.scrollHeight<=canvas.height+1&&canvas.scrollWidth<=canvas.width+1,'Default wire drawing is clipped');
      await page.screenshot({path:`${artifacts}/diagram-${viewport.width}-${locale}-current.png`,fullPage:true});
      await left.getByRole('button',{name:tr('查看完整電路','View full circuit'),exact:true}).click();
      assert.equal(await left.locator('[data-circuit-module]').count(),2);
      assert.equal(await left.locator('[data-circuit-wire].active').count(),0);
      await left.getByRole('button',{name:tr('放大接線圖 ↗','Expand diagram ↗'),exact:true}).click();
      assert.equal(await page.locator('dialog[open] [data-circuit-module]').count(),2);
      await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),0);
      await left.getByRole('button',{name:tr('返回 AI 指出的接線',"Return to AI's wire"),exact:true}).click();
      assert.equal(await left.locator('[data-circuit-wire="hc-sr04:trig"].active').count(),1);
      await current.getByRole('button',{name:'HC · ECHO',exact:true}).click();
      await current.getByRole('button',{name:openName}).click();
      assert.equal(await left.locator('[data-circuit-wire="hc-sr04:echo"].active').count(),1);
      assert.match(await left.locator('h2').innerText(),/ECHO.*Pin 12/);
      await old.getByRole('button',{name:openName}).click();
      assert(await left.locator('.diagram-inspection-heading').getByText(tr('歷史版本 · 僅供檢視','Historical version · read only'),{exact:true}).isVisible());
      assert.match(await left.locator('h2').innerText(),/TRIG.*Pin 13.*GPIO27/,'The old reference substituted the current Pin 11');
      const frozenOrder=await left.locator('[data-module-pin]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-module-pin')));
      assert.deepEqual(frozenOrder,['hc-sr04:GND','hc-sr04:ECHO','hc-sr04:TRIG','hc-sr04:VCC'],'Old profile pin order was not preserved');
      await page.screenshot({path:`${artifacts}/diagram-${viewport.width}-${locale}-historical.png`,fullPage:true});
      await page.evaluate(()=>document.querySelector('#qa-request-capture').click());
      assert.equal(await left.count(),0,'A new capture must temporarily reveal the camera');
      assert(await page.locator('.video-shell').isVisible());
      await old.getByRole('button',{name:openName}).click();
      assert(await left.isVisible());
      assert.match(await left.locator('[role=status]').innerText(),tr(/等待實物照片/,/waiting for a hardware photo/));
      assert.match(await left.locator('h2').innerText(),/Pin 13/);
      await page.evaluate(()=>document.querySelector('#qa-request-capture').click());
      assert.equal(await left.count(),0,'Another new capture cannot reuse the previous override');
      await page.evaluate(()=>document.querySelector('#qa-finish-capture').click());
      assert(await left.isVisible());
      await left.getByRole('button',{name:tr('返回目前步驟','Back to current step'),exact:true}).click();
      assert.equal(await left.locator('.diagram-inspection-heading').count(),0);
      assert.equal(await left.locator('[data-circuit-wire="hc-sr04:gnd"].active').count(),1,'Return changed the real guide cursor');
      await page.getByRole('button',{name:tr('返回鏡頭','Back to camera'),exact:true}).click();
      assert(await page.locator('.video-shell').isVisible());
      assert(await page.evaluate(()=>window.__cameraBeforeLink===document.querySelector('.video-shell')));
      assert.equal(await aiTab.getAttribute('aria-selected'),'true');
      assert.equal(await draft.inputValue(),initialDraft);
      assert.equal(await page.locator('#qa-guide-state').textContent(),guideBefore);
      assert.equal(await page.locator('#qa-view-binding').textContent(),bindingBefore);
      assert.deepEqual(await page.locator('.ai-debug-message > p').allTextContents(),conversationBefore);
      assert.deepEqual(await page.evaluate(()=>window.__wiringQa.events),[]);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.deepEqual(errors,[]);
      report.results.push({viewport,locale,checks:['compact card; one main-view action; no inline diagram','main canvas exact current wire','AI tab, draft, cursor, confirmations and test binding preserved','full circuit, zoom and referenced-wire return on left','historical Pin 13 and reversed frozen pin profile, not current Pin 11','fresh capture reveals the original camera and old overrides cannot hide it','return current step and same camera DOM','no errors, overflow or model/hardware actions']});
      await context.close();
    }
  }
  assert.deepEqual(report.deniedRequests,[]);
  assert(preview.requests.every(fixtureRequestAllowed));
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({scenarios:report.results.length,errors:report.errors,deniedRequests:report.deniedRequests,report:`${artifacts}/report.json`},null,2));
}
