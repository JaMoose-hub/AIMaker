import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const compile=path=>ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
const api={};new Function('exports',compile('../src/lib/piApi.ts'))(api);
let connection,english=false;
const module={};new Function('require','exports','React',compile('../src/components/PiConnectionControl.tsx'))(name=>{
  if(name==='react')return React;
  if(name==='../lib/PiConnection')return {usePiConnection:()=>connection};
  if(name==='../lib/piApi')return api;
  if(name==='../lib/useMaker')return {useMakerText:()=> (zh,en)=>english?en:zh};
  throw Error(name);
},module,React);
const idle={connected:true,busy:false,component_test_id:null,program:'not_deployed',pid:null,execution:{jobs:[],policy:'confirm_then_fifo'}};
const running={...idle,program:'running',pid:41,invocation_id:'current'};
const job={id:'one',label:'Next project',kind:'deploy',state:'queued',owner:null,error:null};
function render(status,extra={}) {
  connection={status,pending:false,networkError:false,error:null,connect(){assert.fail('No connection during render');},perform(){assert.fail('No stop during render');},action(){assert.fail('No queue action during render');},...extra};
  return renderToStaticMarkup(React.createElement(module.PiConnectionControl));
}
const summary=html=>html.match(/<summary\b[^]*?<\/summary>/)?.[0];

test('idle Pi has one status entry and no zero count, connect or execution buttons beside it',()=>{
  for(const [status,text] of [[null,'未連線'],[idle,'已連線']]) {
    const html=render(status),entry=summary(html);
    assert.match(entry,new RegExp(`Pi · ${text}`));
    assert.doesNotMatch(entry,/pi-device-count|連線 Pi|執行管理<|>0</);
    assert.doesNotMatch(html,/class="pi-header-stop"/);
    assert.match(html,/pi-device-panel-heading[^]*pi-global-connect/);
    assert.doesNotMatch(html,/<details[^>]*open=""/);
  }
});
test('running Pi keeps Stop visible outside its closed menu without bypassing consent',()=>{
  const html=render(running);
  assert.match(summary(html),/Pi · 執行中/);
  assert.match(html,/<\/details><button type="button" class="pi-header-stop" title=[^>]+>/);
  const source=read('../src/components/PiConnectionControl.tsx');
  assert.match(source,/className="pi-header-stop"[^]*?onClick=\{\(\) => \{ setMenuOpen\(true\); setStopConsent\(owner\); \}\}/);
  assert.match(source,/stopConsent !== owner \|\| stopping\.current/);
  assert.match(source,/stopPiProgram\(approved\)/);
});
test('test, pending queue, unknown owner and connection loss retain stop guards',()=>{
  for(const candidate of [{...running,component_test_id:'test'},{...running,execution:{jobs:[job]}},{...running,busy:true},{...running,invocation_id:'',pid:null}]) {
    assert.match(render(candidate),/class="pi-header-stop" disabled=""/);
  }
  const offline=render(running,{networkError:true});
  assert.match(summary(offline),/Pi · 狀態未知/);
  assert.doesNotMatch(offline,/class="pi-header-stop"/);
});
test('handoff is visible, opens the manager and never automatically confirms work',()=>{
  const html=render({...idle,execution:{jobs:[{...job,state:'awaiting_confirmation',owner:'program:current'}]}});
  assert.match(summary(html),/待確認/);
  assert.match(summary(html),/class="pi-device-count"[^>]+>1</);
  assert.match(html,/<details[^>]+open=""/);
  assert.match(html,/確認停止目前程式，接著執行/);
  assert.match(html,/取消排隊/);
});
test('errors and status labels remain localized without extra top-row error text',()=>{
  assert.match(summary(render(idle,{error:'stop_owner_changed'})),/操作失敗/);
  assert.match(render(idle,{error:'stop_owner_changed'}),/執行中的作品已變更，請重新確認停止/);
  english=true;
  try {
    assert.match(summary(render(null)),/Pi · Disconnected/);
    assert.match(summary(render(running)),/Pi · Running/);
  } finally {english=false;}
});
test('menu supports accessible disclosure and dismissing UI only with listener cleanup',()=>{
  const html=render(idle);
  assert.match(summary(html),/aria-expanded="false"[^>]*aria-controls="[^"]+"[^>]*aria-haspopup="dialog"/);
  assert.match(html,/role="dialog" aria-label="Pi 連線與執行管理"/);
  const source=read('../src/components/PiConnectionControl.tsx');
  for(const type of ['pointerdown','focusin','keydown']) {
    assert.ok(source.includes(`document.addEventListener("${type}"`));
    assert.ok(source.includes(`document.removeEventListener("${type}"`));
  }
  assert.match(source,/event.key !== "Escape"/);
  assert.match(source,/querySelector\("summary"\)\?\.focus/);
});
test('Pi wrapper loses duplicate label and border, while narrow controls stay tappable',()=>{
  const css=read('../src/deviceConnections.css');
  assert.match(css,/\.maker-device-group\.is-pi\s*\{\s*padding:0; border:0; background:transparent/);
  assert.match(css,/\.maker-device-group\.is-pi>\.maker-device-label \{ display:none;/);
  assert.match(css,/@media\(max-width:960px\)[^]*?\.pi-device-control \.pi-header-stop \{ height:44px; min-height:44px;/);
  assert.match(css,/\.pi-device-menu>\.pi-device-trigger::-webkit-details-marker \{ display:none;/);
});
