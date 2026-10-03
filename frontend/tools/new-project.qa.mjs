// Actual UI and storage on isolated fixture origin; reset callback has no hardware API.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,discardImagePaths} from './tinkro-preview.mjs';
const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./new-project-artifacts/',import.meta.url));await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0),allowed=['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg',...discardImagePaths];
const report={fixture:'Actual new-project confirmation, pure reset and useMaker restore; synthetic project, no hardware/model calls.',results:[],errors:[]};
let browser,page;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const locale of ['zh-TW','en'])for(const width of [1651,390]){
    const context=await browser.newContext({viewport:{width,height:width===390?844:871}});
    await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===new URL(preview.url).origin&&allowed.includes(url.pathname))return route.continue();assert.fail(`Unexpected request ${url.href}`)});
    page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
    await page.goto(`${preview.url}?discard=approved&newProject&locale=${locale}`,{waitUntil:'networkidle'});
    const fresh=page.getByRole('button',{name:locale==='en'?'New project':'新作品',exact:true});
    assert(await fresh.isVisible());await fresh.click();
    assert.match(await page.locator('.maker-chat-confirm').innerText(),locale==='en'?/project, image, preview/:/作品、圖片、預覽/);
    assert.equal(await page.locator('.project-image-concept img').count(),1);
    await page.getByRole('button',{name:locale==='en'?'Cancel':'取消',exact:true}).click();
    assert.equal(await page.locator('.project-image-concept img').count(),1);
    await fresh.click();await page.getByRole('button',{name:locale==='en'?'Confirm start over':'確認從頭開始',exact:true}).click();
    await page.waitForFunction(()=>JSON.parse(localStorage.getItem('boardvision.maker.v1'))?.design===null);
    assert.equal(await page.locator('.project-image-concept img').count(),0);
    assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'empty');
    assert.equal(await page.locator('.maker-message').count(),0);
    assert(await page.locator('.maker-design-views button').nth(1).isDisabled());
    const backup=await page.evaluate(()=>JSON.parse(localStorage.getItem('boardvision.maker.v1.before-new-project')));
    assert.equal(backup.design.revision,2);assert.equal(backup.candidate.revision,3);assert.equal(backup.code,'# Manual approved draft');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:`${artifacts}/new-${width}-${locale}.png`,fullPage:true});
    await page.reload({waitUntil:'networkidle'});
    assert.equal(await page.locator('.project-image-concept img').count(),0);
    assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'empty');
    assert.deepEqual(errors,[]);report.results.push({locale,width,checks:['confirmation/cancel','old image removed','backup retained','empty after reload','no console errors or overflow']});await context.close();
  }
}catch(e){report.errors.push(e.stack);process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});}
finally{await browser?.close();await new Promise(done=>preview.server.close(done));await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));}
