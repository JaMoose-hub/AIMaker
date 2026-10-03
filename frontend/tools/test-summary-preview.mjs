// Static rendering of the real guide. No scripts, API proxy, hardware or dist writes.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {componentTests,maker,designFor,renderGuide} from './project_guide_fixture.mjs';

const css=(await Promise.all(['styles.css','maker.css','debug.css','responsive.css','guideAi.css','tinkro.css','assistant.css','components/ComponentTestCard.css']
  .map(name=>readFile(new URL('../src/'+name,import.meta.url),'utf8')))).join('\n');
const server=createServer(async(req,res)=>{
  if(req.method!=='GET'){res.writeHead(405);res.end();return;}
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname==='/preview.css'){res.writeHead(200,{'Content-Type':'text/css'});res.end(css);return;}
  if(url.pathname!=='/'){res.writeHead(404);res.end();return;}
  const mode=url.searchParams.get('mode')||'stale',locale=url.searchParams.get('lang')==='en'?'en':'zh-TW';
  const cid=mode==='visual'?'mrd-tf240-8p-cs':'hc-sr04',design=designFor([cid]);
  let session=maker.startProjectGuide(maker.emptyGuide());
  while(session.phase==='active')session=maker.confirmProjectWire(design,session);
  const reserved=mode!=='stale';
  const run={id:'preview-test',project_id:design.id,revision:design.revision,component_id:cid,
    guide_key:componentTests.componentTestKey(design,session,cid),created_at:1,finished_at:2,
    template_version:'preview',wiring_hash:'preview',reserved,invalidated:!reserved,
    phase:mode==='visual'?'awaiting_visual':mode==='near'?'awaiting_near':'finished',
    outcome:mode==='visual'?'awaiting_confirmation':reserved?'running':'passed',
    reason:mode==='lost'?'connection_lost':null,detail:'',logs:[],samples:{},latest:null,heartbeat_at:1,
    program_stopped:false,options:['1234','2345','3456','4567']};
  const guide=await renderGuide({design,session,locale,embedded:true,tests:{status:{connected:mode==='near'||mode==='visual',active:reserved?run:null,results:[run]}}});
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store',
    'Content-Security-Policy':"default-src 'self'; script-src 'none'; connect-src 'none'; style-src 'self' 'unsafe-inline'"});
  res.end(`<!doctype html><html lang="${locale}" data-theme="${url.searchParams.get('theme')==='light'?'light':'dark'}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Test summary isolated preview</title><link rel="stylesheet" href="/preview.css"><style>
    body{overflow:auto}.summary-preview{display:block!important;width:min(1000px,calc(100% - 32px));margin:32px auto;height:auto!important}
    .summary-preview>p{font-size:12px;color:var(--muted);margin-bottom:20px}
    .summary-preview .wiring-workspace{height:340px!important}.summary-preview .wiring-workspace-view{height:100%}
    .summary-preview .compact-guide{height:100%;grid-template-rows:auto minmax(0,1fr)}
    .summary-preview .guide-panel-reference{display:none}
    @media(max-width:1100px){.summary-preview .wiring-workspace{height:auto!important}.summary-preview .compact-guide{display:flex!important}.summary-preview .guide-panel-footer{max-height:none!important}}
    </style><main class="app tinkro-theme maker-layout maker-stage-guide summary-preview"><p>隔離排版預覽 · 不連接 Pi、相機或 AI</p><div class="is-unified"><div class="assistant-wiring-stage"><div class="wiring-workspace"><div class="wiring-workspace-view">${guide}</div></div></div></div></main>`);
});
server.listen(18817,'127.0.0.1',()=>console.log('Test summary preview http://127.0.0.1:18817/'));
