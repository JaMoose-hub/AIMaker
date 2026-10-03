import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import ts from 'typescript';
function load(file){const exports={};const code=ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;new Function('exports',code)(exports);return exports;}
const domain=load('../src/lib/mobileBrowser.ts'),rtc=load('../src/lib/mobileBrowserRtc.ts');
const session=(stream={})=>({session_id:'s',conversation_id:'chat',context_id:'ctx',view:{capture_id:null,wire_id:null,revision:1},stream:{active:true,publisher_connected:true,generation:3,preview_seq:8,can_capture:true,valid_for_ms:1200,...stream}});
const turn=()=>new Promise(resolve=>setImmediate(resolve));

test('H264 preference applies to video send and receive while retaining supported fallback codecs',()=>{
  const vp8={mimeType:'video/VP8',clockRate:90000},h264={mimeType:'video/H264',clockRate:90000},rtx={mimeType:'video/rtx',clockRate:90000};
  const calls=[];
  const video={sender:{track:{kind:'video'}},receiver:{track:{kind:'video'}},setCodecPreferences(codecs){calls.push(codecs);}};
  const receive={sender:{track:null},receiver:{track:{kind:'video'}},setCodecPreferences(codecs){calls.push(codecs);}};
  const audio={sender:{track:{kind:'audio'}},receiver:{track:{kind:'audio'}},setCodecPreferences(){throw Error('Audio must remain unchanged');}};
  assert.equal(rtc.preferBrowserH264({getTransceivers:()=>[video,receive,audio]},{codecs:[vp8,rtx,h264]}),true);
  assert.deepEqual(calls,[[h264,vp8,rtx],[h264,vp8,rtx]]);
  assert.equal(rtc.preferBrowserH264({getTransceivers:()=>[video]},{codecs:[vp8]}),false);
  assert.equal(rtc.preferBrowserH264({getTransceivers:()=>[{...video,setCodecPreferences(){throw Error('Unsupported');}}]},{codecs:[h264]}),false);
});
const pairingFixture={token:'fake-token',session_id:'fake-session',conversation_id:'chat',context_id:'ctx',title:'Test',base_url:'https://pc.local'};

test('only exact authenticated session expiry signals revoke a pairing',()=>{
  for(const [status,detail] of [[401,'mobile_session_expired_or_invalid'],[404,'mobile_session_not_found']])assert.equal(domain.expiredBrowserSession(new domain.MobileBrowserError(status,'friendly label',detail)),true);
  for(const [status,detail] of [[401,'mobile_pairing_expired_or_invalid'],[404,'mobile_asset_not_found'],[500,'mobile_session_expired_or_invalid'],[503,'temporarily unavailable'],[403,'mobile_session_mismatch']])assert.equal(domain.expiredBrowserSession(new domain.MobileBrowserError(status,detail)),false);
  assert.equal(domain.expiredBrowserSession(Error('mobile_session_expired_or_invalid')),false);
  assert.equal(domain.sameBrowserPairing(pairingFixture,{...pairingFixture}),true);
  assert.equal(domain.sameBrowserPairing({...pairingFixture,token:'new-token'},pairingFixture),false);
  assert.equal(domain.sameBrowserPairing(null,pairingFixture),false);
});

test('session expiry callback cancels pending requests once; 503 and network failures preserve pairing',async()=>{
  const oldFetch=globalThis.fetch,oldWindow=globalThis.window;
  globalThis.window={location:{origin:'https://pc.local'}};
  try {
    let invalidated=0,aborted=false;
    const api=new domain.MobileBrowserApi(pairingFixture,()=>{invalidated++;api.cancelPending();});
    globalThis.fetch=async(url,options)=>{
      if(url.endsWith('/conversation'))return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>{aborted=true;reject(new DOMException('cancelled','AbortError'));},{once:true}));
      return{ok:false,status:401,json:async()=>({detail:'mobile_session_expired_or_invalid'})};
    };
    const waiting=api.request('conversation').catch(error=>error);
    await assert.rejects(api.request('session'),cause=>domain.expiredBrowserSession(cause));
    assert.equal((await waiting).name,'AbortError');assert.equal(aborted,true);assert.equal(invalidated,1);
    await assert.rejects(api.request('session'));assert.equal(invalidated,1,'one expired API cannot repeatedly reset the workspace');
    const healthy=new domain.MobileBrowserApi(pairingFixture,()=>invalidated++);
    globalThis.fetch=async()=>({ok:false,status:503,json:async()=>({detail:'temporarily unavailable'})});
    await assert.rejects(healthy.request('session'));assert.equal(invalidated,1);
    globalThis.fetch=async()=>{throw TypeError('network offline');};
    await assert.rejects(healthy.request('session'));assert.equal(invalidated,1);assert.equal(healthy.pairing,pairingFixture);
  } finally {globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});

