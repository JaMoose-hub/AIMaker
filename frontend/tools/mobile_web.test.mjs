import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
import {markdownFixture} from './assistant_markdown_fixture.mjs';

function load(file,modules={}) {
  const js=ts.transpileModule(readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};new Function('require','exports',js)(name=>{if(!(name in modules))throw Error(`Unexpected runtime import ${name}`);return modules[name];},exports);return exports;
}
const photo=load('../src/lib/photoWiring.ts');
const streamPolicy=load('../src/lib/mobileStreamPolicy.ts');
const browserRtc=load('../src/lib/mobileBrowserRtc.ts',{'./mobileStreamPolicy':streamPolicy});
const viewerStats=load('../src/lib/mobileViewerStats.ts');
const recognition=load('../src/lib/mobileRecognition.ts');
const mobile=load('../src/lib/mobile.ts',{react:React,'./photoWiring':photo,'./mobileBrowserRtc':browserRtc,'./mobileViewerStats':viewerStats,'./mobileRecognition':recognition});
const view=load('../src/lib/mobileWebView.ts',{'./photoWiring':photo});
const history=load('../src/lib/assistantHistory.ts');
const localCapture=load('../src/lib/mobileBrowserCapture.ts');
const wiringReview=load('../src/lib/wiringReview.ts');
const wiringChat=load('../src/lib/wiringChat.ts',{'./wiringReview':wiringReview});
const WiringReviewOverview=({summary,children})=>React.createElement('section',{'data-review-overview':true},
  React.createElement('p',null,summary.headline),React.createElement('p',null,summary.next_step),children);
