import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compileHeaderFile, dataUrl } from './component_header_fixture.mjs';
import { componentTests as logic, designFor, maker, renderTestCard } from './project_guide_fixture.mjs';

function fixture(overrides={}) {
  const design=designFor();
  let session=maker.startProjectGuide(maker.emptyGuide());
  while(session.phase==='active') session=maker.confirmProjectWire(design,session);
  const run={id:'distance-fixture',project_id:design.id,revision:design.revision,component_id:'hc-sr04',
    guide_key:logic.componentTestKey(design,session,'hc-sr04'),template_version:'fixture',wiring_hash:'fixture',
    created_at:1,outcome:'running',phase:'sampling_near',reason:null,detail:'',logs:[],samples:{},
    latest:null,heartbeat_at:1,exit_code:null,reserved:true,program_stopped:false,invalidated:false,options:[],...overrides};
  return {design,session,run,tests:{status:{connected:true,test_busy:run.reserved,active:run.reserved?run:null,results:[run]},error:null}};
}
const visible=html=>html.split('<details class="test-diagnostics">')[0];

test('live ultrasonic readings expire after two seconds and reject invalid/future values',()=>{
  const {run}=fixture({latest:{cm:15.2,at:100}}),before=structuredClone(run);
  assert.equal(logic.ultrasonicTestReadings(run,{now:101.99}).liveCm,15.2);
  assert.equal(logic.ultrasonicTestReadings(run,{now:101.99}).expiresAt,102);
  for(const now of [99.99,102,500,NaN]) assert.equal(logic.ultrasonicTestReadings(run,{now}).liveCm,null);
  for(const cm of [0,-1,400,Infinity,NaN,'15.2']) assert.equal(logic.ultrasonicTestReadings({...run,latest:{cm,at:100}},{now:101}).liveCm,null);
  assert.deepEqual(run,before);
});

test('only healthy active sampling can present a distance as live',()=>{
  const {run}=fixture({latest:{cm:15.2,at:100}});
  for(const change of [{reserved:false},{phase:'awaiting_far'},{outcome:'passed'},{reason:'connection_lost'},{reason:'no_echo'},{invalidated:true}]) {
    assert.equal(logic.ultrasonicTestReadings({...run,...change},{now:101}).sampling,false);
    assert.equal(logic.ultrasonicTestReadings({...run,...change},{now:101}).liveCm,null);
  }
  for(const options of [{now:101,stale:true},{now:101,error:'connection_lost'}]) assert.equal(logic.ultrasonicTestReadings(run,options).liveCm,null);
  assert.equal(logic.ultrasonicTestReadings({...run,component_id:'mrd-tf240-8p-cs'},{now:101}),null);
});

test('compact dock and instruction cards show real sampling values beside their live label',async()=>{
  const f=fixture({latest:{cm:15.2,at:Date.now()/1000}}),before=structuredClone(f.tests);
  for(const view of ['dock','instructions','all']) {
    const html=visible(await renderTestCard({...f,view}));
    assert.match(html,/即時距離/);
    assert.match(html,/class="test-reading">15.2 <small>cm/);
  }
  const controls=await renderTestCard({...f,view:'actions'});
  assert.doesNotMatch(controls,/test-distance-summary/);
  assert.deepEqual(f.tests,before);
});

test('sampling with missing or expired echoes shows a readable waiting state without a fabricated zero',async()=>{
  for(const latest of [null,{cm:15.2,at:1},{cm:0,at:Date.now()/1000}]) {
    const html=visible(await renderTestCard({...fixture({latest}),view:'dock'}));
    assert.match(html,/即時距離/);
    assert.match(html,/等待有效回波/);
    assert.doesNotMatch(html,/class="test-reading"|0.0 <small>cm/);
  }
});

test('completed near and far medians stay visible with historical provenance and no live label',async()=>{
  const f=fixture({reserved:false,outcome:'passed',phase:'finished',finished_at:2,
    latest:{cm:99,at:Date.now()/1000},samples:{near:{count:76,median_cm:15.2},far:{count:57,median_cm:30.4}}});
  for(const view of ['dock','instructions','results']) {
    const html=visible(await renderTestCard({...f,view}));
    assert.match(html,/先前保存，非目前接線證據/);
    assert.match(html,/近距離[\s\S]*15.2 <small>cm[\s\S]*76 筆有效回波/);
    assert.match(html,/遠距離[\s\S]*30.4 <small>cm[\s\S]*57 筆有效回波/);
    assert.doesNotMatch(html,/即時距離|99.0|class="test-reading"/);
  }
});

