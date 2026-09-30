import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './wiring-ai-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./wiring-restart-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Isolated synthetic data and fake operations; no production camera/Pi/model/storage',results:[],errors:[]};
let browser,lastPage;
try {
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const cases=[...[1651,390].flatMap(width=>['zh-TW','en'].map(locale=>({width,locale,scenario:'restart'}))),
    ...['restart-stop-failure','restart-invalidate-failure','restart-reset-failure'].map(scenario=>({width:1651,locale:'zh-TW',scenario}))];
  for(const item of cases){
    const context=await browser.newContext({viewport:{width:item.width,height:871},locale:item.locale});
    await context.addInitScript(locale=>localStorage.setItem('boardvision.locale.v1',locale),item.locale);
    const page=await context.newPage(),errors=[];
    lastPage=page;
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    // All browser requests must stay inside this isolated asset server.
    await context.route('**/*',route=>{
      if(new URL(route.request().url()).origin!==new URL(preview.url).origin){errors.push('Unexpected external request');return route.abort();}
      return route.continue();
    });
    await page.goto(`${preview.url}?scenario=${item.scenario}`,{waitUntil:'networkidle'});
    assert((await page.locator('body').innerText()).includes('Tinkro'));
    assert.equal(await page.locator('vite-error-overlay,[data-nextjs-dialog]').count(),0);
    const ai=page.getByRole('tab',{name:item.locale==='en'?'AI assistant':'AI 協作',exact:true});
    const guide=page.getByRole('tab',{name:item.locale==='en'?'Wiring guide':'接線引導',exact:true});
    await ai.click();
    const originalMessages=await page.locator('.ai-debug-message').count();
    assert(originalMessages>=3);
    await page.locator('.ai-debug-composer textarea').fill('Old unsent draft');
    const camera=await page.locator('.video-shell').elementHandle();
    const original=JSON.parse(await page.locator('#qa-guide-state').textContent());
    const code=JSON.parse(await page.locator('#qa-view-binding').textContent()).code;
    await guide.click();
    await page.locator('.guide-restart-action').click();
    if(item.scenario==='restart'){
      await page.waitForFunction(()=>JSON.parse(document.querySelector('#qa-guide-state').textContent).phase==='prepare');
      const fresh=JSON.parse(await page.locator('#qa-guide-state').textContent());
      assert.deepEqual(fresh.confirmed,{});assert.equal(fresh.index,0);assert.equal(fresh.componentIndex,0);
      await ai.click();
      assert.equal(await page.locator('.ai-debug-message').count(),0);
      assert.equal(await page.locator('.ai-debug-composer textarea').inputValue(),'');
      assert.equal(await page.locator('.ai-diagram-card,.ai-debug-photo-card').count(),0);
      assert.equal(JSON.parse(await page.locator('#qa-view-binding').textContent()).code,code);
      assert(await camera.evaluate(element=>element===document.querySelector('.video-shell')),'camera must not remount');
      assert.deepEqual(await page.evaluate(()=>window.__wiringQa.events.map(event=>event.kind)),['stop','invalidate','restart-conversation']);
      await page.screenshot({path:`${artifacts}/${item.width}-${item.locale}-fresh.png`,fullPage:true});
      await page.reload({waitUntil:'networkidle'});await ai.click();
      assert.equal(await page.locator('.ai-debug-message').count(),0);
      assert.deepEqual(JSON.parse(await page.locator('#qa-guide-state').textContent()).confirmed,{});
    }else{
      await page.getByRole('alert').waitFor();
      assert.deepEqual(JSON.parse(await page.locator('#qa-guide-state').textContent()),original);
      await ai.click();assert.equal(await page.locator('.ai-debug-message').count(),originalMessages);
      assert.equal(await page.locator('.ai-debug-composer textarea').inputValue(),'Old unsent draft');
      await page.screenshot({path:`${artifacts}/${item.scenario}.png`,fullPage:true});
    }
    assert.deepEqual(errors,[]);report.results.push({...item,passed:true});await context.close();
  }
  assert(preview.requests.every(path=>['/','/preview.js','/preview.css','/api/debug/sessions/qa-check/evidence/photo-one'].includes(path.split('?')[0])));
} catch(error){await lastPage?.screenshot({path:`${artifacts}/error-state.png`,fullPage:true});report.errors.push(error.stack??String(error));process.exitCode=1;}
finally{await browser?.close();await new Promise(resolve=>preview.server.close(resolve));await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));
