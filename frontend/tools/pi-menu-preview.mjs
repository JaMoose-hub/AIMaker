// Isolated, in-memory React fixture. No production bundle, camera, Pi or APIs.
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const mockConnection=`
import {useEffect,useState} from 'react';
export function usePiConnection() {
  const [,update]=useState(0);
  useEffect(()=>{const refresh=()=>update(v=>v+1);window.addEventListener('pi-fixture-state',refresh);return()=>window.removeEventListener('pi-fixture-state',refresh);},[]);
  return {...window.__piMenuQa.connection,
    connect(){window.__piMenuQa.actions.push('connect');},
    action(...args){window.__piMenuQa.actions.push(['queue',...args]);},
    perform(){window.__piMenuQa.actions.push('stop-confirmed');return Promise.resolve();}};
}`;
const result=await build({write:false,bundle:true,format:'esm',platform:'browser',jsx:'automatic',
  stdin:{resolveDir:fileURLToPath(new URL('../',import.meta.url)),loader:'tsx',contents:`
import React from 'react';import {createRoot} from 'react-dom/client';
import {WorkspaceHeader} from './src/components/WorkspaceHeader';
import {DeviceConnectionGroups} from './src/components/DeviceConnectionGroups';
import {PiConnectionControl} from './src/components/PiConnectionControl';
const params=new URLSearchParams(location.search),en=params.get('lang')==='en';
window.__piMenuQa={actions:[],errors:[],connection:{status:null,pending:false,networkError:false,error:null}};
window.addEventListener('error',e=>window.__piMenuQa.errors.push(e.message));
window.addEventListener('unhandledrejection',e=>window.__piMenuQa.errors.push(String(e.reason)));
window.__piMenuQa.setScenario=(scenario)=>{
  const s={connected:true,busy:false,component_test_id:null,program:'not_deployed',pid:null,host:'fixture.invalid',username:'demo',execution:{jobs:[],policy:'confirm_then_fifo'}};
  if(['running','test','handoff','lost'].includes(scenario))Object.assign(s,{program:'running',pid:41,invocation_id:'fixture-owner'});
  if(scenario==='test')s.component_test_id='fixture-test';
  if(scenario==='handoff')s.execution.jobs=[{id:'next',label:'Next project',kind:'deploy',state:'awaiting_confirmation',owner:'program:fixture-owner',error:null}];
  window.__piMenuQa.connection={status:scenario==='offline'?null:s,pending:false,networkError:scenario==='lost',error:null};
  window.dispatchEvent(new Event('pi-fixture-state'));
};
window.__piMenuQa.setScenario(params.get('scenario')||'offline');
const tr=(zh,english)=>en?english:zh;
const phone=<div className="mobile-toolbar-slot"><button className="mobile-connect-button" data-connected="true"><span className="mobile-connection-dot"/>{tr('已連接','Connected')}</button></div>;
const brand=<div className="brand"><div className="brand-text"><h1 className="brand-title"><img className="brand-logo" src="/brand.png" alt="Tinkro"/></h1><div className="brand-subtitle">Vibe Maker Studio</div></div></div>;
const nav=<nav className="maker-nav" aria-label="Workflow">{[tr('設計與藍圖','Design & blueprint'),tr('接線引導＋AI 除錯','Wiring + AI debug'),tr('部署與執行','Deploy & run')].map((label,i)=><button key={i} className={i===1?'active':''}><span>0{i+1}</span>{label}</button>)}</nav>;
createRoot(document.querySelector('#root')).render(<div className="app tinkro-theme pi-deploy-layout maker-layout maker-stage-guide"><main className="main"><WorkspaceHeader brand={brand} navigation={nav} saveStatus={null}><DeviceConnectionGroups phone={phone} pi={<PiConnectionControl/>} phoneLabel="Phone" piLabel="Pi runtime" phoneName={tr('手機','Phone')} piName="Pi"/><button>{tr('設定','Settings')}</button></WorkspaceHeader><p style={{padding:24}}>Isolated Pi menu · no hardware or cloud calls</p></main></div>);
`},plugins:[{name:'fixture-mocks',setup(plugin){
    plugin.onResolve({filter:/\/lib\/(PiConnection|useMaker)$/},args=>({path:args.path,namespace:'fixture'}));
    plugin.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:args.path.endsWith('PiConnection')?mockConnection:`export const useMakerText=()=> (zh,en)=>new URLSearchParams(location.search).get('lang')==='en'?en:zh;`,resolveDir:fileURLToPath(new URL('../',import.meta.url)),loader:'js'}));
    plugin.onLoad({filter:/\.css$/},()=>({contents:'',loader:'js'}));
  }}]});
const script=result.outputFiles.find(f=>f.path.endsWith('.js'))??result.outputFiles[0];
const css=()=>['styles','debug','responsive','guideAi','tinkro','assistant','maker','deviceConnections','mobile'].map(name=>read(`../src/${name}.css`)).join('\n');
const server=createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(req.method!=='GET'){res.writeHead(405);res.end('No mutations');return;}
  let content,type;
  if(url.pathname==='/'){content=`<!doctype html><html data-theme="${url.searchParams.get('theme')==='light'?'light':'dark'}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pi menu fixture</title><link rel="stylesheet" href="/preview.css"></head><body><div id="root"></div><script type="module" src="/preview.js"></script></body></html>`;type='text/html';}
  else if(url.pathname==='/preview.js'){content=script.contents;type='text/javascript';}
  else if(url.pathname==='/preview.css'){content=css();type='text/css';}
  else if(url.pathname==='/brand.png'){content=readFileSync(new URL('../public/brand/tinkro-dark.png',import.meta.url));type='image/png';}
  else if(url.pathname==='/brand/tinkro-light-filter.svg'){content=readFileSync(new URL('../public/brand/tinkro-light-filter.svg',import.meta.url));type='image/svg+xml';}
  else{res.writeHead(404);res.end('No proxy');return;}
  res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'"});res.end(content);
});
await new Promise((done,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',done);});
console.log(`Isolated Pi menu http://127.0.0.1:${server.address().port}/`);
