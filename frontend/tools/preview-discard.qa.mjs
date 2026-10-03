// Real DesignStudio, ProjectConcept, useMaker persistence/restore; static fixture images.
// Own origin only: never access production drafts, camera, Pi or cloud APIs.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,discardImagePaths} from './tinkro-preview.mjs';

const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./preview-discard-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const allowed=['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg',...discardImagePaths];
const report={fixture:'Actual concept components and useMaker storage; synthetic v2/v3 images on isolated origin. No production/hardware/model calls.',results:[],errors:[],deniedRequests:[]};
const storageKey='boardvision.maker.v1';
let browser,currentPage;
async function saved(page){return page.evaluate(key=>JSON.parse(localStorage.getItem(key)),storageKey)}
async function layout(page){
  assert(await page.evaluate(()=>document.body.innerText.trim().length>0),'Blank page');
  assert.equal(await page.locator('vite-error-overlay, .vite-error-overlay, [data-nextjs-dialog]').count(),0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow');
  for(const selector of ['.maker-concept-version','.maker-concept-feedback'])if(await page.locator(selector).count()){
    assert(await page.locator(selector).evaluate(node=>node.scrollWidth<=node.clientWidth+1),`${selector} clipped`);
  }
}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const cases=[...['zh-TW','en'].flatMap(locale=>[1651,390].map(width=>({fixture:'approved',locale,width}))),
    ...['zh-TW','en'].map(locale=>({fixture:'empty',locale,width:390})),
    ...['busy','enqueue'].map(fixture=>({fixture,locale:'zh-TW',width:1651}))];
  for(const scenario of cases){
    const context=await browser.newContext({viewport:{width:scenario.width,height:scenario.width===390?844:871}});
    await context.route('**/*',route=>{
      const request=new URL(route.request().url());
      if(request.origin===new URL(preview.url).origin&&allowed.includes(request.pathname))return route.continue();
      report.deniedRequests.push(request.href);return route.abort();
    });
    const page=await context.newPage();currentPage=page;
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
    await page.goto(`${preview.url}?discard=${scenario.fixture}&locale=${scenario.locale}`,{waitUntil:'networkidle'});
    await layout(page);
    const initial=await saved(page),checks=[];
    const discard=page.getByRole('button',{name:scenario.locale==='en'?'Discard preview':'捨棄此預覽',exact:true});
    assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'preview');
    assert.match(await page.locator('.maker-concept-version').innerText(),scenario.locale==='en'?/Unconfirmed preview · v3/:/未確認預覽 · v3/);
    assert.equal(await page.locator('.project-image-concept img').getAttribute('src'),discardImagePaths[1]);
    assert(await page.locator('.project-image-concept img').evaluate(img=>img.complete&&img.naturalWidth>0));
    if(['busy','enqueue'].includes(scenario.fixture)){
      assert(await discard.isDisabled());
      assert(await page.locator('.maker-concept-confirm').isDisabled());
      assert.equal(await page.locator('.project-generation-status').count(),scenario.fixture==='busy'?1:0);
      assert.deepEqual(await saved(page),initial,'Busy state altered saved draft');
      await page.getByRole('button',{name:'Fixture: ready preview',exact:true}).click();
      assert(await discard.isEnabled());
      checks.push('enqueue/polling blocks discard and confirmation; completion re-enables safely');
    }
    if(scenario.fixture==='approved'){
      await page.locator('.maker-concept-confirm').click();
      assert(await page.locator('.maker-draft-consent').isVisible(),'Manual draft confirmation lost');
      assert.equal((await saved(page)).code,initial.code);
      checks.push('manual code requires explicit consent, never implicitly replaced');
    }
    await discard.click();
    await page.waitForFunction(key=>JSON.parse(localStorage.getItem(key))?.candidate===null,storageKey);
    const after=await saved(page);
    assert.equal(after.candidate,null);
    for(const key of ['design','code','guide','conversation','hardware','prompt'])assert.deepEqual(after[key],initial[key],`${key} changed`);
    assert.equal(await discard.count(),0);
    assert.equal(await page.locator('.maker-draft-consent').count(),0);
    const feedback=page.locator('.maker-concept-feedback');
    assert.equal(await feedback.getAttribute('role'),'status');
    if(scenario.fixture==='empty'){
      assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'empty');
      assert.equal(await page.locator('.project-image-concept img').count(),0);
      assert.match(await feedback.innerText(),scenario.locale==='en'?/No project has been confirmed/:/尚未有已確認作品/);
      checks.push('no confirmed project returns empty, without substitute image');
    }else{
      assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'approved');
      assert.match(await page.locator('.maker-concept-version').innerText(),scenario.locale==='en'?/Confirmed project · v2/:/已確認作品 · v2/);
      assert.equal(await page.locator('.project-image-concept img').getAttribute('src'),discardImagePaths[0]);
      assert.match(await feedback.innerText(),scenario.locale==='en'?/Showing confirmed project v2/:/目前顯示已確認作品 v2/);
      checks.push('discard displays confirmed v2 image and explicit live feedback, preserves records');
    }
    await layout(page);
    await page.screenshot({path:`${artifacts}/${scenario.fixture}-${scenario.width}-${scenario.locale}.png`,fullPage:true});
    await page.reload({waitUntil:'networkidle'});
    assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),scenario.fixture==='empty'?'empty':'approved');
    assert.equal((await saved(page)).candidate,null);
    assert.equal((await saved(page)).code,initial.code);
    assert.deepEqual((await saved(page)).guide.confirmed,initial.guide.confirmed);
    assert.equal(await page.locator('.maker-concept-feedback').count(),0,'Action notice should not become persistent stale status');
    if(scenario.fixture!=='empty'){
      assert.equal(await page.locator('.project-image-concept img').getAttribute('src'),discardImagePaths[0]);
      await page.locator('.maker-design-views button').nth(1).click();
      assert.match(await page.locator('.maker-blueprint-page').innerText(),/Confirmed project v2/);
      await page.locator('.maker-design-views button').first().click();
      assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'approved');
    }
    checks.push('real useMaker persistence/restoration keeps approved version and wiring; blueprint matches');
    await page.getByRole('button',{name:'Fixture: ready preview',exact:true}).click();
    assert.equal(await page.locator('.maker-concept-page').getAttribute('data-concept-state'),'preview');
    assert.equal(await page.locator('.maker-concept-feedback').count(),0);
    checks.push('a genuinely new preview has no stale discard notice');
    await layout(page);
    assert.deepEqual(errors,[]);
    report.results.push({...scenario,checks});
    await context.close();
  }
  assert.deepEqual(report.deniedRequests,[]);
  assert(preview.requests.every(path=>allowed.includes(path)),'Unexpected non-fixture endpoint');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();
  await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
