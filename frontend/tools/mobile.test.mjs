import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';

function load(file, modules={}) {
  const js=ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={}; new Function('require','exports',js)(name=> name==='../lib/headerPanels'
    ? {useHeaderPanel:(_panel,initial=false)=>modules.react.useState(initial)} : modules[name],exports);return exports;
}
const photo=load('../src/lib/photoWiring.ts');
const browserRtc=load('../src/lib/mobileBrowserRtc.ts');
const viewerStats=load('../src/lib/mobileViewerStats.ts');
const recognition=load('../src/lib/mobileRecognition.ts');
const mobile=load('../src/lib/mobile.ts',{'react':React,'./photoWiring':photo,'./mobileBrowserRtc':browserRtc,'./mobileViewerStats':viewerStats,'./mobileRecognition':recognition});

test('viewer diagnostics use interval counters rather than lifetime rates or configured FPS',()=>{
  const previous={id:'video:1',timestamp:1000,framesDecoded:30,bytesReceived:1000000,packetsReceived:100,packetsLost:2,jitterBufferDelay:.6,jitterBufferEmittedCount:30};
  const current={...previous,timestamp:2000,framesDecoded:58,bytesReceived:2000000,packetsReceived:198,packetsLost:4,jitterBufferDelay:1.44,jitterBufferEmittedCount:58,width:1920,height:1080,codec:'video/H264'};
  const result=viewerStats.viewerMetricDelta(previous,current);
  assert.equal(result.decodeFps,28);assert.equal(result.receiveMbps,8);assert.equal(result.packetLossPercent,2);
  assert.ok(Math.abs(result.jitterBufferMs-30)<1e-10);assert.equal(result.width,1920);assert.equal(result.codec,'video/H264');
  assert.equal(viewerStats.viewerMetricDelta(previous,{...current,packetsLost:1}).packetLossPercent,0,'Late recovered packets do not become negative loss');
});

test('unsupported counters, reset SSRCs and clock resets never invent zero or a false spike',()=>{
  const previous={id:'first:10',timestamp:1000,framesDecoded:200,bytesReceived:5000000,packetsReceived:500,packetsLost:12,jitterBufferDelay:6,jitterBufferEmittedCount:200};
  const current={...previous,timestamp:2000};
  for(const changed of [{...current,id:'next:11'},{...current,timestamp:1000},{...current,framesDecoded:2,bytesReceived:10,packetsReceived:1,jitterBufferDelay:.1,jitterBufferEmittedCount:2},{id:previous.id,timestamp:2000}]) {
    const stats=viewerStats.viewerMetricDelta(previous,changed);
    assert.equal(stats.decodeFps,null);assert.equal(stats.receiveMbps,null);assert.equal(stats.jitterBufferMs,null);assert.equal(stats.packetLossPercent,null);
  }
  const stopped=viewerStats.viewerMetricDelta(previous,current);
  assert.equal(stopped.decodeFps,0);assert.equal(stopped.receiveMbps,0);assert.equal(stopped.jitterBufferMs,null);assert.equal(stopped.packetLossPercent,null);
  assert.equal(viewerStats.viewerMetricDelta(null,current).decodeFps,null);assert.deepEqual(viewerStats.viewerMetricDelta(previous,null),viewerStats.emptyViewerMetrics());
});

test('RTC report extraction binds the video SSRC to its actual codec and dimensions',()=>{
  const report=new Map([['audio',{type:'inbound-rtp',kind:'audio',timestamp:1000}],['video',{id:'v',ssrc:77,type:'inbound-rtp',mediaType:'video',timestamp:1000,codecId:'codec',frameWidth:1280,frameHeight:720,framesDecoded:20}],['codec',{type:'codec',mimeType:'video/H264'}]]);
  const sample=viewerStats.readViewerSample(report);
  assert.equal(sample.id,'v:77');assert.equal(sample.codec,'video/H264');assert.equal(sample.width,1280);assert.equal(sample.height,720);
  assert.equal(viewerStats.readViewerSample(new Map()),null);
});

test('video presentation counts submitted frames, detects stalls and cancels late callbacks',()=>{
  const callbacks=new Map(),cancelled=[];let id=0;
  const observer=viewerStats.observeVideoPresentation({requestVideoFrameCallback:callback=>{callbacks.set(++id,callback);return id;},cancelVideoFrameCallback:value=>cancelled.push(value)},()=>0);
  assert.equal(observer.sample(0),null);
  callbacks.get(1)(0,{presentedFrames:1});callbacks.get(2)(999,{presentedFrames:31});
  assert.equal(observer.sample(1000),30);assert.equal(observer.sample(2000),0);
  const late=callbacks.get(3);observer.stop();assert.deepEqual(cancelled,[3]);late(3000,{presentedFrames:61});
  assert.equal(id,3);assert.equal(observer.sample(3000),null);
});

test('presentation fallback excludes dropped frames and leaves unsupported browsers unknown',()=>{
  let quality={totalVideoFrames:60,droppedVideoFrames:5};
  const observer=viewerStats.observeVideoPresentation({getVideoPlaybackQuality:()=>quality},()=>0);
  quality={totalVideoFrames:90,droppedVideoFrames:10};assert.equal(observer.sample(1000),25);
  quality={totalVideoFrames:2,droppedVideoFrames:0};assert.equal(observer.sample(2000),null);
  observer.stop();assert.equal(observer.sample(3000),null);
  assert.equal(viewerStats.observeVideoPresentation({},()=>0).sample(1000),null);
  const unsupported=viewerStats.observeVideoPresentation({requestVideoFrameCallback(){throw Error('not supported');},getVideoPlaybackQuality:()=>quality},()=>0);
  quality={totalVideoFrames:12,droppedVideoFrames:0};assert.equal(unsupported.sample(1000),10);unsupported.stop();
});

test('low-latency receiver target is optional and never requires unsupported properties',()=>{
  const supported={jitterBufferTarget:null};assert.equal(viewerStats.requestLowJitterBuffer(supported),true);assert.equal(supported.jitterBufferTarget,20);
  const unsupported={};assert.equal(viewerStats.requestLowJitterBuffer(unsupported),false);assert.deepEqual(unsupported,{});
  const blocked={get jitterBufferTarget(){return null;},set jitterBufferTarget(value){throw Error('unsupported');}};
  assert.equal(viewerStats.requestLowJitterBuffer(blocked),false);assert.equal(viewerStats.requestLowJitterBuffer(null),false);
});

test('mobile events cannot replace a different desktop conversation',()=>{
  const session={session_id:'phone',conversation_id:'project',context_id:'context',stream:{generation:1},view:{capture_id:null}};
  assert.equal(mobile.mobileStateForConversation({session},'project'),session);
  assert.equal(mobile.mobileStateForConversation({session},'other'),undefined);
  assert.equal(mobile.mobileStateForConversation({session:null},'project'),null);
  assert.equal(mobile.mobileStateForConversation({type:'noise'},'project'),undefined);
});

test('late wire selection replies cannot overwrite a newer shared view or another phone',()=>{
  const session={session_id:'phone',view:{capture_id:'c',wire_id:'new',revision:3}};
  assert.equal(mobile.acceptMobileView(session,'phone',{capture_id:'c',wire_id:'old',revision:2}),session);
  assert.equal(mobile.acceptMobileView(session,'other',{capture_id:'c',wire_id:'other',revision:4}),session);
  assert.equal(mobile.acceptMobileView(session,'phone',{capture_id:'c',wire_id:'latest',revision:4}).view.wire_id,'latest');
});

test('a frozen preview lock expires locally even when repeated status snapshots arrive',()=>{
  const session={session_id:'phone',stream:{active:true,publisher_connected:true,generation:1,preview_seq:8,valid_for_ms:1000}};
  const first=mobile.mobilePreviewLease(session,100,{key:'',deadline:0});
  assert.equal(first.deadline,1100);
  const replay=mobile.mobilePreviewLease(session,900,first);assert.equal(replay.deadline,1100);
  assert.ok(1200>=replay.deadline,'Silent websocket cannot retain Locked indefinitely');
  assert.equal(mobile.mobilePreviewLease({...session,stream:{...session.stream,preview_seq:9}},1200,replay).deadline,2200);
  assert.equal(mobile.mobilePreviewLease({...session,stream:{...session.stream,active:false}},1200,replay).deadline,0);
});

test('CUDA badge reflects available actual runtimes, never the requested backend alone',()=>{
  const status={model_runtime:{pi:{available:true,actual_backend:'cuda'},hc:{available:true,actual_backend:'opencv',requested_backend:'cuda'},tft:{available:false,actual_backend:'cuda'}}};
  assert.deepEqual(mobile.mobileModelRuntime(status),{total:3,available:2,cuda:1});
  assert.deepEqual(mobile.mobileModelRuntime({}),{total:0,available:0,cuda:0});
});

test('video receipt expires independently of Locked, phone telemetry and repeated unchanged snapshots',()=>{
  const stream={active:true,state:'locked',can_capture:true,video_fps:26,video_received_at:100,video_receive_age_ms:100,video_receive_fresh:true};
  assert.equal(mobile.mobileVideoFresh(stream,100100),true);assert.equal(mobile.mobileVideoFresh(stream,101500),true);
  assert.equal(mobile.mobileVideoFresh({...stream},101501),false,'Replaying status cannot renew the receipt timestamp');
  assert.equal(mobile.mobileVideoAgeMs(stream,105000),5000);
  for(const changed of [{...stream,active:false},{...stream,video_receive_fresh:false},{...stream,video_received_at:null},
    {...stream,video_received_at:undefined},{...stream,video_receive_age_ms:2000},{...stream,video_received_at:Infinity}])
    assert.equal(mobile.mobileVideoFresh(changed,100100),false);
  assert.equal(mobile.mobileVideoFresh({active:true,state:'locked',video_fps:26},100100),false,'Old API fields are not receipt evidence');
});