test('protected photo errors retain typed session detail and a late old reply cannot clear a new pairing',async()=>{
  const oldFetch=globalThis.fetch,oldWindow=globalThis.window;
  globalThis.window={location:{origin:'https://pc.local'}};
  try {
    let current=pairingFixture,clears=0,release;
    const api=new domain.MobileBrowserApi(pairingFixture,()=>{if(domain.sameBrowserPairing(current,pairingFixture)){current=null;clears++;}});
    globalThis.fetch=()=>new Promise(resolve=>release=resolve);
    const request=api.assetBlob('/api/mobile/assets/photo/file');
    const replacement={...pairingFixture,session_id:'new-session',token:'new-token'};current=replacement;
    release({ok:false,status:401,json:async()=>({detail:'mobile_session_expired_or_invalid'})});
    await assert.rejects(request,cause=>cause.message==='照片載入失敗，請重試'&&domain.expiredBrowserSession(cause));
    assert.equal(current,replacement);assert.equal(clears,0);
  } finally {globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});

test('multipart upload reports session expiry through the same typed callback',async()=>{
  const oldXhr=globalThis.XMLHttpRequest;let expired=0;
  globalThis.XMLHttpRequest=class {
    upload={};status=401;responseText=JSON.stringify({detail:'mobile_session_expired_or_invalid'});
    open(){}setRequestHeader(){}send(){queueMicrotask(()=>this.onload());}abort(){this.onabort?.();}
  };
  try {
    const api=new domain.MobileBrowserApi(pairingFixture,()=>expired++);
    await assert.rejects(api.upload({upload_id:'u',file:new Blob(['photo']),name:'photo.jpg'},()=>{}),cause=>domain.expiredBrowserSession(cause));
    assert.equal(expired,1);
  } finally {globalThis.XMLHttpRequest=oldXhr;}
});

test('HTTP UUID fallback uses Web Crypto, produces distinct v4 IDs and preserves native support',()=>{
  const prior=Math.random;Math.random=()=>{throw Error('non-cryptographic randomness forbidden');};
  try {
    const fallback={getRandomValues:values=>webcrypto.getRandomValues(values)};
    const ids=Array.from({length:100},()=>domain.browserUuid(fallback));
    assert.equal(new Set(ids).size,100);
    for(const id of ids)assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    let nativeCalls=0;
    assert.equal(domain.browserUuid({randomUUID(){nativeCalls++;return 'native-uuid';},getRandomValues(){throw Error('fallback must not run');}}),'native-uuid');
    assert.equal(nativeCalls,1);
  } finally {Math.random=prior;}
});
test('disconnect stops RTC before server revocation and retains retry credentials on server failure',async()=>{
  const calls=[];let token='pairing-token';
  await domain.closeBrowserSession({async request(path,options){calls.push(`${options.method} ${path}`);}},async()=>{calls.push('stop');});
  assert.deepEqual(calls,['stop','DELETE session']);
  for(const status of [401,404])await domain.closeBrowserSession({async request(){throw new domain.MobileBrowserError(status,'already gone');}},async()=>{});
  try {
    await domain.closeBrowserSession({async request(){throw new domain.MobileBrowserError(500,'server failure');}},async()=>{});
    token=null;
  } catch(cause){assert.equal(cause.status,500);}
  assert.equal(token,'pairing-token');
  await assert.rejects(domain.closeBrowserSession({async request(){throw Error('network offline');}},async()=>{}),/network offline/);
});

test('same-origin bearer assets and QR cannot point token at another server',()=>{
  assert.equal(domain.mobileBrowserPath('/api/mobile/assets/a/file','https://pc.local:8443'),'https://pc.local:8443/api/mobile/assets/a/file');
  for(const path of ['https://evil.invalid/api/mobile/assets/a/file','/video','//evil.invalid/api/mobile/file'])assert.throws(()=>domain.mobileBrowserPath(path,'https://pc.local:8443'));
  assert.equal(domain.parseBrowserPairingCode('123456','https://pc.local'),'123456');
  assert.equal(domain.parseBrowserPairingCode(JSON.stringify({type:'tinkro-mobile',code:'123456',base_url:'https://pc.local'}),'https://pc.local'),'123456');
  assert.throws(()=>domain.parseBrowserPairingCode(JSON.stringify({type:'tinkro-mobile',code:'123456',base_url:'https://other.local'}),'https://pc.local'));
});
test('conversation-based persistence survives a new pairing without crossing project or origin',()=>{
  assert.equal(domain.mobileBrowserDraftKey('https://pc.local:8443/mobile','chat'),domain.mobileBrowserDraftKey('https://pc.local:8443/','chat'));
  assert.notEqual(domain.mobileBrowserDraftKey('https://pc.local','chat'),domain.mobileBrowserDraftKey('https://pc.local','other'));
  assert.notEqual(domain.mobileBrowserDraftKey('https://pc.local','chat'),domain.mobileBrowserDraftKey('https://other.local','chat'));
});
test('fresh preview has bounded TTL, cannot be renewed by repeated events, and revokes on disconnect',()=>{
  const first=domain.browserLease(session(),100,{key:'',deadline:0});assert.equal(first.deadline,1300);
  assert.equal(domain.browserLease(session(),1000,first).deadline,1300);
  assert.equal(domain.browserLease(session({can_capture:false}),1000,first).deadline,1300,'Fresh Hold still uses the same bounded preview, not capture permission');
  const revoked=domain.browserLease(session({active:false}),1000,first);assert.equal(revoked.deadline,0);
  assert.equal(domain.browserLease(session(),1100,revoked).deadline,0);
  assert.equal(domain.browserLease(session({preview_seq:9,valid_for_ms:9999}),1500,revoked).deadline,3000);
  assert.equal(domain.browserLease({...session(),available_context:{context_id:'new'}},100,first).deadline,0);
  assert.equal(domain.browserLease(session({publisher_connected:false}),100,first).deadline,0);
  const transportRevoked={...first,deadline:0};
  assert.equal(domain.browserLease(session(),200,transportRevoked).deadline,0,'A replay after websocket close cannot resurrect the prior sample');
  assert.equal(domain.browserLease(session({preview_seq:9}),200,transportRevoked).deadline,1400,'A genuinely fresh sample can restore preview after reconnect');
});
test('old generation, sample and selected photo cannot resurrect through a late HTTP snapshot',()=>{
  const latest={...session(),view:{capture_id:'new',wire_id:'b',revision:4}};
  const oldView={...session({generation:1}),view:{capture_id:'old',wire_id:'a',revision:2}};
  const merged=domain.mergeBrowserSession(latest,oldView);assert.equal(merged.view.capture_id,'new');assert.equal(merged.stream.generation,3);
  assert.equal(domain.mergeBrowserSession(latest,{...latest,stream:session({preview_seq:2}).stream}).stream.preview_seq,8);
  assert.equal(domain.mergeBrowserSession(latest,{...latest,stream:session({active:false}).stream}).stream.active,false);
});
test('text references freeze an exact media identity and explicit empty reference',()=>{
  const chat={context_epoch:5,active_media:{epoch:5,round:2,asset_ids:['a'],capture_id:'c',attachments:[{asset_id:'a',filename:'Pi.jpg',type:'image'}]}};
  const ref=domain.browserMediaReference(chat,2,0);assert.deepEqual(ref.asset_ids,['a']);assert.equal(ref.capture_id,'c');assert.equal(ref.inherit_media,false);assert.match(ref.label,/Pi.jpg/);
  chat.active_media.asset_ids.push('later');assert.deepEqual(ref.asset_ids,['a'],'frozen list does not alias polling state');
  for(const result of [domain.browserMediaReference(chat,3,0),domain.browserMediaReference(chat,2,1),domain.browserMediaReference(null,2,0),domain.browserMediaReference(chat,2,0,'explicit')]){assert.deepEqual(result.asset_ids,[]);assert.equal(result.inherit_media,false);assert.equal(result.label,null);}
  assert.equal(domain.browserMediaReference({...chat,context_epoch:6},2,0).label,null);
});
test('media accepts four photos or one bounded video without resizing or MIME relabeling',()=>{
  const image={type:'image',size:123};assert.equal(domain.validateBrowserAttachments(Array(4).fill(image)),null);assert.ok(domain.validateBrowserAttachments(Array(5).fill(image)));
  assert.equal(domain.validateBrowserAttachments([{type:'video',size:200*1024*1024,duration:60}]),null);
  for(const list of [[image,{type:'video',size:1,duration:1}],[{type:'video',size:1,duration:60.1}],[{type:'video',size:1,duration:NaN}],[{type:'image',size:200*1024*1024+1}]])assert.ok(domain.validateBrowserAttachments(list));
});
test('history keeps each message once and accepts the newest active reference',()=>{
  const previous={id:'c',messages:[{id:'1',created_at:1},{id:'2',created_at:2}],before:20,active_media:{capture_id:'old'}};
  const next={id:'c',messages:[{id:'2',created_at:2},{id:'3',created_at:3}],before:21,active_media:{capture_id:'new'}};
  const merged=domain.mergeBrowserConversation(previous,next);assert.deepEqual(merged.messages.map(m=>m.id),['1','2','3']);assert.equal(merged.active_media.capture_id,'new');assert.equal(merged.before,20);
});

function setup(overrides={}){
  const calls=[],states=[],constraints=[];let stops=0,parameters;
  const track=Object.assign(new EventTarget(),{kind:'video',stop(){stops++;},getSettings(){return{width:1920,height:1080,frameRate:30};}});
  const media={getTracks:()=>[track],getVideoTracks:()=>[track]};
  const peer={iceGatheringState:'complete',connectionState:'connected',localDescription:null,closed:false,
    addTrack(){return{getParameters:()=>({encodings:[{}]}),async setParameters(value){parameters=value;}};},
    async createOffer(){return{type:'offer',sdp:'offer'};},async setLocalDescription(value){this.localDescription=value;},async setRemoteDescription(value){this.remote=value;},
    async getStats(){return new Map();},close(){this.closed=true;},...overrides.peer};
  const api={async request(path,options){calls.push({path,...options});if(path==='stream'&&options.method==='POST')return{generation:7};if(path==='stream/offer')return{type:'answer',sdp:'answer'};}};
  const publisher=new rtc.BrowserPublisher(api,state=>states.push(state),{getUserMedia:async value=>{constraints.push(value);return overrides.getUserMedia?overrides.getUserMedia(value):media;},makePeer:()=>peer,
    normalizeStream:overrides.normalizeStream??(async stream=>({stream,dispose(){},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})}))});
  return{publisher,peer,api,media,states,calls,constraints,stops:()=>stops,parameters:()=>parameters};
}
test('publisher sends one rear camera, real generation and requested 8 Mbps without claiming measured FPS',async()=>{
  const s=setup();await s.publisher.start();
  assert.equal(s.constraints.length,1);assert.deepEqual(s.constraints[0].video.facingMode,{ideal:'environment'});assert.equal(s.constraints[0].video.width.ideal,1920);
  assert.equal(s.parameters().encodings[0].maxBitrate,8000000);assert.equal(s.parameters().degradationPreference,'maintain-resolution');
  assert.equal(s.parameters().encodings[0].maxFramerate,30);
  assert.deepEqual(s.calls.find(c=>c.path==='stream'&&c.method==='POST').body,{bitrate_kbps:8000});
  assert.deepEqual(s.calls.find(c=>c.path==='stream/offer').body,{sdp:'offer',type:'offer',role:'publisher',generation:7});
  assert.equal(s.states.at(-1).settings.frameRate,30);assert.equal(s.states.at(-1).stats.sendFps,undefined);
  await s.publisher.stop();assert.equal(s.stops(),1);assert.equal(s.peer.closed,true);
});

