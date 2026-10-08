// Actual Find parts UI; isolated preview only, no camera, Pi, cloud or product-site navigation.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./material-part-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const report={fixture:'Actual BlueprintPage and MaterialPartArt, isolated synthetic project; no hardware or cloud',results:[],errors:[],deniedRequests:[]};
const assetPaths=['/','/theme.js','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'];
let browser,currentPage;

async function contextFor(options,theme){
  const context=await browser.newContext(options);
  await context.addInitScript(theme=>localStorage.setItem('boardvision.theme.v1',theme),theme);
  await context.route('**/*',route=>{
    const request=new URL(route.request().url());
    if(request.origin===new URL(preview.url).origin&&assetPaths.includes(request.pathname))return route.continue();
    report.deniedRequests.push(request.href);return route.abort();
  });
  return context;
}
async function openParts(page,locale){
  await page.goto(`${preview.url}?locale=${locale}`,{waitUntil:'networkidle'});
  await page.getByRole('button',{name:locale==='en'?'Build blueprint':'製作藍圖',exact:true}).click();
  await page.getByRole('tab',{name:locale==='en'?'Find parts':'購買材料',exact:true}).click();
}

try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1352,height:871},{width:390,height:844}]){
    for(const locale of ['zh-TW','en'])for(const theme of ['dark','light']){
      const context=await contextFor({viewport,locale},theme);
      const page=await context.newPage();currentPage=page;
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
      await openParts(page,locale);
      assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
      assert(await page.evaluate(()=>document.body.innerText.trim().length>0));
      assert.equal(await page.locator('vite-error-overlay, .vite-error-overlay, [data-nextjs-dialog]').count(),0);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow');
      const cards=page.locator('.blueprint-shop-card');
      assert.equal(await cards.count(),5);
      const kinds=await cards.locator('.material-part-art').evaluateAll(nodes=>nodes.map(n=>n.dataset.partArt));
      assert.deepEqual(kinds,['pi5','ultrasonic','tft','standoff','acrylic-panel']);
      assert.deepEqual(await cards.locator('.blueprint-shop-quantity').allTextContents(),['× 1','× 1','× 1','× 4','× 2']);
      for(const card of await cards.all()){
        await card.scrollIntoViewIfNeeded();
        assert(await card.isVisible());
        assert.equal(await card.getByRole('img').count(),1);
        assert.match(await card.getByRole('img').getAttribute('aria-label'),locale==='en'?/Part illustration/:/零件示意圖/);
        assert.equal(await card.locator('.blueprint-shop-art-caption').innerText(),locale==='en'?'Illustration':'示意圖');
        assert(await card.evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Card overflow');
        for(const selector of ['.blueprint-shop-art','strong','a']){
          assert(await card.locator(selector).evaluate(node=>node.scrollWidth<=node.clientWidth+1),`${selector} overflow`);
        }
        const href=await card.locator('a').getAttribute('href');
        assert(['https://www.google.com','https://www.raspberrypi.com'].includes(new URL(href).origin));
      }
      await cards.first().scrollIntoViewIfNeeded();
      await page.screenshot({path:`${artifacts}/parts-${viewport.width}-${locale}-${theme}.png`,fullPage:true});
      // Navigating away and back must not lose quantities or activate hardware checks.
      await page.getByRole('tab',{name:locale==='en'?'Assembly guide':'組裝引導',exact:true}).click();
      await page.getByRole('tab',{name:locale==='en'?'Find parts':'購買材料',exact:true}).click();
      assert.deepEqual(await cards.locator('.blueprint-shop-quantity').allTextContents(),['× 1','× 1','× 1','× 4','× 2']);
      assert.deepEqual(errors,[]);
      report.results.push({viewport,locale,theme,kinds,checks:['actual cards and accessible SVGs render','no clipping or horizontal overflow','quantities and external links retained','tabs still work; no browser errors']});
      await context.close();
    }
  }
  const context=await contextFor({viewport:{width:1352,height:871},reducedMotion:'reduce'},'dark');
  const page=await context.newPage();currentPage=page;
  await openParts(page,'en');
  await page.locator('.blueprint-shop-card').first().hover();
  const motion=await page.locator('.blueprint-shop-art-inner').first().evaluate(node=>({duration:getComputedStyle(node).transitionDuration,transform:getComputedStyle(node).transform}));
  assert.equal(motion.duration,'0s');assert.equal(motion.transform,'none');
  report.results.push({checks:['reduced motion disables decorative hover movement']});
  await context.close();
  assert.deepEqual(report.deniedRequests,[],'Unexpected request outside isolated assets');
  assert(preview.requests.every(path=>assetPaths.includes(path)),'Non-asset endpoint requested');
}catch(error){
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
}finally{
  await browser?.close();
  await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