test('each transport measurement needs its own fresh clock; reconnect is one bounded foreground attempt',()=>{
  assert.equal(viewerStats.mobileMeasurementFresh(10000,12000),true);assert.equal(viewerStats.mobileMeasurementFresh(10000,12501),false);
  assert.equal(viewerStats.mobileMeasurementFresh(undefined,12000),false);assert.equal(viewerStats.mobileMeasurementFresh(13000,12000),false);
  const input={active:true,publishing:true,foreground:true,wanted:true,busy:false,capturePending:false,attempted:false,receiveAgeMs:5000};
  assert.equal(viewerStats.mobileReconnectEligible(input),true);
  for(const changed of [{active:false},{publishing:false},{foreground:false},{wanted:false},{busy:true},{capturePending:true},{attempted:true},{receiveAgeMs:4999},{receiveAgeMs:null}])
    assert.equal(viewerStats.mobileReconnectEligible({...input,...changed}),false,JSON.stringify(changed));
  assert.equal(viewerStats.mobileReconnectEligible({...input,attempted:true,receiveAgeMs:30000}),false,'A new backend generation does not rearm the automatic attempt');
});

test('a completed local start retries missing first frames after five seconds; unknown old sessions cannot rearm it',()=>{
  const eligible=wait=>viewerStats.mobileReconnectEligible({active:true,publishing:true,foreground:true,wanted:true,busy:false,capturePending:false,attempted:false,receiveAgeMs:wait});
  assert.equal(eligible(viewerStats.mobileReconnectWaitMs(null,10000,14999)),false);
  assert.equal(eligible(viewerStats.mobileReconnectWaitMs(null,10000,15000)),true);
  assert.equal(viewerStats.mobileReconnectWaitMs(100,10000,20000),100,'A fresh received frame takes precedence over time since start');
  assert.equal(eligible(viewerStats.mobileReconnectWaitMs(100,10000,20000)),false);
  for(const localStart of [null,undefined,0,NaN,30000]) {
    assert.equal(viewerStats.mobileReconnectWaitMs(null,localStart,20000),null);
    assert.equal(eligible(viewerStats.mobileReconnectWaitMs(null,localStart,20000)),false,'No valid local start means no first-frame retry');
  }
});

test('a controlled restart cannot reopen after stop, background, capture or owner change during release',async()=>{
  for(const reason of ['stop','background','capture','owner']) {
    let release,current=true;const calls=[];
    const task=viewerStats.restartMobileStream(()=>{calls.push('stop');return new Promise(resolve=>release=resolve);},async()=>{calls.push('start');},()=>current);
    current=false;release();assert.equal(await task,false,reason);assert.deepEqual(calls,['stop']);
  }
  const calls=[];assert.equal(await viewerStats.restartMobileStream(async()=>{calls.push('stop');},async()=>{calls.push('start');},()=>true),true);
  assert.deepEqual(calls,['stop','start']);
});

test('mobile photos keep exact frozen-image coordinate validation and canonical URLs',()=>{
  const pose={frame_id:7,runtime_revision:2,video_size:[1080,1920],tracking:'searching',outline:null,pins:[]};
  const value={capture_id:'cap',session_id:'phone',asset_id:'asset',context_id:'ctx',image_url:'/api/mobile/captures/cap/image',
    frame_id:7,runtime_revision:2,video_size:[1080,1920],camera_id:'phone',image_sha256:'a'.repeat(64),
    detection:{...pose,board_id:'raspberry-pi-5'},components:[],wires:[],quality:{}};
  assert.equal(mobile.acceptMobileCapture(value),true);
  assert.equal(mobile.acceptMobileCapture({...value,image_url:'/api/mobile/assets/asset/file'}),true);
  assert.equal(mobile.acceptMobileCapture({...value,image_url:'/api/mobile/assets/other/file'}),false);
  for(const mutate of [v=>v.image_url='/video',v=>v.detection.frame_id++,v=>v.video_size=[1920,1080],v=>v.image_sha256='bad']) {
    const next=structuredClone(value);mutate(next);assert.equal(mobile.acceptMobileCapture(next),false);
  }
});

function streamCaptureFixture(overrides={}) {
  const pose={frame_id:7,runtime_revision:2,video_size:[1080,1920],tracking:'searching',outline:null,pins:[]};
  return {capture_id:'cap',session_id:'phone',asset_id:'asset',context_id:'ctx',image_url:'/api/mobile/captures/cap/image',
    frame_id:7,runtime_revision:2,video_size:[1080,1920],camera_id:'phone',image_sha256:'a'.repeat(64),
    detection:{...pose,board_id:'raspberry-pi-5'},components:[],wires:[],quality:{},capture_source:'desktop_stream',
    stream_identity:{session_id:'phone',generation:3,frame_seq:88,received_monotonic:123,received_at:1234},...overrides};
}

function captureHookHarness(request) {
  const states=[],refs=[],effects=[],accepted=[];let stateIndex=0,refIndex=0,effectIndex=0,pending=[];
  const hooks={
    useState(initial){const i=stateIndex++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
      return [states[i],next=>{states[i]=typeof next==='function'?next(states[i]):next;}];},
    useRef(initial){const i=refIndex++;return refs[i]??=( {current:initial} );},
    useEffect(callback,deps){const i=effectIndex++,old=effects[i];
      if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index])))pending.push(()=>{old?.cleanup?.();effects[i]={deps,cleanup:callback()};});},
  };
  const library=load('../src/lib/mobile.ts',{react:hooks,'./photoWiring':photo,'./mobileBrowserRtc':browserRtc,'./mobileViewerStats':viewerStats});
  const flush=()=>{const tasks=pending;pending=[];tasks.forEach(task=>task());};
  return {accepted,flush,render(session,commit=true){stateIndex=refIndex=effectIndex=0;const result=library.useDesktopStreamCapture(session,value=>accepted.push(value),request);if(commit)flush();return result;},
    unmount(){effects.forEach(effect=>effect.cleanup?.());}};
}

const captureSession=()=>({session_id:'phone',context_id:'ctx',stream:{active:true,publisher_connected:true,generation:3,state:'finding',can_capture:false}});

test('desktop capture uses the backend frame while finding and coalesces clicks without stopping either camera',async()=>{
  const calls=[];let release;const pending=new Promise(resolve=>release=resolve);
  const harness=captureHookHarness(async(path,options)=>{calls.push({path,...options});return pending;});
  const session=captureSession();let hook=harness.render(session);
  const first=hook.capture();await hook.capture();hook=harness.render(session);
  assert.equal(hook.busy,true);assert.equal(calls.length,1);
  assert.equal(calls[0].path,'stream-capture');assert.equal(calls[0].method,'POST');
  assert.deepEqual({...calls[0].body,request_id:'id'},{session_id:'phone',generation:3,context_id:'ctx',request_id:'id'});
  assert.ok(calls[0].body.request_id);
  release(streamCaptureFixture());await first;
  assert.equal(harness.accepted.length,1);assert.equal(harness.accepted[0].stream_identity.frame_seq,88);
  assert.equal(harness.render(session).busy,false);assert.equal(calls.length,1,'No camera start, stop or photo-PoC calls');harness.unmount();
});

test('unknown capture outcome retries the frozen request even after streaming stops; a new capture gets a new ID',async()=>{
  const calls=[];const harness=captureHookHarness(async(path,options)=>{calls.push({path,...options});if(calls.length!==2)throw Error('network disconnected');return streamCaptureFixture();});
  const session=captureSession();await harness.render(session).capture();
  let hook=harness.render(session);assert.match(hook.error,/network disconnected/);
  const stopped={...session,stream:{...session.stream,active:false,publisher_connected:false}};
  await harness.render(stopped).retry();assert.deepEqual(calls[1].body,calls[0].body);assert.equal(harness.accepted.length,1);
  await harness.render(session).capture();assert.notEqual(calls[2].body.request_id,calls[0].body.request_id);
  hook=harness.render(session);assert.equal(hook.busy,false);assert.match(hook.error,/network disconnected/);harness.unmount();
});

function captureFakeClock() {
  const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout,timers=new Map();let now=0,next=0;
  globalThis.setTimeout=(callback,delay)=>{timers.set(++next,{at:now+delay,callback});return next;};
  globalThis.clearTimeout=id=>timers.delete(id);
  return {timers,advance(ms){now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.callback();}},
    restore(){globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;}};
}

test('a 180-second capture deadline clears busy and retries the same request without accepting a late first response',async()=>{
  const clock=captureFakeClock(),calls=[];let release;
  const harness=captureHookHarness(async(path,options)=>{calls.push({path,...options});return calls.length===1?new Promise(resolve=>release=resolve):streamCaptureFixture();});
  const session=captureSession();
  try {
    const task=harness.render(session).capture();assert.equal(clock.timers.size,1);
    clock.advance(179999);assert.equal(calls[0].signal.aborted,false);assert.equal(harness.render(session).busy,true);
    clock.advance(1);await task;
    let hook=harness.render(session);assert.equal(calls[0].signal.aborted,true);assert.equal(hook.busy,false);
    assert.equal(hook.error,'mobile_capture_timeout');assert.equal(clock.timers.size,0);
    await hook.retry();assert.deepEqual(calls[1].body,calls[0].body);assert.equal(harness.accepted.length,1);
    assert.equal(harness.render(session).error,'');assert.equal(clock.timers.size,0);
    release(streamCaptureFixture({capture_id:'late'}));await Promise.resolve();await Promise.resolve();
    assert.equal(harness.accepted.length,1,'An old HTTP response cannot replace the retry result');
  } finally {harness.unmount();clock.restore();}
});

