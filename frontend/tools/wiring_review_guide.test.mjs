import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {maker,designFor,componentTests} from './project_guide_fixture.mjs';

const source=readFileSync(new URL('../src/lib/wiringReviewGuide.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const helpers={};
new Function('require','exports',js)(name=>{
  if(name==='./maker')return maker;
  if(name==='./componentTests')return componentTests;
  throw Error(name);
},helpers);
const {confirmReviewedWire,unconfirmReviewedWire,invalidateReviewedComponent,contextWithReviewGuide}=helpers;
const design={...designFor(['hc-sr04','mrd-tf240-8p-cs']),profile_versions:{
  'hc-sr04':{version:'hc-test',sha256:'a'.repeat(64)},'mrd-tf240-8p-cs':{version:'tft-test',sha256:'b'.repeat(64)},
}};
const hc=design.wiring.find(w=>w.componentId==='hc-sr04');
const tft=design.wiring.find(w=>w.componentId==='mrd-tf240-8p-cs');
const confirmation=wire=>({signature:maker.wireSignature(wire),mode:'2d',at:'2026-10-04T00:00:00.000Z'});
function guide(extra={}) {
  return {...maker.emptyGuide(),componentIndex:1,index:2,phase:'review',run:7,checks:['visible'],
    inspection:true,inspectionSource:'debug',inspectionReturn:{componentIndex:0,index:1,phase:'active',mode:'camera'},...extra};
}
function context(state) {
  return {project:design,code:'print("same code")',entry:{symptom:'no_echo'},locale:'zh-TW',
    wiring_target:{component_id:hc.componentId,wire_id:hc.id},guide_confirmations:state.confirmed,guide_run:state.run,
    test_keys:Object.fromEntries(design.component_ids.map(id=>[id,componentTests.componentTestKey(design,state,id)]))};
}

test('explicit review confirms the requested wire during inspection without navigating or changing another confirmation',()=>{
  const before=guide({confirmed:{[tft.id]:confirmation(tft)}}),snapshot=structuredClone(before);
  assert.strictEqual(maker.confirmProjectWire(design,before),before,'ordinary browsing still cannot confirm');
  const next=confirmReviewedWire(design,before,hc.id);
  assert.deepEqual({...next,confirmed:before.confirmed},before);
  assert.equal(next.confirmed[hc.id].signature,maker.wireSignature(hc));
  assert.equal(next.confirmed[hc.id].mode,before.mode);
  assert.ok(Number.isFinite(Date.parse(next.confirmed[hc.id].at)));
  assert.strictEqual(next.confirmed[tft.id],before.confirmed[tft.id]);
  assert.deepEqual(before,snapshot);
});

test('repeated explicit confirmation preserves the existing timestamp and original mode',()=>{
  const before=guide({mode:'camera',confirmed:{[hc.id]:confirmation(hc)}});
  const originalKey=componentTests.componentTestKey(design,before,hc.componentId);
  const next=confirmReviewedWire(design,before,hc.id);
  assert.strictEqual(next,before);
  assert.equal(next.confirmed[hc.id].mode,'2d');
  assert.equal(componentTests.componentTestKey(design,next,hc.componentId),originalKey);
});

test('a stale signature or invalid timestamp does not count as an existing valid confirmation',()=>{
  for(const bad of [{...confirmation(hc),signature:'wrong'},{...confirmation(hc),at:'invalid'}, {...confirmation(hc),mode:'ai'}]) {
    const before=guide({confirmed:{[hc.id]:bad}}),next=confirmReviewedWire(design,before,hc.id);
    assert.notStrictEqual(next,before);
    assert.equal(next.confirmed[hc.id].signature,maker.wireSignature(hc));
    assert.ok(Number.isFinite(Date.parse(next.confirmed[hc.id].at)));
    assert.equal(next.confirmed[hc.id].mode,before.mode);
  }
});

test('unknown and ambiguous wire identities fail without mutating the guide',()=>{
  const before=guide(),snapshot=structuredClone(before);
  for(const id of ['', 'another-project-wire',hc.componentPin]) {
    assert.throws(()=>confirmReviewedWire(design,before,id),/wiring_review_wire_not_found/);
  }
  assert.throws(()=>confirmReviewedWire({...design,wiring:[...design.wiring,hc]},before,hc.id),/wiring_review_wire_not_found/);
  assert.deepEqual(before,snapshot);
});

test('targeted invalidation clears all affected confirmations and checks, preserving other component bindings and navigation',()=>{
  const before=guide({confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,confirmation(w)]))}),snapshot=structuredClone(before);
  const oldHcKey=componentTests.componentTestKey(design,before,hc.componentId);
  const oldTftKey=componentTests.componentTestKey(design,before,tft.componentId);
  const next=invalidateReviewedComponent(design,before,hc.componentId);
  assert.ok(design.wiring.filter(w=>w.componentId===hc.componentId).every(w=>!(w.id in next.confirmed)));
  assert.deepEqual(next.checks,[]);
  assert.deepEqual({...next,checks:before.checks,confirmed:before.confirmed},before);
  assert.strictEqual(next.confirmed[tft.id],before.confirmed[tft.id]);
  assert.notEqual(componentTests.componentTestKey(design,next,hc.componentId),oldHcKey);
  assert.equal(componentTests.componentTestKey(design,next,tft.componentId),oldTftKey);
  assert.deepEqual(before,snapshot);
});

