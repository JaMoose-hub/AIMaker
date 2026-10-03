import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
function load(path, imports={}) {
  const js=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',js)(name=>{if(name in imports)return imports[name];throw Error(name);},exports,React);return exports;
}
const photo=load('../src/lib/photoWiring.ts');
const {GpioPhotoCapture,WebcamGpioCapture,photoGuideWire,photoRecordCurrent}=load('../src/lib/gpioPhotoWorkspace.ts',{'./photoWiring':photo});
const project={id:'p',revision:4,catalog_version:'fixture',profile_versions:{},component_ids:['hc-sr04'],
  wiring:[{id:'vcc',componentId:'hc-sr04',componentPin:'VCC',boardPin:'3V3_P1',connectionKind:'direct'}]};
function capture(extra={}) {return {capture_id:'cap',session_id:'s',project_id:'p',project_revision:4,
  image_url:'/api/photo-wiring/captures/cap/image',captured_at:'offline',image_sha256:'a'.repeat(64),frame_id:42,
  runtime_revision:7,video_size:[1920,1080],camera_id:'fixture',quality:{},stale:false,
  detection:{board_id:'raspberry-pi-5',frame_id:42,runtime_revision:7,video_size:[1920,1080],tracking:'searching',pins:[],outline:null},
  components:[],localization:[],wires:photo.photoPlanForProject(project).wires,...extra};}