test('context cancellation and unmount clear capture deadlines without creating timeout errors',async()=>{
  const clock=captureFakeClock();
  try {
    for(const change of ['context','unmount']) {
      const harness=captureHookHarness(async()=>new Promise(()=>{}));const session=captureSession();
      const task=harness.render(session).capture();
      if(change==='context')harness.render({...session,context_id:'new-context'});else harness.unmount();
      await task;assert.equal(clock.timers.size,0);clock.advance(180000);assert.deepEqual(harness.accepted,[]);
      if(change==='context'){assert.equal(harness.render({...session,context_id:'new-context'}).error,'');harness.unmount();}
    }
  } finally {clock.restore();}
});

test('late capture responses cannot replace a different session, context or stream generation, even before effects run',async()=>{
  for(const change of [value=>({...value,session_id:'new-phone'}),value=>({...value,context_id:'new-context'}),value=>({...value,stream:{...value.stream,generation:4}}),()=>null]) {
    let release,signal;const harness=captureHookHarness(async(_path,options)=>{signal=options.signal;return new Promise(resolve=>release=resolve);});
    const session=captureSession();const task=harness.render(session).capture();
    const switched=harness.render(change(session),false);assert.equal(switched.busy,false);assert.equal(switched.error,'');
    release(streamCaptureFixture());await task;assert.deepEqual(harness.accepted,[]);harness.flush();harness.unmount();
    // The old reply was ignored synchronously, without waiting for effect cleanup.
    assert.ok(signal instanceof AbortSignal);
  }
});

test('unmount aborts capture transport and ignores a response from a transport that still resolves',async()=>{
  let release,signal;const harness=captureHookHarness(async(_path,options)=>{signal=options.signal;return new Promise(resolve=>release=resolve);});
  const task=harness.render(captureSession()).capture();harness.unmount();assert.equal(signal.aborted,true);
  release(streamCaptureFixture());await task;assert.deepEqual(harness.accepted,[]);
});

test('capture validates the frozen geometry and origin before showing GPIO; inactive new capture is a no-op',async()=>{
  for(const changed of [{session_id:'other'},{context_id:'other'},{stream_identity:{session_id:'phone',generation:2}},{detection:{frame_id:999}}]) {
    const harness=captureHookHarness(async()=>streamCaptureFixture(changed));const session=captureSession();
    await harness.render(session).capture();assert.deepEqual(harness.accepted,[]);assert.match(harness.render(session).error,/context_mismatch/);harness.unmount();
  }
  let calls=0;const harness=captureHookHarness(async()=>{calls++;return streamCaptureFixture();});
  const session=captureSession();await harness.render({...session,stream:{...session.stream,publisher_connected:false}}).capture();
  assert.equal(calls,0);harness.unmount();
});

function fakePeer() {
  return {iceGatheringState:'complete',localDescription:null,remote:null,closed:false,transceivers:[],
    addTransceiver(kind,options){this.transceivers.push({kind,...options});return{receiver:this.receiver??{}};},
    async createOffer(){return{type:'offer',sdp:'test-offer'};},async setLocalDescription(value){this.localDescription=value;},
    async setRemoteDescription(value){this.remote=value;},close(){this.closed=true;},
    addEventListener(){},removeEventListener(){}};
}
test('desktop WebRTC is receive-only and camera-free; closing rejects a late answer',async()=>{
  const peer=fakePeer();let release;const pending=new Promise(resolve=>release=resolve),requests=[];
  const viewer=mobile.openMobileViewer('phone',9,()=>{},()=>{},async(path,options)=>{requests.push({path,...options});return pending;},()=>peer);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(peer.transceivers,[{kind:'video',direction:'recvonly'}]);
  assert.equal(requests[0].path,'stream/offer');assert.deepEqual(requests[0].body,{session_id:'phone',generation:9,role:'viewer',type:'offer',sdp:'test-offer'});
  viewer.close();release({type:'answer',sdp:'late'});await viewer.ready;
  assert.equal(peer.closed,true);assert.equal(peer.remote,null);assert.equal(requests[0].signal.aborted,true);
  assert.equal(requests.length,1); // No DELETE of the phone stream or camera acquisition.
});

test('desktop viewer applies a matching answer and delivers remote track only while mounted',async()=>{
  const peer=fakePeer(),tracks=[];peer.receiver={jitterBufferTarget:null};
  const viewer=mobile.openMobileViewer('phone',3,value=>tracks.push(value),()=>{},async()=>({type:'answer',sdp:'answer'}),()=>peer);
  await viewer.ready;assert.equal(peer.remote.sdp,'answer');assert.equal(peer.receiver.jitterBufferTarget,20);
  const stream={id:'remote'};peer.ontrack({streams:[stream]});assert.deepEqual(tracks,[stream]);
  viewer.close();assert.equal(peer.ontrack,null);
});

test('mobile request carries exact photo context and reports backend busy without losing details',async()=>{
  const original=globalThis.fetch;let request;
  try {
    globalThis.fetch=async(path,options)=>{request={path,...options};return{ok:false,status:409,json:async()=>({detail:'assistant_busy'})};};
    await assert.rejects(mobile.mobileRequest('messages',{method:'POST',body:{session_id:'s',capture_id:'c',context_id:'old-photo',check_scope:'one',wire_id:'w'}}),/409 · assistant_busy/);
    assert.equal(request.path,'/api/mobile/messages');assert.equal(JSON.parse(request.body).context_id,'old-photo');
  } finally {globalThis.fetch=original;}
});

test('chat attachment cards retain capture identity and avoid replaying media from unrelated messages',()=>{
  const {MobileAttachmentCards}=load('../src/components/MobileCompanion.tsx',{
    react:React,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/mobile':mobile,'../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,'./PhotoWiringPoc':{},'../mobile.css':{},
  });
  const opened=[];
  const message={id:'m',capture_id:'capture-from-message',attachments:[{asset_id:'asset',image_url:'/api/mobile/assets/asset/image',width:1080,height:1920}]};
  const tree=MobileAttachmentCards({message,onOpen:id=>opened.push(id)});
  function visit(node){if(!React.isValidElement(node))return;if(node.type==='button')node.props.onClick();React.Children.forEach(node.props.children,visit);}
  visit(tree);assert.deepEqual(opened,['capture-from-message']);
  const html=renderToStaticMarkup(tree);assert.match(html,/1080 × 1920/);assert.match(html,/View GPIO photo/);
  assert.equal(renderToStaticMarkup(React.createElement(MobileAttachmentCards,{message:{id:'next'},onOpen(){}})),'');
});

test('viewer UI distinguishes decoding from display and rejects previous-generation phone telemetry',()=>{
  const {MobileVideo}=load('../src/components/MobileCompanion.tsx',{
    react:React,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/mobile':mobile,'../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,'./PhotoWiringPoc':{},'../mobile.css':{},
  });
  const session={session_id:'s',stream:{active:true,publisher_connected:true,generation:3,video_fps:30,video_received_at:Date.now()/1000,video_receive_fresh:true,video_receive_age_ms:0,
    publisher_stats:{generation:3,send_fps:29.7,send_bitrate_kbps:8000,reported_at:Date.now()/1000},
    server_metrics:{updated_at:Date.now()/1000,latency_scope:'server_processing_not_end_to_end',viewer_transports:[{codec:'H264',send_bitrate_kbps:6000,target_bitrate_kbps:8000,encode_ms:3.2,clone_ms:1,encode_fps:29.6}]}}};
  const html=renderToStaticMarkup(React.createElement(MobileVideo,{session}));
  assert.match(html,/Decoded — FPS/);assert.match(html,/Displayed — FPS/);assert.doesNotMatch(html,/<span>Preview /);
  assert.match(html,/Phone upload 29.7 FPS · 8.00 Mbps/);assert.match(html,/Laptop receives 30.0 FPS/);
  assert.match(html,/Encode 3.2 ms \/ 29.6 FPS/);assert.match(html,/not end-to-end latency/);
  for(const changed of [{...session.stream,generation:4},{...session.stream,publisher_stats:{...session.stream.publisher_stats,reported_at:Date.now()/1000-10}}]) {
    const stale=renderToStaticMarkup(React.createElement(MobileVideo,{session:{...session,stream:changed}}));
    assert.match(stale,/Phone upload — FPS · — Mbps/);assert.doesNotMatch(stale,/Phone upload 29.7/);
  }
  const stalled=renderToStaticMarkup(React.createElement(MobileVideo,{session:{...session,stream:{...session.stream,video_received_at:Date.now()/1000-5,recognition_fps:26}}}));
  assert.match(stalled,/Phone upload 29.7 FPS/);assert.match(stalled,/Laptop receives — FPS/);assert.match(stalled,/Recognition — FPS/);
  assert.match(stalled,/Waiting for new phone frames/);assert.doesNotMatch(stalled,/Encode 3.2/);
});

