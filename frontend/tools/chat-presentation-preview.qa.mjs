// Actual chat components, on fixture origins only. Never contacts production, AI or Pi.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {startPreview as startDesign} from './tinkro-preview.mjs';
import {startPreview as startWiring,fixtureRequestAllowed} from './wiring-ai-preview.mjs';

const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./chat-presentation-artifacts/',import.meta.url));
await mkdir(artifacts,{recursive:true});
const [design,wiring]=await Promise.all([startDesign(0),startWiring(0)]);
const report={scope:'Real design/wiring/debug chat UI with offline fixtures; no production storage, AI or hardware actions.',checks:[],errors:[],denied:[]};
let browser,page;
async function presentation(view){
  const designView=view==='design',row=page.locator(designView?'.maker-compose-row':'.ai-debug-compose-row');
  const input=row.locator('textarea');
  const result=await row.evaluate(el=>{
    const input=el.querySelector('textarea'),send=el.querySelector('button'),r=el.getBoundingClientRect(),b=send.getBoundingClientRect();
    return {radius:getComputedStyle(el).borderRadius,border:getComputedStyle(el).borderTopWidth,inputHeight:input.getBoundingClientRect().height,sendInside:b.x>=r.x&&b.right<=r.right+1&&b.y>=r.y&&b.bottom<=r.bottom+1,overflow:document.documentElement.scrollWidth>innerWidth+1};
  });
  assert.equal(result.radius,'18px');assert.equal(result.border,'1px');
  assert(result.inputHeight>=64,'Input retains enough writing space');
  assert(result.sendInside,'Send stays inside the input surface');assert(!result.overflow,'No page overflow');
  await input.focus();
  const border=await row.evaluate(el=>getComputedStyle(el).borderColor);
  assert.equal(border,'rgb(65, 122, 190)','Visible keyboard focus');
  const bubbles=await page.locator(designView?'.maker-message':'.ai-debug-message').evaluateAll(items=>items.map(el=>({
    role:el.className.includes('user')?'user':'assistant',side:getComputedStyle(el).alignSelf,border:getComputedStyle(el).borderLeftWidth,radius:getComputedStyle(el).borderRadius,background:getComputedStyle(el).backgroundColor,clipped:el.scrollWidth>el.clientWidth+1,
  })));
  for(const bubble of bubbles){
    assert.equal(bubble.side,bubble.role==='user'?'flex-end':'flex-start');
    assert.equal(bubble.border,'1px','Messages are not striped warning cards');
    assert.equal(bubble.radius,bubble.role==='user'?'16px 16px 4px':'16px 16px 16px 4px');
    assert(!bubble.clipped,'Bubble content stays inside its surface');
  }
  assert(bubbles.some(b=>b.role==='user')&&bubbles.some(b=>b.role==='assistant'));
  assert.notEqual(bubbles.find(b=>b.role==='user').background,bubbles.find(b=>b.role==='assistant').background);
  if(!designView&&page.viewportSize().width<=960){
    result.chatHeight=(await page.locator('.ai-debug-chat').boundingBox()).height;
    assert(result.chatHeight>=180,'Mobile history stays readable even with a long draft');
  }
  return result;
}
try{
  browser=await chromium.launch({headless:true,channel:'chrome'});
  for(const width of [1651,1352,390,320])for(const locale of ['zh-TW','en']){
    const context=await browser.newContext({viewport:{width,height:width<500?844:871}});
    await context.addInitScript(value=>localStorage.setItem('boardvision.locale.v1',value),locale);
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      const allowed=u.origin===new URL(design.url).origin&&['/','/preview.js','/preview.css','/brand/tinkro-dark.png','/brand/tinkro-symbol.svg'].includes(u.pathname)
        ||u.origin===new URL(wiring.url).origin&&fixtureRequestAllowed(u.pathname+u.search);
      if(allowed)return route.continue();report.denied.push(u.href);return route.abort();
    });
    page=await context.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
    await page.goto(`${design.url}?locale=${locale}&reply=paragraph`,{waitUntil:'networkidle'});
    assert(await page.locator('body').innerText());
    const designBefore=await page.locator('.maker-message').allTextContents();
    await page.locator('.maker-composer textarea').fill(locale==='en'?'Keep this unsent question.':'保留這段未送出的問題。');
    const designDraft=await page.locator('.maker-composer textarea').inputValue();
    report.checks.push({width,locale,view:'design',...await presentation('design')});
    await page.locator('.maker-nav button').nth(2).click();
    await page.locator('.maker-nav button').first().click();
    assert.equal(await page.locator('.maker-composer textarea').inputValue(),designDraft);
    assert.deepEqual(await page.locator('.maker-message').allTextContents(),designBefore);
    await page.screenshot({path:`${artifacts}/design-${width}-${locale}.png`,fullPage:true});
    await page.goto(`${wiring.url}?scenario=flow`,{waitUntil:'networkidle'});
    await page.getByRole('tab',{name:locale==='en'?'AI assistant':'AI 協作',exact:true}).click();
    const input=page.locator('.ai-debug-composer textarea');
    const history=await page.locator('.ai-debug-message > p').allTextContents();
    const events=await page.evaluate(()=>JSON.stringify(window.__wiringQa.events));
    assert.equal(await page.locator('.ai-debug-wiring-presets button').count(),3);
    await page.locator('.ai-debug-wiring-presets button').first().click();
    assert(await input.inputValue());
    const draft=locale==='en'?'My unsent wiring question.':'我還沒送出的接線問題。';
    await input.fill(draft);await input.press('Shift+Enter');
    assert.equal(await input.inputValue(),`${draft}\n`,'Shift+Enter remains a new line');
    report.checks.push({width,locale,view:'wiring',...await presentation('wiring')});
    await page.screenshot({path:`${artifacts}/wiring-${width}-${locale}.png`,fullPage:true});
    await page.locator('.guide-ai-mode-picker button').nth(1).click();
    assert.equal(await input.inputValue(),`${draft}\n`,'Changing focus keeps the draft');
    report.checks.push({width,locale,view:'debug',...await presentation('debug')});
    await page.screenshot({path:`${artifacts}/debug-${width}-${locale}.png`,fullPage:true});
    assert.deepEqual(await page.locator('.ai-debug-message > p').allTextContents(),history);
    assert.equal(await page.evaluate(()=>JSON.stringify(window.__wiringQa.events)),events,'No session or hardware action from presentation changes');
    await page.locator('.ai-debug-head-actions button[aria-controls="ai-debug-records"]').click();
    assert(await page.locator('#ai-debug-records').isVisible());
    assert(await input.isHidden(),'Hidden composer does not participate in the layout');
    await page.locator('#ai-debug-records button').first().click();
    assert.equal(await input.inputValue(),`${draft}\n`);
    assert.deepEqual(errors,[]);assert.equal(await page.locator('vite-error-overlay,.vite-error-overlay,[data-nextjs-dialog]').count(),0);
    await context.close();
  }
  assert.deepEqual(report.denied,[]);
}catch(e){report.errors.push(e.stack);process.exitCode=1;if(page&&!page.isClosed())await page.screenshot({path:`${artifacts}/failure.png`,fullPage:true});}
finally{
  await browser?.close();await Promise.all([design,wiring].map(preview=>new Promise(done=>preview.server.close(done))));
  await writeFile(`${artifacts}/report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({scope:report.scope,checked:report.checks.length,errors:report.errors,denied:report.denied},null,2));
}
