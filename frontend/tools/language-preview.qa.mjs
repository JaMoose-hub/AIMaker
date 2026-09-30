// Actual React UI, fixture origin only: no production storage, cameras, AI or Pi.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,discardImagePaths} from './tinkro-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./language-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={scope:'Real UI with synthetic saved project; no model/hardware calls. Historical chat and user drafts intentionally stay unchanged.',checks:[],errors:[],denied:[]};
let browser,page;
async function untranslated(){return page.evaluate(()=>{
  const nodes=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
    const node=walker.currentNode,p=node.parentElement,text=node.textContent.trim();
    if(!/\p{Script=Han}/u.test(text)||!p||p.closest('script,style,textarea,.maker-message,.ai-debug-message > p'))continue;
    if(!p.getClientRects().length||getComputedStyle(p).visibility==='hidden'||p.closest('[hidden]'))continue;
    nodes.push({tag:p.tagName,class:p.className,text});
  }
  return nodes;
});}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const width of [1651,390]){
    const context=await browser.newContext({viewport:{width,height:width===390?844:871}});
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      if(u.origin===new URL(preview.url).origin&&['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg',...discardImagePaths].includes(u.pathname))return route.continue();
      report.denied.push(u.href);return route.abort();
    });
    page=await context.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
    await page.goto(`${preview.url}?languageAudit=1&locale=zh-TW`,{waitUntil:'networkidle'});
    assert.deepEqual(errors,[],'Fixture should load without script errors');
    assert(await page.locator('.maker-composer textarea').inputValue().then(s=>s.includes('我想做')));
    const preserved=await page.evaluate(()=>JSON.stringify({design:window.__languageQa.state.design,guide:window.__languageQa.state.guide,history:window.__languageQa.state.conversation,code:window.__languageQa.state.code}));
    await page.locator('.locale-select select').selectOption('en');
    await page.waitForFunction(()=>document.documentElement.lang==='en');
    assert(!/\p{Script=Han}/u.test(await page.locator('.maker-composer textarea').inputValue()));
    assert.equal(await page.evaluate(()=>JSON.stringify({design:window.__languageQa.state.design,guide:window.__languageQa.state.guide,history:window.__languageQa.state.conversation,code:window.__languageQa.state.code})),preserved);
    assert.deepEqual(await untranslated(),[],'English concept UI contains untranslated text');
    await page.screenshot({path:`${artifacts}/concept-${width}-en.png`,fullPage:true});
    await page.locator('.maker-composer textarea').fill('使用者未送出的中文草稿');
    await page.locator('.locale-select select').selectOption('zh-TW');
    await page.locator('.locale-select select').selectOption('en');
    assert.equal(await page.locator('.maker-composer textarea').inputValue(),'使用者未送出的中文草稿');
    await page.getByRole('button',{name:'Build blueprint',exact:true}).click();
    assert.deepEqual(await untranslated(),[],'English blueprint materials contain untranslated text');
    await page.getByRole('tab',{name:'Build steps',exact:true}).click();
    assert.deepEqual(await untranslated(),[],'English blueprint steps contain untranslated text');
    await page.screenshot({path:`${artifacts}/blueprint-${width}-en.png`,fullPage:true});
    await page.locator('.maker-nav button').nth(1).click();
    await page.waitForFunction(()=>window.__languageQa.context?.locale==='en');
    const binding=await page.evaluate(()=>JSON.stringify({...window.__languageQa.context,locale:undefined}));
    assert.deepEqual(await untranslated(),[],'English wiring/debug UI contains untranslated text');
    const entry=page.locator('.ai-debug-composer textarea');
    await entry.fill('保留這段接線問題');
    await page.locator('.locale-select select').selectOption('zh-TW');
    await page.waitForFunction(()=>window.__languageQa.context?.locale==='zh-TW');
    await page.locator('.locale-select select').selectOption('en');
    await page.waitForFunction(()=>window.__languageQa.context?.locale==='en');
    assert.equal(await page.evaluate(()=>JSON.stringify({...window.__languageQa.context,locale:undefined})),binding);
    assert.equal(await entry.inputValue(),'保留這段接線問題');
    assert.deepEqual(await untranslated(),[]);
    await page.screenshot({path:`${artifacts}/wiring-${width}-en.png`,fullPage:true});
    await page.locator('.maker-nav button').nth(2).click();
    assert.deepEqual(await untranslated(),[],'English deploy UI contains untranslated text');
    await page.screenshot({path:`${artifacts}/deploy-${width}-en.png`,fullPage:true});
    assert.deepEqual(errors,[]);assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.deepEqual(await page.evaluate(()=>window.__headerQa.events.filter(e=>!e.startsWith('locale:'))),[]);
    report.checks.push({width,views:['concept','blueprint materials','blueprint steps','wiring/debug','deploy'],results:['English UI scan clean','new request context follows live locale','untouched starter translated','custom drafts/history/bindings preserved','no hardware/model calls','no console errors or overflow']});
    await context.close();
  }
  assert.deepEqual(report.denied,[]);
}catch(e){report.errors.push(e.stack);process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});}
finally{await browser?.close();await new Promise(done=>preview.server.close(done));await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
