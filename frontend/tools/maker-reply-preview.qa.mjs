// Real MakerAssistant and literal reply parser. Offline examples, never ask the model.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./maker-reply-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const allowed=['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'];
const report={fixture:'Real MakerAssistant, synthetic paragraph/list/step/historical replies; no model or hardware calls',results:[],errors:[],deniedRequests:[]};
let browser,currentPage;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:390,height:844},{width:320,height:700}]){
    for(const locale of ['zh-TW','en']){
      for(const fixture of ['paragraph','bullets','steps','mixed','long']){
        const context=await browser.newContext({viewport,locale});
        await context.route('**/*',route=>{
          const url=new URL(route.request().url());
          if(url.origin===new URL(preview.url).origin&&allowed.includes(url.pathname))return route.continue();
          report.deniedRequests.push(url.href);return route.abort();
        });
        const page=await context.newPage();currentPage=page;
        const errors=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
        await page.goto(`${preview.url}?locale=${locale}&reply=${fixture}`,{waitUntil:'networkidle'});
        assert(await page.evaluate(()=>document.body.innerText.trim().length>0),'Blank page');
        assert.equal(await page.locator('vite-error-overlay, .vite-error-overlay, [data-nextjs-dialog]').count(),0);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow');
        const message=page.locator('.maker-message.assistant');
        assert.equal(await message.count(),1);
        await message.scrollIntoViewIfNeeded();
        const original=await message.textContent();
        if(['paragraph','long'].includes(fixture)){
          assert.equal(await message.locator('ul, ol').count(),0,'A paragraph was converted to a list');
          assert.equal(await message.locator('.maker-reply-text').count(),1);
        }else{
          assert.equal(await message.locator('.maker-reply-points li').count(),2);
          assert.equal(await message.locator(fixture==='steps'?'ol':'ul').count(),1);
          if(fixture==='steps'){
            assert.deepEqual(await message.locator('ol li').evaluateAll(items=>items.map(item=>item.value)),[2,3]);
          }
          for(const item of await message.locator('.maker-reply-points li').all()){
            const style=await item.evaluate(node=>({border:getComputedStyle(node).borderTopWidth,background:getComputedStyle(node).backgroundColor}));
            assert.equal(style.border,'0px');
            assert.equal(style.background,'rgba(0, 0, 0, 0)','Each item is still a bubble card');
          }
        }
        if(fixture==='long'){
          assert.match(await message.locator('.maker-reply-text').innerText(),locale==='en'?/Do not power on until voltage is confirmed/:/未確認電壓前不要通電/);
          const full=message.locator('.maker-reply-full');
          assert.equal(await full.getAttribute('open'),null);
          await full.locator('summary').focus();
          await full.locator('summary').press('Space');
          assert.equal(await full.getAttribute('open'),'');
          assert((await full.locator('p').textContent()).length>600,'Complete original was lost');
          await full.locator('summary').press('Space');
          assert.equal(await full.getAttribute('open'),null);
        }else{
          assert.equal(await message.locator('.maker-reply-full').count(),0,'Short reply unnecessarily duplicated');
        }
        for(const text of await message.locator('.maker-reply-text, li').all()){
          assert(await text.evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Reply text is clipped');
        }
        await page.screenshot({path:`${artifacts}/reply-${viewport.width}-${locale}-${fixture}.png`,fullPage:true});
        await page.locator('.maker-nav button').nth(1).click();
        await page.locator('.maker-nav button').first().click();
        assert.equal(await page.locator('.maker-message.assistant').textContent(),original,'Navigation rewrote the conversation');
        assert.deepEqual(errors,[]);
        report.results.push({viewport,locale,fixture,checks:['natural paragraph or authored semantic list','no bubble item cards or redundant short-reply disclosure','warnings and full original preserved','navigation retains conversation','no errors, clipping or horizontal overflow']});
        await context.close();
      }
    }
  }
  assert.deepEqual(report.deniedRequests,[]);
  assert(preview.requests.every(path=>allowed.includes(path)),'Non-asset request in isolated preview');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();
  await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({scenarios:report.results.length,errors:report.errors,deniedRequests:report.deniedRequests,report:`${artifacts}/report.json`},null,2));
}
