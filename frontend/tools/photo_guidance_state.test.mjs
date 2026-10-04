import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {maker,designFor,componentTests} from './project_guide_fixture.mjs';

function load(path,imports={}) {
  const js=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',js)(name=>{if(name in imports)return imports[name];throw Error(name);},exports,React);return exports;
}
const photo=load('../src/lib/photoWiring.ts');
const workspace=load('../src/lib/gpioPhotoWorkspace.ts',{'./photoWiring':photo,'./maker':maker});
const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
const hc=design.wiring.find(w=>w.componentId==='hc-sr04'&&w.componentPin==='VCC');
const tft=design.wiring.find(w=>w.componentId==='mrd-tf240-8p-cs'&&w.componentPin==='VCC');
function fixture() {
  const outline=[[1,1],[50,1],[50,50],[1,50]];
  const pose=extra=>({tracking:'locked',outline,pins:[],...extra});
  return {capture_id:'fixture',video_size:[1920,1080],image_url:'/fixture',captured_at:1,
    detection:pose({board_id:'raspberry-pi-5',pins:[{id:hc.boardPin,x:10,y:10,v:true},{id:tft.boardPin,x:10,y:20,v:true}]}),
    components:[pose({component_id:hc.componentId,pins:[{id:'VCC',x:80,y:20,v:true}]}),
      pose({component_id:tft.componentId,tracking:'searching',outline:null})],
    localization:['raspberry-pi-5',hc.componentId,tft.componentId].map(object_id=>({object_id,
      status:object_id===tft.componentId?'uncertain':'located',reason:object_id===tft.componentId?'invalid_model_geometry':'verified',
      evidence:{board_geometry_verified:object_id!==tft.componentId,pin_geometry_verified:object_id!==tft.componentId},
      raw_outline_px:object_id===tft.componentId?null:outline,corrected_outline_px:object_id===tft.componentId?null:outline})),
    wires:photo.photoPlanForProject(design).wires};
}
function locatedFixture() {
  const capture=fixture();
  capture.detection.pins=design.wiring.map((wire,index)=>({id:wire.boardPin,x:10,y:10+index*4,v:true}));
  capture.components=design.component_ids.map((component_id,index)=>({tracking:'locked',component_id,
    outline:capture.detection.outline,
    pins:design.wiring.filter(w=>w.componentId===component_id).map((wire,pin)=>({id:wire.componentPin,x:80+index*40,y:20+pin*4,v:true}))}));
  capture.localization=capture.localization.map(item=>({...item,status:'located',reason:'verified',
    evidence:{board_geometry_verified:true,pin_geometry_verified:true},
    raw_outline_px:capture.detection.outline,corrected_outline_px:capture.detection.outline}));
  return capture;
}
const {photoGuidanceState,photoGuidanceTarget,photoRecordMismatch,photoRecordCurrent}=workspace;
test('locked HC does not substitute for the selected unlocated TFT endpoint',()=>{
  const p=fixture(),before=structuredClone(p);
  const s=photoGuidanceState(p,tft,false);
  assert.equal(s.kind,'missing-endpoints');assert.deepEqual(s.missing,[tft.componentId]);
  assert.equal(s.wire.component_id,tft.componentId);assert.equal(s.wire.board_pin,tft.boardPin);
  assert.equal(photoGuidanceState(p,hc,false).kind,'ready');assert.deepEqual(p,before);
});
test('historical and invalidated photos suppress wire overlays even with both endpoints located',()=>{
  for(const [p,historical] of [[fixture(),true],[{...fixture(),stale:true},false]]) {
    const s=photoGuidanceState(p,hc,historical);assert.equal(s.kind,'historical');assert.equal(s.wire,undefined);assert.equal(s.referenceOnly,false);
  }
});
test('photo target waits for Start wiring through module choice, confirmation and a global restart',()=>{
  const capture=locatedFixture(),before=structuredClone(capture);
  const original={...maker.emptyGuide(),run:4};
  const record={projectId:design.id,revision:design.revision,round:4,capture};
  let state=original;
  assert.equal(photoGuidanceTarget(design,state),undefined);
  assert.equal(photoGuidanceTarget(null,maker.startProjectGuide(state)),undefined);
  assert.equal(photoGuidanceState(capture,photoGuidanceTarget(design,state),false).kind,'no-target');
  state=maker.startProjectGuide(state);
  assert.equal(photoGuidanceTarget(design,state).id,design.wiring[0].id);
  assert.equal(photoGuidanceState(capture,photoGuidanceTarget(design,state),false).kind,'ready');
  state=maker.confirmProjectWire(design,state);
  assert.equal(photoGuidanceTarget(design,state).id,design.wiring[1].id);
  assert.equal(Object.keys(state.confirmed).length,1);
  state=maker.restartProjectGuide(state);
  assert.equal(state.phase,'prepare');assert.equal(state.run,5);assert.deepEqual(state.confirmed,{});
  assert.equal(photoGuidanceTarget(design,state),undefined);
  assert.equal(photoRecordCurrent(record,design,state.run),false);
  assert.equal(photoGuidanceState(capture,photoGuidanceTarget(design,state),true,'round').kind,'no-target');
  for(const [index,componentId] of design.component_ids.entries()) {
    const selected=componentTests.selectTestModule(design,state,index);
    assert.equal(selected.phase,'prepare');assert.equal(photoGuidanceTarget(design,selected),undefined);
    const started=maker.startProjectGuide(selected),target=photoGuidanceTarget(design,started);
    assert.equal(target.id,design.wiring.find(w=>w.componentId===componentId).id);
    const view=photoGuidanceState(capture,target,true,photoRecordMismatch(record,design,started.run));
    assert.equal(view.kind,'ready');assert.equal(view.wire.wire_id,target.id);assert.equal(view.referenceOnly,true);
    assert.equal(photoRecordCurrent(record,design,started.run),false,'drawing a reference never renews photo evidence');
    assert.deepEqual(started.confirmed,{});
  }
  assert.deepEqual(capture,before);assert.deepEqual(original,{...maker.emptyGuide(),run:4});assert.equal(record.round,4);
});
test('explicit active inspection selects an exact wire without changing confirmations or photo currency',()=>{
  const capture=locatedFixture(),state={...maker.emptyGuide(),phase:'review',run:3};
  assert.equal(photoGuidanceTarget(design,state),undefined);
  const inspected=maker.reviewProjectWire(design,state,tft.componentId,tft.componentPin);
  assert.equal(photoGuidanceTarget(design,inspected).id,tft.id);
  assert.equal(photoGuidanceState(capture,photoGuidanceTarget(design,inspected),false).referenceOnly,false);
  assert.strictEqual(inspected.confirmed,state.confirmed);assert.equal(inspected.run,state.run);
});
test('only a round mismatch allows an intended-wiring reference and never relaxes exact endpoints',()=>{
  const capture=locatedFixture();
  for(const historicalReason of [undefined,'project','revision','invalidated']) {
    const view=photoGuidanceState(capture,hc,true,historicalReason);
    assert.equal(view.kind,'historical');assert.equal(view.wire,undefined);assert.equal(view.referenceOnly,false);
  }
  const stale=photoGuidanceState({...capture,stale:true},hc,true,'round');
  assert.equal(stale.kind,'historical');assert.equal(stale.wire,undefined);assert.equal(stale.referenceOnly,false);
  const mismatch=photoGuidanceState(capture,{...hc,boardPin:'wrong'},true,'round');
  assert.equal(mismatch.kind,'plan-mismatch');assert.equal(mismatch.wire,undefined);
  const missing=locatedFixture();missing.components.find(p=>p.component_id===tft.componentId).pins=[];
  const view=photoGuidanceState(missing,tft,true,'round');
  assert.equal(view.kind,'missing-endpoints');assert.deepEqual(view.missing,[tft.componentId]);assert.equal(view.referenceOnly,true);
  assert.equal(view.wire.wire_id,tft.id,'an HC pin cannot stand in for the selected TFT endpoint');
});
test('no target, changed plan and divider wiring have distinct non-success states',()=>{
  assert.equal(photoGuidanceState(fixture(),undefined,false).kind,'no-target');
  assert.equal(photoGuidanceState(fixture(),{...hc,id:'other'},false).kind,'plan-mismatch');
  assert.equal(photoGuidanceState(fixture(),{...hc,connectionKind:'divider'},false).kind,'plan-mismatch');
  const p=fixture(),target={...hc,connectionKind:'divider'};p.wires.find(w=>w.wire_id===hc.id).connection_kind='divider';
  assert.equal(photoGuidanceState(p,target,false).kind,'divider');
});
test('a missing or invisible pin still blocks wiring even when the object is located',()=>{
  const p=fixture();p.components[0].pins[0].v=false;
  assert.deepEqual(photoGuidanceState(p,hc,false).missing,[hc.componentId]);
  p.detection.pins=[];assert.deepEqual(photoGuidanceState(p,hc,false).missing,['raspberry-pi-5',hc.componentId]);
});
test('history identifies project, revision, wiring round and invalidation separately',()=>{
  const r={projectId:design.id,revision:design.revision,round:2,capture:fixture()};
  assert.equal(photoRecordMismatch(r,design,2),null);
  assert.equal(photoRecordMismatch(r,null,2),'project');
  assert.equal(photoRecordMismatch(r,{...design,id:'other'},2),'project');
  assert.equal(photoRecordMismatch(r,{...design,revision:99},2),'revision');
  assert.equal(photoRecordMismatch(r,design,3),'round');
  assert.equal(photoRecordMismatch({...r,capture:{...r.capture,stale:true}},design,2),'invalidated');
});
test('inspecting HC then TFT preserves confirmations, checks, test bindings and original cursor',()=>{
  const original={...maker.emptyGuide(),componentIndex:1,index:6,phase:'review',run:5,checks:['saved'],
    confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),at:'saved',mode:'camera'}]))};
  const before=structuredClone(original);
  let state=maker.reviewProjectWire(design,original,hc.componentId,hc.componentPin);
  assert.equal(maker.currentWire(design,state).id,hc.id);
  state=maker.reviewProjectWire(design,state,tft.componentId,tft.componentPin);
  assert.equal(maker.currentWire(design,state).id,tft.id);
  assert.strictEqual(state.confirmed,original.confirmed);assert.strictEqual(state.checks,original.checks);assert.equal(state.run,5);
  for(const id of design.component_ids)assert.equal(componentTests.componentTestKey(design,state,id),componentTests.componentTestKey(design,original,id));
  assert.deepEqual(maker.resumeProjectGuide(state),{...original,inspection:false});assert.deepEqual(original,before);
});
const render=props=>{
  const {GpioPhotoWorkspace}=load('../src/components/GpioPhotoWorkspace.tsx',{
    react:React,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},'../lib/photoWiring':photo,'../lib/gpioPhotoWorkspace':workspace,
    './PhotoWiringPoc':{PhotoViewport:p=>React.createElement('div',{'data-wire':p.wire?.wire_id})},'./GpioCaptureAction.css':{},'../gpioPhotoWorkspace.css':{}});
  return renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{
    record:{source:'webcam',capture:fixture()},target:tft,historical:false,onReturn(){},...props}));
};
test('photo header names the selected TFT and exact failure rather than suggesting HC is missing',()=>{
  const html=render({});assert.match(html,/MRD-TFT240 · VCC/);assert.match(html,/orientation \/ pin geometry not validated/);
  assert.doesNotMatch(html,/HC-SR04\+ pins not located/);
});