test('main phone preview labels its own source, keeps diagnostics closed and retains capture/return controls',()=>{
  const {MobileMainPreview}=load('../src/components/MobileCompanion.tsx',{
    react:React,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/mobile':mobile,'../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,'./PhotoWiringPoc':{},'../mobile.css':{},
  });
  const session={session_id:'s',stream:{active:true,publisher_connected:true,generation:3}};
  const html=renderToStaticMarkup(React.createElement(MobileMainPreview,{session,readiness:'finding',onReturn(){},
    captureActions:React.createElement('button',null,'Capture phone frame')}));
  assert.match(html,/Main phone stream/);assert.match(html,/Live phone camera/);assert.match(html,/Back to webcam/);
  assert.match(html,/Capture phone frame/);assert.match(html,/<details class="mobile-stream-details">/);
  assert.match(html,/Live YOLO recognition/);assert.doesNotMatch(html,/video-img|pin-overlay/,'No overlay until actual decoded dimensions are known');
  const lost=renderToStaticMarkup(React.createElement(MobileMainPreview,{session:null,readiness:'finding',onReturn(){},captureActions:null}));
  assert.match(lost,/Phone disconnected/);assert.match(lost,/Back to webcam/);assert.doesNotMatch(lost,/<video/);
  const css=readFileSync(new URL('../src/mobile.css',import.meta.url),'utf8');
  assert.match(css,/@media\(max-width:700px\)[\s\S]*video-workspace:has\(> \.mobile-main-preview-host\) \{ flex:none; min-height:0; \}/);
  assert.match(css,/\.mobile-main-preview-host \{ flex:none; min-height:360px; \}/,'narrow layouts reserve space for the phone capture footer');
});

test('desktop capture action is independent of preview lock and keeps capture status visible in photo view',()=>{
  const {MobileStreamCaptureActions}=load('../src/components/MobileCompanion.tsx',{
    react:React,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/mobile':mobile,'../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,'./PhotoWiringPoc':{},'../mobile.css':{},
  });
  const props={live:true,active:true,busy:false,error:'',onCapture(){},onRetry(){}};
  const render=changes=>renderToStaticMarkup(React.createElement(MobileStreamCaptureActions,{...props,...changes}));
  assert.match(render({}),/<button type="button">Capture phone frame<\/button>/);
  assert.match(render({active:false}),/disabled=""/);
  const busy=render({busy:true});assert.match(busy,/disabled=""/);assert.match(busy,/Saving the phone frame and locating GPIO/);
  const switched=render({live:false,busy:true});assert.match(switched,/role="status"/);assert.doesNotMatch(switched,/Capture phone frame<\/button>/);
  const error=render({active:false,error:'network disconnected'});assert.match(error,/Retry the same capture/);assert.match(error,/take a new image/);
  assert.doesNotMatch(error,/<button type="button" disabled="">Retry the same capture/);
  const timedOut=render({error:'mobile_capture_timeout'});assert.match(timedOut,/exceeded 180 seconds/);assert.match(timedOut,/retrieve the same capture/);
  assert.doesNotMatch(timedOut,/mobile_capture_timeout/);
});

test('frozen photo review labels actual capture source and geometry dimensions without a new camera lifecycle',()=>{
  const {MobilePhotoReview}=load('../src/components/MobileCompanion.tsx',{
    react:React,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=> (zh,en)=>en},
    '../lib/mobile':mobile,'../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,
    './PhotoWiringPoc':{PhotoViewport:()=>React.createElement('div',{'data-passive-photo':true})},'../mobile.css':{},
  });
  for(const [source,label] of [['desktop_stream','Desktop capture of phone stream'],['phone_frame','Phone local camera frame'],['camera_photo','Phone camera photo']]) {
    const html=renderToStaticMarkup(React.createElement(MobilePhotoReview,{capture:streamCaptureFixture({capture_source:source}),wireId:null,disabled:false,onWire(){},onAsk(){}}));
    assert.ok(html.includes(`${label} · 1080 × 1920`));assert.match(html,/data-passive-photo="true"/);assert.match(html,/Ask about photo/);
  }
});

function companionLayoutHarness({toolbar=true,paired=true,canShow=true,runEffects=false,pairing=null,error='',connection=undefined,connectionError='',locale='en',configuration={available:true,base_url:'https://fixture.test',web_url:'https://fixture.test/mobile'}}={}) {
  let cursor=0,refCursor=0,effectCursor=0,dirty=false,pending=[],captureDone;
  const values=[],refs=[],effects=[],shown=[],requests=[];
  if(!runEffects){values[7]=streamCaptureFixture();values[8]=values[7].capture_id;
    values[2]={payload:pairing?.web_url??(paired?'https://fixture.test/mobile':''),image:'data:image/png;base64,fixture'};}
  const hooks={...React,
    useEffect(callback,deps){if(!runEffects)return;const i=effectCursor++,old=effects[i];
      if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index])))pending.push(()=>{old?.cleanup?.();effects[i]={deps,cleanup:callback()};});},
    useRef(value){const i=refCursor++;return refs[i]??={current:value};},
    useState(initial){const i=cursor++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;
      return[values[i],value=>{const next=typeof value==='function'?value(values[i]):value;dirty||=!Object.is(next,values[i]);values[i]=next;}];},
  };
  const workspace={trigger:{id:'header'},controls:toolbar?{id:'toolbar'}:null,preview:{id:'preview'},showing:false,canShow,onShow(value){shown.push(value);workspace.showing=value;}};
  let session=paired?{session_id:'s',conversation_id:'chat',base_url:'https://fixture.test',stream:{active:true,publisher_connected:true,generation:1,state:'finding'},view:{capture_id:'cap'},context_id:'ctx'}:null;
  const {MobileCompanion}=load('../src/components/MobileCompanion.tsx',{
    react:hooks,'react/jsx-runtime':jsx,'react-dom':{createPortal:(children,host)=>React.createElement('qa-portal',{host},children)},
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='en'?en:zh},'../lib/mobile':{...mobile,useMobileCompanion:()=>({session,connection,connectionError,pairing,error,pairingBusy:false,
      webConfiguration:configuration,
      pair:async(baseUrl)=>{requests.push({path:'pairings',method:'POST',baseUrl});
        const origin=mobile.mobileAddressOrigin(baseUrl)||mobile.mobileWebOrigin(configuration);
        pairing={code:'591204',web_url:origin+'/mobile?code=591204',base_url:origin,base_urls:[],expires_at:Date.now()/1000+300};}}),
      mobileRequest:async(path,options)=>{requests.push({path,...options});return path==='web-config'
        ? configuration
        : streamCaptureFixture({capture_id:decodeURIComponent(path.split('/').at(-1))});},
      useDesktopStreamCapture:(_session,onCapture)=>{captureDone=onCapture;return{busy:false,error:'',capture(){assert.fail('No photo operation');},retry(){assert.fail('No retry');}};}},
    '../lib/mobileViewerStats':viewerStats,'../lib/photoWiring':photo,'./PhotoWiringPoc':{},'./ImageViewControls':{ImageSourceSelect:()=>null},'../mobile.css':{},
    qrcode:{toDataURL:async()=> 'data:image/png;base64,fixture'},
  });
  const render=(selection=null)=>{let tree,passes=0;do{
    cursor=refCursor=effectCursor=0;dirty=false;
    tree=MobileCompanion({controller:{project:{},mobileContext:{conversation_id:'chat'},busy:false,demoOpen:false},aiReady:true,selection,workspace});
    const tasks=pending;pending=[];tasks.forEach(task=>task());
    assert.ok(++passes<20,'companion effects must settle');
  }while(runEffects&&dirty);return tree;};
  const nodes=(tree,predicate)=>{const found=[];function visit(node){if(!React.isValidElement(node))return;if(predicate(node))found.push(node);React.Children.forEach(node.props.children,visit);}visit(tree);return found;};
  return{render,nodes,workspace,shown,requests,setConfiguration(next){configuration=next;},setPairing(next){pairing=next;},setSession(next){if(next?.session_id!==session?.session_id)pairing=null;session=next;},capture(next){captureDone(next);},unmount(){effects.forEach(effect=>effect.cleanup?.());}};
}

test('restoring a saved GPIO photo never selects or opens it on refresh',t=>{
  for(const paired of [true,false]){
    const h=companionLayoutHarness({paired,runEffects:true});t.after(()=>h.unmount());h.render();
    h.setSession({session_id:'s',stream:{active:false,generation:1},view:{capture_id:'cap'},context_id:'ctx'});
    const tree=h.render(),photo=h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0];
    assert.equal(photo.props.disabled,false,'the saved photo remains available');
    assert.equal(photo.props['aria-pressed'],false);
    assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,0);
    assert.deepEqual(h.shown,[],'restoring a photo does not switch camera source');
    assert.equal(h.requests.at(-1).path,'captures/cap');
  }
});

test('restored GPIO photos still open on an explicit toolbar or attachment click',t=>{
  for(const attachment of [false,true]){
    const h=companionLayoutHarness({runEffects:true});t.after(()=>h.unmount());let tree=h.render();
    if(!attachment)h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0].props.onClick();
    tree=h.render(attachment?{id:'cap',nonce:1}:null);
    assert.equal(h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0].props['aria-pressed'],true);
    assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,1);
  }
});

