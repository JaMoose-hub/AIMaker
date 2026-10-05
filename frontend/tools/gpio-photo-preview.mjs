// Isolated UI fixture: no proxies, hardware, cloud models or real media devices.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {maker,designFor,board,componentTests} from './project_guide_fixture.mjs';
const dist=process.env.GPIO_PREVIEW_DIST ? pathToFileURL(process.env.GPIO_PREVIEW_DIST.replaceAll('\\','/')+'/') : new URL('../dist/',import.meta.url);
// Optional local saved-photo replay. No detector/API/proxy or camera is started.
// Replay the exact current localhost capture without recapturing or mutating it.
const replayUrl=process.env.GPIO_REPLAY_CAPTURE_URL ? new URL(process.env.GPIO_REPLAY_CAPTURE_URL) : null;
if(replayUrl && (replayUrl.origin!=='http://127.0.0.1:8100' || !/^\/api\/photo-wiring\/captures\/[a-f0-9]+$/.test(replayUrl.pathname)))throw Error('Only local saved captures are allowed');
const replay=replayUrl ? await (await fetch(replayUrl)).json() : process.env.GPIO_REPLAY_PACKET ? JSON.parse(await readFile(process.env.GPIO_REPLAY_PACKET,'utf8')) : null;
const replayImage=replayUrl ? Buffer.from(await (await fetch(new URL(replayUrl.pathname+'/image',replayUrl.origin))).arrayBuffer()) : replay ? await readFile(process.env.GPIO_REPLAY_IMAGE) : null;
if(replay) {
  const {createHash}=await import('node:crypto');
  if(createHash('sha256').update(replayImage).digest('hex')!==replay.image_sha256)throw Error('Replay image hash mismatch');
}
const design={...designFor(['hc-sr04','mrd-tf240-8p-cs']),title:'Offline GPIO workspace',source:'demo',code:'# offline',
  bom:[{id:'raspberry-pi-5',name:'Raspberry Pi 5',quantity:1,price:2500,purpose:'控制板 / Controller'},
    {id:'hc-sr04',name:'HC-SR04+ 3.3V',quantity:1,price:65,purpose:'超音波 / Ultrasonic'},
    {id:'mrd-tf240-8p-cs',name:'MRD_TFT240_8P_CS ILI9341',quantity:1,price:220,purpose:'螢幕 / Display'},
    {id:'jumper-wires',name:'杜邦線 / Jumper wires',quantity:11,price:2,purpose:'接線 / Connections'}],
  instructions:['先關閉並拔除 Pi 電源；固定底盤，保留通風與散熱空間。','固定 Pi 5、超音波與 TFT 螢幕；先核對零件標籤與供電規格。','依接線引導逐線核對；本預覽不代表實體或電氣驗證。']};