test('12 Mbps selection configures both phone upload and the laptop relay profile',async()=>{
  const s=setup();await s.publisher.start({bitrateKbps:12000});
  assert.equal(s.parameters().encodings[0].maxBitrate,12000000);
  assert.deepEqual(s.calls.find(c=>c.path==='stream'&&c.method==='POST').body,{bitrate_kbps:12000});
  await s.publisher.stop();
});

test('publisher transport measures selected path and counter deltas without inventing missing or reset rates',()=>{
  const report=(out={})=>new Map([
    ['source',{type:'media-source',kind:'video',framesPerSecond:30}],
    ['codec',{type:'codec',mimeType:'video/H264'}],
    ['transport',{type:'transport',selectedCandidatePairId:'selected'}],
    ['wrong',{type:'candidate-pair',state:'succeeded',currentRoundTripTime:5}],
    ['selected',{type:'candidate-pair',state:'succeeded',currentRoundTripTime:.025}],
    ['video',{type:'outbound-rtp',kind:'video',id:'video',timestamp:1000,framesSent:30,bytesSent:100000,totalEncodeTime:.15,codecId:'codec',transportId:'transport',frameWidth:1080,frameHeight:1920,qualityLimitationReason:'none',...out}]
  ]);
  const first=rtc.readBrowserPublisherStats(report(),null);assert.equal(first.stats.sendFps,undefined);assert.equal(first.stats.bitrateKbps,undefined);
  const next=rtc.readBrowserPublisherStats(report({timestamp:2000,framesSent:60,bytesSent:1100000,totalEncodeTime:.3}),first.sample);
  assert.equal(next.stats.sendFps,30);assert.equal(next.stats.bitrateKbps,8000);assert.equal(next.stats.encodeMs,5);assert.equal(next.stats.rttMs,25);assert.equal(next.stats.codec,'video/H264');
  const reset=rtc.readBrowserPublisherStats(report({timestamp:3000,framesSent:1,bytesSent:100,totalEncodeTime:0}),next.sample);
  assert.equal(reset.stats.sendFps,undefined);assert.equal(reset.stats.bitrateKbps,undefined);assert.equal(reset.stats.encodeMs,undefined);
  const missing=rtc.readBrowserPublisherStats(report({framesSent:undefined,bytesSent:undefined,totalEncodeTime:NaN,frameWidth:NaN}),null);
  assert.equal(missing.stats.sendFps,undefined);assert.equal(missing.stats.width,undefined);
});