test('new phone and desktop captures still open GPIO photos after initial restoration',t=>{
  for(const desktop of [false,true]){
    const h=companionLayoutHarness({runEffects:true});t.after(()=>h.unmount());h.render();
    if(desktop)h.capture(streamCaptureFixture({capture_id:'new'}));
    else h.setSession({session_id:'s',stream:{active:false,generation:1},view:{capture_id:'new'},context_id:'ctx'});
    let tree=h.render();
    assert.equal(h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0].props['aria-pressed'],true);
    h.nodes(tree,n=>n.type==='button'&&n.props['aria-label']==='Close phone panel')[0].props.onClick();
    tree=h.render();assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,0,'unchanged photo is not reopened');
  }
});

test('reconnecting a session restores its photo without reopening the photo panel',t=>{
  const h=companionLayoutHarness({runEffects:true});t.after(()=>h.unmount());h.render();
  h.setSession(null);h.render();
  h.setSession({session_id:'reconnected',stream:{active:false,generation:1},view:{capture_id:'saved'},context_id:'ctx'});
  const tree=h.render();assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,0);
  assert.equal(h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0].props['aria-pressed'],false);
});

test('relocated phone views use a toolbar portal, open the canonical photo and never duplicate panel tabs',()=>{
  const h=companionLayoutHarness();let tree=h.render();
  const header=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0];
  assert.equal(header.props.children.props.className,'mobile-connect-button');
  const controls=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.controls)[0];
  const buttons=h.nodes(controls,n=>n.type==='button');assert.deepEqual(buttons.map(n=>n.props.children),['Phone stream','GPIO photo']);
  buttons[0].props.onClick();assert.deepEqual(h.shown,[true]);tree=h.render();
  assert.equal(h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.preview).length,1);
  buttons[1].props.onClick();tree=h.render();const panel=h.nodes(tree,n=>n.type==='section'&&n.props.id==='mobile-companion-panel')[0];
  assert.ok(panel);assert.equal(h.nodes(panel,n=>n.props.className==='mobile-view-tabs').length,0);
  assert.equal(h.nodes(panel,n=>n.type?.name==='MobilePhotoReview').length,1);
  assert.equal(h.workspace.showing,true,'reviewing a photo does not stop the main stream');
  for(const options of [{paired:false},{canShow:false}]) {
    const disabled=companionLayoutHarness(options),rendered=disabled.render();
    const portal=disabled.nodes(rendered,n=>n.type==='qa-portal'&&n.props.host===disabled.workspace.controls)[0];
    assert.equal(disabled.nodes(portal,n=>n.type==='button')[0].props.disabled,true);
  }
});

test('shared GPIO workspace receives desktop phone captures without opening a duplicate photo panel',()=>{
  const h=companionLayoutHarness(),photos=[];
  h.workspace.onPhoto=(capture,show,context)=>photos.push({capture,show,context});
  let tree=h.render();
  const portal=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.controls)[0];
  assert.deepEqual(h.nodes(portal,n=>n.type==='button').map(n=>n.props.children),['Phone stream']);
  const capture=streamCaptureFixture({capture_id:'new'});h.capture(capture);tree=h.render();
  assert.equal(photos.length,1);assert.equal(photos[0].capture,capture);assert.equal(photos[0].show,true);
  assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,0);
  assert.deepEqual(h.shown,[],'App selects the shared photo view, not another video receiver');
});

test('restored photos are passive in shared workspace; explicit attachment selection displays them',async t=>{
  const h=companionLayoutHarness({runEffects:true}),photos=[];t.after(()=>h.unmount());
  h.workspace.onPhoto=(capture,show,context)=>photos.push({capture,show,context});
  h.render();await Promise.resolve();await Promise.resolve();h.render();
  assert.equal(photos[0].show,false);
  const tree=h.render({id:'cap',nonce:1});
  assert.equal(photos.at(-1).show,true);assert.equal(photos.at(-1).capture.capture_id,'cap');
  assert.equal(h.nodes(tree,n=>n.props.id==='mobile-companion-panel').length,0);
});

test('global phone entry shows only QR and connection status, never a second video receiver',async t=>{
  const pairing={code:'482913',web_url:'https://fixture.test/mobile?code=482913',base_url:'https://fixture.test',base_urls:[],expires_at:Date.now()/1000+300};
  const h=companionLayoutHarness({toolbar:false,pairing,runEffects:true});t.after(()=>h.unmount());let tree=h.render();
  const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
  trigger.props.onClick();tree=h.render();for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}const panel=h.nodes(tree,n=>n.type==='section'&&n.props.id==='mobile-companion-panel')[0];
  assert.ok(panel);assert.match(panel.props.className,/is-connection/);
  assert.equal(h.nodes(panel,n=>n.props.className==='mobile-view-tabs').length,0);
  assert.equal(h.nodes(panel,n=>n.type?.name==='MobileVideo'||n.type?.name==='MobilePhotoReview'||n.type?.name==='MobileStreamCaptureActions').length,0);
  const qr=h.nodes(panel,n=>n.type==='img'&&n.props.alt==='Phone pairing QR code')[0];assert.ok(qr);
  const link=h.nodes(panel,n=>n.type==='a')[0];assert.equal(link.props.href,'https://fixture.test/mobile?code=482913');
  assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-code')[0].props.children,'482913');
  assert.deepEqual(h.shown,[],'QR entry must not switch the camera source');
  assert.equal(h.requests.some(r=>r.method==='POST'),false,'reuse the valid invitation without stopping the stream');
  assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-status')[0].props['data-connected'],true);
});

test('header opens QR from photo review without closing the existing main preview',()=>{
  const h=companionLayoutHarness();let tree=h.render();h.workspace.showing=true;
  h.nodes(tree,n=>n.type==='button'&&n.props.children==='GPIO photo')[0].props.onClick();tree=h.render();
  const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
  assert.equal(trigger.props['aria-expanded'],false);
  trigger.props.onClick();tree=h.render();
  const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];assert.match(panel.props.className,/is-connection/);
  assert.equal(h.nodes(panel,n=>n.type?.name==='MobilePhotoReview').length,0);
  assert.equal(h.workspace.showing,true);assert.deepEqual(h.shown,[]);
  assert.equal(h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.preview).length,1);
});

test('unpaired QR keeps pairing code and setup help but no camera controls, in both languages',async t=>{
  const pairing={code:'482913',web_url:'https://fixture.test/mobile?code=482913',base_url:'https://fixture.test',base_urls:[],expires_at:Date.now()/1000+300};
  for(const locale of ['en','zh-TW']){
    const h=companionLayoutHarness({paired:false,pairing,locale,runEffects:true});t.after(()=>h.unmount());let tree=h.render();
    h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children.props.onClick();tree=h.render();
    for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}
    const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
    assert.equal(h.nodes(panel,n=>n.type==='img').length,1);
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-code')[0].props.children,'482913');
    const help=h.nodes(panel,n=>n.type==='details')[0];assert.equal(help.props.open,undefined);
    assert.equal(h.nodes(panel,n=>n.type?.name==='MobileVideo'||n.type?.name==='MobileStreamCaptureActions').length,0);
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-status')[0].props['data-connected'],false);
    assert.equal(h.requests.some(r=>r.method==='POST'),false,'reuse the current valid pairing');
  }
});

test('connection polling failure is unknown rather than a stale green connected state',()=>{
  const h=companionLayoutHarness({error:'Network unavailable'});let tree=h.render();
  const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
  assert.equal(trigger.props['data-connected'],false);assert.equal(trigger.props['aria-label'],'Phone connection status unavailable');
  trigger.props.onClick();tree=h.render();const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
  assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-status')[0].props['data-connected'],false);
  assert.match(renderToStaticMarkup(panel),/Connection status unavailable|Network unavailable/);
});

test('a connected phone on another project stays green without granting photo or stream actions',()=>{
  for(const locale of ['en','zh-TW']) {
    const connection={session_id:'old-phone',conversation_id:'old-project',context_id:'old-context',title:'Old project'};
    const h=companionLayoutHarness({paired:false,connection,locale});let tree=h.render();
    const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
    assert.equal(trigger.props['data-connected'],true);
    assert.equal(trigger.props['aria-label'],locale==='en'?'Phone connected, current project not synced':'手機已連接，尚未同步目前作品');
    trigger.props.onClick();tree=h.render();
    const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-status')[0].props['data-connected'],true);
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-project-sync').length,1);
    assert.equal(h.nodes(tree,n=>n.type==='button'&&n.props.children===(locale==='en'?'Phone stream':'手機串流'))[0].props.disabled,true);
    assert.equal(h.nodes(tree,n=>n.type==='button'&&n.props.children===(locale==='en'?'GPIO photo':'GPIO 照片'))[0].props.disabled,true);
    assert.deepEqual(h.shown,[],'a connection badge cannot switch the camera');
  }
});

test('explicit offline presence overrides retained pairing, and status failure stays unknown',()=>{
  for(const connectionError of ['', 'Network unavailable']) {
    const h=companionLayoutHarness({connection:null,connectionError});let tree=h.render();
    const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
    assert.equal(trigger.props['data-connected'],false);
    trigger.props.onClick();tree=h.render();
    const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
    assert.match(renderToStaticMarkup(panel),connectionError?/Connection status unavailable/:/Phone paired, currently offline/);
  }
});

