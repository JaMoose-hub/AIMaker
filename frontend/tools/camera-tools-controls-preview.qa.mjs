// Actual VideoView + StatusBar controls; isolated synthetic image/packets only.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview,fixtureRequestAllowed} from './wiring-ai-preview.mjs';

const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./camera-tools-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0),origin=new URL(preview.url).origin;
const legacyImage='<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#ccd8d4"/><text x="300" y="500" font-size="60">Synthetic legacy image transport</text></svg>';
const report={fixture:'Real VideoView/StatusBar; synthetic frames/hooks/legacy image only; no production camera, Pi, model or storage',results:[],errors:[],deniedRequests:[],syntheticImageRequests:[]};
let browser,currentPage;
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:1352,height:871},{width:390,height:844},{width:320,height:700}]){
    for(const locale of ['zh-TW','en']){
      const context=await browser.newContext({viewport,locale});
      await context.addInitScript(value=>localStorage.setItem('boardvision.locale.v1',value),locale);
      await context.route('**/*',route=>{
        const url=new URL(route.request().url());
        if(url.origin===origin&&['/video','/frame.jpg'].includes(url.pathname)){
          report.syntheticImageRequests.push(url.pathname);
          return route.fulfill({status:200,contentType:'image/svg+xml',body:legacyImage});
        }
        if(url.origin===origin&&fixtureRequestAllowed(url.pathname+url.search))return route.continue();
        report.deniedRequests.push(url.href);return route.abort();
      });
      const page=await context.newPage();currentPage=page;page.setDefaultTimeout(5000);
      const errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
      await page.goto(`${preview.url}?scenario=overlay`,{waitUntil:'networkidle'});
      assert((await page.locator('body').innerText()).includes('疊圖篩選隔離 QA'));
      assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay').count(),0);
      const tr=(zh,en)=>locale==='en'?en:zh;
      const trigger=page.getByRole('button',{name:tr('相機工具','Camera tools'),exact:true});
      const panel=page.locator('.camera-tools-popover');
      const tracking=panel.locator('.realtime-toggle');
      const horizontal=panel.getByRole('button',{name:tr('左右鏡像','Left/right'),exact:true});
      const vertical=panel.getByRole('button',{name:tr('上下鏡像','Up/down'),exact:true});
      const direction=panel.getByRole('button',{name:tr('校正方向','Calibrate direction'),exact:true});
      const result={viewport,locale,checks:[]};
      const withinViewport=async()=>{
        const bounds=await panel.boundingBox();
        assert(bounds&&bounds.x>=11&&bounds.y>=11&&bounds.x+bounds.width<=viewport.width-11&&bounds.y+bounds.height<=viewport.height-11);
        assert(await panel.evaluate(node=>node.scrollWidth<=node.clientWidth+1),'Tools have horizontal overflow');
      };
      await page.locator('.video-control-toolbar').scrollIntoViewIfNeeded();
      const before=await page.locator('.video-shell').boundingBox();
      await page.evaluate(()=>{window.__qaCameraBeforeTools=document.querySelector('.video-img');});
      const geometry=()=>page.evaluate(()=>JSON.stringify([window.__overlayQa.frame.detection,...window.__overlayQa.frame.components].map(({outline,pins})=>({outline,pins}))));
      const originalPackets=await geometry();
      assert.equal(await page.locator('.video-control-toolbar button').count(),2);
      assert.equal(await panel.isVisible(),false);
      assert.equal(await page.locator('.video-control-toolbar .mirror-controls,.video-control-toolbar .pin-calibration-controls').count(),0);
      result.checks.push('Toolbar contains only the 2D switch and camera-tools trigger; four image actions are hidden in tools');
      await page.screenshot({path:`${artifacts}/camera-${viewport.width}-${locale}-collapsed.png`,fullPage:true});
      await trigger.click();assert(await panel.isVisible());await withinViewport();
      assert.equal(await panel.locator('.camera-tools-video-controls button').count(),4);
      for(const action of [tracking,horizontal,vertical,direction])assert(await action.isVisible());
      assert.deepEqual(await page.locator('.video-shell').boundingBox(),before);
      result.checks.push('Opening tools reveals all four existing actions without resizing the camera');
      await page.screenshot({path:`${artifacts}/camera-${viewport.width}-${locale}-tools.png`,fullPage:true});
      assert.equal(await tracking.getAttribute('aria-pressed'),'true');
      await tracking.click();assert.equal(await tracking.getAttribute('aria-pressed'),'false');
      await tracking.click();assert.equal(await tracking.getAttribute('aria-pressed'),'true');
      assert.equal(await page.locator('.video-img').getAttribute('data-tracking-frame'),'77');
      assert.equal(await horizontal.getAttribute('aria-pressed'),'true');
      await horizontal.click();assert.equal(await horizontal.getAttribute('aria-pressed'),'false');
      assert(!((await page.locator('.video-img').getAttribute('class')).includes('mirrored-x')));
      await horizontal.click();await vertical.click();
      assert.equal(await vertical.getAttribute('aria-pressed'),'true');
      assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('boardvision.camera-mirror.v2'))),{x:true,y:true});
      result.checks.push('Tracking toggles; both mirror axes retain their original image classes and storage key');
      await direction.click();assert(await panel.locator('.pin-calibration-panel').isVisible());
      await panel.getByTitle(tr('向右移動','Move right'),{exact:true}).click();
      const offset=await page.evaluate(()=>JSON.parse(localStorage.getItem('boardvision.gpio-pin-calibration.v3:raspberry-pi-5')));
      assert.equal(offset.x,-1);assert.equal(offset.y,0);
      assert.match(await panel.locator('.pin-calibration-value').innerText(),/X -1 · Y 0/);
      await withinViewport();
      await page.screenshot({path:`${artifacts}/camera-${viewport.width}-${locale}-direction.png`,fullPage:true});
      await page.keyboard.press('Escape');assert.equal(await panel.isVisible(),false);
      assert(await trigger.evaluate(node=>node===document.activeElement));
      await trigger.click();
      assert.equal(await horizontal.getAttribute('aria-pressed'),'true');
      assert.equal(await vertical.getAttribute('aria-pressed'),'true');
      assert.equal(await direction.getAttribute('aria-expanded'),'true');
      assert.match(await panel.locator('.pin-calibration-value').innerText(),/X -1 · Y 0/);
      result.checks.push('Direction nudges preserve mirrored source-coordinate signs; Escape returns focus and reopening preserves settings');
      await panel.getByTitle(tr('重設校正','Reset calibration'),{exact:true}).click();
      assert.equal(await page.evaluate(()=>localStorage.getItem('boardvision.gpio-pin-calibration.v3:raspberry-pi-5')),null);
      assert.match(await panel.locator('.pin-calibration-value').innerText(),/X 0 · Y 0/);
      await page.evaluate(()=>document.querySelector('#qa-calibration-state').click());
      for(const action of [horizontal,vertical,direction])assert(await action.isDisabled());
      await page.evaluate(()=>document.querySelector('#qa-calibration-state').click());
      for(const action of [horizontal,vertical,direction])assert.equal(await action.isDisabled(),false);
      result.checks.push('Reset and the existing board-calibration disabled guard still work');
      await page.keyboard.press('Escape');
      await page.getByRole('button',{name:tr('本步驟 2D 接線圖','Step 2D diagram'),exact:true}).click();
      assert(await page.locator('#qa-camera-diagram').isVisible());
      await trigger.click();assert(await panel.isVisible());
      assert.equal(await panel.locator('.camera-tools-video-controls').count(),0);
      await page.keyboard.press('Escape');
      await page.getByRole('button',{name:tr('返回鏡頭','Back to camera'),exact:true}).click();
      await trigger.click();
      assert.equal(await vertical.getAttribute('aria-pressed'),'true');
      assert.equal(await direction.getAttribute('aria-expanded'),'true');
      assert.equal(await tracking.getAttribute('aria-pressed'),'true');
      result.checks.push('2D view keeps camera-only controls hidden and restores their unchanged state on return');
      // The viewport-bounded panel starts at least 12px from the edge.
      // A neutral outer corner stays outside even on 320px phones; the scene
      // buttons below the camera may legitimately be covered by the popover.
      await page.mouse.click(2,2);
      assert.equal(await panel.isVisible(),false);
      assert(await page.evaluate(()=>window.__qaCameraBeforeTools===document.querySelector('.video-img')));
      assert.equal(await geometry(),originalPackets);
      assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage).sort()),['boardvision.camera-mirror.v2','boardvision.locale.v1']);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]);
      assert.deepEqual(report.deniedRequests,[]);
      result.checks.push('Outside click closes tools; same camera DOM and unchanged geometry; no errors, overflow or production requests');
      report.results.push(result);await context.close();
    }
  }
}catch(error){
  report.errors.push(error.stack);
  await currentPage?.screenshot({path:`${artifacts}/failure.png`,fullPage:true}).catch(()=>{});
  throw error;
}finally{
  await writeFile(`${artifacts}/report.json`,JSON.stringify({...report,requests:preview.requests},null,2));
  await browser?.close();await new Promise(resolve=>preview.server.close(resolve));
  console.log(JSON.stringify(report,null,2));
}