test('cached publisher timestamps cannot refresh capture or fallback send FPS; reset clocks recover from a new baseline',()=>{
  const report=(timestamp,frames,bytes)=>new Map([
    ['source',{type:'media-source',kind:'video',framesPerSecond:30}],
    ['video',{type:'outbound-rtp',kind:'video',id:'video',ssrc:1,timestamp,framesSent:frames,bytesSent:bytes,framesPerSecond:29,frameWidth:1920,frameHeight:1080}]
  ]);
  const initial=rtc.readBrowserPublisherStats(report(2000,60,2000000),null);
  const cached=rtc.readBrowserPublisherStats(report(2000,60,2000000),initial.sample);
  assert.deepEqual(cached.stats,{});assert.deepEqual(cached.sample,initial.sample);
  const reset=rtc.readBrowserPublisherStats(report(100,1,1000),cached.sample);
  assert.deepEqual(reset.stats,{});assert.equal(reset.sample.timestamp,100);assert.equal(reset.sample.frames,1);
  const recovered=rtc.readBrowserPublisherStats(report(1100,31,1001000),reset.sample);
  assert.equal(recovered.stats.captureFps,30);assert.equal(recovered.stats.sendFps,30);assert.equal(recovered.stats.bitrateKbps,8000);
});

test('a failed getStats poll discards its counter baseline instead of averaging across the interruption',async()=>{
  const priorSetTimeout=globalThis.setTimeout,priorClearTimeout=globalThis.clearTimeout;
  const timers=new Map();let timerId=0,polls=0;
  globalThis.setTimeout=(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;};
  globalThis.clearTimeout=id=>timers.delete(id);
  const s=setup({peer:{async getStats(){
    polls++;if(polls===2)throw Error('temporary RTC statistics failure');
    return new Map([['v',{type:'outbound-rtp',kind:'video',id:'v',timestamp:polls*1000,framesSent:polls===1?30:150,bytesSent:polls===1?1000:3000000}]]);
  }}});
  const runPoll=async()=>{const [id,timer]=[...timers].find(([,value])=>value.delay===1000);timers.delete(id);await timer.callback();await turn();};
  try {
    await s.publisher.start();await turn();assert.equal(s.states.at(-1).stats.sendFps,undefined);
    await runPoll();assert.equal(polls,2);
    await runPoll();assert.equal(polls,3);assert.equal(s.states.at(-1).stats.sendFps,undefined);assert.equal(s.states.at(-1).stats.bitrateKbps,undefined);
  } finally {await s.publisher.stop();globalThis.setTimeout=priorSetTimeout;globalThis.clearTimeout=priorClearTimeout;}
});

test('bitrate-only retry supports browsers which reject optional FPS/degradation controls',async()=>{
  let applied={encodings:[{}]},attempts=[];
  const sender={getParameters:()=>structuredClone(applied),async setParameters(value){attempts.push(structuredClone(value));if(value.degradationPreference)throw Error('Unsupported');applied=structuredClone(value);}};
  const result=await rtc.tuneBrowserVideoSender(sender,12000);
  assert.equal(attempts.length,2);assert.equal(attempts[1].degradationPreference,undefined);assert.equal(attempts[1].encodings[0].maxFramerate,undefined);
  assert.equal(result.appliedBitrateKbps,12000);assert.equal(result.parameterStatus,'accepted');
  assert.equal((await rtc.tuneBrowserVideoSender({getParameters:()=>({encodings:[]})},8000)).parameterStatus,'unsupported');
});

test('late publisher statistics after stop cannot update UI or report an old stream',async()=>{
  let release;const waiting=new Promise(resolve=>release=resolve);
  const s=setup({peer:{getStats:()=>waiting}});await s.publisher.start();await s.publisher.stop();
  const count=s.states.length;release(new Map([['v',{type:'outbound-rtp',kind:'video',id:'v',timestamp:1,framesPerSecond:30}]]));await turn();
  assert.equal(s.states.length,count);assert.equal(s.calls.some(call=>call.path==='stream/metrics'),false);
});

test('phone statistics are generation scoped and reporting does not block media startup',async()=>{
  const s=setup({peer:{async getStats(){return new Map([['v',{type:'outbound-rtp',kind:'video',id:'v',timestamp:1000,framesPerSecond:29,frameWidth:1080,frameHeight:1920}]]);}}});
  await s.publisher.start();await turn();const report=s.calls.find(call=>call.path==='stream/metrics');
  assert.equal(report.body.generation,7);assert.equal(report.body.send_fps,29);assert.equal(report.body.width,1080);assert.equal(report.timeoutMs,2500);
  await s.publisher.stop();
});
test('stop during camera permission waits, releases the late track and never negotiates it',async()=>{
  let release;const delayed=new Promise(resolve=>release=resolve);const s=setup({getUserMedia:()=>delayed});
  const started=s.publisher.start();await turn();let finished=false;const stopped=s.publisher.stop().then(()=>finished=true);await turn();assert.equal(finished,false);
  release(s.media);await Promise.all([started,stopped]);assert.equal(s.stops(),1);assert.equal(s.calls.some(c=>c.path==='stream/offer'),false);assert.equal(s.states.at(-1).stream,null);
});
test('stop during remote description cannot publish a released camera afterwards',async()=>{
  let release;const delayed=new Promise(resolve=>release=resolve);const s=setup({peer:{setRemoteDescription:()=>delayed}});
  const started=s.publisher.start();await turn();const stopped=s.publisher.stop();release();await Promise.all([started,stopped]);
  assert.equal(s.states.at(-1).stream,null);assert.equal(s.stops(),1);assert.equal(s.peer.closed,true);
});
test('unsupported 1080 falls back to 720 once, permission denial never reprompts',async()=>{
  let count=0,outputResolution;const s=setup({getUserMedia:()=>{if(!count++)throw new DOMException('constraint','OverconstrainedError');return s.media;},
    normalizeStream:async(stream,resolution)=>{outputResolution=resolution;return{stream,dispose(){},readFrame:()=>({sourceSize:[1280,720],outputSize:[1280,720],rotation:0})};}});
  await s.publisher.start();assert.equal(s.constraints[1].video.width.ideal,1280);assert.equal(outputResolution,'720p');await s.publisher.stop();
  const denied=setup({getUserMedia:()=>{throw new DOMException('denied','NotAllowedError');}});await assert.rejects(denied.publisher.start());assert.equal(denied.constraints.length,1);
});