const browserTree=ts.createSourceFile('useMobileBrowser.ts',readFileSync(new URL('../src/lib/useMobileBrowser.ts',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
const flowFunction=browserTree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='mobileWiringPhotoFlow');
assert.ok(flowFunction,'UI fixtures must use the current shared-question eligibility guard');
const flowCode=ts.transpileModule(flowFunction.getText(browserTree).replace(/^export\s+/,''),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const mobileWiringPhotoFlow=new Function(`${flowCode}; return mobileWiringPhotoFlow;`)();
const analysisFunction=browserTree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='mobileWiringAnalysisFlow');
const analysisCode=ts.transpileModule(analysisFunction.getText(browserTree).replace(/^export\s+/,''),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const mobileWiringAnalysisFlow=new Function(`${analysisCode}; return mobileWiringAnalysisFlow;`)();
const WiringPhotoSequence = props => React.createElement('div', {className:'fixture-photo-sequence', ...props});
const FramingGuide = () => React.createElement('svg');
function capture(){
  const outline=[[20,20],[300,20],[300,250],[20,250]],size=[1080,1920];
  const pin=(id,x,y)=>({id,x,y,c:.9,v:true});
  const pose={frame_id:17,runtime_revision:2,tracking:'locked',video_size:size,outline};
  return {capture_id:'c',session_id:'s',asset_id:'a',context_id:'ctx',image_url:'/api/mobile/captures/c/image',image_sha256:'a'.repeat(64),captured_at:1,camera_id:'phone',frame_id:17,runtime_revision:2,video_size:size,quality:{},
    detection:{...pose,board_id:'raspberry-pi-5',pins:[pin('GPIO17',30,60)]},components:[{...pose,component_id:'hc-sr04',pins:[pin('TRIG',260,200)]}],
    localization:['raspberry-pi-5','hc-sr04'].map(id=>({object_id:id,status:'located',method:'fixture',reason:'fixture',evidence:{board_geometry_verified:true,pin_geometry_verified:true},raw_outline_px:outline,corrected_outline_px:outline})),
    wires:[{wire_id:'wire',component_id:'hc-sr04',board_pin:'GPIO17',component_pin:'TRIG',connection_kind:'direct'}]};
}

test('query pairing code accepts only the six-digit code and never treats another URL as an instruction',()=>{
  assert.equal(view.mobilePairingCode('?code=003219'),'003219');assert.equal(view.mobilePairingCode('?code=12345'),'');
  assert.equal(view.mobilePairingCode('?code=https://elsewhere.invalid/'),'');assert.equal(view.mobilePairingCode('?code=1234567'),'');
});

test('formal photo ticket has a separate 120-second handoff window, never a renewed preview lock',()=>{
  const issued=100000,expiresAt=(issued+120000)/1000;
  assert.equal(view.mobileCaptureSeconds(expiresAt,issued),120);
  assert.equal(view.mobileCaptureSeconds(expiresAt,issued+2000),118);
  assert.equal(view.mobileCaptureSeconds(expiresAt,issued+120001),0);
  assert.equal(view.mobileCaptureSeconds(undefined,issued),0);
});

test('portrait, landscape and zoom share one proportional image and SVG coordinate plane',()=>{
  for(const size of [[1080,1920],[4032,3024],[3024,4032]]) {
    const fitted=view.mobilePhotoLayout(size,327,410,1),zoomed=view.mobilePhotoLayout(size,327,410,2);
    assert.ok(fitted.width<=327.001 && fitted.height<=410.001);
    assert.ok(Math.abs(fitted.width/fitted.height-size[0]/size[1])<1e-9);
    assert.equal(zoomed.width,fitted.width*2);assert.equal(zoomed.height,fitted.height*2);
  }
  assert.equal(view.mobilePhotoLayout([0,1920],320,400),null);
});

test('saved-photo pins require matching natural size and exact frame/runtime geometry',()=>{
  const good=capture(),geometry=view.mobilePhotoGeometry(good,'wire',[1080,1920]);
  assert.equal(geometry.boardPin.id,'GPIO17');assert.equal(geometry.componentPin.id,'TRIG');
  for(const mutate of [c=>c.detection.frame_id++,c=>c.components[0].runtime_revision++,c=>c.stale=true,c=>c.image_sha256='bad']) {
    const changed=structuredClone(good);mutate(changed);assert.equal(view.mobilePhotoGeometry(changed,'wire',[1080,1920]),null);
  }
  assert.equal(view.mobilePhotoGeometry(good,'wire',[1920,1080]),null);assert.equal(view.mobilePhotoGeometry(good,'wire',null),null);
});

test('uncertain physical contacts retain their reason without promoted GPIO',()=>{
  const value=capture();value.localization[1]={...value.localization[1],status:'uncertain',reason:'hc_geometry_unverified',corrected_outline_px:null,evidence:{}};
  value.components[0]={...value.components[0],tracking:'searching',outline:null,pins:[]};
  const geometry=view.mobilePhotoGeometry(value,'wire',[1080,1920]);assert.ok(geometry);assert.equal(geometry.componentPin,null);
  assert.deepEqual(view.mobilePhotoReasons(value),[{id:'hc-sr04',reason:'hc_geometry_unverified'}]);
});

test('a stale locked preview cannot tell the user it is ready to capture',()=>{
  assert.equal(view.mobileReadiness({active:true,state:'locked'},true),'locked');
  assert.equal(view.mobileReadiness({active:true,state:'locked'},false),'finding');
  assert.equal(view.mobileReadiness({active:false,state:'locked'},true),'idle');
  assert.equal(view.mobileReadiness({active:true,state:'hold_still'},false,false),'finding');
  assert.equal(view.mobileReadiness({active:true,state:'hold_still'},false,true),'hold_still');
});

test('a retired GPIO photo exposes explicit attachment recovery and disables an invalid retry',()=>{
  const h=hookHarness(),calls=[],{MobileWebCamera}=components('en',h.hooks);
  const w={...workspace(),captureJob:{ticket:{context_id:'old-step'},error:'Retired capture',attachment:{name:'original.jpg'}},
    discardCapture:keep=>{calls.push(['keep',keep]);return true;},retryCapture(){throw Error('A retired ticket cannot be retried');}};
  h.reset();const nodes=treeNodes(MobileWebCamera({w,onCaptured(){},onDebugCaptured:()=>calls.push(['chat'])}));
  const text=node=>React.Children.toArray(node.props.children).filter(child=>typeof child==='string').join('');
  assert.equal(nodes.find(node=>node.type==='button'&&text(node)==='Retry this photo').props.disabled,true);
  const keep=nodes.find(node=>node.type==='button'&&text(node)==='Keep as chat attachment');
  assert.equal(keep.props.disabled,false);keep.props.onClick();assert.deepEqual(calls,[['keep',true],['chat']]);
});

test('the current shared analysis message exposes a phone action, pending state and retry without a second photo panel',()=>{
  const h=hookHarness(),{MobileWiringChatActions}=components('zh-TW',h.hooks),calls=[];
  const review={id:'review',revision:4,round:1,component_id:'hc-sr04',status:'collecting'};
  const message={id:'ready',role:'assistant',epoch:0,round:1,wiring_flow:{flow_id:'flow',review_id:'review',revision:4,
    round:1,component_id:'hc-sr04',kind:'analysis_request',current:true,can_act:true,actions:['analyse']}};
  const w={...workspace(),session:{conversation_id:'chat',context_id:'ctx',context:{round:1}},
    conversation:{id:'chat',context_epoch:0},wiringReview:review,wiringCanAct:true,wiringReviewBusy:false,
    analyseWiringChat:entry=>calls.push(entry.id)};
  const render=(state=w,entry=message)=>{h.reset();return treeNodes(MobileWiringChatActions({w:state,message:entry}));};
  let nodes=render(),button=nodes.find(node=>node.type==='button');
  assert.equal(button.props.children,'開始分析');assert.equal(button.props.disabled,false);
  button.props.onClick();assert.deepEqual(calls,['ready']);assert.equal(nodes.filter(node=>node.type==='button').length,1);
  for(const state of [{connected:false},{busy:true},{wiringReviewBusy:true},{chatSendBlocked:true},{wiringCanAct:false}])
    assert.equal(render({...w,...state}).find(node=>node.type==='button').props.disabled,true);
  assert.equal(render({...w,wiringReviewBusy:true}).find(node=>node.type==='button').props.children,'送出中…');
  assert.equal(render(w,{...message,wiring_flow:{...message.wiring_flow,kind:'error'}}).find(node=>node.type==='button').props.children,'重新分析');
  assert.equal(render({...w,wiringReviewError:'分析未完成，請重試'}).some(node=>node.props.role==='alert'),true);
  assert.equal(render(w,{...message,wiring_flow:{...message.wiring_flow,can_act:false}}).find(node=>node.type==='button').props.disabled,true);
  assert.equal(render(w,{...message,wiring_flow:{...message.wiring_flow,actions:[]}}).find(node=>node.type==='button').props.disabled,true);
  for(const changed of [{current:false},{revision:3},{kind:'analysing'}])
    assert.equal(render(w,{...message,wiring_flow:{...message.wiring_flow,...changed}}).length,0);
});

function workspace(){return {ready:true,pairing:{session_id:'s'},connected:true,secureContext:true,busy:false,error:'',api:null,
  session:{session_id:'s',conversation_id:'conversation-1',title:'Desk project',context:{stage:'guide'},context_id:'ctx',view:{wire_id:'wire'},stream:{active:false,state:'finding'}},
  conversation:{id:'conversation-1',context_epoch:1,round:3,messages:[],jobs:[],before:null},draft:'Preserve this draft',attachments:[],outbox:[],capture:null,captureJob:null,captureTicket:null,
  rtc:{stream:null,settings:null,stats:{},status:'off'},canCapture:false,inheritedMediaLabel:null,
  setDraft(){},pair:async()=>{},send:async()=>{},removeMediaReference(){},disconnect:async()=>{},stopStream:async()=>{},openCapture:async()=>{},older:async()=>{},addFiles:async()=>{},removeAttachment(){},retry:async()=>{},removeOutbox(){}};}
function components(locale='en',reactOverrides={},captureOverrides={},assetHook=()=>({url:null,error:'',retry(){}}),setLocale=()=>{}) {
  return load('../src/components/MobileWebApp.tsx',{
    react:{...React,useLayoutEffect(){},...reactOverrides},'react/jsx-runtime':jsx,'../lib/i18n':{useI18n:()=>({locale,setLocale})},
    '../lib/mobile':mobile,'../lib/mobileWebView':view,'../lib/assistantHistory':history,'../lib/mobileBrowserCapture':{...localCapture,...captureOverrides},'../lib/useMobileBrowser':{useMobileBrowser:workspace,useMobileAssetUrl:assetHook,
      mobileTestHelpOffer:()=>null,mobileWiringPhotoFlow,mobileWiringAnalysisFlow},
    '../lib/wiringReview':wiringReview,'./WiringPhotoSequence':{WiringPhotoSequence},'./WiringReviewCard':{FramingGuide},'./wiringReview.css':{},'../mobileWeb.css':{},
    './AssistantAnalysisTime':{AssistantAnalysisTime:()=>null},
    './AssistantMarkdown':markdownFixture(locale),
    './WiringChatMessage':{WiringCaptureFraming:()=>null,WiringReviewOverview,WiringPhotoDelivery:()=>null},'../lib/wiringChat':wiringChat,
    './MobileWiringAlbumPanel':{MobileWiringAlbumPanel:()=>null},
    '../lib/useMobileWiringAlbum':load('../src/lib/useMobileWiringAlbum.ts',{react:{...React,...reactOverrides},'./wiringReview':wiringReview}),
    './PhoneCameraAutoTune':{PhoneCameraAutoTune:()=>null},
  });
}

function hookHarness() {
  const states=[],refs=[];let stateCursor=0,refCursor=0;
  return {refs,reset(){stateCursor=0;refCursor=0;},hooks:{
    useState(initial){const index=stateCursor++;if(!(index in states))states[index]=typeof initial==='function'?initial():initial;return [states[index],value=>{states[index]=typeof value==='function'?value(states[index]):value;}];},
    useRef(initial){const index=refCursor++;return refs[index]??=( {current:initial} );},useEffect(){},
  }};
}
const treeNodes=element=>!React.isValidElement(element)?[]:[element,...React.Children.toArray(element.props.children).flatMap(treeNodes)];

test('compact phone finding shows one shared overview and keeps the original message collapsed without granting actions',()=>{
  const h=hookHarness(),{ChatView}=components('en',h.hooks);
  const result={wire_id:'ground',expected:{component_pin:'GND',physical_pin:6},comparison:'unknown',next_step:'Retake the module header.',
    diagnosis:{status:'uncertain',retake_roles:['component_header']},pi_candidates:[],component_candidates:[]};
  const summary={schema_version:2,headline:'The module header is unclear.',next_step:'Show its labels and connector bases.',retake_role:'component_header',
    counts:{suspected:0,uncertain:1,no_issue_seen:0},results:[result],evidence:'The label is hidden.'};
  const message={id:'finding',role:'assistant',text:'Verbose original pin inventory retained for this exact photograph.',epoch:1,round:3,
    wiring_flow:{kind:'wire_review',current:true,can_act:false,actions:[],flow_id:'flow',review_id:'review',revision:3,round:3,
      component_id:'hc-sr04',wire_id:'ground',result,summary,elapsed_ms:75000}};
  const w=workspace();w.conversation.messages=[message];
  const before=structuredClone(w.conversation);
  h.reset();const tree=ChatView({w,onPhoto(){throw Error('Reading a finding must not open a capture');}});
  const nodes=treeNodes(tree),overview=nodes.find(node=>node.type===WiringReviewOverview);
  assert.equal(overview.props.summary,summary);
  const record=treeNodes(overview).find(node=>node.type==='details');
  assert.equal(record.props.open,undefined);
  assert.ok(treeNodes(record).some(node=>node.props.text===message.text));
  const article=nodes.find(node=>node.type==='article'&&node.props['data-message-id']==='finding');
  const html=renderToStaticMarkup(article);
  assert.equal((html.match(/data-review-overview/g)||[]).length,1);
  assert.match(html,/The module header is unclear/);assert.match(html,/Show its labels and connector bases/);
  assert.match(html,/Choose Retake on your computer/);
  assert.doesNotMatch(html,/<button/);
  assert.deepEqual(w.conversation,before);
});

test('compact phone history folds only past routine steps and preserves user text and failures in view',()=>{
  const h=hookHarness(),{ChatView}=components('en',h.hooks),w=workspace();
  const flow={kind:'photo_request',role:'pi_side_a',current:false,can_act:false,actions:[]};
  const messages=[
    {id:'past',role:'assistant',text:'The original detailed photographic instructions remain available.',epoch:1,round:3,wiring_flow:flow},
    {id:'user',role:'user',text:'Please keep my own wording exactly.',epoch:1,round:3,wiring_flow:flow},
    {id:'failure',role:'assistant',text:'Analysis failed; the saved photograph is retained.',epoch:1,round:3,wiring_flow:{...flow,kind:'error',error:'The cloud request timed out after receiving the photographs.'}}];
  w.conversation.messages=messages;
  h.reset();const nodes=treeNodes(ChatView({w,onPhoto(){}}));
  const article=id=>nodes.find(node=>node.type==='article'&&node.props['data-message-id']===id);
  const folded=treeNodes(article('past')).find(node=>node.type==='details'&&node.props.className==='wiring-chat-history');
  assert.ok(folded);assert.equal(folded.props.open,undefined);
  assert.ok(treeNodes(folded).some(node=>node.props.text===messages[0].text));
  for(const id of ['user','failure']) assert.ok(!treeNodes(article(id)).some(node=>node.props.className==='wiring-chat-history'));
  assert.match(renderToStaticMarkup(article('user')),/Please keep my own wording exactly/);
  assert.match(renderToStaticMarkup(article('failure')),/Analysis failed; the saved photograph is retained/);
  const errorDetails=treeNodes(article('failure')).find(node=>node.type==='details');
  assert.ok(errorDetails);assert.equal(errorDetails.props.open,undefined);
  assert.match(renderToStaticMarkup(errorDetails),/View error details/);
  assert.match(renderToStaticMarkup(errorDetails),/The cloud request timed out after receiving the photographs/);
  assert.equal(messages[0].text,'The original detailed photographic instructions remain available.');
});

test('phone language switch exposes Traditional Chinese and English with the selected language announced',()=>{
  for(const locale of ['zh-TW','en']) {
    const {MobileLanguageSwitch}=components(locale);
    const buttons=treeNodes(MobileLanguageSwitch()).filter(node=>node.type==='button');
    assert.deepEqual(buttons.map(node=>node.props.children),['繁中','English']);
    assert.deepEqual(buttons.map(node=>node.props['aria-pressed']),[locale==='zh-TW',locale==='en']);
    assert.ok(buttons.every(node=>node.props.type==='button'));
    assert.deepEqual(buttons.map(node=>node.props.lang),['zh-Hant','en']);
  }
});

test('phone language change uses the existing saved locale without workspace or camera actions',()=>{
  const calls=[],{MobileLanguageSwitch}=components('zh-TW',{}, {},undefined,locale=>calls.push(locale));
  const buttons=treeNodes(MobileLanguageSwitch()).filter(node=>node.type==='button');
  assert.deepEqual(calls,[]);
  buttons[1].props.onClick();buttons[0].props.onClick();
  assert.deepEqual(calls,['en','zh-TW']);
});

test('phone language control is available before pairing and throughout the paired workspace',()=>{
  const {MobileWebSurface}=components('en');
  for(const pairing of [null,{session_id:'s'}]) {
    const w={...workspace(),pairing};
    const html=renderToStaticMarkup(React.createElement(MobileWebSurface,{workspace:w}));
    assert.equal((html.match(/aria-label="語言 \/ Language"/g)||[]).length,1);
    assert.match(html,/>繁中<\/button>/);assert.match(html,/>English<\/button>/);
    assert.equal(w.draft,'Preserve this draft');
  }
});

test('phone stream keeps the language control in its compact header without changing the active tab',()=>{
  const h=hookHarness(),{MobileWebSurface}=components('en',h.hooks),w=workspace();
  h.reset();const first=MobileWebSurface({workspace:w});
  treeNodes(first).find(node=>node.type==='button'&&node.props.children?.some?.(child=>child?.props?.children==='Stream')).props.onClick();
  h.reset();const camera=MobileWebSurface({workspace:w});
  const header=treeNodes(camera).find(node=>node.type==='header'&&node.props.className==='mw-header');
  const html=renderToStaticMarkup(header);
  assert.equal((html.match(/aria-label="語言 \/ Language"/g)||[]).length,1);
  assert.equal(camera.props['data-tab'],'camera');
  assert.equal(w.draft,'Preserve this draft');
  assert.equal(w.rtc.status,'off');
});

function localVideoScene(width=1080,height=1920) {
  const draws=[],track={readyState:'live'},stream={getVideoTracks:()=>[track]};
  const canvas={width:0,height:0,getContext:()=>({drawImage(...args){draws.push(args);}}),
    toBlob(callback,mime,quality){draws.push({width:canvas.width,height:canvas.height,mime,quality});callback(new Blob(['raw camera JPEG'],{type:mime}));}};
  const video={srcObject:stream,readyState:4,paused:false,videoWidth:width,videoHeight:height,ownerDocument:{createElement:()=>canvas}};
  return {draws,stream,track,canvas,video};
}
const nextTurn=()=>new Promise(resolve=>setImmediate(resolve));

function photoRound(overrides={}) {
  return {id:'review-1',revision:7,round:2,component_id:'hc-sr04',status:'collecting',photo_flow_version:2,
    slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:[],reviews:{},missing_roles:['pi_side_a','pi_side_b','component_header'],no_progress_count:0,...overrides};
}

function photoQuestion(review,role='pi_side_a') {
  return {id:'photo-question',role:'assistant',epoch:1,round:3,wiring_flow:{kind:'photo_request',flow_id:'flow-1',review_id:review.id,
    revision:review.revision,round:review.round,component_id:review.component_id,role,current:true,can_act:true,actions:['capture']}};
}
function photoWorkspace(review) {
  const w=workspace();return {...w,session:{...w.session,context:{...w.session.context,round:3}},wiringReview:review,wiringCanAct:true,wiringReviewBusy:false,wiringReviewError:''};
}

test('paired phone shared question captures each requested native-camera view without GPIO tickets or ordinary chat',async()=>{
  for(const role of ['pi_side_a','pi_side_b','component_header']) {
    const h=hookHarness(),calls=[],review=photoRound(),message=photoQuestion(review,role),request={message_id:message.id,flow_id:'flow-1',role,review};
    const {MobileWiringChatActions}=components('en',h.hooks);
    const w={...photoWorkspace(review),prepareWiringChatPhoto(question){assert.equal(question,message);return request;},
      uploadWiringChatPhoto:async(file,target,onSubmitted)=>{calls.push(['upload',file,target]);onSubmitted?.();return true;},
      beginCapture(){throw Error('Side photographs must not require a GPIO pose ticket');},send(){throw Error('A photograph must not send an ordinary AI question');}};
    h.reset();const tree=MobileWiringChatActions({w,message}),input=treeNodes(tree).find(node=>node.type==='input'&&node.props.type==='file');
    input.ref.current={click:()=>calls.push(['camera'])};assert.equal(input.props.capture,'environment');assert.equal(input.props.accept,'image/*');
    const button=treeNodes(tree).find(node=>node.type==='button');assert.equal(button.props.disabled,false);button.props.onClick();
    const file={name:`${role}.jpg`},event={target:{files:[file],value:'native-photo'}};input.props.onChange(event);await nextTurn();
    assert.equal(event.target.value,'');assert.deepEqual(calls,[['camera'],['upload',file,request]]);
    button.props.onClick();input.props.onChange({target:{files:[],value:''}});await nextTurn();assert.equal(calls.length,3,'cancelling the camera does not submit');
    input.props.onChange({target:{files:[file],value:'late'}});assert.equal(calls.length,3,'an input change without an explicit request cannot submit');
  }
});

test('paired phone album selects each requested view through the same role-bound upload without forcing a camera',async()=>{
  for(const locale of ['zh-TW','en']) for(const role of ['pi_side_a','pi_side_b','component_header']) {
    const h=hookHarness(),calls=[],review=photoRound(),message=photoQuestion(review,role),request={message_id:message.id,flow_id:'flow-1',role,review};
    const {MobileWiringChatActions}=components(locale,h.hooks);
    const w={...photoWorkspace(review),prepareWiringChatPhoto(question){assert.equal(question,message);return request;},
      uploadWiringChatPhoto:async(file,target,onSubmitted)=>{calls.push(['upload',file,target]);onSubmitted?.();return true;},
      beginCapture(){throw Error('Album photos must not require a GPIO ticket');},send(){throw Error('Album photos must not become ordinary chat');}};
    h.reset();const tree=MobileWiringChatActions({w,message}),nodes=treeNodes(tree);
    const input=nodes.find(node=>node.type==='input'&&node.props.type==='file'&&!node.props.capture);
    assert.equal(input.props.accept,'image/*');assert.notEqual(input.props.multiple,true,'standalone one-view actions remain single selection');
    input.ref.current={click:()=>calls.push(['album'])};
    const label=locale==='en'?'Choose from album':'從相簿選擇';
    const button=nodes.find(node=>node.type==='button'&&React.Children.toArray(node.props.children).includes(label));
    assert.ok(button);assert.equal(button.props.disabled,false);button.props.onClick();
    const file={name:`saved-${role}.jpg`},event={target:{files:[file],value:'selected-album-photo'}};
    input.props.onChange(event);await nextTurn();
    assert.deepEqual(calls,[['album'],['upload',file,request]]);assert.equal(event.target.value,'');
    button.props.onClick();input.props.onChange({target:{files:[],value:''}});await nextTurn();
    assert.equal(calls.length,3,'cancelling the album leaves the question unanswered');
    input.props.onChange({target:{files:[file],value:'late'}});assert.equal(calls.length,3,'unrequested selection cannot upload');
    button.props.onClick();input.props.onChange({target:{files:[file],value:'same-file'}});await nextTurn();
    assert.deepEqual(calls.at(-1),['upload',file,request],'the same saved file can be explicitly selected again');
    assert.match(renderToStaticMarkup(tree),locale==='en'?/Use new photos if the wiring changed/:/接線改過請用新照片/);
  }
});

test('album and camera keep independent frozen question requests and refuse unavailable requests',async()=>{
  const h=hookHarness(),calls=[],review=photoRound(),message=photoQuestion(review),{MobileWiringChatActions}=components('en',h.hooks);
  let request={role:'pi_side_a',request_id:'album-request',review};
  const w={...photoWorkspace(review),prepareWiringChatPhoto:()=>request,
    uploadWiringChatPhoto:async(file,target,onSubmitted)=>{calls.push([file,target]);onSubmitted?.();return true;}};
  h.reset();const tree=MobileWiringChatActions({w,message}),nodes=treeNodes(tree);
  const camera=nodes.find(node=>node.type==='input'&&node.props.capture==='environment');
  const album=nodes.find(node=>node.type==='input'&&node.props.type==='file'&&!node.props.capture);
  let cameraOpened=0,albumOpened=0;camera.ref.current={click:()=>cameraOpened++};album.ref.current={click:()=>albumOpened++};
  const buttons=nodes.filter(node=>node.type==='button');
  buttons[1].props.onClick();const frozen=request;
  request={role:'component_header',request_id:'camera-request',review};buttons[0].props.onClick();
  const albumFile={name:'album.jpg'},cameraFile={name:'camera.jpg'};
  album.props.onChange({target:{files:[albumFile],value:'selected'}});
  camera.props.onChange({target:{files:[cameraFile],value:'selected'}});await nextTurn();
  assert.deepEqual(calls,[[albumFile,frozen],[cameraFile,request]]);
  request=null;buttons[0].props.onClick();buttons[1].props.onClick();
  assert.equal(cameraOpened,1);assert.equal(albumOpened,1);
  album.props.onChange({target:{files:[albumFile],value:'late'}});assert.equal(calls.length,2);
});

test('mobile multi-select stages three photos without uploading and sends only the current fresh question',async()=>{
  const h=hookHarness(),calls=[],review=photoRound(),message=photoQuestion(review),{MobileWiringChatActions}=components('en',h.hooks);
  const files=[{name:'side-a.jpg'},{name:'side-b.jpg'},{name:'header.jpg'}];
  let selected=null,confirmed=false,request={message_id:message.id,role:'pi_side_a',request_id:'picker',review};
  const photoAlbum={selection:{photos:[]},stage(values,target){selected=values;calls.push(['stage',values,target]);return true;},
    fileFor(target){assert.equal(target,request);return confirmed?selected[0]:null;},submitted:target=>calls.push(['submitted',target])};
  const w={...photoWorkspace(review),prepareWiringChatPhoto:()=>request,
    uploadWiringChatPhoto:async(file,target,onSubmitted)=>{calls.push(['upload',file,target]);onSubmitted?.();return true;}};
  h.reset();let tree=MobileWiringChatActions({w,message,photoAlbum});
  const input=treeNodes(tree).find(node=>node.type==='input'&&node.props.type==='file'&&!node.props.capture);
  assert.equal(input.props.multiple,true);input.ref.current={click(){}};
  treeNodes(tree).filter(node=>node.type==='button')[1].props.onClick();
  input.props.onChange({target:{files,value:'three'}});await nextTurn();
  assert.deepEqual(calls,[['stage',files,request]],'multi-selection is local only');
  request={...request,request_id:'fresh-question',review:{...review,revision:8}};
  h.reset();tree=MobileWiringChatActions({w,message,photoAlbum});
  const panel=treeNodes(tree).find(node=>node.props.album===photoAlbum);
  panel.props.onUse();await nextTurn();assert.equal(calls.length,1,'no upload until views are confirmed');
  confirmed=true;panel.props.onUse();await nextTurn();
  assert.deepEqual(calls.slice(1),[['upload',files[0],request],['submitted',request]]);
});

test('three selected album photos survive switching phone tabs without any automatic upload',()=>{
  const h=hookHarness(),review=photoRound(),{MobileWebSurface,ChatView}=components('en',h.hooks);
  const w=photoWorkspace(review),files=[{name:'a.jpg'},{name:'b.jpg'},{name:'module.jpg'}];
  const render=()=>{h.reset();return MobileWebSurface({workspace:w});};
  let tree=render(),chat=treeNodes(tree).find(node=>node.type===ChatView);
  const request={contextId:w.session.context_id,conversationId:w.conversation.id,epoch:w.conversation.context_epoch,review,role:'pi_side_a'};
  assert.equal(chat.props.photoAlbum.stage(files,request),true);tree=render();
  const navigate=name=>treeNodes(tree).find(node=>node.type==='nav').props.children.find(node=>React.Children.toArray(node.props.children)
    .some(child=>React.isValidElement(child)&&child.type==='span'&&child.props.children===name)).props.onClick();
  navigate('Stream');tree=render();assert.equal(tree.props['data-tab'],'camera');
  navigate('Chat');tree=render();chat=treeNodes(tree).find(node=>node.type===ChatView);
  assert.deepEqual(chat.props.photoAlbum.selection.photos.map(photo=>photo.file),files);
  assert.equal(chat.props.photoAlbum.selection.confirmed,false);
});

test('shared photo retry stays bound to its question and offers no manual confirmation or analysis panel',async()=>{
  const h=hookHarness(),calls=[],review=photoRound(),message=photoQuestion(review),{MobileWiringChatActions}=components('en',h.hooks);
  const w={...photoWorkspace(review),pendingWiringPhoto:{dialogue:{message_id:message.id},attachment:{progress:.5}},
    retryWiringPhoto:async()=>calls.push('retry'),refresh:async()=>calls.push('refresh'),discardWiringPhoto:()=>calls.push('discard')};
  h.reset();const tree=MobileWiringChatActions({w,message});const buttons=treeNodes(tree).filter(node=>node.type==='button');
  buttons.find(node=>node.props.children==='Retry this photo').props.onClick();await nextTurn();assert.deepEqual(calls,['retry']);
  const html=renderToStaticMarkup(tree);assert.match(html,/Photo delivery is not confirmed/);assert.doesNotMatch(html,/confirm wiring|Analyse|fixture-photo-sequence/);
  h.reset();const other=MobileWiringChatActions({w,message:{...message,id:'another-question'}});
  assert.doesNotMatch(renderToStaticMarkup(other),/Retry this photo|Remove pending photo/);
});

test('phone round and workspace changes make old shared photo questions inert',()=>{
  const review=photoRound(),message=photoQuestion(review);
  for(const change of [w=>{w.wiringCanAct=false;},w=>{w.session.available_context={context_id:'new-project'};},w=>{w.wiringReview={...review,revision:8};},w=>{w.conversation={...w.conversation,context_epoch:2};}]) {
    const h=hookHarness(),calls=[],{MobileWiringChatActions}=components('en',h.hooks),w={...photoWorkspace(review),prepareWiringChatPhoto:()=>calls.push('prepare')};
    change(w);h.reset();const tree=MobileWiringChatActions({w,message});assert.equal(treeNodes(tree).filter(node=>node.type==='button').length,0);assert.deepEqual(calls,[]);
  }
  for(const busy of ['busy','wiringReviewBusy']) {
    const h=hookHarness(),{MobileWiringChatActions}=components('en',h.hooks),w=photoWorkspace(review);w[busy]=true;
    h.reset();const buttons=treeNodes(MobileWiringChatActions({w,message})).filter(node=>node.type==='button');
    assert.equal(buttons.length,2);assert.ok(buttons.every(node=>node.props.disabled),'camera and album share the in-flight guard');
  }
});

test('unlocked portrait and horizontal debug photos preserve native JPEG dimensions and become chat attachments without GPIO tickets',async()=>{
  for(const [width,height] of [[1080,1920],[1920,1080]]) for(const added of [true,false]) {
    const h=hookHarness(),scene=localVideoScene(width,height),calls=[];let finishAdd;
    const {MobileWebCamera}=components('en',h.hooks);
    const w={...workspace(),canCapture:false,rtc:{stream:scene.stream,publishing:false,stats:{},settings:{width:1920,height:1080}},
      addFiles:files=>{calls.push(['files',files]);return new Promise(resolve=>finishAdd=resolve);},
      beginCapture(){throw Error('Generic debug photos must not request GPIO tickets');},finishCapture(){throw Error('Generic debug photos must not claim GPIO localization');}};
    const render=()=>{h.reset();return MobileWebCamera({w,onCaptured(){throw Error('Must not open GPIO photo');},onDebugCaptured:()=>calls.push(['chat'])});};
    let tree=render(),videoNode=treeNodes(tree).find(node=>node.type==='video');videoNode.ref.current=scene.video;videoNode.props.onLoadedData();tree=render();
    const viewfinder=treeNodes(tree).find(node=>node.props.className==='mw-viewfinder');assert.equal(viewfinder.props.style.aspectRatio,width/height);
    const debug=treeNodes(tree).find(node=>String(node.props.className).includes('mw-debug-capture'));
    const gpio=treeNodes(tree).find(node=>String(node.props.className).includes('mw-capture-button'));
    assert.equal(debug.props.disabled,false);assert.equal(gpio.props.disabled,true);gpio.props.onClick();
    debug.props.onClick();debug.props.onClick();await nextTurn();
    assert.equal(calls.length,1);assert.equal(calls[0][0],'files');assert.equal(calls[0][1][0].type,'image/jpeg');
    assert.deepEqual(scene.draws[0],[scene.video,0,0,width,height]);assert.deepEqual(scene.draws[1],{width,height,mime:'image/jpeg',quality:.95});
    assert.equal(scene.track.readyState,'live');assert.equal(scene.canvas.width,0);
    finishAdd(added);await nextTurn();assert.deepEqual(calls.map(call=>call[0]),added?['files','chat']:['files']);
  }
});

test('a pending debug snapshot cannot attach or navigate into a different session, project or camera',async()=>{
  for(const change of [w=>{w.session={...w.session,session_id:'new-phone'};},w=>{w.session={...w.session,context_id:'new-project'};},w=>{w.session={...w.session,conversation_id:'new-chat'};},w=>{w.rtc={...w.rtc,stream:{}};}]) {
    const h=hookHarness(),scene=localVideoScene(),calls=[];let encode;
    scene.canvas.toBlob=callback=>{encode=callback;};
    const {MobileWebCamera}=components('en',h.hooks);
    const w={...workspace(),rtc:{stream:scene.stream,publishing:false,stats:{}},addFiles:async()=>{calls.push('files');return true;}};
    const render=()=>{h.reset();return MobileWebCamera({w,onCaptured(){},onDebugCaptured:()=>calls.push('chat')});};
    let tree=render();const node=treeNodes(tree).find(node=>node.type==='video');node.ref.current=scene.video;node.props.onLoadedData();tree=render();
    treeNodes(tree).find(node=>String(node.props.className).includes('mw-debug-capture')).props.onClick();change(w);render();
    encode(new Blob(['JPEG'],{type:'image/jpeg'}));await nextTurn();assert.deepEqual(calls,[]);
  }
});

test('debug photo waits for successful attachment ownership and paused preview cannot capture',async()=>{
  const h=hookHarness(),scene=localVideoScene(),calls=[];let attach;
  const {MobileWebCamera}=components('en',h.hooks);
  const w={...workspace(),rtc:{stream:scene.stream,stats:{}},addFiles:()=>new Promise(resolve=>attach=resolve)};
  const render=()=>{h.reset();return MobileWebCamera({w,onCaptured(){},onDebugCaptured:()=>calls.push('chat')});};
  let tree=render();const videoNode=treeNodes(tree).find(node=>node.type==='video');videoNode.ref.current=scene.video;videoNode.props.onLoadedData();tree=render();
  scene.video.paused=true;videoNode.props.onPause();tree=render();
  let button=treeNodes(tree).find(node=>String(node.props.className).includes('mw-debug-capture'));assert.equal(button.props.disabled,true);
  button.props.onClick();await nextTurn();assert.equal(scene.draws.length,0);
  scene.video.paused=false;videoNode.props.onPlaying();tree=render();button=treeNodes(tree).find(node=>String(node.props.className).includes('mw-debug-capture'));
  button.props.onClick();await nextTurn();assert.ok(attach);w.session={...w.session,context_id:'changed-during-attachment'};render();
  attach(true);await nextTurn();assert.deepEqual(calls,[]);
});

test('chat camera shortcut reuses the camera tab and debug completion returns to chat without sending',()=>{
  const h=hookHarness(),calls=[];const {MobileWebSurface,ChatView,MobileWebCamera}=components('en',h.hooks);
  const w={...workspace(),send:()=>calls.push('send'),startStream:()=>calls.push('start'),stopStream:()=>calls.push('stop')};
  const render=()=>{h.reset();return MobileWebSurface({workspace:w});};
  let tree=render();treeNodes(tree).find(node=>node.type===ChatView).props.onCamera();tree=render();
  assert.equal(tree.props['data-tab'],'camera');treeNodes(tree).find(node=>node.type===MobileWebCamera).props.onDebugCaptured();tree=render();
  assert.equal(tree.props['data-tab'],'chat');assert.deepEqual(calls,[]);
});

test('locked phone capture is single-flight, keeps streaming, and enters photo only after success',async()=>{
  for(const success of [true,false]) {
    const h=hookHarness(),calls=[],file={name:'local-frame.jpg'},ticket={ticket_id:'ticket'},stream={};let release;
    const {MobileWebCamera}=components('en',h.hooks,{captureBrowserVideoFrame:async(video,source)=>{assert.equal(source,stream);assert.equal(video,'actual-video');return file;}});
    const w={...workspace(),canCapture:true,rtc:{stream,stats:{}},
      beginCapture:options=>{calls.push(['ticket',options]);return new Promise(resolve=>{release=resolve;});},
      finishCapture:async(...args)=>{calls.push(['finish',...args]);return success;},stopStream:()=>calls.push(['stop']),cancelCapture:()=>calls.push(['cancel'])};
    w.session.stream={active:true,state:'locked',video_received_at:Date.now()/1000,video_receive_fresh:true,video_receive_age_ms:0};
    h.reset();const tree=MobileWebCamera({w,onCaptured:()=>calls.push(['photo'])});
    treeNodes(tree).find(node=>node.type==='video').ref.current='actual-video';
    const click=treeNodes(tree).find(node=>node.type==='button' && String(node.props.className).includes('mw-capture-button')).props.onClick;
    click();click();assert.deepEqual(calls,[['ticket',{keepStreaming:true}]]);
    release(ticket);await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(calls,[['ticket',{keepStreaming:true}],['finish',file,ticket,'phone_frame'],...(success?[['photo']]:[])]);
  }
});

test('chat and photo navigation retain the active publisher and show streaming status',()=>{
  const h=hookHarness(),calls=[];const {MobileWebSurface}=components('en',h.hooks);
  const w={...workspace(),capture:capture(),rtc:{stream:{},stats:{},status:'on'},stopStream:()=>calls.push('stop')};
  function render(){h.reset();return MobileWebSurface({workspace:w});}
  let tree=render();
  for(const name of ['Stream','GPIO photo','Chat','Stream']) {
    const nav=treeNodes(tree).find(node=>node.type==='nav'&&node.props['aria-label']==='Mobile workspace');
    treeNodes(nav).find(node=>node.type==='button'&&treeNodes(node).some(child=>child.type==='span'&&child.props.children===name)).props.onClick();
    tree=render();assert.equal(tree.props['data-tab'],name === 'Stream' ? 'camera' : name === 'GPIO photo' ? 'photo' : 'chat');
    assert.match(renderToStaticMarkup(tree),/Camera streaming/);
  }
  assert.deepEqual(calls,[]);
});

test('desktop context changes explain why phone capture needs the current workspace',()=>{
  const {MobileWebCamera}=components(),w={...workspace(),canCapture:true,previewFresh:true};
  w.rtc={...w.rtc,stream:{}};
  w.session={...w.session,available_context:{context_id:'new-step'},stream:{active:true,state:'locked',can_capture:true}};
  const tree=React.createElement(MobileWebCamera,{w,onCaptured(){}}),html=renderToStaticMarkup(tree);
  assert.match(html,/Desktop wiring changed/);
  assert.match(html,/<button[^>]*class="[^"]*mw-capture-button[^"]*"[^>]*disabled=""/);
});

test('framing reasons show specific bilingual guidance only while their preview remains fresh',()=>{
  const reasons=[
    ['find_board','請讓 Raspberry Pi 完整入鏡','Bring the Raspberry Pi into view'],
    ['find_target_component','請讓目標零件入鏡','Bring the target module into view'],
    ['keep_targets_in_frame','請讓板卡與目標零件完整入鏡','Keep the board and target module fully in view'],
    ['move_closer','請稍微靠近','Move a little closer'],
    ['improve_focus_or_light','請調整對焦距離或光線','Adjust focus distance or lighting'],
    ['hold_still','請穩住手機','Hold the phone still'],
  ];
  for(const locale of ['zh-TW','en']) {
    const h=hookHarness(),{MobileWebCamera}=components(locale,h.hooks),w=workspace();
    w.rtc={stream:{},publishing:true,stats:{},status:'Streaming'};w.previewFresh=true;
    const renderFeedback=()=>{
      h.reset();
      const tree=MobileWebCamera({w,onCaptured(){}});
      return treeNodes(tree).find(node=>String(node.props.className).includes('mw-camera-feedback'));
    };
    for(const [reason,zh,en] of reasons) {
      w.session.stream={active:true,state:'finding',reason,video_received_at:Date.now()/1000,video_receive_fresh:true,video_receive_age_ms:0};
      w.previewFresh=true;
      const expected=locale==='en'?en:zh;
      assert.ok(renderToStaticMarkup(renderFeedback()).includes(expected),reason);
      w.previewFresh=false;
      const stale=renderToStaticMarkup(renderFeedback());
      assert.ok(stale.includes(locale==='en'?'Waiting for a fresh position':'等待新的定位'));
      assert.ok(!stale.includes(expected));
    }
    w.previewFresh=true;w.session.stream.reason='find_board';w.session.stream.video_received_at=Date.now()/1000-6;
    assert.ok(renderToStaticMarkup(renderFeedback()).includes(locale==='en'?'Waiting for fresh frames':'等待電腦接收新的影格'));
    w.session.available_context={context_id:'new-project'};
    assert.ok(renderToStaticMarkup(renderFeedback()).includes(locale==='en'?'Desktop wiring changed':'筆電已更新接線步驟'));
  }
});

test('camera resolution defaults to 1080p and offers an explicit 720p selection',()=>{
  const states=[];let cursor=0,requested;
  const {MobileWebCamera}=components('en',{
    useState(initial){const index=cursor++;if(!(index in states))states[index]=typeof initial==='function'?initial():initial;return [states[index],value=>{states[index]=typeof value==='function'?value(states[index]):value;}];},
    useRef:()=>({current:null}),useEffect(){},
  });
  const w={...workspace(),startStream:options=>{requested=options;}};
  const render=()=>{cursor=0;return MobileWebCamera({w,onCaptured(){}});};
  const nodes=element=>!React.isValidElement(element)?[]:[element,...React.Children.toArray(element.props.children).flatMap(nodes)];
  let tree=render();assert.equal(nodes(tree).find(node=>node.type==='select' && node.props.value==='1080p')?.props.value,'1080p');
  const initialHtml=renderToStaticMarkup(tree);
  assert.equal((initialHtml.match(/>Start stream<\/button>/g)??[]).length,1);
  assert.ok(initialHtml.indexOf('>Start stream</button>')<initialHtml.indexOf('class="mw-viewfinder"'));
  assert.equal(nodes(tree).find(node=>node.type==='select' && node.props.value==='1080p').props.disabled,false);
  assert.equal(nodes(tree).some(node=>node.type==='option' && node.props.value==='720p'),true);
  assert.match(initialHtml,/1280 × 720/);
  w.rtc.settings={width:1920,height:1080};w.rtc.stats={bitrateKbps:2200,width:1920,height:1080};
  tree=render();const html=renderToStaticMarkup(tree);
  assert.equal(nodes(tree).find(node=>node.type==='select' && node.props.value==='1080p')?.props.value,'1080p');assert.match(html,/1920 × 1080/);
  assert.match(html,/Smooth \/ Standard \/ High caps are 3 \/ 8 \/ 12 Mbps/);assert.match(html,/Actual send 2.2 Mbps/);
  assert.match(html,/Phone upload/);
  nodes(tree).find(node=>node.type==='button' && node.props.children==='Start stream').props.onClick();
  assert.deepEqual(requested,{resolution:'1080p',bitrateKbps:12000});
  requested=undefined;
  nodes(tree).find(node=>node.type==='select' && node.props.value==='1080p').props.onChange({target:{value:'720p'}});
  assert.equal(requested,undefined,'Selecting a resolution must not start or interrupt the camera');
  tree=render();nodes(tree).find(node=>node.type==='button' && node.props.children==='Start stream').props.onClick();
  assert.deepEqual(requested,{resolution:'720p',bitrateKbps:12000});
});

test('720p warning follows the running target, not the pending selection, and apply is explicit',()=>{
  const h=hookHarness(),{MobileWebCamera}=components('en',h.hooks),calls=[];
  const w={...workspace(),startStream:options=>calls.push(options),rtc:{stream:{},publishing:true,resolution:'720p',
    stats:{width:1280,height:720},frame:{sourceSize:[1280,720],outputSize:[1280,720],ready:true}}};
  const render=()=>{h.reset();return MobileWebCamera({w,onCaptured(){}});};
  let tree=render();assert.doesNotMatch(renderToStaticMarkup(tree),/Actual video is below/);
  treeNodes(tree).find(node=>node.type==='select'&&node.props.value==='720p').props.onChange({target:{value:'1080p'}});
  tree=render();assert.equal(calls.length,0);assert.doesNotMatch(renderToStaticMarkup(tree),/Actual video is below/);
  treeNodes(tree).find(node=>node.type==='button'&&node.props.children==='Apply & restart stream').props.onClick();
  assert.deepEqual(calls,[{resolution:'1080p',bitrateKbps:12000}]);
  w.rtc.stats={width:960,height:540};assert.match(renderToStaticMarkup(render()),/Actual video is below 720p/);
  w.captureTicket={};assert.equal(treeNodes(render()).find(node=>node.type==='select'&&node.props.value==='1080p').props.disabled,true);
});

test('phone camera warns about actual sub-1080 upload and unresolved orientation without hiding video',()=>{
  const {MobileWebCamera}=components('en'),w=workspace();
  w.rtc={stream:{},publishing:true,stats:{width:1280,height:720},frame:{sourceSize:[1920,1080],outputSize:[1920,1080],ready:true}};
  let html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.match(html,/Actual video is below 1080p/);assert.match(html,/<video/);
  w.rtc.frame={...w.rtc.frame,ready:false,issue:'orientation'};
  html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.match(html,/Synchronizing camera orientation/);assert.match(html,/<video/);
  w.rtc.stats={width:1920,height:1080};w.rtc.frame={...w.rtc.frame,ready:true,issue:undefined};
  html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.doesNotMatch(html,/Actual video is below 1080p|Synchronizing camera orientation/);
});

test('photo metadata uses the original source dimensions without changing analysis geometry',()=>{
  const {MobileWebPhoto}=components(),value=capture();
  value.original_size=[3024,4032];value.analysis_limited=true;
  value.quality={original_width:100,original_height:200,analysis_limited:false};
  const w={...workspace(),capture:value,captureImageUrl:'blob:authorized-photo',imageError:''};
  const html=renderToStaticMarkup(React.createElement(MobileWebPhoto,{w,onAsk(){},onCheck(){}}));
  assert.match(html,/Original photo 3024 × 4032/);assert.match(html,/proportional analysis image/);assert.match(html,/1080 × 1920/);
  assert.doesNotMatch(html,/Original photo 100 × 200/);
  assert.deepEqual(view.mobilePhotoSource({...value,analysis_limited:false,quality:{analysis_limited:true}}),{originalSize:[3024,4032],analysisLimited:false});
  assert.deepEqual(view.mobilePhotoSource({...capture(),quality:{original_width:4032,original_height:3024,analysis_limited:true}}),{originalSize:[4032,3024],analysisLimited:true});
  assert.equal(view.mobilePhotoSource(capture()).originalSize,null);
});

test('phone camera labels genuine landscape input and output without claiming rotation or measured FPS',()=>{
  const {MobileWebCamera}=components(),w=workspace();
  w.rtc={stream:{},publishing:true,settings:{width:1920,height:1080},status:'Streaming',stats:{},frame:{sourceSize:[1920,1080],outputSize:[1920,1080],rotation:0}};
  const html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.match(html,/Camera input 1920 × 1080 → Streaming size 1920 × 1080/);
  assert.doesNotMatch(html,/Rotated 90/);
  assert.match(html,/Portrait and horizontal photos keep the full frame without stretching or cropping/);
  assert.equal((html.match(/—<small> FPS<\/small>/g)??[]).length,4,'30 FPS target is not measured performance');
});

test('portrait preview keeps its own pixel ratio, has no rotation restriction, and stale server rates remain hidden',()=>{
  const {MobileWebCamera}=components(),w=workspace();
  w.canCapture=true;w.session.stream={active:true,state:'locked',video_fps:30,recognition_fps:9,video_size:[1920,1080]};
  w.rtc={stream:{},settings:{width:1080,height:1920},status:'waiting',stats:{},publishing:false,waitingForLandscape:true,
    frame:{sourceSize:[1080,1920],outputSize:[1920,1080],rotation:0,ready:false,phoneOrientation:'portrait'}};
  const html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.match(html,/aspect-ratio:0.5625/);assert.match(html,/1080 × 1920/);
  assert.doesNotMatch(html,/Hold your phone sideways|Waiting for landscape|rotation lock/);
  assert.match(html,/<button[^>]*class="mw-button mw-secondary mw-capture-button"[^>]*disabled=""/);assert.doesNotMatch(html,/Ready to capture|>30.0<|>9.0</);
});

test('phone receive and recognition rates expire without hiding independently current local upload rates',()=>{
  const {MobileWebCamera}=components(),w=workspace();
  w.canCapture=true;w.previewFresh=true;
  w.session.stream={active:true,state:'locked',video_fps:26,recognition_fps:9,video_receive_fresh:true,video_received_at:Date.now()/1000-6,video_receive_age_ms:6000};
  w.rtc={stream:{},publishing:true,settings:{width:1920,height:1080},stats:{sendFps:29.1,captureFps:29.9},status:'Streaming'};
  const html=renderToStaticMarkup(React.createElement(MobileWebCamera,{w,onCaptured(){}}));
  assert.doesNotMatch(html,/>26.0<|>9.0<|Ready to capture/);assert.match(html,/29.1/);assert.match(html,/29.9/);
  assert.match(html,/disabled=""/);assert.match(html,/Waiting/);
});

test('Safari standalone entry offers pairing and the correct HTTPS link without desktop UI',()=>{
  const {MobileWebSurface}=components();const w={...workspace(),pairing:null,secureContext:false};
  const html=renderToStaticMarkup(React.createElement(MobileWebSurface,{workspace:w,httpsUrl:'https://workbench.local:8443/mobile'}));
  assert.match(html,/Six-digit code from your desktop/);assert.match(html,/https:\/\/workbench.local:8443\/mobile/);assert.match(html,/Open the camera from HTTPS/);
  assert.doesNotMatch(html,/unified-assistant|webcam|PiDeployPanel|canvas/);
});

test('phone reference has an accessible cancel action without submitting or deleting the draft',()=>{
  for(const locale of ['en','zh-TW']) {
    const h=hookHarness(),{ChatView}=components(locale,h.hooks),w=workspace(),calls=[];
    w.inheritedMediaLabel='Reference: latest-photo.jpg';
    w.removeMediaReference=()=>{calls.push('remove');w.inheritedMediaLabel=null;};
    w.send=async()=>calls.push('send');
    h.reset();const before=ChatView({w,onPhoto(){}}),label=locale==='en'?'Remove reference':'取消引用';
    const cancel=treeNodes(before).find(node=>node.type==='button'&&node.props['aria-label']===label);
    assert.ok(cancel);assert.equal(cancel.props.type,'button');assert.equal(cancel.props.disabled,false);
    cancel.props.onClick();h.reset();const after=ChatView({w,onPhoto(){}});
    assert.deepEqual(calls,['remove']);assert.equal(w.draft,'Preserve this draft');
    assert.equal(treeNodes(after).some(node=>node.props.className==='mw-reference is-removable'),false);
  }
});

test('shared phone chat shows current draft, inherited reference and durable upload retry',()=>{
  for(const locale of ['en','zh-TW']) {
    const {MobileWebSurface}=components(locale),w=workspace();w.inheritedMediaLabel='Reference: latest-photo.jpg';
    w.outbox=[{id:'send-1',payload:{text:'My queued question'},attachments:[{id:'a',name:'photo.jpg',progress:.5}],status:'failed',error:'Network interrupted'}];
    const html=renderToStaticMarkup(React.createElement(MobileWebSurface,{workspace:w}));
    assert.match(html,/Preserve this draft/);assert.match(html,/latest-photo.jpg/);assert.match(html,/My queued question/);assert.match(html,/50%/);
    assert.match(html,locale==='en'?/Retry/:/重試/);assert.match(html,locale==='en'?/Chat/:/對話/);
  }
});

test('phone chat keeps earlier-round 安安 visible and only reveals cleared context on request',()=>{
  for(const locale of ['en','zh-TW']) {
    const states=[];let cursor=0;
    const {ChatView}=components(locale,{
      useState(initial){const index=cursor++;if(!(index in states))states[index]=typeof initial==='function'?initial():initial;return [states[index],value=>{states[index]=typeof value==='function'?value(states[index]):value;}];},
      useRef:()=>({current:null}),useEffect(){},
    });
    const w=workspace();w.conversation.messages=[
      {id:'old',epoch:0,round:1,role:'user',text:'Already cleared question',archived:true},
      {id:'mobile',epoch:1,round:2,role:'user',source:'mobile',stage:'guide',capability:'auto',text:'安安'},
      {id:'current',epoch:1,round:3,role:'assistant',text:'Current round reply'},
    ];
    const render=()=>{cursor=0;return ChatView({w,onPhoto(){}});};
    const nodes=element=>!React.isValidElement(element)?[]:[element,...React.Children.toArray(element.props.children).flatMap(nodes)];
    let tree=render(),html=renderToStaticMarkup(tree);
    assert.match(html,/安安/);assert.match(html,/Current round reply/);assert.match(html,locale==='en'?/Earlier round/:/先前輪次/);
    assert.match(html,/<article[^>]*class="mw-message is-user is-archived"><header>[\s\S]*?<p>安安<\/p>/);
    assert.doesNotMatch(html,/Already cleared question/);assert.match(html,locale==='en'?/View cleared history/:/查看已清除紀錄/);
    const toggle=()=>nodes(tree).find(node=>node.type==='button' && 'aria-expanded' in node.props).props.onClick();
    toggle();tree=render();html=renderToStaticMarkup(tree);
    assert.match(html,/Already cleared question/);assert.match(html,/安安/);
    assert.match(html,locale==='en'?/Earlier conversation context/:/先前聊天上下文/);assert.match(html,locale==='en'?/Hide cleared history/:/隱藏已清除紀錄/);
    toggle();tree=render();assert.doesNotMatch(renderToStaticMarkup(tree),/Already cleared question/);
    toggle();tree=render();w.conversation.context_epoch=2;tree=render();html=renderToStaticMarkup(tree);
    assert.doesNotMatch(html,/Already cleared question|安安|Current round reply/);assert.match(html,locale==='en'?/View cleared history/:/查看已清除紀錄/);
  }
});

test('design-stage part camera and albums use shared attachments without sending or requiring GPIO lock',async()=>{
  const h=hookHarness(),calls=[],{ChatView}=components('en',h.hooks);
  const w={session:{context:{stage:'design',ui:{parts_check:true}}},conversation:null,attachments:[],outbox:[],draft:'existing draft',busy:false,chatSendBlocked:false,
    addFiles:async (files,purpose)=>calls.push(['files',files,purpose]),send:()=>calls.push(['send'])};
  h.reset();let tree=ChatView({w,onPhoto(){}});
  const fileInputs=treeNodes(tree).filter(n=>n.type==='input'&&n.props.type==='file');
  const camera=fileInputs.find(n=>n.props['aria-label']==='Photograph part labels');assert.equal(camera.props.capture,'environment');
  const album=fileInputs.find(n=>n.props['aria-label']==='Select part photographs');assert.equal(album.props.multiple,true);
  for(const input of [camera,album]){const event={target:{files:[{name:'parts.jpg'}],value:'selected'}};input.props.onChange(event);await Promise.resolve();assert.equal(event.target.value,'');}
  assert.equal(calls.length,2);assert.ok(calls.every(call=>call[0]==='files'));assert.equal(w.draft,'existing draft');
  assert.ok(calls.every(call=>call[2]==='parts_check'),'part camera and albums preserve the comparison purpose');
  h.reset();tree=ChatView({w:{...w,attachments:[{id:'part',name:'part.jpg',purpose:'parts_check',type:'image',size:100}]},onPhoto(){}});
  const send=treeNodes(tree).find(n=>n.props.className==='mw-send');
  assert.equal(send.props['aria-label'],'Send hardware comparison');
  assert.match(renderToStaticMarkup(tree),/hardware comparison, not project redesign/);
  h.reset();tree=ChatView({w:{...w,session:{context:{stage:'guide'}}},onPhoto(){}});
  assert.equal(treeNodes(tree).filter(n=>n.props.className==='mw-hardware-upload').length,0);
});

test('mobile hardware entry is hidden on startup and normal design chat until the desktop explicitly requests it',()=>{
  const h=hookHarness(),{ChatView}=components('en',h.hooks);
  for(const context of [{stage:'design'},{stage:'design',ui:{parts_check:false}},{stage:'guide',ui:{parts_check:true}},{stage:'deploy',ui:{parts_check:true}}]) {
    const w={session:{context},conversation:null,attachments:[],outbox:[],draft:'kept draft',busy:false,chatSendBlocked:false};
    h.reset();const tree=ChatView({w,onCamera(){}});
    assert.equal(treeNodes(tree).filter(n=>n.props.className==='mw-hardware-upload').length,0);
    const html=renderToStaticMarkup(tree);
    assert.doesNotMatch(html,/Photograph parts|Select part photos/);
    assert.match(html,/Add media|Photo for AI/);
    assert.equal(w.draft,'kept draft');
  }
});

test('photo UI keeps unverified image geometry hidden before natural dimensions arrive',()=>{
  const {MobileWebPhoto}=components();const w={...workspace(),capture:capture(),captureImageUrl:'blob:authorized-photo',imageError:''};
  const html=renderToStaticMarkup(React.createElement(MobileWebPhoto,{w,onAsk(){},onCheck(){}}));
  assert.match(html,/blob:authorized-photo/);assert.match(html,/1080 × 1920/);assert.match(html,/GPIO17/);
  assert.doesNotMatch(html,/mw-photo-overlay/);assert.match(html,/<button[^>]*disabled=""[^>]*>Ask about this photo/);
  const old=renderToStaticMarkup(React.createElement(MobileWebPhoto,{w:{...w,session:{...w.session,context_id:'new-context'}},onAsk(){},onCheck(){}}));
  assert.match(old,/earlier project version/);assert.match(old,/<button[^>]*disabled=""[^>]*>Check all wires/);
});
