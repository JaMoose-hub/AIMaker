// Source-only header layout fixture. No production bundle, camera, Pi or API.
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const jsx=(type,props)=>React.createElement(type,props);
const runtime={jsx,jsxs:jsx,Fragment:React.Fragment};
const load=(path,deps={})=>{
  const module={};
  new Function('require','exports',ts.transpileModule(read(path),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText)(id=>{
    if(id==='react')return React;
    if(id==='../lib/headerPanels')return {useHeaderPanel:(_panel,initial=false)=>React.useState(initial)};
    if(id==='react/jsx-runtime')return runtime;
    if(id.endsWith('.css'))return {};
    if(id in deps)return deps[id];
    throw Error(`Unmocked dependency ${id}`);
  },module);
  return module;
};
const {WorkspaceHeader}=load('../src/components/WorkspaceHeader.tsx');
const deny=()=>{throw Error('Hardware actions disabled in layout fixture');};
const phoneSource=ts.createSourceFile('MobileCompanion.tsx',read('../src/components/MobileCompanion.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let phoneTrigger;
function findPhoneTrigger(node) {
  if(ts.isVariableDeclaration(node)&&node.name.getText(phoneSource)==='trigger')phoneTrigger=node.initializer.getText(phoneSource);
  ts.forEachChild(node,findPhoneTrigger);
}
findPhoneTrigger(phoneSource);
const renderPhone=new Function('React','session','mobile','connectionLabel','open','view','controller','showConnection','workspace','tr',
  ts.transpileModule(`const trigger=${phoneTrigger};`,{compilerOptions:{jsx:ts.JsxEmit.React}}).outputText+';return trigger;');
const css=()=>['styles','debug','responsive','guideAi','tinkro','assistant','maker','deviceConnections','mobile']
  .map(name=>read(`../src/${name}.css`)).join('\n');
function html(url) {
  const en=url.searchParams.get('lang')==='en',connected=!url.searchParams.has('offline');
  const tr=(zh,english)=>en?english:zh;
  const {DeviceConnectionGroups}=load('../src/components/DeviceConnectionGroups.tsx');
  const {PiConnectionControl}=load('../src/components/PiConnectionControl.tsx',{
    '../lib/PiConnection':{usePiConnection:()=>({status:{connected,program:'not_deployed',execution:{jobs:[]}},pending:false,connect:deny,perform:deny,action:deny})},
    '../lib/piApi':{executionPending:()=>false,programOwner:()=>null,stopPiProgram:deny},
    '../lib/useMaker':{useMakerText:()=>tr},
  });
  const strings=JSON.parse(read(`../src/locales/${en?'en':'zh-TW'}.json`));
  const {RuntimeToolbar}=load('../src/components/RuntimeToolbar.tsx',{
    '../lib/i18n':{useI18n:()=>({locale:en?'en':'zh-TW',t:key=>strings[key],tx:value=>value})},
    './ThemeSelect':{ThemeSelect:()=>React.createElement('label',{className:'runtime-select'},tr('外觀','Theme'),React.createElement('select',{'aria-label':'Theme'},React.createElement('option',null,tr('深色','Dark'))))},
  });
  const h=React.createElement;
  const phone=h('div',{className:'mobile-toolbar-slot mobile-header-slot'},
    renderPhone(React,connected?{}:null,{},connected?tr('手機已連接','Phone connected'):tr('連接手機','Connect phone'),false,'connection',{project:{}},deny,{trigger:{}},tr));
  const brand=h('div',{className:'brand'},h('div',{className:'brand-text'},
    h('h1',{className:'brand-title'},h('img',{className:'brand-logo',src:'/brand/tinkro-dark.png',alt:'Tinkro',width:128,height:40})),h('div',{className:'brand-subtitle'},'Vibe Maker Studio')));
  const navigation=h('nav',{className:'maker-nav','aria-label':tr('作品工作流程','Maker workflow')},
    [tr('設計與藍圖','Design & blueprint'),tr('接線引導＋AI 除錯','Wiring + AI debug'),tr('部署與執行','Deploy & run')].map((label,i)=>h('button',{key:i,className:i===1?'active':'','aria-current':i===1?'step':undefined},h('span',null,`0${i+1}`),label)));
  const content=h('div',{className:'app tinkro-theme pi-deploy-layout maker-layout maker-stage-guide maker-wiring-full-width'},h('main',{className:'main'},
    h(WorkspaceHeader,{brand,navigation,saveStatus:null},
      h(DeviceConnectionGroups,{phoneLabel:tr('手機取景','Phone camera'),piLabel:tr('Pi 執行','Pi runtime'),phoneName:tr('手機','Phone'),piName:'Pi',phone,pi:h(PiConnectionControl)}),
      h(RuntimeToolbar,{collapsible:true,controllers:[{board_id:'pi5',name:'Raspberry Pi 5'}],activeBoardId:'pi5',onControllerChange:deny,onLocaleChange:deny})),
    h('section',{style:{padding:'28px 12px',color:'var(--text-dim)',fontSize:12}},tr('隔離排版預覽 · 不會連接手機或 Pi','Isolated layout preview · no phone or Pi connection'))));
  return `<!doctype html><html lang="${en?'en':'zh-Hant'}" data-theme="${url.searchParams.get('theme')==='light'?'light':'dark'}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Device header layout fixture</title><link rel="stylesheet" href="/preview.css"></head><body>${renderToStaticMarkup(content)}</body></html>`;
}
const server=createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(req.method!=='GET'){res.writeHead(405);res.end();return;}
  let content,type;
  if(url.pathname==='/'){content=html(url);type='text/html';}
  else if(url.pathname==='/preview.css'){content=css();type='text/css';}
  else if(url.pathname==='/brand/tinkro-dark.png'){content=readFileSync(new URL('../public/brand/tinkro-dark.png',import.meta.url));type='image/png';}
  else if(url.pathname==='/brand/tinkro-light-filter.svg'){content=readFileSync(new URL('../public/brand/tinkro-light-filter.svg',import.meta.url));type='image/svg+xml';}
  else {res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':`${type}; charset=utf-8`,'Cache-Control':'no-store',
    'Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'none'"});
  res.end(content);
});
await new Promise((done,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',done);});
console.log(`Device header layout fixture: http://127.0.0.1:${server.address().port}/`);