test('whole-project invalidation clears confirmations; an unknown component cannot accidentally clear them',()=>{
  const before=guide({confirmed:{[hc.id]:confirmation(hc),[tft.id]:confirmation(tft)}});
  assert.throws(()=>invalidateReviewedComponent(design,before,'other-component'),/wiring_review_component_not_found/);
  const next=invalidateReviewedComponent(design,before);
  assert.deepEqual(next.confirmed,{});assert.deepEqual(next.checks,[]);assert.equal(next.run,before.run);
  assert.equal(Object.keys(before.confirmed).length,2);
});

test('explicit unsure or needs-change retracts only the targeted wire and its component test binding',()=>{
  const before=guide({confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,confirmation(w)]))}),snapshot=structuredClone(before);
  const old=context(before),next=unconfirmReviewedWire(design,before,hc.id),updated=contextWithReviewGuide(old,design,next);
  assert.ok(!(hc.id in next.confirmed));
  for(const wire of design.wiring.filter(w=>w.id!==hc.id))assert.strictEqual(next.confirmed[wire.id],before.confirmed[wire.id]);
  assert.deepEqual({...next,confirmed:before.confirmed},before,'cursor, checks, inspection and round are preserved');
  assert.notEqual(updated.test_keys[hc.componentId],old.test_keys[hc.componentId]);
  assert.equal(updated.test_keys[tft.componentId],old.test_keys[tft.componentId]);
  assert.strictEqual(unconfirmReviewedWire(design,next,hc.id),next,'repeated retraction is a no-op');
  assert.throws(()=>unconfirmReviewedWire(design,next,'unknown-wire'),/wiring_review_wire_not_found/);
  assert.throws(()=>unconfirmReviewedWire({...design,wiring:[...design.wiring,hc]},before,hc.id),/wiring_review_wire_not_found/);
  assert.deepEqual(before,snapshot);
});

test('new guide confirmations, round and every component test key enter the context atomically',()=>{
  const before=guide(),old=context(before),snapshot=structuredClone(old);
  const next=confirmReviewedWire(design,before,hc.id);
  const result=contextWithReviewGuide(old,design,next);
  assert.strictEqual(result.guide_confirmations,next.confirmed);
  assert.equal(result.guide_run,next.run);
  for(const id of design.component_ids)assert.equal(result.test_keys[id],componentTests.componentTestKey(design,next,id));
  assert.notEqual(result.test_keys[hc.componentId],old.test_keys[hc.componentId]);
  assert.equal(result.test_keys[tft.componentId],old.test_keys[tft.componentId]);
  assert.deepEqual({...result,guide_confirmations:old.guide_confirmations,test_keys:old.test_keys},old);
  assert.deepEqual(old,snapshot);
});

test('a missing guide round becomes zero and context rebinding rejects different projects, revisions and wire plans',()=>{
  const before=guide({run:undefined}),original=context(before);
  assert.equal(contextWithReviewGuide(original,design,before).guide_run,0);
  for(const project of [null,{...design,id:'other'},{...design,revision:2},
    {...design,wiring:design.wiring.map(w=>w.id===hc.id?{...w,boardPin:'changed'}:w)}]) {
    assert.throws(()=>contextWithReviewGuide({...original,project},design,before),/wiring_review_project_changed/);
  }
});
