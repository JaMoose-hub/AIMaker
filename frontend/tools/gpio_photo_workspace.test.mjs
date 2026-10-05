import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {maker} from './project_guide_fixture.mjs';
function load(path, imports={}) {
  const js=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',js)(name=>{if(name in imports)return imports[name];throw Error(name);},exports,React);return exports;
}
const photo=load('../src/lib/photoWiring.ts');
const workspace=load('../src/lib/gpioPhotoWorkspace.ts',{'./photoWiring':photo,'./maker':maker});
const {GpioPhotoCapture,WebcamGpioCapture,photoGuideWire,photoRecordCurrent}=workspace;
const project={id:'p',revision:4,catalog_version:'fixture',profile_versions:{},component_ids:['hc-sr04'],
  wiring:[{id:'vcc',componentId:'hc-sr04',componentPin:'VCC',boardPin:'3V3_P1',connectionKind:'direct'}]};
function capture(extra={}) {return {capture_id:'cap',session_id:'s',project_id:'p',project_revision:4,
  image_url:'/api/photo-wiring/captures/cap/image',captured_at:'offline',image_sha256:'a'.repeat(64),frame_id:42,
  runtime_revision:7,video_size:[1920,1080],camera_id:'fixture',continuous_inference:true,quality:{},stale:false,
  detection:{board_id:'raspberry-pi-5',frame_id:42,runtime_revision:7,video_size:[1920,1080],tracking:'searching',pins:[],outline:null},
  components:[],localization:[],wires:photo.photoPlanForProject(project).wires,...extra};}