test('no echo preserves zero-count evidence and never treats a stored value as a measurement',async()=>{
  for(const samples of [{},{near:{count:0,median_cm:null},far:{count:0,median_cm:25}}]) {
    const html=visible(await renderTestCard({...fixture({reserved:false,outcome:'inconclusive',phase:'finished',finished_at:2,
      reason:'no_echo',latest:{cm:99,at:Date.now()/1000},samples}),view:'dock'}));
    assert.match(html,/無法判定/);
    assert.match(html,/有效回波不足|無有效距離/);
    assert.doesNotMatch(html,/即時距離|class="test-reading"|25.0 <small>cm|99.0/);
  }
});

test('changed wiring, foreign tests and status errors cannot display a current distance',async()=>{
  for(const overrides of [{invalidated:true},{guide_key:'old-wiring'},{revision:0},{project_id:'another-project'}]) {
    const f=fixture({latest:{cm:88.8,at:Date.now()/1000},samples:{near:{count:8,median_cm:15.2}},...overrides});
    const html=visible(await renderTestCard({...f,view:'dock'}));
    assert.doesNotMatch(html,/test-distance-summary|class="test-reading"|88.8|15.2/);
  }
  const f=fixture({latest:{cm:88.8,at:Date.now()/1000}});
  f.tests.error='connection_lost';
  assert.doesNotMatch(visible(await renderTestCard({...f,view:'dock'})),/即時距離|class="test-reading"|88.8/);
  f.tests.error=null;f.tests.status.connected=false;
  assert.doesNotMatch(visible(await renderTestCard({...f,view:'dock'})),/即時距離|class="test-reading"|88.8/);
});

test('a mounted distance expires even without another status response and cancels its timer on cleanup',async()=>{
  const previous={now:Date.now,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
  let now=100000,cursor=0,states=[],effects=[],timers=new Map(),timerId=0;
  const harness={
    useState(initial){const index=cursor++;if(!(index in states))states[index]=typeof initial==='function'?initial():initial;
      return [states[index],value=>{states[index]=typeof value==='function'?value(states[index]):value;}];},
    useRef(initial){return {current:initial};},useEffect(callback){effects.push(callback);},
  };
  globalThis.__ultrasonicDistanceHooks=harness;
  Date.now=()=>now;
  globalThis.setTimeout=(callback,delay)=>{timers.set(++timerId,{callback,delay});return timerId;};
  globalThis.clearTimeout=id=>timers.delete(id);
  try {
    // maker imports catalog JSON; the existing render fixture already supplies its helpers.
    // The card only calls ultrasonicTestReadings and the test key from this module.
    const testsUrl=compileHeaderFile('lib/componentTests.ts',{'./maker':dataUrl(`export const makerRequest=()=>{};
      export const resumeProjectGuide=x=>x;export const wireSignature=${maker.wireSignature.toString()};`)});
    const hooksUrl=dataUrl(`export const useState=(...a)=>globalThis.__ultrasonicDistanceHooks.useState(...a);
      export const useRef=(...a)=>globalThis.__ultrasonicDistanceHooks.useRef(...a);
      export const useEffect=(...a)=>globalThis.__ultrasonicDistanceHooks.useEffect(...a);`);
    const cardUrl=compileHeaderFile('components/ComponentTestCard.tsx',{'react':hooksUrl,
      '../lib/componentTests':testsUrl,'../lib/useMaker':dataUrl(`export const useMakerText=()=>((zh,en)=>zh);`),
      './ComponentTestCard.css':dataUrl('')});
    const {ComponentTestCard}=await import(cardUrl);
    const f=fixture({latest:{cm:15.2,at:100}});
    const render=()=>{cursor=0;effects=[];return renderToStaticMarkup(createElement(ComponentTestCard,{...f,view:'dock',onViewWiring(){}}));};
    assert.match(visible(render()),/class="test-reading">15.2/);
    const cleanups=effects.map(effect=>effect()).filter(Boolean);
    assert.equal(timers.size,1);
    const timer=[...timers.values()][0];
    assert.equal(timer.delay,2000);
    now=102001;timer.callback();
    assert.match(visible(render()),/等待有效回波/);
    assert.doesNotMatch(visible(render()),/class="test-reading"/);
    for(const cleanup of cleanups)cleanup();
    assert.equal(timers.size,0);
  } finally {
    Date.now=previous.now;globalThis.setTimeout=previous.setTimeout;globalThis.clearTimeout=previous.clearTimeout;
    delete globalThis.__ultrasonicDistanceHooks;
  }
});