test('legacy layout accepts portrait and square pixels without rotation or stretching',()=>{
  assert.deepEqual(rtc.landscapeFrameLayout(1080,1920,1920,1080),{rotation:0,drawWidth:607.5,drawHeight:1080});
  assert.deepEqual(rtc.landscapeFrameLayout(1080,1080,1920,1080),{rotation:0,drawWidth:1080,drawHeight:1080});
  assert.deepEqual(rtc.landscapeFrameLayout(1920,1080,1920,1080),{rotation:0,drawWidth:1920,drawHeight:1080});
  assert.deepEqual(rtc.landscapeFrameLayout(1920,1080,1280,720),{rotation:0,drawWidth:1280,drawHeight:720});
  assert.deepEqual(rtc.landscapeFrameLayout(640,480,1920,1080),{rotation:0,drawWidth:1440,drawHeight:1080});
  for(const bad of [0,-1,NaN,Infinity])assert.throws(()=>rtc.landscapeFrameLayout(bad,1080,1920,1080));
});

test('RTC publishes the original native track after camera verification; duplicate start remains single-flight',async()=>{
  let released=0,normalized=0,added,addedTrack;
  const s=setup({normalizeStream:async(input,resolution)=>{
    normalized++;assert.equal(input,s.media);assert.equal(resolution,'1080p');
    return{stream:input,dispose(){released++;},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};
  },peer:{addTrack(track,stream){added=stream;addedTrack=track;return{getParameters:()=>({encodings:[]})};}}});
  await Promise.all([s.publisher.start(),s.publisher.start()]);
  assert.equal(normalized,1);assert.equal(s.constraints.length,1);assert.equal(added,s.media);assert.equal(addedTrack,s.media.getVideoTracks()[0]);assert.equal(s.states.at(-1).stream,s.media);
  assert.deepEqual(s.states.at(-1).frame,{sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0});assert.equal(s.states.at(-1).publishing,true);
  assert.equal(s.states.at(-1).settings.width,1920);
  await Promise.all([s.publisher.stop(),s.publisher.stop()]);assert.equal(released,1);assert.equal(s.stops(),1);
});

test('stop during normalization drains and disposes late output without negotiating or reviving UI',async()=>{
  let release,disposed=0;const delayed=new Promise(resolve=>release=resolve);
  const s=setup({normalizeStream:()=>delayed});const starting=s.publisher.start();await turn();
  const stopping=s.publisher.stop();assert.equal(s.stops(),1);
  release({stream:s.media,dispose(){disposed++;},readFrame(){throw Error('stale result');}});
  await Promise.all([starting,stopping]);assert.equal(disposed,1);assert.equal(s.states.at(-1).stream,null);assert.equal(s.peer.closed,false);
  assert.equal(s.calls.some(call=>call.path==='stream/offer'),false);
});

test('camera verification failure releases the camera and session instead of publishing unavailable pixels',async()=>{
  const s=setup({normalizeStream:async()=>{throw Error('camera pixels unavailable');}});
  await assert.rejects(s.publisher.start(),/camera pixels unavailable/);assert.equal(s.stops(),1);assert.equal(s.states.at(-1).stream,null);
  assert.equal(s.calls.some(call=>call.path==='stream/offer'),false);assert.ok(s.calls.some(call=>call.path==='stream'&&call.method==='DELETE'));
});

test('native camera ending stops normalized output and clears capture-ready media',async()=>{
  let disposed=0;const s=setup({normalizeStream:async stream=>({stream,dispose(){disposed++;},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})})});
  await s.publisher.start();s.media.getVideoTracks()[0].dispatchEvent(new Event('ended'));await turn();
  assert.equal(s.states.at(-1).stream,null);assert.equal(disposed,1);assert.equal(s.stops(),1);assert.equal(s.peer.closed,true);
});

function nativeEnvironment({ready=true,portrait=false,width=1920,height=1080}={}) {
  const prior={document:globalThis.document,window:globalThis.window,requestAnimationFrame:globalThis.requestAnimationFrame,cancelAnimationFrame:globalThis.cancelAnimationFrame};
  let inputStops=0,removed=0,perFrameCallbacks=0;const elements=[];
  const source=Object.assign(new EventTarget(),{videoWidth:ready?(portrait?1080:width):0,videoHeight:ready?(portrait?1920:height):0,readyState:ready?2:0,currentTime:0,paused:true,
    style:{},setAttribute(){},play(){this.paused=false;return Promise.resolve();},pause(){this.paused=true;},remove(){removed++;}});
  const track=Object.assign(new EventTarget(),{kind:'video',readyState:'live',stop(){inputStops++;},getSettings(){return{width:source.videoWidth,height:source.videoHeight,frameRate:30};}});
  const input={getVideoTracks:()=>[track],getTracks:()=>[track]};
  const forbidden=()=>{perFrameCallbacks++;throw Error('Native publication must not schedule per-frame canvas work');};
  source.requestVideoFrameCallback=forbidden;globalThis.requestAnimationFrame=forbidden;
  globalThis.cancelAnimationFrame=()=>{throw Error('No synthetic frame callback should exist');};
  const orientation=Object.assign(new EventTarget(),{type:'landscape-primary'});
  globalThis.window=Object.assign(new EventTarget(),{screen:{orientation}});
  globalThis.document={createElement:tag=>{elements.push(tag);assert.equal(tag,'video','No canvas or generated video track');return source;},body:{appendChild(){}}};
  return{source,input,track,orientation,elements,stats:()=>({inputStops,removed,perFrameCallbacks}),
    restore(){Object.assign(globalThis,prior);}};
}

test('portrait camera pixels publish immediately at their actual size without rotation or resampling',async()=>{
  const env=nativeEnvironment({portrait:true}),abort=new AbortController(),waiting=[];
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{readOrientation:()=> 'portrait',waiting:f=>waiting.push(f)});
    assert.equal(waiting.length,0);assert.deepEqual(env.elements,['video']);
    assert.equal(result.stream,env.input);assert.equal(result.stream.getVideoTracks()[0],env.track);
    assert.deepEqual(result.stream.getVideoTracks()[0].getSettings(),{width:1080,height:1920,frameRate:30});
    assert.deepEqual(result.readFrame(),{sourceSize:[1080,1920],outputSize:[1080,1920],rotation:0,ready:true,phoneOrientation:'portrait'});
    result.readFrame().sourceSize[0]=1;assert.equal(result.readFrame().sourceSize[0],1080,'metadata does not alias internal state');
    abort.abort();result.dispose();assert.deepEqual(env.stats(),{inputStops:0,removed:1,perFrameCallbacks:0});
  } finally {env.restore();}
});