function requestFixture(options={}) {
  const calls=[];let captureFails=!!options.captureFails;
  const request=async(path,init={})=>{
    calls.push({path,...init});
    assert.equal(path,'snapshot');assert.equal(init.method,'POST');await options.acquire;
    if(captureFails)throw Error('capture failed');return options.photo??capture();
  };
  return{request,calls,allowRetry(){captureFails=false;}};
}
test('viewing is passive; explicit capture uses one snapshot without pausing inference',async()=>{
  const f=requestFixture(),owner=new WebcamGpioCapture(f.request),photos=[];
  assert.equal(f.calls.length,0);await owner.capture(project,p=>photos.push(p));
  assert.deepEqual(f.calls.map(c=>[c.path,c.method]),[['snapshot','POST']]);
  assert.deepEqual(f.calls[0].body,{project_id:'p',project_revision:4,catalog_version:'fixture',profile_versions:{},wires:photo.photoPlanForProject(project).wires});
  assert.equal(photos.length,1);assert.equal(owner.needsResume,false);
});
test('double-click coalesces to a single snapshot',async()=>{
  let resolve;const f=requestFixture({acquire:new Promise(r=>resolve=r)}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  const first=owner.capture(project,()=>accepted++),second=owner.capture(project,()=>accepted++);
  resolve();await Promise.all([first,second]);assert.equal(accepted,1);assert.equal(f.calls.length,1);
});
test('capture failure never pauses inference or accepts a photograph',async()=>{
  const f=requestFixture({captureFails:true}),owner=new WebcamGpioCapture(f.request);
  await assert.rejects(owner.capture(project,()=>assert.fail('invalid capture')),/capture failed/);
  assert.equal(f.calls.at(-1).path,'snapshot');assert.equal(owner.needsResume,false);
});
test('failed snapshots can retry directly without a resume lease',async()=>{
  const f=requestFixture({captureFails:true}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  await assert.rejects(owner.capture(project,()=>accepted++),/capture failed/);
  assert.equal(accepted,0);assert.equal(owner.needsResume,false);
  f.allowRetry();await owner.capture(project,()=>accepted++);
  assert.equal(accepted,1);assert.equal(f.calls.length,2);assert.equal(owner.needsResume,false);
});

for (const source of ['webcam','phone']) test(`${source} uses the shared service with explicit source and runtime binding`,async()=>{
  const f=requestFixture({photo:capture({camera_id:source+'-opaque'})}),owner=new GpioPhotoCapture(f.request),photos=[];
  await owner.capture(project,p=>photos.push(p),{kind:source,runtimeRevision:7});
  assert.equal(photos.length,1);assert.equal(photos[0].camera_id,source+'-opaque');
  assert.equal(f.calls.length,1);assert.equal(f.calls.at(-1).path,'snapshot');
});

test('late source or runtime switches reject the photograph without a camera lease',async()=>{
  for(const [id,rev] of [['phone-opaque',7],['webcam-opaque',8],['other-camera',7]]) {
    const f=requestFixture({photo:capture({camera_id:id})}),owner=new GpioPhotoCapture(f.request);
    await assert.rejects(owner.capture(project,()=>assert.fail('mislabeled photograph'),{kind:'webcam',runtimeRevision:rev}),/photo_source_changed/);
    assert.equal(f.calls.at(-1).path,'snapshot');assert.equal(owner.needsResume,false);
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
test('wrong project revision or source geometry rejects the snapshot',async()=>{
  for(const bad of [capture({project_revision:3}),capture({project_id:'other'}),capture({video_size:[1280,720]})]) {
    const f=requestFixture({photo:bad}),owner=new WebcamGpioCapture(f.request);
    await assert.rejects(owner.capture(project,()=>assert.fail('invalid photo')),/GPIO/);
    assert.equal(f.calls.at(-1).path,'snapshot');assert.equal(owner.needsResume,false);
  }
});
test('late snapshot completion remains bound; unsupported plans never request',async()=>{
  let resolve;const f=requestFixture({acquire:new Promise(r=>resolve=r)}),owner=new WebcamGpioCapture(f.request);let accepted=0;
  const task=owner.capture(project,()=>accepted++);resolve();await task;
  assert.equal(accepted,1);assert.equal(f.calls.at(-1).path,'snapshot');
  const bad=requestFixture();await assert.rejects(new WebcamGpioCapture(bad.request).capture({...project,component_ids:['unsupported']},()=>{}),/無效/);
  assert.equal(bad.calls.length,0);
});
test('guide highlighting requires exact wire, component and endpoint identity; there is no fallback',()=>{
  const p=capture(),target=project.wiring[0];assert.equal(photoGuideWire(p,target),p.wires[0]);
  assert.equal(photoGuideWire(p,undefined),undefined);
  for(const extra of [{id:'missing'},{componentId:'other'},{boardPin:'GPIO17'},{componentPin:'TRIG'},{connectionKind:'divider'}])assert.equal(photoGuideWire(p,{...target,...extra}),undefined);
});
test('project id, revision and wiring round each invalidate current-photo evidence',()=>{
  const record={source:'phone',capture:capture(),projectId:'p',revision:4,round:2};
  assert.equal(photoRecordCurrent(record,project,2),true);
  for(const [p,r] of [[null,2],[{...project,id:'other'},2],[{...project,revision:5},2],[project,3]])assert.equal(photoRecordCurrent(record,p,r),false);
});
test('both sources share a passive viewport; historical records do not highlight the current guide wire',()=>{
  const wires=[];
  const {GpioPhotoWorkspace}=load('../src/components/GpioPhotoWorkspace.tsx',{
    react:React,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},'../lib/photoWiring':photo,'../lib/gpioPhotoWorkspace':workspace,
    './PhotoWiringPoc':{PhotoViewport:props=>{wires.push(props.wire);return React.createElement('div',{'data-photo':props.capture.capture_id});}},'./GpioCaptureAction.css':{},'../gpioPhotoWorkspace.css':{}});
  for(const source of ['webcam','phone']) {
    const html=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source,capture:capture()},target:project.wiring[0],historical:false,onReturn(){}}));
    assert.match(html,/data-photo="cap"/);assert.match(html,source==='phone'?/Phone capture/:/Webcam/);assert.ok(wires.at(-1));
  }
  const old=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source:'phone',capture:capture()},target:project.wiring[0],historical:true,onReturn(){}}));
  assert.equal(wires.at(-1),undefined);assert.match(old,/Historical photo: current wiring is hidden/);
  assert.match(renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:null,historical:false,onReturn(){}})),/No wiring photos yet/);
  const timed=renderToStaticMarkup(React.createElement(GpioPhotoWorkspace,{record:{source:'phone',capture:capture({captured_at:'2026-10-03T05:06:00Z'})},historical:false,onReturn(){}}));
  assert.match(timed,/<time dateTime="2026-10-03T05:06:00.000Z">/);
  assert.match(timed,/Wiring photo/);
});

function workspaceNode(props) {
  const {GpioPhotoWorkspace}=load('../src/components/GpioPhotoWorkspace.tsx',{
    react:{...React,useState:value=>[value,()=>{}]},
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/photoWiring':photo,'../lib/gpioPhotoWorkspace':workspace,
    './PhotoWiringPoc':{PhotoViewport:props=>React.createElement('div',{'data-photo':props.capture.capture_id})},
    './GpioCaptureAction.css':{},'../gpioPhotoWorkspace.css':{},
  });
  return GpioPhotoWorkspace(props);
}
function elements(node) {
  if(Array.isArray(node))return node.flatMap(elements);
  if(!React.isValidElement(node))return [];
  return [node,...elements(node.props.children)];
}

