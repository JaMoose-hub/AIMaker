import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const library={};new Function('exports',compile(read('../src/lib/captureCountdown.ts')))(library);
function fixture(){
  const values=[];
  return{timer:library.createCaptureCountdown(value=>values.push(value)),values};
}
test('capture submits immediately with no countdown or scheduled timer',async()=>{
  const f=fixture();let calls=0;const p=f.timer.run(()=>++calls,()=>true);
  assert.equal(calls,1);assert.equal(await p,1);assert.deepEqual(f.values,[null]);
  assert.equal(library.CAPTURE_DELAY_MS,0);assert.doesNotMatch(read('../src/lib/captureCountdown.ts'),/setTimeout|clock\.later/);
});
test('double clicks cannot duplicate an in-flight immediate capture',async()=>{
  const f=fixture();let calls=0,finish;const p=f.timer.run(()=>{calls++;return new Promise(resolve=>finish=resolve);},()=>true);
  assert.equal(calls,1);assert.equal(await f.timer.run(()=>++calls,()=>true),undefined);
  finish('captured');assert.equal(await p,'captured');assert.equal(calls,1);
});
test('a settled capture permits a fresh immediate attempt',async()=>{
  const f=fixture();let calls=0;assert.equal(await f.timer.run(()=>++calls,()=>true),1);
  f.timer.cancel();const retry=f.timer.run(()=>++calls,()=>true);assert.equal(calls,2);assert.equal(await retry,2);
});
test('a hidden unmounted changed context or lost camera prevents dispatch',async()=>{
  for(const reason of ['hidden','unmounted','new wire','new project','new camera','new session','camera offline']){
    const f=fixture();let calls=0;assert.equal(await f.timer.run(()=>++calls,()=>false),undefined,reason);
    assert.equal(calls,0,reason);assert.deepEqual(f.values,[]);
  }
});
test('cancel never claims to undo an already submitted immediate request',async()=>{
  const f=fixture();let finish,calls=0;const p=f.timer.run(()=>{calls++;return new Promise(resolve=>finish=resolve);},()=>true);
  f.timer.cancel();
  assert.equal(await f.timer.run(()=>++calls,()=>true),undefined);finish('captured');assert.equal(await p,'captured');assert.equal(calls,1);
});
test('photo failures propagate and release the single-flight lock for retry',async()=>{
  const f=fixture();const p=f.timer.run(()=>{throw Error('capture failed');},()=>true);
  await assert.rejects(p,/capture failed/);
  const retry=f.timer.run(()=>42,()=>true);assert.equal(await retry,42);
});
test('immediate capture never renders the former countdown panel in either language',()=>{
  for(const locale of ['en','zh-TW']){
    const strings=JSON.parse(read(`../src/locales/${locale}.json`));const module={};
    new Function('require','exports',compile(read('../src/components/CaptureCountdown.tsx')))(name=>name==='react/jsx-runtime'?{jsx:React.createElement.bind(null),jsxs:React.createElement.bind(null)}:name.endsWith('/i18n')?{useI18n:()=>({t:(key,args)=>strings[key].replace('{seconds}',args?.seconds)})}:{},module);
    const html=renderToStaticMarkup(React.createElement(module.CaptureCountdown,{remaining:null,onCancel(){}}));
    assert.equal(html,'');
  }
});
test('photo entry points keep shared readiness guards and omit countdown labels',()=>{
  const panel=read('../src/components/AiDebugPanel.tsx');
  assert.match(panel,/wiringMode \? create\(\) : countdown.run\(create\)/);
  assert.match(panel,/countdown.run\(\(\) => session.action\("start_debug"/);
  assert.match(panel,/takesPhoto \? countdown.run\(action\)/);
  assert.match(panel,/async function captureStep\(\)[\s\S]*?await countdown.run\(async/);
  assert.match(read('../src/components/CalibratePanel.tsx'),/countdown.run\(handleCapture\)/);
  assert.match(read('../src/components/CloudWiringDetails.tsx'),/if \(readAgain\) onCheck\(\); else void countdown.run\(onCheck\)/);
  const hook=read('../src/lib/useCaptureCountdown.ts');
  assert.match(hook,/latest.current.scope === scope/);assert.match(hook,/getClientRects/);assert.match(hook,/closest\("\[hidden\]"\)/);
  assert.match(hook,/document.removeEventListener\("visibilitychange"/);
  assert.doesNotMatch(panel,/10 秒倒數|10-second countdown|<small>10s/);
  assert.doesNotMatch(read('../src/components/WiringPhotoSequence.tsx'),/10 秒倒數|10-second countdown/);
});
