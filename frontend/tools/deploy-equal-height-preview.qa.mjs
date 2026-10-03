// Real deployment UI with synthetic state; no production API, camera or Pi access.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./deploy-equal-height-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={scope:'Real deployment UI on an isolated fixture origin. No hardware actions or production API calls.',checks:[],errors:[],denied:[]};
let browser,page;
async function layout(){
  return page.evaluate(()=>{
    const rect=selector=>{const el=document.querySelector(selector),r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight};};
    return {code:rect('.deploy-code-card'),output:rect('.deploy-output'),editor:rect('.pi-code-editor'),console:rect('.pi-console'),footer:rect('.pi-editor-foot'),overflow:document.documentElement.scrollWidth>innerWidth+1};
  });
}
function checkLayout(result,width){
  assert(!result.overflow,`${width}: page must not overflow horizontally`);
  assert(result.editor.height>=280,`${width}: editor remains usable`);
  assert(result.footer.bottom<=result.code.bottom,`${width}: editor footer stays inside card`);
  if(width>960){
    assert(Math.abs(result.code.y-result.output.y)<=1,`${width}: card tops align`);
    assert(Math.abs(result.code.bottom-result.output.bottom)<=1,`${width}: card bottoms align`);
    assert(result.code.x+result.code.width<=result.output.x,`${width}: cards remain side by side`);
  }else{
    assert(result.output.y>=result.code.bottom,`${width}: narrow layout stays stacked`);
    assert(result.editor.height<650,`${width}: editor has natural height when stacked`);
  }
}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const width of [1651,1352,1024,960,390]){
    for(const locale of ['zh-TW','en']){
      const context=await browser.newContext({viewport:{width,height:871}});
      await context.route('**/*',route=>{
        const u=new URL(route.request().url());
        if(u.origin===new URL(preview.url).origin&&['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'].includes(u.pathname))return route.continue();
        report.denied.push(u.href);return route.abort();
      });
      page=await context.newPage();const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
      for(const state of ['running','failed','blocked','offline']){
        await page.goto(`${preview.url}?locale=${locale}&deployState=${state}${state==='offline'?'&connectionError=1':''}`,{waitUntil:'networkidle'});
        await page.locator('.maker-nav button').nth(2).click();
        await page.locator('.deploy-code-card').waitFor();
        const initial=await layout();checkLayout(initial,width);
        if(state==='running'||state==='failed')assert(initial.console.scrollHeight>initial.console.clientHeight,'Long output scrolls inside the console');
        if(state==='failed')assert(await page.locator('.pi-error').count()>0,'Failure evidence remains visible');
        if(state==='blocked'||state==='offline')assert(await page.locator('.deploy-code-deploy').isDisabled(),'Safety gate stays enforced');
        const editor=page.locator('.pi-code-editor');
        const draft='# Keep this edited draft\n'+Array.from({length:150},(_,i)=>`print(${i})`).join('\n');
        await editor.fill(draft);
        const edited=await layout();checkLayout(edited,width);
        assert(edited.editor.scrollHeight>edited.editor.clientHeight,'Long draft scrolls inside the editor');
        assert.equal(await editor.inputValue(),draft,'Layout keeps draft contents');
        if(width>960&&state==='running'){
          // The existing resize handle may make the left card taller: right output follows.
          await editor.evaluate(el=>el.style.height='700px');
          const resized=await layout();checkLayout(resized,width);
          assert(resized.console.height>initial.console.height,'Output uses extra height after editor resize');
          await editor.evaluate(el=>el.style.removeProperty('height'));
        }
        if(state==='running'&&[1651,1352,390].includes(width))await page.screenshot({path:`${artifacts}/deploy-${width}-${locale}.png`,fullPage:true});
        assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
        assert.deepEqual(errors,[]);
        report.checks.push({width,locale,state,...initial});
      }
      await context.close();
    }
  }
  assert.deepEqual(report.denied,[]);
}catch(e){
  report.errors.push(e.stack);process.exitCode=1;
  if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({scope:report.scope,checked:report.checks.length,errors:report.errors,denied:report.denied},null,2));
}
