// Static rendering of production components/CSS; no API, camera or Pi actions.
import {createServer} from 'node:http';
import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import {designFor,maker,componentTests,renderGuide} from './project_guide_fixture.mjs';
const styles=['styles.css','maker.css','debug.css','responsive.css','guideAi.css','tinkro.css','assistant.css','components/ComponentTestCard.css','components/WiringTaskToolbar.css'];
const bundle=await build({stdin:{contents:styles.map(s=>`@import "./${s}";`).join('\n'),loader:'css',resolveDir:fileURLToPath(new URL('../src/',import.meta.url))},bundle:true,write:false,external:['/brand/*']});
const css=bundle.outputFiles[0].contents;
const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
let session=maker.startProjectGuide(maker.emptyGuide());
while(session.phase==='active') session=maker.confirmProjectWire(design,session);
const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname==='/preview.css'){res.writeHead(200,{'content-type':'text/css'});res.end(css);return;}
  if(url.pathname!=='/'){res.writeHead(404);res.end();return;}
  const locale=url.searchParams.get('lang')==='en'?'en':'zh-TW';
  const run={id:'icons',project_id:design.id,revision:design.revision,component_id:'hc-sr04',guide_key:componentTests.componentTestKey(design,session,'hc-sr04'),
    outcome:'inconclusive',reason:'no_echo',created_at:Date.now()/1000,finished_at:Date.now()/1000+60,phase:'finished',reserved:false,invalidated:false,
    samples:{near:{count:0,median_cm:null},far:{count:0,median_cm:null}},logs:[],options:[]};
  const html=await renderGuide({design,session,locale,toolbar:true,embedded:true,floating:true,onDebug(){},tests:{status:{connected:true,active:null,results:[run]}}});
  res.writeHead(200,{'content-type':'text/html; charset=utf-8'});
  res.end(`<!doctype html><html lang="${locale}" data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Test action icons — isolated preview</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"></head><body><div class="app maker-layout maker-stage-guide tinkro-theme" style="display:block;padding:24px;height:auto;min-height:100vh"><main class="is-unified"><div class="assistant-wiring-stage has-task-toolbar"><div class="wiring-task-toolbar">${html}</div></div></main></div></body></html>`);
});
server.listen(18788,'127.0.0.1',()=>console.log('http://127.0.0.1:18788/'));