test('phone orientation metadata never overrides the actual native video dimensions',async()=>{
  const env=nativeEnvironment(),abort=new AbortController();
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{readOrientation:()=> 'portrait'});
    assert.deepEqual(result.readFrame().sourceSize,[1920,1080]);assert.deepEqual(result.readFrame().outputSize,[1920,1080]);
    assert.equal(result.readFrame().phoneOrientation,'portrait');assert.equal(result.readFrame().ready,true);
    assert.equal(env.stats().perFrameCallbacks,0);result.dispose();
  } finally {abort.abort();env.restore();}
});

test('square native frames are valid and retain their exact pixels',async()=>{
  const env=nativeEnvironment({width:1024,height:1024}),abort=new AbortController();
  try {
    const prepared=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal);
    assert.equal(prepared.stream,env.input);assert.deepEqual(prepared.readFrame().outputSize,[1024,1024]);
    assert.equal(prepared.readFrame().ready,true);assert.equal(prepared.readFrame().rotation,0);prepared.dispose();
    assert.deepEqual(env.stats(),{inputStops:0,removed:1,perFrameCallbacks:0});
  } finally {abort.abort();env.restore();}
});

test('portrait native publication uses direction-specific 1080p and 720p ideals with one camera acquisition',async()=>{
  for(const [resolution,width,height] of [['1080p',1080,1920],['720p',720,1280]]) {
    const env=nativeEnvironment({width,height});env.orientation.type='portrait-primary';let added;
    const s=setup({getUserMedia:async()=>env.input,normalizeStream:rtc.prepareBrowserLandscapeStream,
      peer:{addTrack(track,stream){added=[track,stream];return{getParameters:()=>({encodings:[]})};}}});
    try {
      await s.publisher.start({resolution,bitrateKbps:12000});assert.equal(s.constraints.length,1);
      assert.deepEqual(s.constraints[0].video.width,{ideal:width});assert.deepEqual(s.constraints[0].video.height,{ideal:height});
      assert.deepEqual(s.constraints[0].video.aspectRatio,{ideal:9/16});assert.deepEqual(s.constraints[0].video.frameRate,{ideal:30,max:30});
      assert.equal(added[0],env.track);assert.equal(added[1],env.input);assert.equal(s.states.at(-1).publishing,true);
      assert.equal(s.states.at(-1).frame.phoneOrientation,'portrait');assert.deepEqual(s.states.at(-1).frame.sourceSize,[width,height]);
      assert.deepEqual(s.states.at(-1).frame.outputSize,[width,height]);assert.deepEqual(env.elements,['video']);
      await s.publisher.stop();assert.equal(env.stats().inputStops,1);
    } finally {await s.publisher.stop();env.restore();}
  }
});

test('same-size viewport resize cannot reinterpret keyboard geometry as a camera direction change',async()=>{
  const env=nativeEnvironment(),abort=new AbortController();let invalidated=0;
  delete globalThis.window.screen;globalThis.window.matchMedia=()=>({matches:true});
  try {
    const prepared=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{invalidated(){invalidated++;}});
    globalThis.window.matchMedia=()=>({matches:false});globalThis.window.dispatchEvent(new Event('resize'));
    assert.equal(invalidated,0);assert.equal(prepared.readFrame().ready,true);assert.equal(prepared.readFrame().phoneOrientation,'landscape');
    assert.deepEqual(prepared.readFrame().outputSize,[1920,1080]);prepared.dispose();
  } finally {abort.abort();env.restore();}
});

test('an upside-down landscape orientation change invalidates even when native dimensions stay the same',async()=>{
  const env=nativeEnvironment(),abort=new AbortController();let invalidated=0;
  try {
    const prepared=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{invalidated(){invalidated++;}});
    env.orientation.type='landscape-secondary';env.orientation.dispatchEvent(new Event('change'));
    assert.equal(invalidated,1);assert.equal(prepared.readFrame().ready,false);assert.equal(prepared.readFrame().phoneOrientation,'landscape');
    assert.deepEqual(prepared.readFrame().sourceSize,[1920,1080]);assert.equal(env.stats().inputStops,0);
  } finally {abort.abort();env.restore();}
});

test('a portrait camera resize revokes publication and leaves native track disposal to its owner',async()=>{
  const env=nativeEnvironment(),abort=new AbortController();let invalidated=0;
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{invalidated(){invalidated++;}});
    env.source.videoWidth=1080;env.source.videoHeight=1920;env.source.dispatchEvent(new Event('resize'));
    assert.equal(invalidated,1);assert.equal(result.readFrame().ready,false);assert.deepEqual(result.readFrame().outputSize,[1080,1920]);
    assert.equal(env.stats().inputStops,0);result.dispose();assert.equal(env.stats().removed,1);
  } finally {abort.abort();env.restore();}
});

test('a landscape size change invalidates once, while ordinary resize notifications keep the native stream',async()=>{
  const env=nativeEnvironment(),abort=new AbortController(),invalidated=[];
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{invalidated:frame=>invalidated.push(frame)});
    env.source.dispatchEvent(new Event('resize'));
    globalThis.window.dispatchEvent(new Event('resize'));
    assert.equal(invalidated.length,0,'unchanged decoded pixels do not stop the camera');
    env.source.videoWidth=1280;env.source.videoHeight=720;env.source.dispatchEvent(new Event('resize'));
    assert.equal(invalidated.length,1);assert.equal(invalidated[0].ready,false);
    assert.deepEqual(result.readFrame().sourceSize,[1280,720]);assert.deepEqual(result.readFrame().outputSize,[1280,720]);
    env.source.videoWidth=1920;env.source.videoHeight=1080;env.source.dispatchEvent(new Event('resize'));
    env.orientation.dispatchEvent(new Event('change'));result.dispose();
    assert.equal(invalidated.length,1,'disposed callbacks cannot revive or invalidate the old generation again');
    assert.deepEqual(env.stats(),{inputStops:0,removed:1,perFrameCallbacks:0});
  } finally {abort.abort();env.restore();}
});

