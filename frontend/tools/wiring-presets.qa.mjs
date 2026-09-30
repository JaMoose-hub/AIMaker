// Real wiring composer on the isolated fixture origin, never production/Pi/model.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,fixtureRequestAllowed} from './wiring-ai-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./wiring-presets-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Real AiDebugPanel; synthetic catalog project and mocked sessions, no production camera/Pi/model/storage',results:[],errors:[],deniedRequests:[]};
let browser,page;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const locale of ['zh-TW','en'])for(const width of [1651,390]){
    const context=await browser.newContext({viewport:{width,height:width===390?844:871}});
    await context.addInitScript(value=>localStorage.setItem('boardvision.locale.v1',value),locale);
    await context.route('**/*',route=>{const url=new URL(route.request().url());
      if(url.origin===new URL(preview.url).origin&&fixtureRequestAllowed(url.pathname+url.search))return route.continue();
      report.deniedRequests.push(url.href);return route.abort();});
    page=await context.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
    await page.goto(`${preview.url}?scenario=flow`,{waitUntil:'networkidle'});
    assert(await page.evaluate(()=>document.body.innerText.trim().length>0));
    assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
    await page.getByRole('tab',{name:locale==='en'?'AI assistant':'AI 協作',exact:true}).click();
    const group=page.getByRole('group',{name:locale==='en'?'Common wiring questions':'常見接法問題',exact:true});
    await group.waitFor({state:'visible'});
    const buttons=group.getByRole('button'),entry=page.locator('.ai-debug-composer textarea');
    assert.deepEqual(await buttons.allTextContents(),locale==='en'?['How do I connect this?','Where is the Pi pin?','How do I check the wiring?']:['這一步怎麼接？','Pi 腳位在哪？','怎麼檢查接線？']);
    const before=await page.evaluate(()=>JSON.stringify(window.__wiringQa.events));
    const guideBefore=await page.locator('#qa-guide-state').textContent();
    const messagesBefore=await page.locator('.ai-debug-message > p').allTextContents();
    for(let i=0;i<3;i++){
      await entry.fill('');const expected=await buttons.nth(i).getAttribute('title');
      await buttons.nth(i).click();assert.equal(await entry.inputValue(),expected);assert(await entry.evaluate(node=>node===document.activeElement));
      assert(expected.includes('Pin 6 · GND'));
    }
    await entry.fill(locale==='en'?'My unsent draft':'我還沒送出的草稿');
    const draft=await entry.inputValue(),question=await buttons.first().getAttribute('title');
    await buttons.first().click();await buttons.first().click();assert.equal(await entry.inputValue(),`${draft}\n${question}`);
    await entry.fill(`${draft}\n${question}\n${locale==='en'?'I edited this.':'我可以再修改。'}`);
    assert.equal(await page.evaluate(()=>JSON.stringify(window.__wiringQa.events)),before);
    assert.equal(await page.locator('#qa-guide-state').textContent(),guideBefore);
    assert.deepEqual(await page.locator('.ai-debug-message > p').allTextContents(),messagesBefore);
    const boxes=await buttons.evaluateAll(items=>items.map(node=>node.getBoundingClientRect().toJSON()));
    for(const box of boxes)assert(box.x>=0&&box.x+box.width<=width+1);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.deepEqual(errors,[]);
    await page.screenshot({path:`${artifacts}/presets-${width}-${locale}.png`,fullPage:true});
    report.results.push({locale,width,checks:['three visible questions','exact current pin','editable prefill and focus','draft preserved and duplicate prevented','no session or hardware action','guide and conversation unchanged','no console errors or overflow']});
    await context.close();
  }
  assert.deepEqual(report.deniedRequests,[]);
}catch(e){report.errors.push(e.stack);process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});}
finally{await browser?.close();await new Promise(done=>preview.server.close(done));await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