const state={...maker.initialMaker(),design,stage:'guide',code:design.code};
const reviewGuide={...maker.emptyGuide(),phase:'review',confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),mode:'camera',at:'fixture'}]))};
const dockCases=Object.fromEntries(['active','stale','retest','near','visual','lost'].map(name=>{
  const cid=name==='visual'?'mrd-tf240-8p-cs':'hc-sr04';
  const guide={...reviewGuide,confirmed:name==='active'?{}:name==='retest'?Object.fromEntries(Object.entries(reviewGuide.confirmed).filter(([id])=>id.startsWith('hc-sr04:'))):reviewGuide.confirmed,componentIndex:design.component_ids.indexOf(cid),phase:name==='active'?'active':'review'};
  const run={id:'dock-'+name,project_id:design.id,revision:design.revision,component_id:cid,guide_key:componentTests.componentTestKey(design,guide,cid),
    created_at:1,heartbeat_at:1,outcome:name==='stale'?'inconclusive':name==='retest'?'failed':name==='visual'?'awaiting_confirmation':'running',
    phase:name==='retest'?'finished':name==='visual'?'awaiting_visual':'awaiting_near',reserved:!['active','stale','retest'].includes(name),invalidated:name==='stale',
    reason:name==='lost'?'connection_lost':name==='retest'?'no_echo':null,detail:'',samples:{},logs:[],options:['1234','2468','4567','7890'],program_stopped:false};
  return [name,{state:{...state,guide},tests:{connected:name!=='stale',test_busy:run.reserved,active:run.reserved?run:null,results:name==='active'?[]:[run],execution:{jobs:[]}}}];
}));
const pi={connected:false,busy:false,program:'stopped',deployment:'idle',pid:null,execution:{jobs:[]},logs:[]};
const fixed={
  '/api/config':{board_id:'raspberry-pi-5',runtime_revision:1,default_locale:'en',video_size:[1920,1080],detector:'offline',camera_source:'device',realtime_tracking:false,accuracy:null},
  '/api/boards/raspberry-pi-5':board,'/api/controllers':{controllers:[{board_id:'raspberry-pi-5',name:board.board.name,active:true}]},
  '/api/pi/status':pi,'/api/pi/component-tests':{connected:false,test_busy:false,active:null,results:[],execution:{jobs:[]}},
  '/api/debug/trials':{active:null,results:[]},'/api/debug/sessions':{active:null},'/api/debug/conversations':{conversation:null},
  '/api/ai/status':{available:true,logged_in:true,busy:false},'/api/ai/models':{models:[{id:'gpt-6-luna',name:'Offline fake',efforts:['low'],default_effort:'low',is_default:true,excluded_efforts:[]}],default_model:'gpt-6-luna',billing_mode:'fake'},
};
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#172731"/><rect x="200" y="180" width="420" height="720" rx="24" fill="#316f61"/><rect x="1040" y="250" width="470" height="200" rx="18" fill="#3a718a"/><rect x="1040" y="620" width="470" height="200" rx="18" fill="#315775"/><text x="900" y="100" fill="white" font-size="36" text-anchor="middle">OFFLINE GPIO FIXTURE — NOT A HARDWARE TEST</text></svg>';
const bootstrap=`
const options=new URLSearchParams(location.search);
const resetFixture=options.has('workflow-reset');
const entryFixture=options.get('guide-entry');
const entrySeedKey='guide-entry-seeded:'+entryFixture;
if((!resetFixture&&!entryFixture)||(resetFixture&&!sessionStorage.getItem('workflow-reset-seeded'))||(entryFixture&&!sessionStorage.getItem(entrySeedKey))) {
  localStorage.clear();localStorage.setItem('boardvision.maker.v1',JSON.stringify(${JSON.stringify(state)}));
  if(resetFixture)sessionStorage.setItem('workflow-reset-seeded','true');
  if(entryFixture) {
    const s=${JSON.stringify({...state,guide:{...reviewGuide,componentIndex:1,index:6,run:3}})};
    if(entryFixture==='inspection') {
      s.guide.inspection=true;s.guide.inspectionSource='debug';
      s.guide.inspectionReturn={componentIndex:1,index:6,phase:'review',mode:'camera'};
    }
    localStorage.setItem('boardvision.maker.v1',JSON.stringify(s));
    sessionStorage.setItem(entrySeedKey,'true');
  }
}
localStorage.setItem('boardvision.locale.v1',options.get('lang')||'en');localStorage.setItem('boardvision.theme.v1',options.get('theme')||'dark');
localStorage.setItem('boardvision.wiring-guide-visible.v1','true');
if(options.has('blueprint')) {
  const s=JSON.parse(localStorage.getItem('boardvision.maker.v1'));s.stage='design';s.designView='blueprint';
  localStorage.setItem('boardvision.maker.v1',JSON.stringify(s));
}
const fixed=${JSON.stringify(fixed)},design=${JSON.stringify(design)},board=${JSON.stringify(board)};
if(options.get('reset-case')==='hardware')Object.assign(fixed['/api/pi/status'],{program:'running',pid:1234});
if(options.get('reset-case')==='unknown')delete fixed['/api/pi/status'].execution;
const dockCase=(${JSON.stringify(dockCases)})[options.get('guide-case')];
if(dockCase){localStorage.setItem('boardvision.maker.v1',JSON.stringify(dockCase.state));fixed['/api/pi/component-tests']=dockCase.tests;fixed['/api/pi/status'].connected=dockCase.tests.connected;}
const replay=${JSON.stringify(replay)};
if(options.get('photo-case')==='missing-tft') {
  const s=${JSON.stringify(state)};s.guide={...s.guide,phase:'active',componentIndex:1,index:6};
  localStorage.setItem('boardvision.maker.v1',JSON.stringify(s));
}
fixed['/api/config'].realtime_tracking=options.get('tracking')==='1';
let sourceKind='webcam',sourceGeneration=null;
const trackingCanvas=document.createElement('canvas');trackingCanvas.width=1920;trackingCanvas.height=1080;
const paint=trackingCanvas.getContext('2d');paint.fillStyle='#172731';paint.fillRect(0,0,1920,1080);
paint.fillStyle='#316f61';paint.fillRect(200,180,420,720);paint.fillStyle='#3a718a';paint.fillRect(1040,250,470,200);paint.fillRect(1040,620,470,200);
paint.fillStyle='white';paint.font='36px sans-serif';paint.fillText('OFFLINE SHARED TRACKING FIXTURE',200,100);
const trackingImage=${JSON.stringify(replayImage ? `data:image/jpeg;base64,${replayImage.toString('base64')}` : null)}||trackingCanvas.toDataURL('image/jpeg');
window.__gpioQa={requests:[],errors:[],viewers:{opened:0,closed:0},pauseRecognition:false,phoneActive:true,generation:1,videoSize:[1920,1080],captureDelay:0,captureFails:false,resumeFails:false};
addEventListener('error',e=>window.__gpioQa.errors.push(e.error?.stack||e.message));
addEventListener('unhandledrejection',e=>window.__gpioQa.errors.push(String(e.reason)));
let context=null,chat=null,seq=0,phonePhoto=null;
let lastRecognition=null;
function packet(source,body={}) {
  const id=source+'-'+(++seq),sid=source==='phone'?'offline-phone':'offline-webcam';
  const wires=(body.wires||design.wiring.map(w=>({wire_id:w.id,component_id:w.componentId,board_pin:w.boardPin,component_pin:w.componentPin,connection_kind:w.connectionKind})));
  const revision=fixed['/api/config'].runtime_revision;
  const pose=(extra)=>({frame_id:seq,runtime_revision:revision,video_size:[1920,1080],tracking:'locked',...extra});
  const outline=[[200,180],[620,180],[620,900],[200,900]];
  const detection=pose({board_id:'raspberry-pi-5',outline,pins:board.pins.map((p,i)=>({id:p.id,x:500+(i%2)*36,y:200+Math.floor(i/2)*32,c:1,v:true}))});
  const components=design.component_ids.map((cid,k)=>pose({component_id:cid,outline:[[1040,250+k*370],[1510,250+k*370],[1510,450+k*370],[1040,450+k*370]],
    pins:[...new Set(wires.filter(w=>w.component_id===cid).map(w=>w.component_pin))].map((id,i)=>({id,x:1100+i*42,y:400+k*370,c:1,v:true}))}));
  const localization=[detection,...components].map(p=>({object_id:p.board_id||p.component_id,status:'located',method:'offline-fixture',reason:'synthetic-only',
    evidence:{board_geometry_verified:true,pin_geometry_verified:true},raw_outline_px:p.outline,corrected_outline_px:p.outline}));
  const result={capture_id:id,session_id:sid,context_id:'offline-context',asset_id:id,capture_source:'desktop_stream',
    project_id:body.project_id||design.id,project_revision:body.project_revision||design.revision,image_url:'/api/'+(source==='phone'?'mobile':'photo-wiring')+'/captures/'+id+'/image',
    captured_at:new Date().toISOString(),image_sha256:'a'.repeat(64),frame_id:seq,runtime_revision:revision,video_size:[1920,1080],camera_id:source+'-offline',quality:{},stale:false,
    wires,detection,components,localization};
  if(replay) {
    const mapped=p=>({...p,frame_id:seq,runtime_revision:revision});
    Object.assign(result,{detection:mapped(replay.detection),components:replay.components.map(mapped),
      localization:replay.localization,image_sha256:replay.image_sha256,captured_at:replay.captured_at});
  }
  // Explicit UI-only regression: HC located while the selected TFT is not.
  if(options.get('photo-case')==='missing-tft') {
    const cid='mrd-tf240-8p-cs',module=result.components.find(p=>p.component_id===cid);
    Object.assign(module,{tracking:'searching',pins:[],outline:null,body:{box:[1040,620,1510,820],confidence:.73,partial:true}});
    Object.assign(result.localization.find(p=>p.object_id===cid),{status:'uncertain',reason:'invalid_model_geometry',
      evidence:{},raw_outline_px:null,corrected_outline_px:null});
  }
  return result;
}
function phoneSession(cid) {
  const qa=window.__gpioQa;
  if(!qa.pauseRecognition) {
    const p=packet('phone');const size=qa.videoSize;
    const pose=old=>({...old,video_size:size,runtime_revision:qa.generation});
    lastRecognition={source:'phone',session_id:'offline-phone',generation:qa.generation,context_id:'offline-context',
      frame_seq:p.frame_id,video_size:size,valid_for_ms:1000,coordinates_are_hints_only:true,detection:pose(p.detection),components:p.components.map(pose)};
  }
  return{session_id:'offline-phone',conversation_id:cid,context_id:'offline-context',title:'Offline phone',base_url:location.origin,
    context,stream:{active:qa.phoneActive,publisher_connected:qa.phoneActive,generation:qa.generation,state:'finding',can_capture:false,
      preview_seq:lastRecognition?.frame_seq||0,valid_for_ms:1000,video_fps:null,recognition:lastRecognition},view:{capture_id:null,wire_id:null,revision:0}};
}
window.fetch=async(input,init={})=>{
  const url=new URL(String(input),location.href),path=url.pathname,method=init.method||'GET',body=init.body?JSON.parse(init.body):{};
  window.__gpioQa.requests.push({path,method,body});
  if(url.origin!==location.origin)throw Error('External requests forbidden');
  const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
  if(path==='/api/camera/live-source'){
    if(method==='POST'){
      if(body.kind==='phone'&&!window.__gpioQa.phoneActive)return json({ok:false,error:'mobile_publisher_not_ready'});
      sourceKind=body.kind;sourceGeneration=body.generation??null;
      const cfg=fixed['/api/config'];cfg.camera_source=sourceKind==='phone'?'phone':'device';cfg.runtime_revision++;
      cfg.camera_identity=sourceKind==='phone'?'phone:offline-phone:'+sourceGeneration:'device';
    }
    return json({ok:true,kind:sourceKind,session_id:sourceKind==='phone'?'offline-phone':null,generation:sourceGeneration,
      runtime_revision:fixed['/api/config'].runtime_revision,ready:sourceKind==='webcam'||(window.__gpioQa.phoneActive&&window.__gpioQa.generation===sourceGeneration),error:null});
  }
  if(path==='/api/tracking/frame'){
    if(sourceKind==='phone'&&(!window.__gpioQa.phoneActive||window.__gpioQa.generation!==sourceGeneration))return new Response(null,{status:204});
    const p=packet(sourceKind),revision=fixed['/api/config'].runtime_revision;
    return json({seq:p.frame_id,frame_id:p.frame_id,board_id:'raspberry-pi-5',runtime_revision:revision,image:trackingImage,
      detection:{...p.detection,runtime_revision:revision},components:p.components.map(c=>({...c,runtime_revision:revision}))});
  }
  if(path in fixed&&method==='GET')return json(fixed[path]);
  // Guide restart QA uses only these local receipts; no debug worker or model is started.
  if(path==='/api/debug/conversations/restart'&&method==='POST') {
    const conversation={id:'offline-debug-'+(++seq),project_id:body.project_id,messages:[],check_ids:[],archived:false};
    fixed['/api/debug/conversations']={conversation};return json({conversation});
  }
  if(path==='/api/assistant/conversations'&&method==='POST') {chat={id:body.id,kind:'project',locale:body.locale,project_id:body.project_id??null,messages:[],jobs:[],before:null,total:0,context_epoch:0,round:0,demo:null};return json(chat);}
  if(options.has('blueprint')&&path.endsWith('/messages')&&path.startsWith('/api/assistant/conversations/')&&method==='POST') {
    if(body.target!=='answer')throw Error('Hardware comparison must be read-only');
    chat={...chat,messages:[...chat.messages,{id:'parts-user-'+(++seq),role:'user',text:body.text,stage:'design',capability:'answer',source:'desktop',epoch:0,round:0,created_at:Date.now()/1000},
      {id:'parts-ai-'+seq,role:'assistant',text:options.get('lang')==='zh-TW'?'離線流程測試：僅收到零件型號描述，缺少標籤規格的項目無法確認。這不是實物核對結果。':'OFFLINE FLOW TEST: supplied model text received. Missing ratings cannot be confirmed. This is not a real hardware comparison.',stage:'design',capability:'answer',source:'assistant',epoch:0,round:0,created_at:Date.now()/1000}],total:chat.total+2};
    return json(chat);
  }
  if(path.startsWith('/api/assistant/conversations/')&&['reset','import'].includes(path.split('/').at(-1))&&method==='POST') {
    if(path.endsWith('/reset'))chat={...chat,messages:[],jobs:[],total:0,round:body.round??chat?.round??0,context_epoch:(chat?.context_epoch??0)+1};
    return json(chat);
  }
  if(path.startsWith('/api/assistant/conversations/')&&method==='GET')return json(chat);
  if(path==='/api/ai/estimate')return json({model:'gpt-6-luna',effort:'low',input_tokens:{min:1,max:1},output_tokens:{min:1,max:1},expected_output_tokens:1,api_equivalent_usd:null,reference_credits:null,unavailable_reason:'unknown_price',rates:null});
  if(path==='/api/mobile/context') {context=body;return json({});}
  if(path==='/api/mobile/web-config')return json({available:true,base_url:location.origin,web_url:location.origin+'/mobile'});
  if(path==='/api/mobile/pairings')return json({code:'123456',base_url:location.origin,base_urls:[location.origin],web_url:location.origin+'/mobile?code=123456',expires_at:Date.now()/1000+300});
  if(path==='/api/mobile/desktop-session')return json({session:phoneSession(url.searchParams.get('conversation_id'))});
  if(path==='/api/mobile/session')return json(phoneSession(context?.conversation_id));
  if(path==='/api/mobile/stream/offer')return json({type:'answer',sdp:'offline'});
  if(path==='/api/mobile/stream-capture') {phonePhoto=packet('phone');return json(phonePhoto);}
  if(path.startsWith('/api/mobile/captures/'))return json(phonePhoto);
  if(path==='/api/photo-wiring/snapshot'&&method==='POST') {
    const photo=packet(sourceKind,body);
    photo.image_url='/api/photo-wiring/captures/'+photo.capture_id+'/image';
    return json({...photo,continuous_inference:true});
  }
  if(path==='/api/photo-wiring/sessions'&&method==='POST')return json({session_id:'offline-webcam',continuous_inference:false});
  if(path==='/api/photo-wiring/sessions/offline-webcam/captures'){
    if(window.__gpioQa.captureDelay)await new Promise(r=>setTimeout(r,window.__gpioQa.captureDelay));
    if(window.__gpioQa.captureFails)return new Response(JSON.stringify({detail:'fixture_capture_failed'}),{status:503});
    const photo=packet(sourceKind,body);photo.session_id='offline-webcam';photo.image_url='/api/photo-wiring/captures/'+photo.capture_id+'/image';
    return json(photo);
  }
  if(path==='/api/photo-wiring/sessions/offline-webcam'&&method==='DELETE'){
    if(window.__gpioQa.resumeFails)return new Response(JSON.stringify({detail:'fixture_resume_failed'}),{status:503});
    return json({resumed:true,continuous_inference:true});
  }
  if(path.endsWith('/invalidate'))return json({});
  throw Error('Unmocked offline API '+method+' '+path);
};
window.WebSocket=class extends EventTarget{static CONNECTING=0;static OPEN=1;static CLOSING=2;static CLOSED=3;readyState=0;
  constructor(url){super();const u=new URL(url);if(u.pathname==='/api/mobile/events')this.timer=setInterval(()=>{
    this.readyState=1;this.onmessage?.({data:JSON.stringify({type:'state',session:phoneSession(u.searchParams.get('conversation_id'))})});},350);}
  close(){clearInterval(this.timer);this.readyState=3;}send(){throw Error('Offline socket');}};
window.RTCPeerConnection=class{
  iceGatheringState='complete';connectionState='new';localDescription=null;
  addTransceiver(){return{receiver:{},setCodecPreferences(){}};}getTransceivers(){return[];}
  async createOffer(){return{type:'offer',sdp:'offline'};}async setLocalDescription(v){this.localDescription=v;}
  async setRemoteDescription(){const c=document.createElement('canvas');c.width=1920;c.height=1080;const ctx=c.getContext('2d');ctx.fillStyle='#225d67';ctx.fillRect(0,0,1920,1080);
    const image=new Image();image.src='/video';image.onload=()=>{ctx.drawImage(image,0,0);};
    this.frameTimer=setInterval(()=>{if(image.complete&&image.naturalWidth)ctx.drawImage(image,0,0);},200);
    this.stream=c.captureStream(5);this.connectionState='connected';window.__gpioQa.viewers.opened++;this.ontrack?.({streams:[this.stream],receiver:{}});this.onconnectionstatechange?.();}
  async getStats(){return new Map();}close(){clearInterval(this.frameTimer);if(this.stream){this.stream.getTracks().forEach(t=>t.stop());this.stream=null;window.__gpioQa.viewers.closed++;}}
};
if(new URLSearchParams(location.search).has('header-panels'))window.addEventListener('DOMContentLoaded',()=>{
  const status=document.createElement('output');status.id='header-panel-monitor';
  status.style.cssText='position:fixed;left:12px;bottom:6px;z-index:1000;font:11px monospace;color:#8bd7c5;background:#111b22;padding:4px 7px;border-radius:5px;pointer-events:none';
  document.body.append(status);let previous=null,overlaps=0,changes=0;
  const observe=()=>{
    const active=[document.querySelector('#mobile-companion-panel')?'phone':null,
      document.querySelector('.pi-device-menu[open]')?'pi':null,
      document.querySelector('.runtime-settings[open]')?'settings':null].filter(Boolean);
    const key=active.join(',');if(key===previous)return;previous=key;changes++;
    if(active.length>1)overlaps++;
    status.dataset.active=key;status.dataset.overlaps=String(overlaps);status.dataset.changes=String(changes);
    status.textContent='Offline UI · active: '+(key||'none')+' · overlaps: '+overlaps;
  };
  new MutationObserver(observe).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});observe();
});
`;
const html=(await readFile(new URL('index.html',dist),'utf8')).replace('<head>','<head><script src="/fixture.js"></script>');
const baselineEntry=process.env.GPIO_HEADER_BASELINE_ENTRY;
if(baselineEntry&&!/^\/assets\/index-[\w-]+\.js$/.test(baselineEntry))throw Error('Invalid header baseline asset');
const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1'),path=url.pathname;
  if(req.method!=='GET'){res.writeHead(405);res.end('Offline fixture: no mutations');return;}
  let content,type;
  if(path==='/'){content=baselineEntry&&url.searchParams.has('legacy-header')
    ? html.replace(/src="\/assets\/index-[\w-]+\.js"/,`src="${baselineEntry}"`) : html;type='text/html';}
  else if(path==='/fixture.js'){content=bootstrap;type='text/javascript';}
  else if(path==='/video'||path==='/frame.jpg'||/^\/api\/(mobile|photo-wiring)\/captures\/[^/]+\/image$/.test(path)){content=replayImage||svg;type=replayImage?'image/jpeg':'image/svg+xml';}
  else if(/^\/(assets|brand|demo)\/[a-zA-Z0-9._-]+$/.test(path)||path==='/theme.js'){
    try{content=await readFile(new URL('.'+path,dist));type=path.endsWith('.css')?'text/css':path.endsWith('.png')?'image/png':path.endsWith('.svg')?'image/svg+xml':'text/javascript';}catch{}
  }
  if(content===undefined){res.writeHead(404);res.end('Offline fixture: no proxy');return;}
  res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-src 'none'"});res.end(content);
});
const port=Number(process.env.GPIO_PREVIEW_PORT||18794);
server.listen(port,'127.0.0.1',()=>console.log('Isolated GPIO fixture http://127.0.0.1:'+port+'/'));