test('photo workspace forwards recognition scope independently of endpoint readiness and retains original capture',()=>{
  const current=capture();
  for(const overlayComponentId of [null,'hc-sr04','mrd-tf240-8p-cs']) {
    const node=workspaceNode({record:{source:'webcam',capture:current},historical:false,overlayComponentId,onReturn(){}});
    const viewport=elements(node).find(el=>el.props.capture);
    assert.equal(viewport.props.overlayComponentId,overlayComponentId);
    assert.equal(viewport.props.capture,current);
    assert.equal(viewport.props.wire,undefined);
  }
});

test('photo workspace retains an explicit return action by default for hosts without view tabs',()=>{
  let returned=0;
  const node=workspaceNode({record:null,historical:false,onReturn(){returned++;}});
  const button=elements(node).find(element=>element.props.className?.includes('gpio-photo-return'));
  assert.ok(button);assert.equal(button.props.disabled,false);
  assert.equal(returned,0);button.props.onClick();assert.equal(returned,1);
  const busy=workspaceNode({record:null,historical:false,busy:true,onReturn(){}});
  assert.equal(elements(busy).find(element=>element.props.className?.includes('gpio-photo-return')).props.disabled,true);
});

test('photo view embeds navigation in its existing header without a duplicate title or losing provenance',()=>{
  const viewControls=React.createElement('nav',{'data-view-tabs':true},'Live · Diagram · Photo');
  for(const source of ['webcam','phone']) {
    const record={source,capture:capture({captured_at:'2026-10-03T05:06:00Z'})};
    const node=workspaceNode({record,target:project.wiring[0],historical:false,showReturn:false,viewControls,onReturn(){}});
    const header=elements(node).find(el=>el.type==='header');
    assert.equal(header.props.className,'image-workspace-heading');
    assert.equal(elements(header).find(el=>el.props['data-view-tabs']),viewControls);
    assert.equal(elements(header).some(el=>el.type==='strong'),false);
    const html=renderToStaticMarkup(node);
    assert.match(html,source==='phone'?/Phone capture/:/Webcam/);
    assert.match(html,/<time dateTime="2026-10-03T05:06:00.000Z">/);
    assert.match(html,/not a wiring pass/);
    assert.equal(elements(node).find(el=>el.props.capture).props.capture,record.capture);
  }
});

test('view-tab hosts can hide only the redundant return action while preserving capture and photo evidence',()=>{
  let captured=0;
  const captureAction=React.createElement('button',{'data-capture-action':true,onClick(){captured++;}},'Capture wiring photo');
  for(const source of ['webcam','phone']) {
    const current=capture();
    const node=workspaceNode({record:{source,capture:current},target:project.wiring[0],historical:false,
      showReturn:false,captureAction,onReturn(){assert.fail('Hidden return must not run');}});
    const all=elements(node);
    assert.equal(all.some(element=>element.props.className?.includes('gpio-photo-return')),false);
    assert.equal(all.find(element=>element.props['data-capture-action']),captureAction);
    assert.equal(captured,source==='webcam'?0:1);
    const viewport=all.find(element=>element.props.capture);
    assert.equal(viewport.props.capture,current);assert.equal(viewport.props.wire,current.wires[0]);
    const html=renderToStaticMarkup(node);
    assert.match(html,/data-photo="cap"/);assert.doesNotMatch(html,/Back to live view/);
    captureAction.props.onClick();
  }
  const empty=workspaceNode({record:null,historical:false,showReturn:false,captureAction,onReturn(){assert.fail();}});
  assert.match(renderToStaticMarkup(empty),/No wiring photos yet/);
  assert.equal(elements(empty).find(element=>element.props['data-capture-action']),captureAction);
  assert.equal(captured,2);
});

test('photo header accepts the shared source and capture controls without duplicate return actions',()=>{
  const captureAction=React.createElement(React.Fragment,null,
    React.createElement('div',{'data-source-host':true}),React.createElement('button',{'data-capture':true},'Retake photo'));
  const node=workspaceNode({record:{source:'webcam',capture:capture()},historical:false,onReturn(){},showReturn:false,
    captureAction,sourceError:'fixture source rejected'});
  const html=renderToStaticMarkup(node);
  assert.equal((html.match(/data-source-host/g)||[]).length,1);
  assert.equal((html.match(/data-capture=/g)||[]).length,1);
  assert.doesNotMatch(html,/Back to live view/);
  assert.match(html,/role="status" title="fixture source rejected"/);
  assert.match(html,/original source retained/);
});