test('opening an expired invitation hides its old code and refreshes QR and code together',async t=>{
  const pairing={code:'482913',web_url:'https://fixture.test/mobile?code=482913',base_url:'https://fixture.test',base_urls:[],expires_at:Date.now()/1000-1};
  const h=companionLayoutHarness({paired:false,pairing,runEffects:true});t.after(()=>h.unmount());let tree=h.render();
  h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children.props.onClick();tree=h.render();
  const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
  assert.match(renderToStaticMarkup(panel),/Pairing code expired/);
  assert.equal(h.nodes(panel,n=>n.type==='img').length,0);
  assert.equal(h.nodes(panel,n=>n.type==='a').length,0,'expired invitations must not remain clickable');
  for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}
  assert.equal(h.requests.filter(r=>r.path==='pairings').length,1);
  const refreshed=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
  assert.equal(h.nodes(refreshed,n=>n.props.className==='mobile-pairing-code')[0].props.children,'591204');
  assert.equal(h.nodes(refreshed,n=>n.type==='a')[0].props.href,'https://fixture.test/mobile?code=591204');
  assert.equal(h.nodes(refreshed,n=>n.type?.name==='MobileVideo'||n.type?.name==='MobileStreamCaptureActions').length,0);
});

test('opening after a code is consumed creates a new invitation without disconnecting the phone',async t=>{
  const h=companionLayoutHarness({paired:false,runEffects:true});t.after(()=>h.unmount());let tree=h.render();
  const trigger=()=>h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
  trigger().props.onClick();tree=h.render();for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}
  assert.equal(h.requests.filter(r=>r.path==='pairings').length,1);
  h.setSession({session_id:'new',base_url:'https://fixture.test',stream:{active:true,publisher_connected:true,generation:1},view:{capture_id:null},context_id:'ctx'});tree=h.render();
  trigger().props.onClick();tree=h.render();trigger().props.onClick();tree=h.render();for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}
  assert.equal(h.requests.filter(r=>r.path==='pairings').length,2);
  assert.equal(h.nodes(tree,n=>n.props.className==='mobile-pairing-code')[0].props.children,'591204');
  assert.ok(h.requests.every(r=>['web-config','pairings'].includes(r.path)),'no stream or disconnect operation');
  assert.deepEqual(h.shown,[]);
});

test('connected phones show QR plus a readable pairing code in both languages',async()=>{
  for(const locale of ['en','zh-TW']){
    const h=companionLayoutHarness({locale,runEffects:true});let tree=h.render();
    h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children.props.onClick();
    for(let i=0;i<8;i++){await Promise.resolve();tree=h.render();}
    const panel=h.nodes(tree,n=>n.props.id==='mobile-companion-panel')[0];
    assert.equal(h.nodes(panel,n=>n.type==='img').length,1);
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-code')[0].props.children,'591204');
    assert.equal(h.nodes(panel,n=>n.type==='a')[0].props.href,'https://fixture.test/mobile?code=591204');
    assert.equal(h.requests.filter(r=>r.path==='pairings').length,1);
    assert.equal(h.nodes(panel,n=>n.props.className==='mobile-pairing-status')[0].props['data-connected'],true);
    h.unmount();
  }
});

function pairingHookHarness(t) {
  let cursor=0,refCursor=0,effectCursor=0,pending=[],state={session:null},resolvePairing,pollError='';
  let configuration={available:true,base_url:'https://fixture.test',web_url:'https://fixture.test/mobile'};
  const configurationReplies=[];
  const values=[],refs=[],effects=[],sockets=[],requests=[],timers=[];
  const invitation={code:'482913',web_url:'https://fixture.test/mobile?code=482913',base_url:'https://fixture.test',expires_at:Date.now()/1000+300,base_urls:[]};
  const hooks={...React,useCallback:callback=>callback,
    useState(initial){const i=cursor++;if(!(i in values))values[i]=initial;return[values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value;}];},
    useRef(initial){return refs[refCursor++]??={current:initial};},
    useEffect(callback,deps){const i=effectCursor++,old=effects[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index])))
      pending.push(()=>{old?.cleanup?.();effects[i]={deps,cleanup:callback()};});},
  };
  const names=['window','WebSocket','fetch','setTimeout','clearTimeout'];
  const descriptors=names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]);
  globalThis.window={location:{href:'http://fixture.test/'}};
  globalThis.WebSocket=class {constructor(){sockets.push(this);}close(){}};
  globalThis.setTimeout=(callback,delay)=>{const id=timers.length+1;timers.push({id,callback,delay,cancelled:false});return id;};
  globalThis.clearTimeout=id=>{const timer=timers.find(item=>item.id===id);if(timer)timer.cancelled=true;};
  globalThis.fetch=async(path,options)=>{
    requests.push({path,method:options.method,cache:options.cache,body:options.body?JSON.parse(options.body):undefined});
    if(path.includes('desktop-session')&&pollError)throw Error(pollError);
    const value=path.includes('desktop-session')?state:path.endsWith('web-config')
      ? configurationReplies.length?await configurationReplies.shift():configuration:path.endsWith('pairings')
      ? await new Promise(resolve=>{const origin=JSON.parse(options.body).base_url;resolvePairing=next=>resolve(next??{...invitation,base_url:origin,web_url:origin+'/mobile?code='+invitation.code});}) : {context_id:'ctx'};
    return{ok:true,status:200,json:async()=>value};
  };
  t.after(()=>{effects.forEach(effect=>effect.cleanup?.());for(const[name,descriptor]of descriptors){
    if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}});
  const {useMobileCompanion}=load('../src/lib/mobile.ts',{react:hooks,'./photoWiring':photo,'./mobileBrowserRtc':browserRtc,'./mobileViewerStats':viewerStats,'./mobileRecognition':recognition});
  const context={conversation_id:'chat'};
  const render=(currentContext=context)=>{cursor=refCursor=effectCursor=0;const result=useMobileCompanion(currentContext,true);const tasks=pending;pending=[];tasks.forEach(task=>task());return result;};
  const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();return render();};
  return{render,tick,requests,resolve(next){assert.ok(resolvePairing);resolvePairing(next);},
    setConfiguration(next){configuration=next;},queueConfiguration(promise){configurationReplies.push(promise);},
    pollState(value){state=value;},
    failPoll(message){pollError=message;},
    poll(){const timer=timers.findLast(item=>item.delay===5000&&!item.cancelled);assert.ok(timer);timer.cancelled=true;timer.callback();},
    accept(session){state={session};sockets.at(-1).onmessage({data:JSON.stringify(state)});},
    session(id='phone'){return{session_id:id,conversation_id:'chat',context_id:'ctx',stream:{active:true,generation:1},view:{capture_id:null,revision:0}};}};
}

test('an existing phone heartbeat preserves its new invitation, but a new paired session consumes it',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.accept(h.session());
  const creating=h.render().pair();await h.tick();h.resolve();await creating;
  assert.equal(h.render().pairing.code,'482913');
  h.accept({...h.session(),stream:{active:true,generation:1,preview_seq:5}});
  assert.equal(h.render().pairing.code,'482913','same phone does not erase the displayed code');
  h.accept(h.session('new-phone'));
  assert.equal(h.render().pairing,null,'consumed code must not be presented as valid');
  assert.equal(h.render().session.session_id,'new-phone');
  assert.equal(h.requests.some(r=>r.method==='DELETE'||r.path.includes('/stream')),false);
});

test('pairing requests are single-flight and a late response cannot restore a consumed invitation',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.accept(h.session());
  const current=h.render(),creating=current.pair();await current.pair();await h.tick();
  assert.equal(h.requests.filter(r=>r.path.endsWith('pairings')).length,1);
  h.accept(h.session('new-phone'));h.resolve();await creating;
  assert.equal(h.render().pairing,null);
  assert.equal(h.render().session.session_id,'new-phone');
});

const lanConfiguration=(ip,available=true)=>({available,base_url:`https://${ip}:8443`,web_url:`https://${ip}:8443/mobile`});
const lanInvitation=ip=>({code:'482913',base_url:`https://${ip}:8443`,web_url:`https://${ip}:8443/mobile?code=482913`,
  expires_at:Date.now()/1000+300,base_urls:[]});
async function settleCompanion(h){let tree;for(let i=0;i<12;i++){await Promise.resolve();tree=h.render();}return tree;}
function openConnection(h,tree){h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children.props.onClick();return h.render();}

test('automatic pairing reads the fresh HTTPS origin before and after POST with no browser cache',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.setConfiguration(lanConfiguration('192.168.50.138'));
  const operation=h.render().pair();await h.tick();
  const post=h.requests.find(r=>r.path.endsWith('/pairings'));
  assert.equal(post.body.base_url,'https://192.168.50.138:8443');
  h.resolve();await operation;
  assert.equal(h.render().pairing.base_url,'https://192.168.50.138:8443');
  const reads=h.requests.filter(r=>r.path.endsWith('/web-config'));
  assert.equal(reads.length,2);assert.ok(reads.every(r=>r.cache==='no-store'));
  assert.equal(h.requests.some(r=>r.method==='DELETE'||r.path.includes('/stream')),false);
});

test('a network change during pairing cannot restore an old-IP code; the new origin can pair',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.setConfiguration(lanConfiguration('192.168.50.141'));
  const old=h.render().pair();await h.tick();
  h.setConfiguration(lanConfiguration('192.168.50.138'));await h.render().refreshWebConfiguration();
  h.resolve();await old;
  assert.equal(h.render().pairing,null);
  assert.equal(h.render().webConfiguration.base_url,'https://192.168.50.138:8443');
  const fresh=h.render().pair();await h.tick();h.resolve();await fresh;
  assert.equal(h.render().pairing.base_url,'https://192.168.50.138:8443');
  assert.deepEqual(h.requests.filter(r=>r.path.endsWith('/pairings')).map(r=>r.body.base_url),
    ['https://192.168.50.141:8443','https://192.168.50.138:8443']);
});

