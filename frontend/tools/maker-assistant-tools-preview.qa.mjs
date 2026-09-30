// Real MakerAssistant and catalog. Synthetic state only; never touch production, AI or hardware.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview} from './tinkro-preview.mjs';

const runtime='C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=createRequire(import.meta.url)(`${runtime}/playwright`);
const artifacts=fileURLToPath(new URL('./maker-assistant-tools-preview-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0);
const allowed=['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg'];
const report={fixture:'Real MakerAssistant, offline catalog selection and busy state; no production drafts, model or hardware calls',results:[],errors:[],deniedRequests:[]};
let browser,currentPage;
try {
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const viewport of [{width:1651,height:871},{width:1352,height:871},{width:390,height:844},{width:320,height:700}]) {
    for(const locale of ['zh-TW','en']) {
      for(const busy of [false,true]) {
        const context=await browser.newContext({viewport,locale});
        await context.route('**/*',route=>{
          const url=new URL(route.request().url());
          if(url.origin===new URL(preview.url).origin&&allowed.includes(url.pathname))return route.continue();
          report.deniedRequests.push(url.href);return route.abort();
        });
        const page=await context.newPage();currentPage=page;
        const errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
        await page.goto(`${preview.url}?locale=${locale}&reply=paragraph${busy?'&generation=empty':''}`,{waitUntil:'networkidle'});
        assert(await page.evaluate(()=>document.body.innerText.trim().length>0),'Blank page');
        assert.equal(await page.locator('vite-error-overlay, .vite-error-overlay, [data-nextjs-dialog]').count(),0);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow');
        const assistant=page.locator('.maker-assistant');
        const menu=assistant.locator('.maker-chat-tools > .maker-assistant-parts');
        const summary=menu.locator('summary');
        const popover=menu.locator('.maker-parts-popover');
        const input=assistant.locator('.maker-composer textarea');
        const send=assistant.locator('.maker-compose-send');
        const checkboxes=popover.locator('input[type=checkbox]');
        assert.equal(await assistant.locator(':scope > .maker-assistant-parts').count(),0,'Parts still occupy the footer');
        assert.equal(await assistant.locator('.maker-composer > small').count(),0,'Visible hint still occupies the footer');
        assert(await assistant.locator('.maker-composer').evaluate(node=>node.nextElementSibling===null));
        const hint=await input.evaluate(node=>{
          const description=document.getElementById(node.getAttribute('aria-describedby'));
          return {text:description?.textContent,height:description?.getBoundingClientRect().height};
        });
        assert.match(hint.text,locale==='en'?/after confirmation/:/作品確認後才更新/);
        assert.equal(hint.height,1,'Accessible hint consumes normal layout height');
        assert.equal(await menu.getAttribute('open'),null);
        assert.equal(await popover.isVisible(),false);
        await input.fill(locale==='en'?'Keep this unsent request':'保留這段未送出的需求');
        const unsent=await input.inputValue();
        const conversation=await assistant.locator('.maker-conversation').textContent();
        const conversationHeight=await assistant.locator('.maker-conversation').evaluate(node=>node.getBoundingClientRect().height);
        if(viewport.width>=1000) {
          assert(await assistant.locator('.maker-chat-tools').evaluate(node=>{
            const controls=[...node.querySelectorAll(':scope > button, :scope > details > summary')];
            const tops=controls.map(control=>control.getBoundingClientRect().top);
            return Math.max(...tops)-Math.min(...tops)<3;
          }),'Desktop tools should share one row');
        }
        await page.screenshot({path:`${artifacts}/tools-${viewport.width}-${locale}-${busy?'busy':'idle'}-closed.png`,fullPage:true});
        await summary.focus();await summary.press('Space');
        assert.equal(await menu.getAttribute('open'),'');
        assert.equal(await popover.isVisible(),true);
        assert.equal(await checkboxes.count(),2,'Only the existing supported modules are selectable');
        assert.match(await popover.locator('.maker-parts-hint').textContent(),locale==='en'?/after confirmation/:/作品確認後才更新/);
        assert(await popover.evaluate(node=>{
          const panel=node.closest('.maker-assistant').getBoundingClientRect();
          const rect=node.getBoundingClientRect();
          return rect.left>=panel.left&&rect.right<=panel.right&&rect.width>200&&rect.height<=360.1;
        }),'Parts popover is clipped or outside the assistant');
        assert.equal(await assistant.locator('.maker-conversation').evaluate(node=>node.getBoundingClientRect().height),conversationHeight,'Opening parts shrinks the conversation');
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Open menu causes horizontal overflow');
        await page.screenshot({path:`${artifacts}/tools-${viewport.width}-${locale}-${busy?'busy':'idle'}-open.png`,fullPage:true});
        if(busy) {
          for(const checkbox of await checkboxes.all())assert(await checkbox.isDisabled());
          assert(await send.isDisabled());
        } else {
          for(const checkbox of await checkboxes.all())await checkbox.uncheck();
          assert.match(await summary.textContent(),/· 0/);
          assert.match(await popover.locator('header strong').textContent(),/Pi 5 \+ 0/);
          assert(await send.isDisabled(),'An empty module selection enabled send');
          await checkboxes.first().check();
          assert.match(await summary.textContent(),/· 1/);
          assert.equal(await send.isDisabled(),false);
          assert.equal(await menu.getAttribute('open'),'','Selection remounted/closed the disclosure');
          await checkboxes.nth(1).check();
        }
        await summary.press('Escape');
        assert.equal(await menu.getAttribute('open'),null);
        assert(await summary.evaluate(node=>document.activeElement===node),'Escape did not restore summary focus');
        await summary.click();
        await popover.locator('header button').click();
        assert.equal(await menu.getAttribute('open'),null);
        assert(await summary.evaluate(node=>document.activeElement===node));
        await summary.click();await input.click();
        assert.equal(await menu.getAttribute('open'),null,'Outside click does not dismiss');
        await summary.focus();await summary.press('Space');await summary.press('Shift+Tab');
        assert.equal(await menu.getAttribute('open'),null,'Keyboard focus leaving the disclosure does not dismiss');
        assert.equal(await input.inputValue(),unsent,'Settings cleared unsent text');
        assert.equal(await assistant.locator('.maker-conversation').textContent(),conversation,'Settings rewrote conversation');
        await page.locator('.maker-nav button').nth(1).click();
        await page.locator('.maker-nav button').first().click();
        assert.equal(await input.inputValue(),unsent);
        assert.equal(await assistant.locator('.maker-conversation').textContent(),conversation);
        assert.match(await summary.textContent(),/· 2/);
        assert.equal(await menu.getAttribute('open'),null);
        assert.deepEqual(errors,[]);
        report.results.push({viewport,locale,busy,conversationHeight,checks:['closed toolbar parts disclosure; no footer rows','accessible confirmation description','one-row desktop tools; bounded mobile popover','opening does not shrink conversation','catalog selection/count and busy/empty send guards','Escape, close, outside and keyboard dismissal','unsent text, selection and conversation survive navigation','no errors or horizontal overflow']});
        await context.close();
      }
    }
  }
  assert.deepEqual(report.deniedRequests,[]);
  assert(preview.requests.every(path=>allowed.includes(path)),'Non-asset request in isolated preview');
} catch(error) {
  report.errors.push(error.stack);process.exitCode=1;
  if(currentPage&&!currentPage.isClosed())await currentPage.screenshot({path:`${artifacts}/failure.png`,fullPage:true});
} finally {
  await browser?.close();await new Promise(done=>preview.server.close(done));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({scenarios:report.results.length,errors:report.errors,deniedRequests:report.deniedRequests,report:`${artifacts}/report.json`},null,2));
}