test('photo module selection enters the guide, while normal module selection exits stale inspection',()=>{
  const original={...maker.emptyGuide(),phase:'review',componentIndex:1,index:6,run:8,
    confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),at:'saved',mode:'camera'}]))};
  const inspecting=maker.reviewProjectWire(design,original,hc.componentId);
  assert.equal(inspecting.phase,'active');assert.equal(maker.currentWire(design,inspecting).componentId,hc.componentId);
  const normal=componentTests.selectTestModule(design,inspecting,1);
  assert.equal(normal.inspection,false);assert.equal(normal.inspectionReturn,undefined);
  assert.equal(normal.phase,'review');assert.equal(normal.componentIndex,1);
  assert.strictEqual(normal.confirmed,original.confirmed);assert.equal(normal.run,8);
  const source=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.match(source,/onInspectComponent=\{photoMainActive \? cid => inspectWiring\(cid\) : undefined\}/);
});
test('previous-round references remain visibly distinct from wiring evidence',()=>{
  const html=render({target:hc,historical:true,historicalReason:'round'});
  assert.match(html,/Previous-round photo: intended wiring reference only\. Retake after moving boards or changing wires\./);
  assert.match(html,new RegExp(`data-wire="${hc.id}"`));
  for(const reason of ['project','revision','invalidated']) {
    const hidden=render({target:hc,historical:true,historicalReason:reason});
    assert.match(hidden,/Historical photo/);assert.doesNotMatch(hidden,/data-wire=/);
  }
});
test('unstarted photo guidance offers Start wiring without selecting a first wire',()=>{
  const html=render({target:undefined});
  assert.match(html,/Press Start wiring, or choose a wire to inspect\./);assert.doesNotMatch(html,/data-wire=/);
});
test('plan mismatch and pending controls remain explicit',()=>{
  assert.match(render({target:{...hc,id:'different'}}),/no matching wiring data/);
  assert.match(render({busy:true}),/disabled=""/);
});
