import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import ts from 'typescript';

function harness({onReset=async()=>true,busy=false,error='',locale='zh-TW'}={}) {
  const values=[],refs=[];let cursor=0,refCursor=0,open=false;
  const react={...React,useEffect(){},useId:()=> 'reset-fixture',
    useRef(value){const i=refCursor++;return refs[i]??= {current:value};},
    useState(initial){const i=cursor++;if(!(i in values))values[i]=initial;return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next;}];}};
  const output=ts.transpileModule(readFileSync(new URL('../src/components/WorkflowResetControl.tsx',import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('React','require','exports',output)(React,id=>{
    if(id==='react')return react;
    if(id==='../lib/headerPanels')return {useHeaderPanel:()=>[open,next=>{open=next;}]};
    if(id==='../lib/useMaker')return {useMakerText:()=> (zh,en)=>locale==='en'?en:zh};
    if(id.endsWith('.css'))return {};
    throw Error('unexpected import '+id);
  },exports);
  const props={onReset,busy,error};
  const render=()=>{cursor=refCursor=0;return exports.WorkflowResetControl(props);};
  const nodes=tree=>React.isValidElement(tree)?[tree,...React.Children.toArray(tree.props.children).flatMap(nodes)]:[];
  const find=predicate=>nodes(render()).find(predicate);
  const text=node=>React.isValidElement(node)?React.Children.toArray(node.props.children).map(text).join(''):String(node??'');
  return{render,props,open:()=>open,trigger:()=>find(n=>n.props.className==='workflow-reset-trigger'),button:name=>find(n=>n.type==='button'&&(n.props['aria-label']??text(n))===name),dialog:()=>find(n=>n.type==='dialog'),find,text};
}

test('Reset is a single header action; opening and cancelling do not mutate work',()=>{
  let calls=0;const h=harness({onReset:async()=>{calls++;return true;}});
  h.trigger().props.onClick();assert.equal(h.open(),true);assert.equal(calls,0);
  assert.match(h.text(h.dialog()),/01「設計與藍圖」/);
  assert.match(h.text(h.dialog()),/不會停止 Pi/);
  assert.match(h.text(h.dialog()),/照片和對話歷史/);
  h.button('取消').props.onClick();assert.equal(h.open(),false);assert.equal(calls,0);
});

test('Escape cancels before confirmation, while native modal supplies focus containment',()=>{
  const h=harness();h.trigger().props.onClick();let prevented=false;
  h.dialog().props.onCancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(h.open(),false);
  const source=readFileSync(new URL('../src/components/WorkflowResetControl.tsx',import.meta.url),'utf8');
  assert.match(source,/element\.showModal\(\); cancel\.current\?\.focus\(\)/);
  assert.match(source,/element\.close\(\); trigger\.current\?\.focus/);
});

test('confirmed Reset is single-flight, cannot cancel mid-commit, and closes only on success',async()=>{
  let finish,calls=0;const h=harness({onReset:()=>{calls++;return new Promise(resolve=>{finish=resolve;});}});
  h.trigger().props.onClick();const confirm=h.button('備份並重新開始');
  confirm.props.onClick();confirm.props.onClick();assert.equal(calls,1);
  assert.equal(h.button('取消').props.disabled,true);assert.equal(h.button('正在備份與重置…').props.disabled,true);
  h.dialog().props.onCancel({preventDefault(){}});assert.equal(h.open(),true);
  finish(true);await new Promise(resolve=>setImmediate(resolve));assert.equal(h.open(),false);
});

test('failed or throwing Reset retains confirmation, exposes the reason and allows retry',async()=>{
  for(const throwing of [false,true]) {
    let calls=0;const h=harness({error:'Pi 還在執行，已保留作品',onReset:async()=>{calls++;if(throwing)throw Error('network');return false;}});
    h.trigger().props.onClick();h.button('備份並重新開始').props.onClick();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(h.open(),true);assert.equal(h.text(h.find(n=>n.props.role==='alert')),'Pi 還在執行，已保留作品');
    h.props.onReset=async()=>{calls++;return true;};h.button('備份並重新開始').props.onClick();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls,2);assert.equal(h.open(),false);
  }
});

test('busy work disables Reset before opening or confirming and hides stale failure messages',()=>{
  const h=harness({busy:true,error:'old error'});assert.equal(h.trigger().props.disabled,true);
  h.trigger().props.onClick();assert.equal(h.open(),false);
  h.props.busy=false;h.trigger().props.onClick();h.props.busy=true;
  assert.equal(h.button('備份並重新開始').props.disabled,true);assert.equal(h.find(n=>n.props.role==='alert'),undefined);
});

test('the English confirmation has the same scope and compact responsive theme tokens',()=>{
  const h=harness({locale:'en'});assert.match(h.text(h.dialog()),/Back up your current project/);assert.ok(h.button('Back up & restart'));
  const css=readFileSync(new URL('../src/components/workflowReset.css',import.meta.url),'utf8');
  assert.match(css,/var\(--surface-card\)/);assert.match(css,/::backdrop/);assert.match(css,/max-height: calc\(100dvh - 32px\)/);
});

test('Reset is icon-only with a localized accessible name and the same footprint as header shortcuts',()=>{
  for(const [locale,name] of [['zh-TW','重新開始工作流程'],['en','Restart workflow']]) {
    const h=harness({locale}),button=h.trigger();assert.equal(h.text(button),'');
    assert.equal(button.props['aria-label'],name);assert.equal(button.props['aria-haspopup'],'dialog');
    assert.ok(button.props.title);const svg=React.Children.only(button.props.children);
    assert.equal(svg.type,'svg');assert.equal(svg.props['aria-hidden'],'true');assert.equal(svg.props.focusable,'false');
  }
  const css=readFileSync(new URL('../src/components/workflowReset.css',import.meta.url),'utf8');
  assert.match(css,/width: 32px; height: 32px/);assert.match(css,/width: 44px; height: 44px/);
  assert.match(css,/prefers-reduced-motion: reduce/);
});
