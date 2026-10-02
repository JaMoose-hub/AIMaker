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
  let now=0,id=0;const tasks=new Map(),values=[];
  const clock={now:()=>now,later:fn=>{tasks.set(++id,{at:now+100,fn});return id;},clear:id=>tasks.delete(id)};
  const timer=library.createCaptureCountdown(value=>values.push(value),clock);
  const advance=ms=>{const end=now+ms;for(;;){const next=[...tasks].sort((a,b)=>a[1].at-b[1].at)[0];if(!next||next[1].at>end)break;tasks.delete(next[0]);now=next[1].at;next[1].fn();}now=end;};
  return{timer,advance,values,tasks};
}
test('capture waits ten complete seconds and submits exactly once with no early API work',async()=>{
  const f=fixture();let calls=0;const p=f.timer.run(()=>++calls,()=>true);
  assert.deepEqual(f.values,[10]);f.advance(9999);await Promise.resolve();assert.equal(calls,0);
  f.advance(1);assert.equal(await p,1);assert.equal(calls,1);
  assert.deepEqual(f.values,[10,9,8,7,6,5,4,3,2,1,null]);
});
test('double clicks do not shorten the countdown or create duplicate requests',async()=>{
  const f=fixture();let calls=0;const p=f.timer.run(()=>++calls,()=>true);
  f.advance(5000);assert.equal(await f.timer.run(()=>++calls,()=>true),undefined);
  f.advance(4999);assert.equal(calls,0);f.advance(1);await p;assert.equal(calls,1);
});
test('cancel clears the timer, submits nothing and permits a fresh ten-second attempt',async()=>{
  const f=fixture();let calls=0;const p=f.timer.run(()=>++calls,()=>true);
  f.advance(8000);f.timer.cancel();assert.equal(await p,undefined);f.advance(30000);assert.equal(calls,0);assert.equal(f.tasks.size,0);
  const retry=f.timer.run(()=>++calls,()=>true);f.advance(10000);assert.equal(await retry,1);
});
test('a hidden/unmounted/changed context or lost camera invalidates the delayed capture',async()=>{
  for(const reason of ['hidden','unmounted','new wire','new project','new camera','new session','camera offline']){
    const f=fixture();let valid=true,calls=0;const p=f.timer.run(()=>++calls,()=>valid);
    f.advance(9000);valid=false;f.advance(1000);assert.equal(await p,undefined,reason);assert.equal(calls,0,reason);
  }
});
test('countdown cancellation never claims to undo an already submitted request',async()=>{
  const f=fixture();let finish,calls=0;const p=f.timer.run(()=>{calls++;return new Promise(resolve=>finish=resolve);},()=>true);
  f.advance(10000);await Promise.resolve();f.timer.cancel();
  assert.equal(await f.timer.run(()=>++calls,()=>true),undefined);finish('captured');assert.equal(await p,'captured');assert.equal(calls,1);
});
test('photo failures propagate and release the single-flight lock for retry',async()=>{
  const f=fixture();const p=f.timer.run(()=>{throw Error('capture failed');},()=>true);
  f.advance(10000);await assert.rejects(p,/capture failed/);await Promise.resolve();
  const retry=f.timer.run(()=>42,()=>true);f.advance(10000);assert.equal(await retry,42);
});
test('countdown has localized accessible status and a cancel button in both languages',()=>{
  for(const locale of ['en','zh-TW']){
    const strings=JSON.parse(read(`../src/locales/${locale}.json`));const module={};
    new Function('require','exports',compile(read('../src/components/CaptureCountdown.tsx')))(name=>name==='react/jsx-runtime'?{jsx:React.createElement.bind(null),jsxs:React.createElement.bind(null)}:name.endsWith('/i18n')?{useI18n:()=>({t:(key,args)=>strings[key].replace('{seconds}',args?.seconds)})}:{},module);
    const html=renderToStaticMarkup(React.createElement(module.CaptureCountdown,{remaining:10,onCancel(){}}));
    assert.match(html,/role="status" aria-live="polite" aria-atomic="true"/);
    assert.ok(html.includes(locale==='en'?'Photo in 10 seconds':'10 秒後拍攝'));
    assert.ok(html.includes(locale==='en'?'Cancel photo':'取消拍攝'));
  }
});
test('all user photo entry points use the shared countdown, while text and result reads stay immediate',()=>{
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
});
