import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';

const viewSource=ts.createSourceFile('VideoView.tsx',readFileSync(new URL('../src/components/VideoView.tsx',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const imageSelector=viewSource.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='liveCameraImageState');
assert.ok(imageSelector,'Test the production image routing selector');
const compiled=ts.transpileModule(imageSelector.getText(viewSource),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const selectors={};new Function('exports',compiled)(selectors);
const select=(overrides={})=>selectors.liveCameraImageState({cameraSource:'phone',realtimeActive:true,frameImage:null,fallbackSrc:'/video',sourceBlocked:false,opticalHudMode:false,glassesMode:false,glassesReady:false,glassesLeaving:false,...overrides});

test('pending synchronized phone frames never fall back to MJPEG or snapshots and resume on the next image',()=>{
  for(const fallbackSrc of ['/video','/frame.jpg?v=11']) {
    assert.deepEqual(select({fallbackSrc}),{src:undefined,hidden:true,phoneWaiting:true});
    const first='data:image/jpeg;base64,first',next='data:image/jpeg;base64,next';
    const sequence=[first,null,next].map(frameImage=>select({fallbackSrc,frameImage}));
    assert.deepEqual(sequence.map(state=>state.src),[first,undefined,next]);
    assert.deepEqual(sequence.map(state=>state.hidden),[false,true,false]);
    assert.deepEqual(select({fallbackSrc,realtimeActive:false}),{src:fallbackSrc,hidden:false,phoneWaiting:false});
  }
});

test('phone waiting leaves existing webcam, Eye, optical and source-switch image branches unchanged',()=>{
  const image='data:image/jpeg;base64,current';
  for(const fallbackSrc of ['/video','/frame.jpg?v=11']) {
    assert.deepEqual(select({cameraSource:'device',fallbackSrc}),{src:fallbackSrc,hidden:false,phoneWaiting:false});
    assert.deepEqual(select({cameraSource:'device',fallbackSrc,frameImage:image}),{src:image,hidden:false,phoneWaiting:false});
    assert.deepEqual(select({cameraSource:'xreal',fallbackSrc,glassesMode:true,glassesReady:true}),{src:fallbackSrc,hidden:true,phoneWaiting:false});
    assert.deepEqual(select({cameraSource:'xreal',fallbackSrc,glassesMode:true,glassesReady:true,frameImage:image}),{src:image,hidden:false,phoneWaiting:false});
    assert.deepEqual(select({cameraSource:'xreal',fallbackSrc,glassesMode:true}),{src:undefined,hidden:true,phoneWaiting:false});
  }
  assert.deepEqual(select({frameImage:image,sourceBlocked:true}),{src:undefined,hidden:true,phoneWaiting:false});
  assert.deepEqual(select({frameImage:image,glassesLeaving:true}),{src:undefined,hidden:true,phoneWaiting:false});
  assert.deepEqual(select({cameraSource:'device',frameImage:image,opticalHudMode:true}),{src:image,hidden:true,phoneWaiting:false});
});

test('phone shares the real webcam tracking, GPIO and camera controls without a separate video viewer',async()=>{
  const webcam=await renderWiringVideo({viewControl:c=>c});
  const phone=await renderWiringVideo({cameraSource:'phone',cameraIdentity:'phone:paired:2',viewControl:c=>c});
  assert.equal(phone.tracking[0],true);
  assert.equal(phone.tracking[4],'phone:paired:2');
  assert.equal(phone.pin.detection.frame_id,webcam.pin.detection.frame_id);
  for(const label of ['即時追蹤','左右鏡像','上下鏡像','校正方向']) assert(phone.html.includes(label));
  assert(phone.html.includes('data-tracking-frame="77"'));
  assert(!phone.html.includes('<video')&&!phone.html.includes('mobile-main-preview'));
  assert(!phone.html.includes('video-img mirrored-x'));
});

test('source switching and loss suppress old images, pins and tracking requests immediately',async()=>{
  for(const blocked of ['sourceChanging','sourceUnavailable']) {
    const {html,pin,tracking}=await renderWiringVideo({cameraSource:'phone',cameraIdentity:'phone:paired:2',[blocked]:true});
    assert.equal(tracking[0],false);
    assert.equal(pin,undefined);
    assert.match(html,/<img[^>]*class="video-img hidden/);
    assert(!html.includes('src="/video"')&&!html.includes('data:image/jpeg'));
    assert(html.includes('role="status"'));
  }
});

test('ordinary phone view still supports GPIO when the optional tracking mode is disabled',async()=>{
  const {html,tracking,pin}=await renderWiringVideo({cameraSource:'phone',cameraIdentity:'phone:paired:3',realtimeEnabled:false});
  assert.equal(tracking[0],false);
  assert.equal(pin.detection.frame_id,77);
  assert(html.includes('src="/video"'));
});

test('the actual App follows an already selected phone in guide and deployment without borrowing webcam or photo ownership',()=>{
  const app=ts.createSourceFile('App.tsx',readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let selected,workspace;
  function visit(node){
    if(ts.isVariableDeclaration(node)&&node.name.getText(app)==='phoneSourceSelected')selected=node.initializer;
    if(ts.isJsxAttribute(node)&&node.name.getText(app)==='mobileWorkspace')workspace=node.initializer?.expression;
    ts.forEachChild(node,visit);
  }
  visit(app);assert.ok(selected);assert.ok(workspace);
  const property=workspace.properties.find(item=>item.name?.getText(app)==='phoneSourceSelected');
  assert.ok(property&&ts.isShorthandPropertyAssignment(property),'the real desktop companion receives selected-source ownership separately from guide UI');
  const follows=new Function('config','imageView','makerStage','displayModeActive','assistant',`return ${selected.getText(app)};`);
  for(const stage of ['guide','deploy']) {
    assert.equal(follows({camera_source:'phone'},'phone',stage,false,{demoOpen:false}),true);
    for(const [config,view,display,demo] of [
      [{camera_source:'device'},'webcam',false,false],
      [{camera_source:'device'},'phone',false,false],
      [{camera_source:'phone'},'photo',false,false],
      [{camera_source:'phone'},'phone',true,false],
      [{camera_source:'phone'},'phone',false,true],
    ])assert.equal(follows(config,view,stage,display,{demoOpen:demo}),false);
  }
  assert.equal(follows({camera_source:'phone'},'phone','design',false,{demoOpen:false}),false);
});