test('a late configuration response cannot overwrite a newer ready origin or revive its invitation',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();
  let resolve;h.queueConfiguration(new Promise(done=>resolve=done));
  const stale=h.render().refreshWebConfiguration();await h.tick();
  h.setConfiguration(lanConfiguration('192.168.50.138'));await h.render().refreshWebConfiguration();
  resolve(lanConfiguration('192.168.50.141'));await stale;
  assert.equal(h.render().webConfiguration.base_url,'https://192.168.50.138:8443');
  assert.equal(h.render().pairing,null);
});

test('an unavailable automatic HTTPS entry creates no invitation and does not fall back to a session IP',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.accept({...h.session(),base_url:'https://192.168.50.141:8443'});
  h.setConfiguration(lanConfiguration('192.168.50.138',false));await h.render().pair();
  assert.equal(h.render().pairing,null);assert.equal(h.requests.filter(r=>r.path.endsWith('/pairings')).length,0);
  assert.equal(h.render().error,'mobile_web_https_unavailable');
});

test('an explicit advanced address remains authoritative when automatic HTTPS is unavailable',async t=>{
  const h=pairingHookHarness(t);h.render();await h.tick();h.setConfiguration(lanConfiguration('192.168.50.138',false));
  const operation=h.render().pair('  https://manual.example:8443  ');await h.tick();h.resolve();await operation;
  assert.equal(h.render().pairing.base_url,'https://manual.example:8443');
  assert.equal(h.requests.filter(r=>r.path.endsWith('/web-config')).length,0);
  await h.render().refreshWebConfiguration();
  assert.equal(h.render().pairing.base_url,'https://manual.example:8443','automatic refresh does not replace an explicit override');
});

test('reopening the panel hides a cached old-IP QR until this opening has read the latest configuration',async t=>{
  const h=companionLayoutHarness({runEffects:true,pairing:lanInvitation('192.168.50.141'),configuration:lanConfiguration('192.168.50.141')});t.after(()=>h.unmount());
  let tree=openConnection(h,h.render());
  assert.equal(h.nodes(tree,n=>n.type==='a').length,0,'no cached link while opening configuration is pending');
  tree=await settleCompanion(h);
  assert.equal(h.nodes(tree,n=>n.type==='a')[0].props.href,'https://192.168.50.141:8443/mobile?code=482913');
  tree=openConnection(h,tree);h.setConfiguration(lanConfiguration('192.168.50.138'));
  tree=openConnection(h,tree);
  assert.equal(h.nodes(tree,n=>n.type==='a').length,0,'old invitation must not flash on reopen');
  tree=await settleCompanion(h);
  assert.equal(h.nodes(tree,n=>n.type==='a')[0].props.href,'https://192.168.50.138:8443/mobile?code=591204');
  assert.equal(h.requests.filter(r=>r.path==='pairings').length,1);
});

test('a ready new origin replaces QR and link once; unavailable state hides both without affecting cameras',async t=>{
  const h=companionLayoutHarness({runEffects:true,pairing:lanInvitation('192.168.50.141'),configuration:lanConfiguration('192.168.50.141')});t.after(()=>h.unmount());
  let tree=openConnection(h,h.render());tree=await settleCompanion(h);
  h.setConfiguration(lanConfiguration('192.168.50.138',false));tree=h.render();
  assert.equal(h.nodes(tree,n=>n.type==='a').length,0);assert.equal(h.nodes(tree,n=>n.type==='img').length,0);
  h.setConfiguration(lanConfiguration('192.168.50.138'));tree=h.render();tree=await settleCompanion(h);
  assert.equal(h.nodes(tree,n=>n.type==='a')[0].props.href,'https://192.168.50.138:8443/mobile?code=591204');
  const posts=h.requests.filter(r=>r.path==='pairings').length;
  for(let i=0;i<4;i++){h.setConfiguration({...lanConfiguration('192.168.50.138')});tree=h.render();tree=await settleCompanion(h);}
  assert.equal(h.requests.filter(r=>r.path==='pairings').length,posts,'unchanged origin never rotates a still-valid code');
  h.setPairing(lanInvitation('192.168.50.141'));tree=h.render();
  assert.equal(h.nodes(tree,n=>n.type==='a')[0].props.href,'https://192.168.50.138:8443/mobile','late old pairing cannot revive an old URL');
  assert.ok(h.requests.every(r=>['web-config','pairings'].includes(r.path)||r.path.startsWith('captures/')));
  assert.equal(h.requests.some(r=>r.method==='DELETE'||r.path.includes('/stream')),false);assert.deepEqual(h.shown,[]);
});

test('connection summaries are whitelisted and cannot become a project session',()=>{
  const connection={session_id:'phone',conversation_id:'old',context_id:'ctx',title:'Old project'};
  assert.deepEqual(mobile.mobileConnectionFromState({connection:{...connection,token:'secret',context:{private:true}}}),connection);
  assert.equal(mobile.mobileStateForConversation({session:null,connection},'new'),null);
  assert.equal(mobile.mobileConnectionFromState({session:null}),undefined,'older backend compatibility');
  assert.equal(mobile.mobileConnectionFromState({connection:null}),null);
  assert.equal(mobile.mobileConnectionFromState({connection:{...connection,session_id:''}}),null);
});

test('a global connection never becomes a scoped session or authorizes photo messages',async t=>{
  const h=pairingHookHarness(t);
  const connection={session_id:'old-phone',conversation_id:'old-project',context_id:'old-context',title:'Old project'};
  h.pollState({session:null,connection});h.render();await h.tick();
  const current=h.render();assert.equal(current.session,null);assert.deepEqual(current.connection,connection);
  await assert.rejects(current.sendPhoto({}),/Phone is not connected/);
  assert.equal(h.requests.some(request=>request.path.endsWith('messages')),false);
});

test('global status failures revoke green and scoped websocket events cannot hide that failure',async t=>{
  const h=pairingHookHarness(t),connection={session_id:'phone',conversation_id:'chat',context_id:'ctx',title:'Project'};
  h.pollState({session:h.session(),connection});h.render();await h.tick();
  assert.deepEqual(h.render().connection,connection);
  h.failPoll('Network unavailable');h.poll();await h.tick();
  assert.equal(h.render().connection,null);assert.equal(h.render().connectionError,'Network unavailable');
  h.accept(h.session());assert.equal(h.render().error,'');
  assert.equal(h.render().connection,null);assert.equal(h.render().connectionError,'Network unavailable');
  h.failPoll('');h.pollState({session:h.session(),connection});h.poll();await h.tick();
  assert.deepEqual(h.render().connection,connection);assert.equal(h.render().connectionError,'');
});

test('changing desktop projects preserves device presence without retaining a foreign project session',async t=>{
  const h=pairingHookHarness(t),connection={session_id:'phone',conversation_id:'chat',context_id:'ctx',title:'Project'};
  h.pollState({session:h.session(),connection});h.render();await h.tick();
  h.pollState({session:null,connection});
  const current=h.render({conversation_id:'new-project'});
  assert.equal(current.session,null);assert.deepEqual(current.connection,connection);
});