function requestFixture(options={}) {
  const calls=[];let resumeFails=!!options.resumeFails;
  const request=async(path,init={})=>{
    calls.push({path,...init});
    if(path==='sessions') {await options.acquire;return{session_id:'s',continuous_inference:false};}
    if(init.method==='DELETE') {if(resumeFails)throw Error('resume disconnected');return{resumed:true,continuous_inference:true};}
    if(options.captureFails)throw Error('capture failed');return options.photo??capture();
  };
  return{request,calls,allowResume(){resumeFails=false;}};
}
test('viewing is passive; explicit capture uses only existing photo endpoints and always restores inference',async()=>{
  const f=requestFixture(),owner=new WebcamGpioCapture(f.request),photos=[];
  assert.equal(f.calls.length,0);await owner.capture(project,p=>photos.push(p));
  assert.deepEqual(f.calls.map(c=>[c.path,c.method]),[['sessions','POST'],['sessions/s/captures','POST'],['sessions/s','DELETE']]);
  assert.deepEqual(f.calls[1].body,{project_id:'p',project_revision:4,catalog_version:'fixture',profile_versions:{},wires:photo.photoPlanForProject(project).wires});
  assert.equal(photos.length,1);assert.equal(owner.needsResume,false);
});
test('double-click coalesces to a single capture and release',async()=>{
  let resolve;const f=requestFixture({acquire:new Promise(r=>resolve=r)}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  const first=owner.capture(project,()=>accepted++),second=owner.capture(project,()=>accepted++);
  resolve();await Promise.all([first,second]);assert.equal(accepted,1);assert.equal(f.calls.length,3);
});
test('capture failure still restores continuous inference without accepting a photograph',async()=>{
  const f=requestFixture({captureFails:true}),owner=new WebcamGpioCapture(f.request);
  await assert.rejects(owner.capture(project,()=>assert.fail('invalid capture')),/capture failed/);
  assert.equal(f.calls.at(-1).method,'DELETE');assert.equal(owner.needsResume,false);
});
test('resume failure retains the photo and blocks another capture until explicit recovery',async()=>{
  const f=requestFixture({resumeFails:true}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  await assert.rejects(owner.capture(project,()=>accepted++),/resume disconnected/);
  assert.equal(accepted,1);assert.equal(owner.needsResume,true);
  await assert.rejects(owner.capture(project,()=>{}),/即時辨識/);assert.equal(f.calls.length,3);
  f.allowResume();await owner.resume();assert.equal(owner.needsResume,false);
});

for (const source of ['webcam','phone']) test(`${source} uses the shared service with explicit source and runtime binding`,async()=>{
  const f=requestFixture({photo:capture({camera_id:source+'-opaque'})}),owner=new GpioPhotoCapture(f.request),photos=[];
  await owner.capture(project,p=>photos.push(p),{kind:source,runtimeRevision:7});
  assert.equal(photos.length,1);assert.equal(photos[0].camera_id,source+'-opaque');
  assert.equal(f.calls.length,3);assert.equal(f.calls.at(-1).method,'DELETE');
});

test('late source or runtime switches reject the photograph without losing the camera lease',async()=>{
  for(const [id,rev] of [['phone-opaque',7],['webcam-opaque',8],['other-camera',7]]) {
    const f=requestFixture({photo:capture({camera_id:id})}),owner=new GpioPhotoCapture(f.request);
    await assert.rejects(owner.capture(project,()=>assert.fail('mislabeled photograph'),{kind:'webcam',runtimeRevision:rev}),/photo_source_changed/);
    assert.equal(f.calls.at(-1).method,'DELETE');assert.equal(owner.needsResume,false);
  }
});

test('capture action has one explicit button, accessible pending state, retry and recovery',()=>{
  const {GpioCaptureAction}=load('../src/components/GpioCaptureAction.tsx',{
    react:React,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},'./GpioCaptureAction.css':{}});
  const base={source:'phone',busy:false,needsResume:false,error:null,disabledReason:'',onCapture(){},onResume(){}};
  const render=extra=>renderToStaticMarkup(React.createElement(GpioCaptureAction,{...base,...extra}));
  assert.match(render({}),/Capture wiring photo/);assert.match(render({}),/Phone stream/);
  assert.equal((render({}).match(/<button/g)||[]).length,1);
  assert.match(render({busy:true}),/Capturing/);assert.match(render({busy:true}),/aria-busy="true"/);
  assert.match(render({busy:true}),/disabled=""/);
  assert.match(render({disabledReason:'Waiting for live video'}),/aria-describedby=/);
  assert.match(render({error:'source'}),/Source changed/);
  assert.match(render({error:'capture'}),/Capture failed/);
  assert.match(render({needsResume:true,disabledReason:'Waiting for live video'}),/Resume live recognition/);
  assert.doesNotMatch(render({needsResume:true,disabledReason:'Waiting for live video'}),/disabled=""/);
  assert.match(render({retake:true}),/Retake photo/);
});
test('wrong project revision or source geometry is rejected and the acquired session is released',async()=>{
  for(const bad of [capture({project_revision:3}),capture({project_id:'other'}),capture({video_size:[1280,720]})]) {
    const f=requestFixture({photo:bad}),owner=new WebcamGpioCapture(f.request);
    await assert.rejects(owner.capture(project,()=>assert.fail('invalid photo')),/GPIO/);
    assert.equal(f.calls.at(-1).method,'DELETE');assert.equal(owner.needsResume,false);
  }
});
test('late session acquisition drains safely; unsupported plans never acquire',async()=>{
  let resolve;const f=requestFixture({acquire:new Promise(r=>resolve=r)}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  const task=owner.capture(project,()=>accepted++);resolve();await task;
  assert.equal(accepted,1);assert.equal(f.calls.at(-1).method,'DELETE');
  const bad=requestFixture();await assert.rejects(new WebcamGpioCapture(bad.request).capture({...project,component_ids:['unsupported']},()=>{}),/無效/);
  assert.equal(bad.calls.length,0);
});
test('guide highlighting requires exact wire, component and endpoint identity; there is no fallback',()=>{
  const p=capture(),target=project.wiring[0];assert.equal(photoGuideWire(p,target),p.wires[0]);
  assert.equal(photoGuideWire(p,undefined),undefined);
  for(const extra of [{id:'missing'},{componentId:'other'},{boardPin:'GPIO17'},{componentPin:'TRIG'}])assert.equal(photoGuideWire(p,{...target,...extra}),undefined);
});
test('project id, revision and wiring round each invalidate current-photo evidence',()=>{
  const record={source:'phone',capture:capture(),projectId:'p',revision:4,round:2};
  assert.equal(photoRecordCurrent(record,project,2),true);
  for(const [p,r] of [[null,2],[{...project,id:'other'},2],[{...project,revision:5},2],[project,3]])assert.equal(photoRecordCurrent(record,p,r),false);
});
test('both sources share a passive viewport; historical records do not highlight the current guide wire',()=>{
  const wires=[];
  const {GpioPhotoWorkspace}=load('../src/components/GpioPhotoWorkspace.tsx',{
    react:React,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},'../lib/photoWiring':photo,
    './PhotoWiringPoc':{PhotoViewport:props=>{wires.push(props.wire);return React.createElement('div',{'data-photo':props.capture.capture_id});}},'../gpioPhotoWorkspace.css':{}});
  for(const source of ['webcam','phone']) {
    const html=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source,capture:capture()},wire:capture().wires[0],historical:false,onReturn(){}}));
    assert.match(html,/data-photo="cap"/);assert.match(html,source==='phone'?/Phone capture/:/Webcam/);assert.ok(wires.at(-1));
  }
  const old=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source:'phone',capture:capture()},wire:capture().wires[0],historical:true,onReturn(){}}));
  assert.equal(wires.at(-1),undefined);assert.match(old,/not current wiring evidence/);
  assert.match(renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:null,historical:false,onReturn(){}})),/No wiring photos yet/);
  const timed=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source:'phone',capture:capture({captured_at:'2026-10-03T05:06:00Z'})},historical:false,onReturn(){}}));
  assert.match(timed,/<time dateTime="2026-10-03T05:06:00.000Z">/);
  assert.match(timed,/Wiring photo/);
});
