// Actual components, synthetic cloud phases, isolated origin. Never generate an image.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./project-generation-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Real DesignStudio/ProjectConcept, synthetic phases, no cloud, camera or Pi',results:[],errors:[],deniedRequests:[]};
const assetPaths=['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'];
let browser,currentPage;
async function contextFor(options){
  const context=await browser.newContext(options);
  await context.route('**/*',route=>{
    const request=new URL(route.request().url());
    if(request.origin===new URL(preview.url).origin&&assetPaths.includes(request.pathname))return route.continue();
    report.deniedRequests.push(request.href);return route.abort();
  });
  return context;
}
async function checkLayout(page){
  assert(await page.evaluate(()=>document.body.innerText.trim().length>0),'Blank page');
  assert.equal(await page.locator('vite-error-overlay, .vite-error-overlay, [data-nextjs-dialog]').count(),0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal document overflow');
  const status=page.locator('.project-generation-status');
  assert.equal(await status.count(),1);
  assert(await status.isVisible());
  assert.equal(await status.getAttribute('role'),'status');
  assert.equal(await page.locator('.maker-concept-page').getAttribute('aria-busy'),'true');
  assert.equal(await page.locator('.maker-concept-page .project-image-empty:not(.project-generation-status)').count(),0);
  for(const selector of ['.project-generation-status','.project-generation-copy h3','.project-generation-copy p']){
    assert(await page.locator(selector).evaluate(node=>node.scrollWidth<=node.clientWidth+1),`${selector} text overflows`);
  }
  return status.evaluate(node=>node.getBoundingClientRect().toJSON());
}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:1352,height:871},{width:390,height:844}]){
    for(const locale of ['zh-TW','en']){
      for(const fixture of ['first','empty','existing']){
        const context=await contextFor({viewport,locale});
        const page=await context.newPage();currentPage=page;
        const errors=[];
        page.on('pageerror',e=>errors.push(e.message));
        page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
        await page.goto(`${preview.url}?locale=${locale}&generation=${fixture}`,{waitUntil:'networkidle'});
        const result={viewport,locale,fixture,checks:[],status:await checkLayout(page)};
        assert.equal(await page.locator('.project-generation-status').getAttribute('data-phase'),'design');
        assert.match(await page.locator('.project-generation-status h3').innerText(),locale==='en'?/AI is thinking/:/AI 正在推論中/);
        assert.equal(await page.locator('.project-image-concept figure img').count(),fixture==='existing'?1:0);
        const before=await page.locator('.project-generation-orbit').evaluate(node=>getComputedStyle(node,'::before').transform);
        await page.waitForTimeout(120);
        const after=await page.locator('.project-generation-orbit').evaluate(node=>getComputedStyle(node,'::before').transform);
        assert.notEqual(before,after,'Orbit is not actually animated');
        result.checks.push('real inference status animates; existing image retained');
        await page.getByRole('button',{name:'Fixture: image phase',exact:true}).click();
        await checkLayout(page);
        assert.equal(await page.locator('.project-generation-status').getAttribute('data-phase'),'image');
        assert.match(await page.locator('.project-generation-status h3').innerText(),locale==='en'?/Generating your project image/:/正在生成作品圖片/);
        await page.screenshot({path:`${artifacts}/image-${viewport.width}-${locale}-${fixture}.png`,fullPage:true});
        await page.locator('.maker-nav button').nth(1).click();
        assert.equal(await page.locator('.maker-concept-page').count(),0);
        await page.locator('.maker-nav button').first().click();
        assert.equal(await page.locator('.project-generation-status').getAttribute('data-phase'),'image');
        result.checks.push('actual image phase label, page switch retains active phase');
        await page.getByRole('button',{name:'Fixture: complete',exact:true}).click();
        assert.equal(await page.locator('.project-generation-status').count(),0);
        assert.equal(await page.locator('.maker-concept-page').getAttribute('aria-busy'),'false');
        assert(await page.locator('.project-image-concept img').evaluate(img=>img.complete&&img.naturalWidth>0));
        assert(await page.locator('.maker-concept-confirm').isEnabled());
        result.checks.push('completion stops animation and displays actual fixture image');
        await page.getByRole('button',{name:'Fixture: fail',exact:true}).click();
        assert.equal(await page.locator('.project-generation-status').count(),0);
        assert.match(await page.locator('.project-image-empty').innerText(),/Offline fixture: generation failed/);
        assert(await page.locator('.maker-concept-confirm').isDisabled());
        await page.getByRole('button',{name:'Fixture: image phase',exact:true}).click();
        await checkLayout(page);
        assert.doesNotMatch(await page.locator('.project-generation-status').innerText(),/generation failed/);
        await page.getByRole('button',{name:'Fixture: stop',exact:true}).click();
        assert.equal(await page.locator('.project-generation-status').count(),0);
        assert.equal(await page.locator('.maker-concept-page').getAttribute('aria-busy'),'false');
        result.checks.push('failure stops motion; retry/stop does not leave stale animation');
        assert.deepEqual(errors,[]);
        result.checks.push('no browser errors, clipped status text or horizontal overflow');
        report.results.push(result);
        await context.close();
      }
    }
  }
  const context=await contextFor({viewport:{width:320,height:700},reducedMotion:'reduce'});
  const page=await context.newPage();currentPage=page;
  await page.goto(`${preview.url}?generation=empty&locale=en`,{waitUntil:'networkidle'});
  await checkLayout(page);
  assert.equal(await page.locator('.project-generation-orbit').evaluate(node=>getComputedStyle(node,'::before').animationName),'none');
  assert.equal(await page.locator('.project-generation-dots i').first().evaluate(node=>getComputedStyle(node).animationName),'none');
  assert.match(await page.locator('.project-generation-status').innerText(),/AI is thinking/);
  await page.screenshot({path:`${artifacts}/reduced-motion-320.png`,fullPage:true});
  report.results.push({viewport:{width:320,height:700},checks:['reduced motion disables orbit and dots; status stays readable']});
  await context.close();
  assert.deepEqual(report.deniedRequests,[],'Unexpected request outside isolated assets');
  assert(preview.requests.every(path=>assetPaths.includes(path)),'Preview contacted a non-asset endpoint');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();
  await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