test('physical portrait orientation revokes capture before Safari changes its decoded pixel dimensions',async()=>{
  const env=nativeEnvironment(),abort=new AbortController(),invalidated=[];
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal,{invalidated:frame=>invalidated.push(frame)});
    env.orientation.type='portrait-primary';env.orientation.dispatchEvent(new Event('change'));
    assert.equal(invalidated.length,1);assert.equal(result.readFrame().ready,false);
    assert.equal(result.readFrame().phoneOrientation,'portrait');assert.deepEqual(result.readFrame().outputSize,[1920,1080]);
    env.orientation.type='landscape-primary';env.orientation.dispatchEvent(new Event('change'));
    assert.equal(result.readFrame().ready,false,'old pixel dimensions cannot restore the invalidated publication');
    assert.equal(invalidated.length,1);assert.equal(env.stats().inputStops,0);
  } finally {abort.abort();env.restore();}
});

test('the real verifier adds the native camera track and stops it exactly once across repeated cleanup',async()=>{
  const env=nativeEnvironment();let addedTrack,addedStream;
  const s=setup({getUserMedia:async()=>env.input,normalizeStream:rtc.prepareBrowserLandscapeStream,
    peer:{addTrack(track,stream){addedTrack=track;addedStream=stream;return{getParameters:()=>({encodings:[]})};}}});
  try {
    await Promise.all([s.publisher.start(),s.publisher.start()]);
    assert.equal(s.constraints.length,1);assert.deepEqual(s.constraints[0].video.frameRate,{ideal:30,max:30});
    assert.equal(addedTrack,env.track);assert.equal(addedStream,env.input);assert.equal(s.states.at(-1).stream,env.input);
    env.source.dispatchEvent(new Event('resize'));assert.equal(s.states.at(-1).publishing,true);
    await Promise.all([s.publisher.stop(),s.publisher.stop()]);s.publisher.stopLocal();
    assert.equal(env.stats().inputStops,1);assert.equal(env.stats().removed,1);assert.equal(env.stats().perFrameCallbacks,0);
    assert.equal(s.peer.closed,true);assert.deepEqual(env.elements,['video']);
  } finally {await s.publisher.stop();env.restore();}
});

test('stop while native video play is pending drains startup without an offer or a late camera revival',async()=>{
  const env=nativeEnvironment();let releasePlay;
  env.source.play=()=>new Promise(resolve=>{releasePlay=()=>{env.source.paused=false;resolve();};});
  const s=setup({getUserMedia:async()=>env.input,normalizeStream:rtc.prepareBrowserLandscapeStream});
  try {
    const starting=s.publisher.start();await turn();
    assert.equal(s.calls.some(call=>call.method==='POST'),false);
    const stopping=s.publisher.stop();await Promise.all([starting,stopping]);
    const states=s.states.length;releasePlay();env.source.dispatchEvent(new Event('playing'));await turn();
    assert.equal(s.states.length,states);assert.equal(s.states.at(-1).stream,null);
    assert.equal(s.calls.some(call=>call.method==='POST'),false);assert.equal(env.stats().inputStops,1);
    assert.deepEqual(env.stats(),{inputStops:1,removed:1,perFrameCallbacks:0});
  } finally {await s.publisher.stop();env.restore();}
});

test('orientation state respects screen type, legacy angle and viewport fallback',()=>{
  const prior=globalThis.window;
  try {
    for(const type of ['landscape-primary','landscape-secondary']){globalThis.window={screen:{orientation:{type}}};assert.equal(rtc.readBrowserPhoneOrientation(),'landscape');}
    globalThis.window={screen:{orientation:{type:'portrait-primary'}},orientation:90};assert.equal(rtc.readBrowserPhoneOrientation(),'portrait','screen type wins over contradictory fallback');
    for(const angle of [90,-90,270]){globalThis.window={orientation:angle};assert.equal(rtc.readBrowserPhoneOrientation(),'landscape');}
    globalThis.window={orientation:0};assert.equal(rtc.readBrowserPhoneOrientation(),'portrait');
    globalThis.window={matchMedia:()=>({matches:true})};assert.equal(rtc.readBrowserPhoneOrientation(),'landscape');
    globalThis.window={matchMedia:()=>({matches:false})};assert.equal(rtc.readBrowserPhoneOrientation(),'portrait');
    globalThis.window=undefined;assert.equal(rtc.readBrowserPhoneOrientation(),'unknown');
  } finally {globalThis.window=prior;}
});

test('waiting for decoded pixels makes no server start/offer request and cancellation cannot publish later',async()=>{
  let options,release;const delayed=new Promise(resolve=>release=resolve);
  const s=setup({normalizeStream:(stream,resolution,signal,value)=>{options=value;value.waiting({sourceSize:[0,0],outputSize:[0,0],rotation:0,ready:false,phoneOrientation:'portrait'});return delayed;}});
  const starting=s.publisher.start();await turn();
  assert.equal(s.states.at(-1).stream,s.media);assert.equal(s.states.at(-1).publishing,false);assert.equal(s.states.at(-1).waitingForLandscape,false);
  assert.equal(s.calls.some(call=>call.method==='POST'),false);
  const stopping=s.publisher.stop();release({stream:s.media,dispose(){},readFrame(){throw Error('late result');}});await Promise.all([starting,stopping]);
  options.waiting({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0});assert.equal(s.states.at(-1).stream,null);assert.equal(s.calls.some(call=>call.method==='POST'),false);
});

test('orientation invalidation closes publisher, revokes local media and ignores late readiness',async()=>{
  let options,disposals=0;const s=setup({normalizeStream:async(stream,resolution,signal,value)=>{options=value;return{stream,dispose(){disposals++;},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};}});
  await s.publisher.start();options.invalidated({sourceSize:[1080,1920],outputSize:[1080,1920],rotation:0,ready:false,phoneOrientation:'portrait'});await turn();
  assert.equal(s.states.at(-1).publishing,false);assert.equal(s.states.at(-1).stream,null);assert.equal(s.stops(),1);assert.equal(disposals,1);
  assert.ok(s.calls.some(call=>call.method==='DELETE'&&call.path==='stream'));assert.equal(s.peer.closed,true);
  assert.equal(s.states.at(-1).sourceChanged,true);
  const count=s.states.length;options.waiting({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0});assert.equal(s.states.length,count);
});

