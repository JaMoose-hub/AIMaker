import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const {chromium}=createRequire(import.meta.url)('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts='C:/Users/james/.codex/visualizations/2026/10/05/01a10b38-2bdd-7183-bbab-2bc27f8d4a08';
await mkdir(artifacts,{recursive:true});
const bundle=await build({entryPoints:[fileURLToPath(new URL('./assistant-markdown-preview.tsx',import.meta.url))],bundle:true,write:false,outdir:'preview',jsx:'automatic',external:['/brand/*']});
const js=bundle.outputFiles.find(f=>f.path.endsWith('.js')).contents;
const css=bundle.outputFiles.find(f=>f.path.endsWith('.css')).contents;
const html='<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><style>body{margin:0;padding:16px;background:var(--surface-canvas);color:var(--ink-primary)}.markdown-preview{display:block;width:100%;max-width:740px;height:auto;min-height:0;padding:0;margin:0 auto}.markdown-preview .unified-message-list{overflow:visible}.mobile-web-app{position:relative;height:auto}.mw-messages{overflow:visible}.mobile-web-app .mw-chat{height:auto}</style></head><body><div id="root"></div><script type="module" src="/preview.js"></script></body></html>';
const server=createServer((req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1').pathname;
  const resource=path==='/'?[html,'text/html']:path==='/preview.js'?[js,'text/javascript']:path==='/preview.css'?[css,'text/css']:null;
  if(!resource){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':resource[1],'Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});
  res.end(resource[0]);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
const report=[];
try {
  browser=await chromium.launch({channel:'msedge',headless:true});
  for(const surface of ['desktop','mobile'])for(const theme of ['dark','light']) {
    const page=await browser.newPage({viewport:{width:surface==='mobile'?390:760,height:900}});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/?surface=${surface}&theme=${theme}`);
    await page.locator('.assistant-markdown table').waitFor();
    await page.locator('.assistant-markdown-table-hint').waitFor();
    const result=await page.evaluate(()=>{
      const wrapper=document.querySelector('.assistant-markdown-table');
      const pre=document.querySelector('.assistant-markdown pre');
      const paragraph=document.querySelector('.assistant-markdown p');
      const originalUser=document.querySelector('.is-user p');
      wrapper.scrollLeft=240;
      return {tableColumns:wrapper.querySelectorAll('th').length,tableRows:wrapper.querySelectorAll('tbody tr').length,
        scrolled:wrapper.scrollLeft>0,tableOverflow:wrapper.scrollWidth>wrapper.clientWidth,
        pageOverflow:document.documentElement.scrollWidth>innerWidth+1,codeWhitespace:getComputedStyle(pre).whiteSpace,
        paragraphWhitespace:getComputedStyle(paragraph).whiteSpace,userLiteral:originalUser.textContent,
        headings:document.querySelectorAll('.assistant-markdown h2,.assistant-markdown h3').length,
        bodyFont:getComputedStyle(paragraph).fontSize,tableFont:getComputedStyle(wrapper.querySelector('td')).fontSize};
    });
    assert.equal(result.tableColumns,5);assert.equal(result.tableRows,3);
    assert(result.tableOverflow&&result.scrolled,'The table scrolls inside the bubble');
    assert(!result.pageOverflow,'Markdown must not widen the page');
    assert.equal(result.codeWhitespace,'pre');assert.equal(result.paragraphWhitespace,'pre-line');
    assert.equal(result.userLiteral,'**我買的零件**：幫我核對，不要更改接線。');assert.equal(result.headings,2);
    assert.deepEqual(errors,[]);
    await page.locator('.assistant-markdown-table').evaluate(el=>{el.scrollLeft=0;});
    await page.screenshot({path:`${artifacts}/assistant-markdown-${surface}-${theme}.png`,fullPage:true});
    report.push({surface,theme,...result,errors});
    await page.close();
  }
  console.log(JSON.stringify({passed:report.length,checks:report,artifacts},null,2));
} finally {
  await browser?.close();
  await new Promise(resolve=>server.close(resolve));
}