test('grouped phone button keeps a full accessible name and a compact status independent of Pi',()=>{
  for(const paired of [true,false]) {
    const h=companionLayoutHarness({paired}),tree=h.render();
    const trigger=h.nodes(tree,n=>n.type==='qa-portal'&&n.props.host===h.workspace.trigger)[0].props.children;
    assert.equal(trigger.props['aria-label'],paired?'Phone connected':'Connect phone');
    assert.equal(trigger.props['data-connected'],paired);
    assert.equal(trigger.props['aria-controls'],'mobile-companion-panel');
    const html=renderToStaticMarkup(trigger);
    assert.ok(html.includes(`<span class="mobile-connection-label">${paired?'Connected':'Connect'}</span>`));
    assert.match(html,/mobile-connection-dot" aria-hidden="true"/);
    assert.doesNotMatch(html,/Pi|runtime|execution/);
  }
});

function followedPhone(overrides={}) {
  return {session_id:'selected-phone',conversation_id:'project',context_id:'context-a',
    stream:{active:true,generation:1,video_receive_fresh:true,video_received_at:200,video_receive_age_ms:0},
    ...overrides};
}

test('selected phone establishes a source baseline without repeating the initial camera selection',t=>{
  t.mock.method(Date,'now',()=>200000);
  const session=followedPhone();
  const baseline=mobile.followMobileSource(null,session,true,true);
  assert.ok(baseline.key);assert.equal(baseline.reselect,false);
  assert.deepEqual(mobile.followMobileSource(baseline.key,session,true,true),baseline);
  assert.deepEqual(mobile.followMobileSource(baseline.key,null,true,true),baseline,'Missing status cannot invent a new source');
});

test('new phone generation waits for actual fresh video and an idle camera transaction',t=>{
  t.mock.method(Date,'now',()=>200000);
  const first=followedPhone(),baseline=mobile.followMobileSource(null,first,true,true);
  const next=followedPhone({stream:{...first.stream,generation:2}});
  for(const changed of [{video_receive_fresh:false},{active:false},{video_received_at:198},{video_received_at:null},{video_receive_age_ms:1501}]) {
    assert.deepEqual(mobile.followMobileSource(baseline.key,{...next,stream:{...next.stream,...changed}},true,true),baseline,
      'The pending generation must not consume its key before fresh frames arrive');
  }
  assert.deepEqual(mobile.followMobileSource(baseline.key,next,true,false),baseline,'Busy leaves the source pending');
  const selected=mobile.followMobileSource(baseline.key,next,true,true);
  assert.equal(selected.reselect,true);assert.notEqual(selected.key,baseline.key);
  assert.deepEqual(mobile.followMobileSource(selected.key,next,true,true),{key:selected.key,reselect:false});
});

test('repeated websocket telemetry for one followed generation never retriggers source selection',t=>{
  t.mock.method(Date,'now',()=>200000);
  const initial=followedPhone();let key=mobile.followMobileSource(null,initial,true,true).key,calls=0;
  for(let sample=1;sample<=20;sample++) {
    const session=followedPhone({stream:{...initial.stream,generation:2,received_frames:sample*30,
      preview_seq:sample,video_fps:sample%2?29.8:30,recognition_fps:sample}});
    const next=mobile.followMobileSource(key,session,true,true);
    key=next.key;calls+=Number(next.reselect);
  }
  assert.equal(calls,1);
});

test('choosing webcam clears the follower and new phone generations cannot switch it back',t=>{
  t.mock.method(Date,'now',()=>200000);
  const session=followedPhone();const baseline=mobile.followMobileSource(null,session,true,true);
  let next=mobile.followMobileSource(baseline.key,session,false,true);
  assert.deepEqual(next,{key:null,reselect:false});
  for(const generation of [2,3,4]) {
    next=mobile.followMobileSource(next.key,followedPhone({stream:{...session.stream,generation}}),false,true);
    assert.deepEqual(next,{key:null,reselect:false});
  }
  const manualSelection=mobile.followMobileSource(next.key,session,true,true);
  assert.ok(manualSelection.key);assert.equal(manualSelection.reselect,false,'The explicit camera transaction already selected the phone');
});

test('repaired phone session is followed only when the phone source remains selected',t=>{
  t.mock.method(Date,'now',()=>200000);
  const original=followedPhone();const baseline=mobile.followMobileSource(null,original,true,true);
  const repaired=followedPhone({session_id:'replacement-phone'});
  const waiting=mobile.followMobileSource(baseline.key,null,true,true);
  assert.equal(waiting.key,baseline.key);assert.equal(waiting.reselect,false);
  const next=mobile.followMobileSource(waiting.key,repaired,true,true);
  assert.equal(next.reselect,true);assert.notEqual(next.key,baseline.key);
  assert.equal(mobile.followMobileSource(next.key,repaired,true,true).reselect,false);
  assert.deepEqual(mobile.followMobileSource(baseline.key,repaired,false,true),{key:null,reselect:false});
});

test('source follower distinguishes contexts even when session and generation match',t=>{
  t.mock.method(Date,'now',()=>200000);
  const original=followedPhone();const baseline=mobile.followMobileSource(null,original,true,true);
  const changed=followedPhone({context_id:'context-b'});
  assert.deepEqual(mobile.followMobileSource(baseline.key,changed,true,false),baseline);
  const next=mobile.followMobileSource(baseline.key,changed,true,true);
  assert.equal(next.reselect,true);assert.notEqual(next.key,baseline.key);
  assert.equal(mobile.followMobileSource(next.key,{...changed,title:'same-context-new-title'},true,true).reselect,false);
});

function sourceFollowHarness(t) {
  let now=200000;
  t.mock.method(Date,'now',()=>now);
  const h=companionLayoutHarness({runEffects:true});t.after(()=>h.unmount());
  const calls=[];
  h.workspace.showing=true;
  h.workspace.onShow=(show,session,current)=>new Promise(resolve=>calls.push({show,session,current,resolve}));
  const sample=(generation=1,changes={})=>{
    const session={...followedPhone(),session_id:'s',base_url:'https://fixture.test',view:{capture_id:null,revision:1},
      stream:{...followedPhone().stream,generation,video_received_at:now/1000},...changes};
    h.setSession(session);h.render();return session;
  };
  sample();assert.equal(calls.length,0);
  return {h,calls,sample,advance(ms){now+=ms;},async settle(index,result){calls[index].resolve(result);for(let i=0;i<4;i++)await Promise.resolve();}};
}

test('real companion commits a followed source only on success and retries one failure after five seconds',async t=>{
  const f=sourceFollowHarness(t);f.sample(2);assert.equal(f.calls.length,1);
  for(let i=0;i<5;i++){f.advance(100);f.sample(2);}assert.equal(f.calls.length,1,'One transaction owns all repeated websocket samples');
  await f.settle(0,false);
  f.advance(4999);f.sample(2);assert.equal(f.calls.length,1);
  f.advance(1);f.sample(2);assert.equal(f.calls.length,2);
  assert.equal(f.calls[1].current(),true);
  await f.settle(1,true);
  f.advance(10000);f.sample(2);assert.equal(f.calls.length,2,'Successful generation is consumed exactly once');
});

test('real companion stops automatic retries after two failures and allows a distinct new generation',async t=>{
  const f=sourceFollowHarness(t);f.sample(2);await f.settle(0,false);
  f.advance(5000);f.sample(2);await f.settle(1,false);
  for(let i=0;i<4;i++){f.advance(10000);f.sample(2);}assert.equal(f.calls.length,2);
  f.sample(3);assert.equal(f.calls.length,3);await f.settle(2,true);
});

test('real companion invalidates late transaction continuations on webcam, stop, context, generation and unmount',async t=>{
  for(const reason of ['webcam','stop','context','generation','unmount']) {
    const f=sourceFollowHarness(t);f.sample(2);assert.equal(f.calls[0].current(),true);
    if(reason==='webcam'){f.h.workspace.showing=false;f.h.render();}
    else if(reason==='stop')f.sample(2,{stream:{...followedPhone().stream,generation:2,active:false}});
    else if(reason==='context')f.sample(2,{context_id:'changed'});
    else if(reason==='generation')f.sample(3);
    else f.h.unmount();
    assert.equal(f.calls[0].current(),false,reason);
    await f.settle(0,true);
    if(reason==='webcam'){f.advance(5000);f.sample(3);assert.equal(f.calls.length,1,'Late success cannot select the phone again');}
  }
});

test('returning to guide follows a portrait generation newer than the actual selected backend source',async t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:1};
  f.h.workspace.showing=false;f.h.render();
  f.sample(2);assert.equal(f.calls.length,0,'No source switch while the guide phone view is hidden');
  f.h.workspace.showing=true;f.h.render();
  assert.equal(f.calls.length,1);assert.equal(f.calls[0].session.stream.generation,2);
  await f.settle(0,true);
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:2};
  f.advance(1000);f.sample(2);assert.equal(f.calls.length,1);
});

test('returning to guide with the same backend source does not reopen the camera',t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:1};
  f.h.workspace.showing=false;f.h.render();
  f.advance(1000);f.sample(1);
  f.h.workspace.showing=true;f.h.render();
  assert.equal(f.calls.length,0);
});

test('returning to guide without a session waits before comparing the actual backend source',async t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:1};
  f.h.workspace.showing=false;f.h.render();
  f.h.setSession(null);f.h.render();
  f.h.workspace.showing=true;f.h.render();
  assert.equal(f.calls.length,0);
  f.sample(2);assert.equal(f.calls.length,1);
  await f.settle(0,true);
  f.h.workspace.showing=false;f.h.render();
  f.h.workspace.selectedPhoneSource=null;f.sample(3);
  assert.equal(f.calls.length,1,'Choosing webcam still blocks following any phone generation');
});

test('deployment follows the already selected phone generation and replacement session while guide UI is hidden',async t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.showing=false;f.h.workspace.phoneSourceSelected=true;f.h.workspace.source='phone';
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:1};f.h.render();
  f.sample(2);assert.equal(f.calls.length,1);assert.equal(f.calls[0].session.stream.generation,2);
  assert.equal(f.calls[0].current(),true);await f.settle(0,true);
  f.h.workspace.selectedPhoneSource={session_id:'s',generation:2};
  for(let i=0;i<3;i++){f.advance(100);f.sample(2);}
  assert.equal(f.calls.length,1,'steady deployment does not open a second camera owner');
  f.sample(1,{session_id:'replacement-phone'});
  assert.equal(f.calls.length,2);assert.equal(f.calls[1].session.session_id,'replacement-phone');
  assert.equal(f.calls[1].current(),true);await f.settle(1,true);
});

test('deployment retains pending generation until fresh frames and the existing camera operation guard permit selection',async t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.showing=false;f.h.workspace.phoneSourceSelected=true;f.h.workspace.source='phone';
  f.h.workspace.canShow=false;
  f.sample(2);assert.equal(f.calls.length,0);
  f.h.workspace.canShow=true;
  f.sample(2,{stream:{...followedPhone().stream,generation:2,video_receive_fresh:false}});assert.equal(f.calls.length,0);
  f.sample(2);assert.equal(f.calls.length,1);await f.settle(0,true);
});

test('a webcam selection invalidates an in-flight deployment follow even if the old guide preview remains marked showing',async t=>{
  const f=sourceFollowHarness(t);
  f.h.workspace.showing=false;f.h.workspace.phoneSourceSelected=true;f.h.workspace.source='phone';
  f.sample(2);assert.equal(f.calls.length,1);assert.equal(f.calls[0].current(),true);
  f.h.workspace.phoneSourceSelected=false;f.h.workspace.source='webcam';f.h.workspace.showing=true;f.h.render();
  assert.equal(f.calls[0].current(),false);
  await f.settle(0,true);
  f.advance(5000);f.sample(3);
  assert.equal(f.calls.length,1,'a late successful response never switches webcam back to phone');
});