function holdStreamDelete(s) {
  let release;const pending=new Promise(resolve=>release=resolve),request=s.api.request;
  s.api.request=async(path,options)=>{const value=await request(path,options);if(path==='stream'&&options.method==='DELETE')await pending;return value;};
  return release;
}
const changedFrame={sourceSize:[1080,1920],outputSize:[1080,1920],rotation:0,ready:false,phoneOrientation:'portrait'};

test('sourceChanged is emitted only after old stream DELETE completes and native ownership is released',async()=>{
  let options,disposed=0;const s=setup({normalizeStream:async(stream,resolution,signal,value)=>{options=value;return{stream,dispose(){disposed++;},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};}});
  await s.publisher.start();const release=holdStreamDelete(s);
  try {
    options.invalidated(changedFrame);await turn();
    assert.equal(s.stops(),1);assert.equal(disposed,1);assert.equal(s.peer.closed,true);
    assert.equal(s.states.some(state=>state.sourceChanged),false);assert.equal(s.states.at(-1).stream,null);
    assert.equal(s.calls.filter(call=>call.path==='stream'&&call.method==='POST').length,1);
    release();await turn();assert.equal(s.states.at(-1).sourceChanged,true);assert.deepEqual(s.states.at(-1).frame,changedFrame);
    assert.equal(s.states.filter(state=>state.sourceChanged).length,1);
  } finally {release();await s.publisher.stop();}
});

test('manual stop or context stopLocal during old DELETE suppresses the late sourceChanged continuation',async()=>{
  for(const local of [false,true]) {
    let options;const s=setup({normalizeStream:async(stream,resolution,signal,value)=>{options=value;return{stream,dispose(){},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};}});
    await s.publisher.start();const release=holdStreamDelete(s);
    try {
      options.invalidated(changedFrame);await turn();const cancelled=local?s.publisher.stopLocal():s.publisher.stop();
      release();await cancelled;await turn();assert.equal(s.states.some(state=>state.sourceChanged),false);
      assert.equal(s.stops(),1);assert.equal(s.states.at(-1).stream,null);
    } finally {release();await s.publisher.stop();}
  }
});

test('an explicit restart waits for old DELETE, cancels its sourceChanged notification and cannot revive after stop',async()=>{
  for(const cancel of [false,true]) {
    let options;const s=setup({normalizeStream:async(stream,resolution,signal,value)=>{options=value;return{stream,dispose(){},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};}});
    await s.publisher.start();const release=holdStreamDelete(s);
    try {
      options.invalidated(changedFrame);await turn();const restart=s.publisher.start();await turn();
      assert.equal(s.constraints.length,1);assert.equal(s.calls.filter(call=>call.path==='stream'&&call.method==='POST').length,1);
      const stopped=cancel?s.publisher.stop():Promise.resolve();release();await Promise.all([restart,stopped]);await turn();
      assert.equal(s.states.some(state=>state.sourceChanged),false);assert.equal(s.constraints.length,cancel?1:2);
      assert.equal(s.calls.filter(call=>call.path==='stream'&&call.method==='POST').length,cancel?1:2);
      assert.equal(s.states.at(-1).publishing,!cancel);
    } finally {release();await s.publisher.stop();}
  }
});

test('an unconfirmed old stream DELETE never emits an automatic reconnect signal',async()=>{
  let options;const s=setup({normalizeStream:async(stream,resolution,signal,value)=>{options=value;return{stream,dispose(){},readFrame:()=>({sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0})};}});
  await s.publisher.start();const request=s.api.request;
  s.api.request=async(path,value)=>{if(path==='stream'&&value.method==='DELETE')throw Error('shutdown reply timed out');return request(path,value);};
  try {
    options.invalidated(changedFrame);await turn();assert.equal(s.states.some(state=>state.sourceChanged),false);
    assert.equal(s.states.at(-1).publishing,false);assert.match(s.states.at(-1).status,/尚未確認/);assert.equal(s.stops(),1);
  } finally {await s.publisher.stop();}
});

test('a 1080p request preserves actual 720p camera pixels without upscaling or a synthetic frame clock',async()=>{
  const env=nativeEnvironment({width:1280,height:720}),abort=new AbortController();
  try {
    const result=await rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal);
    assert.equal(result.stream,env.input);assert.deepEqual(result.readFrame().outputSize,[1280,720]);assert.deepEqual(result.readFrame().sourceSize,[1280,720]);
    env.source.currentTime=.1;env.source.dispatchEvent(new Event('resize'));
    assert.deepEqual(env.elements,['video']);assert.equal(env.stats().perFrameCallbacks,0);
    result.dispose();assert.equal(env.stats().inputStops,0);
  } finally {env.restore();}
});

test('aborting before the first decoded image removes the source and never creates an output',async()=>{
  const env=nativeEnvironment({ready:false}),abort=new AbortController();
  try {
    const waiting=rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal);abort.abort();
    await assert.rejects(waiting,cause=>cause.name==='AbortError');assert.equal(env.stats().removed,1);assert.equal(env.stats().inputStops,0);
  } finally {env.restore();}
});

test('camera decoder play failure cleans up its element without stopping the owned native track',async()=>{
  const env=nativeEnvironment(),abort=new AbortController();
  env.source.play=()=>Promise.reject(Error('source play blocked'));
  try {
    await assert.rejects(rtc.prepareBrowserLandscapeStream(env.input,'1080p',abort.signal),/source play blocked/);
    assert.equal(env.stats().removed,1);assert.equal(env.stats().inputStops,0);assert.equal(env.source.srcObject,null);
  } finally {env.restore();}
});
test('formal capture obtains ticket before releasing RTC and never manufactures a video snapshot',async()=>{
  const calls=[],ticket={ticket_id:'ticket',generation:7,context_id:'ctx',expires_at:123};let release;
  const stopped=new Promise(resolve=>release=resolve);
  const handoff=rtc.browserCaptureHandoff({async request(path){calls.push(path);return ticket;}},{async stop(){calls.push('stop');await stopped;}});
  await turn();assert.deepEqual(calls,['capture-ticket','stop']);let done=false;handoff.then(()=>done=true);await turn();assert.equal(done,false);release();assert.equal(await handoff,ticket);
  let didStop=false;await assert.rejects(rtc.browserCaptureHandoff({async request(){throw Error('not locked');}},{async stop(){didStop=true;}}));assert.equal(didStop,false);
});
