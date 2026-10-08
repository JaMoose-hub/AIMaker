import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

function fixture() {
  let state=false, previous, effect, cleanup, now=0, serial=0;
  const timers=new Map(), exports={};
  const react={useState:()=>[state,value=>{state=value;}],useEffect(callback,deps){
    if(previous===undefined || deps[0]!==previous){previous=deps[0];effect=callback;}
  }};
  const code=ts.transpileModule(readFileSync(new URL('../src/lib/useStreamWaitingNotice.ts',import.meta.url),'utf8'),
    {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
  new Function('require','exports','setTimeout','clearTimeout',code)(name=>{
    assert.equal(name,'react');return react;
  },exports,(callback,delay)=>{const id=++serial;timers.set(id,{callback,at:now+delay});return id;},id=>timers.delete(id));
  return {
    render(waiting){const result=exports.useStreamWaitingNotice(waiting);if(effect){cleanup?.();cleanup=effect();effect=null;}return result;},
    tick(ms){now+=ms;for(const[id,timer]of timers){if(timer.at<=now){timers.delete(id);timer.callback();}}},
    dispose(){cleanup?.();},get timerCount(){return timers.size;},
  };
}

test('brief frame gaps never show the waiting message and do not change media freshness',()=>{
  const f=fixture();assert.equal(f.render(true),false);f.tick(399);assert.equal(f.render(true),false);
  assert.equal(f.render(false),false);f.tick(1000);assert.equal(f.render(false),false);assert.equal(f.timerCount,0);
});
test('a sustained gap shows the notice after 400 ms and recovery hides it immediately',()=>{
  const f=fixture();assert.equal(f.render(true),false);f.tick(400);assert.equal(f.render(true),true);
  assert.equal(f.render(false),false);assert.equal(f.render(true),false);f.tick(399);assert.equal(f.render(true),false);f.dispose();
});
test('source teardown cancels the pending notice instead of reviving the old source',()=>{
  const f=fixture();f.render(true);assert.equal(f.timerCount,1);f.dispose();assert.equal(f.timerCount,0);
  f.tick(1000);assert.equal(f.render(true),false);
});
