// Loopback-only closed mock: shared persisted chat receipts, synthetic photos.
// This fixture implements no model, camera, production fallthrough or Pi route.
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {build} from 'esbuild';

export async function startPreview(port=18810) {
  const bundle=await build({entryPoints:[fileURLToPath(new URL('wiring-chat-preview.tsx',import.meta.url))],bundle:true,
    write:false,outdir:'preview',jsx:'automatic',external:['/brand/*']});
  const js=bundle.outputFiles.find(f=>f.path.endsWith('.js')).contents,css=bundle.outputFiles.find(f=>f.path.endsWith('.css')).contents;
  const roles=['pi_side_a','pi_side_b','component_header'],labels=['Pi 第一側','Pi 另一側','HC-SR04 接頭'];
  let requests=[],events=[],publishedContext=null,debugRecord=null,debugConversation=null,serial=0,failNext='',delayNext=0,dropAckNext=false;
  const assets=new Map(),pictures=new Map(),receipts=new Map(),imports=new Map();
  const chat={id:'wiring-chat-conversation',kind:'project',project_id:'wiring-chat-project',locale:'zh-TW',
    messages:[],jobs:[],before:null,total:0,context_epoch:0,round:2,demo:null,wiring_analysis:null};
  const key=(...args)=>createHash('sha256').update(JSON.stringify(args)).digest('hex');
  const fakePicture=role=>`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#d6e6e4"/><rect x="100" y="230" width="600" height="230" rx="12" fill="#347254"/><rect x="180" y="250" width="440" height="50" fill="#202b32"/>${['#e8b434','#e95148','#407ad3','#875baf','#328971'].map((c,i)=>`<path d="M${220+i*65} 272V110" stroke="${c}" stroke-width="20"/>`).join('')}<text x="400" y="530" text-anchor="middle" font-size="24">SYNTHETIC QA: ${role}</text></svg>`;
  function readChat(mobile=false) {
    const copy=structuredClone(chat);
    if(mobile)for(const m of copy.messages)if(m.wiring_flow?.capture_id&&m.wiring_flow.kind==='photo')m.wiring_flow.image_url=`/api/mobile/wiring-review/evidence/${m.wiring_flow.capture_id}`;
    return copy;
  }
  function reviewFor(mobile=false) {
    const copy=structuredClone(debugRecord?.wiring_review??null);
    if(mobile&&copy)for(const slot of Object.values(copy.slots))if(slot)slot.image_url=`/api/mobile/wiring-review/evidence/${slot.capture_id}`;
    return copy;
  }
  const snapshot=(mobile=false)=>({review:reviewFor(mobile),component_label:'HC-SR04+',can_act:Boolean(debugRecord?.wiring_review&&debugRecord.wiring_review.status!=='stale'),conversation:readChat(mobile)});
  const result=()=>({conversation:readChat(),debug_session_id:debugRecord.id,debug_session:structuredClone(debugRecord)});
  const phoneSession=()=>({session_id:'wiring-chat-phone',conversation_id:chat.id,context_id:'wiring-chat-context',title:'聊天接線核對',
    context:publishedContext??{round:2,stage:'guide',design:{current:{id:chat.project_id,revision:2,component_ids:['hc-sr04']}},context:{debug_context:{guide_run:2,test_keys:{'hc-sr04':'fixture-key'}}}},
    available_context:{context_id:'wiring-chat-context'},stream:{active:false,generation:0,state:'finding',can_capture:false},view:{capture_id:null,wire_id:null,revision:serial}});
  function reset() {requests=[];events=[];serial=0;debugRecord=null;debugConversation=null;chat.messages=[];chat.total=0;chat.context_epoch=0;
    chat.wiring_analysis=null;failNext='';delayNext=0;dropAckNext=false;assets.clear();pictures.clear();receipts.clear();imports.clear();}
  function createDebug(context) {
    const dc=context??publishedContext?.context?.debug_context??{};
    debugConversation={id:'wiring-chat-debug-conversation',project_id:chat.project_id,archived:false,check_ids:['wiring-chat-debug'],messages:[],evidence:[],diagrams:[]};
    debugRecord={id:'wiring-chat-debug',conversation_id:debugConversation.id,status:'awaiting_capture',phase:'wiring_review',purpose:'wiring_review',
      symptom:'Synthetic no_echo test',instruction:'請拍攝接線照片。',context:dc,camera:{source:'device',runtime_revision:1},camera_current:true,
      current_target:true,conversation_current:true,wiring_target:dc.wiring_target??null,binding:{project_id:chat.project_id,code_hash:'synthetic-code-hash',test_keys:dc.test_keys??{}},
      model_busy:false,jobs:[],test_results:[],observations:[],evidence:[],messages:[],capture_task:null,created_at:100,updated_at:100,
      budget:{model_calls:0,max_model_calls:6,tests:{},max_tests_per_component:2,captures:0,max_captures:20},wiring_review:null,response_mode:'fast'};
  }
  function newReview(previous=null) {
    return{id:previous?.id??'wiring-chat-review',revision:(previous?.revision??0)+1,round:(previous?.round??0)+1,component_id:'hc-sr04',status:'collecting',photo_flow_version:2,
      slots:Object.fromEntries(roles.map(r=>[r,null])),observations:[],results:[],reviews:{},missing_roles:[...roles],no_progress_count:0};
  }
  function retire() {for(const m of chat.messages)if(m.wiring_flow){m.wiring_flow.current=false;m.wiring_flow.can_act=false;m.wiring_flow.actions=[];}}
  function append(role,text,flow=null) {
    const message={id:`wiring-message-${++serial}`,role,text,source:'legacy-debug',created_at:Date.now()/1000,stage:'guide',capability:'debug',
      epoch:chat.context_epoch,round:chat.round,session_id:debugRecord?.id,...(flow?{wiring_flow:flow}:{})};
    chat.messages.push(message);chat.total=chat.messages.length;return message;
  }
  function metadata(kind,extra={}) {const r=debugRecord.wiring_review;return{flow_id:'wiring-chat-flow',review_id:r.id,revision:r.revision,round:r.round,
    component_id:r.component_id,kind,current:true,can_act:true,actions:[],...extra};}
  function nextQuestion() {
    retire();const r=debugRecord.wiring_review,role=roles.find(role=>!r.slots[role]);
    if(role)return append('assistant',`${labels[roles.indexOf(role)]}：請拍清楚排針、插接底部及線色${role==='component_header'?'，保留 pin 文字':''}。`,metadata('photo_request',{role,actions:['capture']}));
    if(!r.results.length)return append('assistant','三張照片已保存，尚未確認接線。準備好後按「開始核對」。',metadata('analysis_request',{actions:['analyse','capture','crop']}));
    const priority={ambiguous:0,different:1,unknown:2,similar:3};
    const row=[...r.results].sort((a,b)=>(priority[a.comparison]??2)-(priority[b.comparison]??2)).find(row=>!r.reviews[row.wire_id]||r.reviews[row.wire_id].evidence_stale);
    if(row){
      const first=Object.values(r.reviews).every(item=>item.evidence_stale),ambiguous=r.results.filter(row=>row.comparison==='ambiguous').length;
      const unknownPins=r.results.filter(row=>!row.pi_candidates.length||row.pi_candidates.some(p=>p.physical_pin===null)).length;
      const summary=first?`照片重點：${ambiguous} 條有多個候選；${unknownPins} 條的 Pi 腳號仍待確認。請優先沿線核對。\n`:'';
      return append('assistant',`${summary}先核對 ${row.expected.component_pin} 這條線。照片線色相符仍不能證明是同一條線，請沿線親自確認。`,metadata('wire_review',{wire_id:row.wire_id,result:row,actions:['review','capture','crop','changed']}));
    }
    append('assistant','這些線路已有你的人工核對紀錄。照片無法驗證電氣連通；確認完畢後可回原功能測試。',metadata('complete',{actions:['changed']}));
  }
  function capture(role,asset_id=null) {
    const r=debugRecord.wiring_review;r.revision++;const capture_id=`synthetic-${role}-${serial+1}`,picture=fakePicture(role),asset=assets.get(asset_id);
    const sha256=asset?.sha256??key(picture,capture_id);pictures.set(capture_id,picture);
    r.slots[role]={role,capture_id,image_url:`/api/debug/sessions/wiring-chat-debug/evidence/${capture_id}`,sha256,size:[800,600],crop:null,crop_source:'none',available:true,
      ...(asset_id?{provenance:{asset_id}}:{}),photo_acceptance:{capture_id,sha256,round:r.round,accepted_at:Date.now()/1000,source:'human'}};
    r.missing_roles=roles.filter(role=>!r.slots[role]);r.status='collecting';r.results=[];r.reviews={};
    retire();append('user',`${labels[roles.indexOf(role)]}照片。`,metadata('photo',{role,capture_id,image_url:r.slots[role].image_url,current:false,can_act:false}));
    nextQuestion();events.push({op:'synthetic-capture',role,capture_id,asset_id,revision:r.revision});
  }
  function syntheticAnalysis() {
    const r=debugRecord.wiring_review;r.revision++;r.status='ready';
    const wiring=debugRecord.context?.project?.wiring??publishedContext?.design?.current?.wiring??[];
    const expected=wire=>{
      // Reuse the project preset rather than assigning a synthetic pin by row index.
      const physical=String(wire.boardPin??'').match(/_P(\d+)$/i)??String(wire.boardLabel??'').match(/\bPin\s+(\d+)\b/i);
      const bcm=String(wire.boardPin??'').match(/^GPIO(\d+)(?:_|$)/i)??String(wire.boardLabel??'').match(/\bBCM\s*(\d+)\b/i);
      return{physical_pin:physical?Number(physical[1]):null,bcm:bcm?Number(bcm[1]):null,board_pin:wire.boardPin??'',
        component_pin:wire.componentPin??'腳位待確認',connection_kind:wire.connectionKind};
    };
    r.results=wiring.filter(w=>w.componentId==='hc-sr04'&&w.connectionKind!=='not-connected').map((w,i)=>({wire_id:w.id,component_id:'hc-sr04',
      expected:expected(w),
      pi_candidates:[{id:`A${i+1}`,capture_id:r.slots.pi_side_a.capture_id,physical_pin:null,pin_label:null,color:['yellow','red','blue','yellow'][i]??'blue',evidence:'Synthetic connector observation; pin identity unconfirmed.'}],
      component_candidates:[{id:`C${i+1}`,capture_id:r.slots.component_header.capture_id,physical_pin:null,pin_label:w.componentPin??'Echo',color:['yellow','red','blue','yellow'][i]??'blue',evidence:'Synthetic pin-label observation.'}],
      comparison:i===0?'ambiguous':'similar',next_step:'請沿同一條線親自核對兩端；此處僅為合成 UI 證據。',authority:'visual_advisory'}));
    if(!r.results.length)r.results=[{wire_id:'synthetic-wire-unavailable',expected:{physical_pin:null,bcm:null,component_pin:'腳位待確認'},pi_candidates:[],component_candidates:[],comparison:'unknown',next_step:'接線表尚無可用線路，請先核對作品。'}];
    nextQuestion();events.push({op:'synthetic-analysis',real_model_calls:0});
  }
  function applyFlow(body) {
    const m=chat.messages.find(m=>m.id===body.message_id),f=m?.wiring_flow,a=body.action,r=debugRecord?.wiring_review;
    if(!m||m.epoch!==chat.context_epoch||!f?.current||!f.can_act||f.flow_id!==body.flow_id||!r||r.id!==f.review_id||r.revision!==f.revision||r.round!==f.round
      ||a.review_id!==r.id||a.revision!==r.revision||!f.actions.includes(a.op))return{detail:'wiring_photo_flow_stale'};
    if(body.context) {
      const current=debugRecord.context?.project??publishedContext?.design?.current;
      if(body.context.project?.id!==chat.project_id||body.context.project?.revision!==2||body.context.guide_run!==2
        ||current&&key(body.context.project.wiring)!==key(current.wiring))return{detail:'stale_debug_context'};
      if(a.op==='review'&&a.decision==='confirmed'&&!body.context.guide_confirmations?.[a.wire_id]?.signature)return{detail:'wiring_confirmation_required'};
      if(a.op==='review'&&a.decision!=='confirmed'&&body.context.guide_confirmations?.[a.wire_id])return{detail:'wiring_confirmation_changed'};
      debugRecord.context=body.context;
    }
    if(a.op==='capture') {if(!roles.includes(a.role)||f.kind==='photo_request'&&a.role!==f.role)return{detail:'photo_role_changed'};capture(a.role,body.asset_id);}
    else if(a.op==='analyse'){if(roles.some(role=>!r.slots[role]))return{detail:'wiring_photos_missing'};syntheticAnalysis();}
    else if(a.op==='crop'){
      const slot=r.slots[a.role];if(!slot||slot.capture_id!==a.capture_id)return{detail:'wiring_capture_changed'};
      slot.crop=a.crop;slot.crop_source=a.crop?'manual':'none';r.revision++;r.status='collecting';r.results=[];r.observations=[];r.analysis_revision=null;
      r.reviews=Object.fromEntries(Object.entries(r.reviews).map(([id,decision])=>[id,{...decision,evidence_stale:true}]));
      nextQuestion();events.push({op:'synthetic-crop-invalidated-analysis',revision:r.revision});
    }
    else if(a.op==='review') {if(f.wire_id!==a.wire_id||!['confirmed','unsure','needs_change'].includes(a.decision))return{detail:'wiring_wire_changed'};
      r.reviews[a.wire_id]={decision:a.decision,source:'human',at:Date.now()/1000,review_revision:r.revision,evidence_stale:false};r.revision++;
      retire();append('user',a.decision==='confirmed'?'我已親自確認接對。':a.decision==='needs_change'?'我發現接錯，準備修正。':'仍無法確定。',metadata('human_decision',{wire_id:a.wire_id,decision:a.decision,current:false,can_act:false}));nextQuestion();}
    else if(a.op==='changed'){retire();append('user','我已改線，重新拍照。',metadata('human_decision',{current:false,can_act:false}));debugRecord.wiring_review=newReview(r);nextQuestion();}
    else return{detail:'fixture_action_not_allowed'};
    return null;
  }
  function offerAction(message_id,offer_id,op,mobile=false) {
    const m=chat.messages.find(m=>m.id===message_id),offer=m?.test_help_offer;
    if(!offer||offer.offer_id!==offer_id||!['pending','started'].includes(offer.state))return{detail:'test_help_stale'};
    if(op==='later'){offer.state='dismissed';offer.can_act=false;offer.can_dismiss=false;return{offer,conversation:readChat(mobile),...snapshot(mobile)};}
    if(op!=='start')return{detail:'fixture_action_not_allowed'};
    if(!debugRecord)createDebug(publishedContext?.context?.debug_context);
    if(!debugRecord.wiring_review){debugRecord.wiring_review=newReview();nextQuestion();}
    else if(!chat.messages.some(m=>m.wiring_flow?.current))nextQuestion();
    offer.state='started';offer.reusable_review=true;offer.review_id=debugRecord.wiring_review.id;
    events.push({op:'offer-start',review_id:offer.review_id});return{offer,...snapshot(mobile),...(!mobile?result():{})};
  }
  const server=createServer(async(req,res)=>{
    const url=new URL(req.url,'http://127.0.0.1'),path=url.pathname,chunks=[];for await(const chunk of req)chunks.push(chunk);
    const raw=Buffer.concat(chunks);let body={};try{if(req.headers['content-type']?.includes('application/json'))body=JSON.parse(raw.toString()||'{}');}catch{return res.writeHead(400).end();}
    const bearer=req.headers.authorization==='Bearer synthetic-wiring-chat-token';requests.push({path,method:req.method,body,bearer});
    const send=(value,status=200,type='application/json')=>{res.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store'});res.end(type==='application/json'?JSON.stringify(value):value);};
    if(path==='/'||path==='/phone')return send('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>True chat wiring — isolated QA</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>',200,'text/html');
    if(path==='/preview.js')return send(js,200,'text/javascript');if(path==='/preview.css')return send(css,200,'text/css');
    if(path.startsWith('/brand/'))return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="0" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>',200,'image/svg+xml');
    if(path==='/__fixture/requests')return send(requests);
    if(path==='/__fixture/state')return send({chat:readChat(),review:reviewFor(),debugRecord,publishedContext,events,real_model_calls:0,real_hardware_calls:0});
    if(path==='/__fixture/reset'){reset();return send({ok:true});}
    // Explicit QA controls: show a pending analysis without any model or camera.
    if(path==='/__fixture/analysis-start'){
      if(!debugRecord)createDebug(publishedContext?.context?.debug_context);
      if(!debugRecord.wiring_review)debugRecord.wiring_review=newReview();
      const r=debugRecord.wiring_review,started_at=Date.now()/1000;
      r.status='analysing';debugRecord.model_busy=true;retire();
      chat.wiring_analysis={flow_id:'wiring-chat-flow',session_id:debugRecord.id,review_id:r.id,round:r.round,revision:r.revision,started_at};
      append('assistant','正在分析照片中的腳位與線色。這是隔離測試，沒有呼叫模型。',metadata('analysing',{started_at,can_act:false}));
      return send(snapshot());
    }
    if(path==='/__fixture/analysis-finish'){
      const elapsed_ms=Math.max(0,(Date.now()/1000-(chat.wiring_analysis?.started_at??Date.now()/1000))*1000);
      for(const m of chat.messages)if(m.wiring_flow?.kind==='analysing')m.wiring_flow.elapsed_ms=elapsed_ms;
      chat.wiring_analysis=null;retire();if(debugRecord){debugRecord.model_busy=false;debugRecord.wiring_review.status='ready';
        append('assistant','合成分析已完成，可以繼續提問。',metadata('complete',{elapsed_ms,can_act:false}));}
      return send(snapshot());
    }
    if(path==='/__fixture/fail-next'){failNext=body.detail??'camera_frame_unavailable';return send({ok:true});}
    if(path==='/__fixture/delay-next'){delayNext=body.ms??1500;return send({ok:true});}
    if(path==='/__fixture/drop-ack'){dropAckNext=true;return send({ok:true});}
    if(path==='/__fixture/new-round'){if(!debugRecord?.wiring_review)return send({detail:'No review'},409);debugRecord.wiring_review=newReview(debugRecord.wiring_review);nextQuestion();return send(snapshot());}
    if(path==='/__fixture/stale'){retire();if(debugRecord?.wiring_review)debugRecord.wiring_review.status='stale';return send(snapshot());}
    if(path==='/__fixture/broken-photo'){for(const id of pictures.keys())pictures.delete(id);return send({ok:true});}
    if(path==='/api/mobile/context'){publishedContext=body;return send({context_id:'wiring-chat-context'});}
    if(path==='/api/mobile/desktop-session')return send({session:null});
    if(path.startsWith('/api/mobile/')&&!bearer)return send({detail:'mobile_session_expired_or_invalid'},401);
    if(path==='/api/mobile/session')return send(phoneSession());
    if(path==='/api/mobile/conversation')return send(readChat(true));
    if(path==='/api/mobile/stream'&&req.method==='DELETE')return send(phoneSession());
    if(path==='/api/mobile/assets'&&req.method==='POST'){const id=`synthetic-asset-${assets.size+1}`,asset={id,type:'image',mime:'image/svg+xml',filename:'synthetic-photo.svg',
      width:800,height:600,duration:null,size:raw.length,sha256:key(raw.toString('base64')),url:`/api/mobile/assets/${id}/file`,thumbnail_url:null};assets.set(id,asset);return send(asset);}
    if(path.startsWith('/api/mobile/assets/'))return send(fakePicture('uploaded-phone-photo'),200,'image/svg+xml');
    const image=path.match(/^\/api\/(?:debug\/sessions\/wiring-chat-debug\/evidence|mobile\/wiring-review\/evidence)\/([^/]+)$/);
    if(image)return pictures.has(image[1])?send(pictures.get(image[1]),200,'image/svg+xml'):send({detail:'synthetic_evidence_unavailable'},404);
    if(path==='/api/assistant/conversations'||path===`/api/assistant/conversations/${chat.id}`)return send(readChat());
    if(path===`/api/assistant/conversations/${chat.id}/import`){
      if(!imports.has(body.source_id)){imports.set(body.source_id,true);for(const imported of body.messages??[]){
        const m=append(imported.role,imported.text);m.import_key=createHash('sha256').update('['+[body.source_id,imported.id,imported.role,imported.text].map(v=>JSON.stringify(v)).join(', ')+']').digest('hex');
        if(body.test_help){const t=body.test_help;m.test_help_offer={offer_id:t.offer_id,message_id:m.id,state:'pending',can_act:true,can_dismiss:true,component_id:t.component_id,
          reusable_review:Boolean(debugRecord?.wiring_review),project_id:t.project_id,project_revision:t.project_revision,
          guide_key:t.guide_key,guide_run:t.guide_run,context_epoch:t.context_epoch,test_id:t.test_id,reason:t.reason,mode:'wiring'};}
      }}return send(readChat());}
    if(path===`/api/assistant/conversations/${chat.id}/test-help`||path==='/api/mobile/wiring-review'&&body.invitation){
      const a=body.invitation??body;if(body.invitation&&a.context_id!=='wiring-chat-context')return send({detail:'context_changed'},409);
      const answer=offerAction(a.message_id,a.offer_id,a.op,Boolean(body.invitation));return send(answer,answer.detail?409:200);}
    if(path==='/api/mobile/wiring-review'&&req.method==='GET')return send(snapshot(true));
    const savedReceipt=path.match(/^\/api\/assistant\/conversations\/wiring-chat-conversation\/wiring-flow\/receipts\/([^/]+)$/);
    if(savedReceipt){
      const answer=receipts.get(savedReceipt[1]);events.push({op:'receipt-get',request_id:savedReceipt[1],receipt_state:answer?'done':'missing'});
      return send(answer?{...structuredClone(answer),receipt_state:'done',conversation:readChat()}:{request_id:savedReceipt[1],receipt_state:'missing',guide_receipt:null,conversation:readChat()});
    }
    if(path===`/api/assistant/conversations/${chat.id}/wiring-flow`||path==='/api/mobile/wiring-review'&&body.dialogue){
      const mobile=Boolean(body.dialogue),payload=mobile?{...body,...body.dialogue}:body;
      const receipt=receipts.get(payload.request_id);if(receipt)return send(receipt);
      const wait=delayNext;delayNext=0;if(wait)await new Promise(done=>setTimeout(done,wait));
      if(failNext){const detail=failNext;failNext='';return send({detail},409);}
      const before_binding=structuredClone(debugRecord?.binding??{});
      const failure=applyFlow(payload);if(failure)return send(failure,409);
      const manual=['review','changed'].includes(payload.action.op);
      if(payload.context)debugRecord.binding={...debugRecord.binding,test_keys:structuredClone(payload.context.test_keys??{})};
      const guide_receipt=manual?{request_id:payload.request_id,flow_id:payload.flow_id,context_epoch:chat.context_epoch,
        project_id:chat.project_id,project_revision:2,op:payload.action.op,...(payload.action.wire_id?{wire_id:payload.action.wire_id}:{}),
        ...(payload.action.decision?{decision:payload.action.decision}:{}),before_binding,after_binding:structuredClone(debugRecord.binding),
        guide_confirmations:structuredClone(payload.context?.guide_confirmations??{}),guide_run:payload.context?.guide_run??2,
        test_keys:structuredClone(debugRecord.binding.test_keys),review_id:debugRecord.wiring_review.id,round:debugRecord.wiring_review.round,
        context_fingerprint:key(payload.context)}:null;
      const answer={...(mobile?snapshot(true):result()),request_id:payload.request_id,guide_receipt};
      receipts.set(payload.request_id,structuredClone(answer));events.push({op:'flow-commit',request_id:payload.request_id,action:payload.action.op,wire_id:payload.action.wire_id,guide_receipt:Boolean(guide_receipt)});
      if(dropAckNext&&manual){dropAckNext=false;events.push({op:'synthetic-ack-dropped',request_id:payload.request_id});return send({detail:'synthetic_ack_lost_after_commit'},500);}
      return send(answer);}
    if(path===`/api/assistant/conversations/${chat.id}/messages`||path==='/api/mobile/messages'){
      if(chat.wiring_analysis)return send({detail:'wiring_analysis_in_progress'},409);
      append('user',body.text??'');append('assistant','這是一般問題的合成回覆；聊天提問不會觸發拍照或硬體測試。');return send(readChat(path==='/api/mobile/messages'));}
    if(path===`/api/assistant/conversations/${chat.id}/reset`){if(body.mode==='clear'){chat.context_epoch++;retire();}return send(readChat());}
    if(path==='/api/debug/sessions'&&req.method==='GET')return send({active:debugRecord});
    if(path==='/api/debug/conversations')return send({conversation:debugConversation});
    if(path==='/api/debug/sessions/wiring-chat-debug')return debugRecord?send(debugRecord):send({detail:'session_not_found'},404);
    if(path==='/api/debug/sessions/wiring-chat-debug/actions'&&body.action==='prepare_wiring'){
      if(!debugRecord)return send({detail:'session_not_found'},404);
      debugRecord.wiring_edit_ready=true;events.push({op:'synthetic-prepare-wiring',real_hardware_calls:0});return send(debugRecord);
    }
    return send({detail:'No production/model/hardware route in this closed fixture'},404);
  });
  await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done);});
  return{url:`http://127.0.0.1:${server.address().port}/`,server};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))console.log((await startPreview()).url);
