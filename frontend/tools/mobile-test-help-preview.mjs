// Loopback-only, real MobileWebApp/hooks with synthetic persisted test-help offers.
// No production fallthrough, camera, model, electrical or Pi route exists.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';

export async function startPreview(port=18809) {
  const directory=fileURLToPath(new URL('../',import.meta.url));
  const bundle=await build({entryPoints:[fileURLToPath(new URL('mobile-test-help-preview.tsx',import.meta.url))],bundle:true,
    write:false,outdir:'preview',jsx:'automatic',external:['/brand/*'],plugins:[{name:'fixture-translation',setup(builder){
      builder.onResolve({filter:/\/lib\/useMaker$/},()=>({path:'translation',namespace:'fixture'}));
      builder.onLoad({filter:/.*/,namespace:'fixture'},()=>({resolveDir:directory,contents:'export const useMakerText=()=> (zh,en)=>new URLSearchParams(location.search).get("lang")==="en"?en:zh;'}));
    }}]});
  const js=bundle.outputFiles.find(file=>file.path.endsWith('.js')).contents;
  const css=bundle.outputFiles.find(file=>file.path.endsWith('.css')).contents;
  const roles=['pi_side_a','pi_side_b','component_header'];
  const freshReview=()=>({id:'synthetic-review',revision:1,round:1,component_id:'hc-sr04',status:'collecting',photo_flow_version:2,
    slots:Object.fromEntries(roles.map(role=>[role,null])),observations:[],results:[],reviews:{},missing_roles:[...roles],no_progress_count:0});
  const picture='<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#d6e6e4"/><rect x="80" y="320" width="640" height="110" fill="#337555"/><text x="400" y="530" text-anchor="middle" font-size="25">SYNTHETIC QA PHOTO</text></svg>';
  let review=null,offer,session,chat,delayNext=0,failNext=false,serial=0;
  const requests=[],events=[],manualConfirmations={trig:'synthetic-existing-human-decision'};
  function reset(scenario='normal') {
    serial++;
    session={session_id:'test-help-phone',conversation_id:'test-help-conversation',context_id:'test-help-context',title:'手機接線檢查',
      context:{round:1,stage:'guide',design:{current:{id:'synthetic-project',revision:1,component_ids:['hc-sr04','mrd-tf240-8p-cs']}},
        context:{debug_context:{guide_run:1,test_keys:{'hc-sr04':'synthetic-key','mrd-tf240-8p-cs':'synthetic-tft-key'}}}},available_context:{context_id:'test-help-context'}, // Synthetic guide revision IDs, not credentials. gitleaks:allow
      stream:{active:false,generation:0,state:'finding',can_capture:false},view:{capture_id:null,wire_id:null,revision:serial}};
    offer={offer_id:`synthetic-offer-${serial}`,message_id:`synthetic-message-${serial}`,state:'pending',can_act:true,can_dismiss:true,
      component_id:'hc-sr04',reusable_review:false,project_id:'synthetic-project',project_revision:1,guide_run:1,context_epoch:0,
      guide_key:'synthetic-key',test_id:'synthetic-failed-test',reason:'no_echo',mode:'wiring'};
    review=null;delayNext=0;failNext=false;
    if(scenario==='continue') {
      review=freshReview();review.revision=4;
      review.slots.pi_side_a={role:'pi_side_a',capture_id:'original-selected-photo',sha256:'synthetic-source-hash',size:[800,600],
        image_url:'/api/mobile/wiring-review/evidence/original-selected-photo',crop:null,crop_source:'none',available:true,
        photo_acceptance:{capture_id:'original-selected-photo',sha256:'synthetic-source-hash',round:1,accepted_at:1,source:'human'}};
      review.missing_roles=['pi_side_b','component_header'];offer.reusable_review=true;offer.review_id=review.id;
    }
    chat={id:'test-help-conversation',messages:[{id:offer.message_id,role:'assistant',text:'HC-SR04 沒有讀到足夠的距離資料。\n要拍照檢查接線嗎？我會帶你拍 Pi 兩側和 HC-SR04 接頭，逐條核對。',
      source:'legacy-debug',created_at:1,epoch:0,round:1,stage:'guide',capability:'debug',test_help_offer:offer}],
      jobs:[],before:null,total:1,context_epoch:0,round:1,locale:'zh-TW'};
    events.push({op:'reset',scenario,serial});
  }
  reset();
  const snapshot=()=>({review:structuredClone(review),component_label:'HC-SR04',can_act:Boolean(review&&review.status!=='analysing'),offer:structuredClone(offer)});
  const allState=()=>({...snapshot(),session:structuredClone(session),chat:structuredClone(chat),manualConfirmations:structuredClone(manualConfirmations),events:[...events]});
  const html='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; style-src \'self\' \'unsafe-inline\'; connect-src \'self\'; img-src \'self\' data: blob:; media-src blob:; font-src \'self\' data:"><title>Mobile inline test help — isolated QA</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>';
  const server=createServer(async(request,response)=>{
    const path=new URL(request.url,'http://127.0.0.1').pathname;
    const chunks=[];for await(const chunk of request)chunks.push(chunk);
    let body={};if(request.headers['content-type']?.includes('application/json'))body=JSON.parse(Buffer.concat(chunks).toString()||'{}');
    requests.push({path,method:request.method,body,bearer:request.headers.authorization==='Bearer synthetic-test-help-token',serial});
    const send=(value,status=200,type='application/json')=>{response.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store'});response.end(type==='application/json'?JSON.stringify(value):value);};
    if(path==='/')return send(html,200,'text/html');
    if(path==='/preview.js')return send(js,200,'text/javascript');
    if(path==='/preview.css')return send(css,200,'text/css');
    if(path.startsWith('/brand/'))return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="0" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>',200,'image/svg+xml');
    if(path==='/__fixture/requests')return send(requests);
    if(path==='/__fixture/state')return send(allState());
    if(path==='/__fixture/reset'){reset(body.scenario);return send(allState());}
    if(path==='/__fixture/delay-next'){delayNext=body.ms??1800;return send({ok:true});}
    if(path==='/__fixture/fail-next'){failNext=true;return send({ok:true});}
    if(path==='/__fixture/desktop-dismiss'){offer.state='dismissed';offer.can_act=false;offer.can_dismiss=false;events.push({op:'desktop-dismiss',serial});return send(allState());}
    if(path==='/__fixture/new-context'){
      offer.state='stale';offer.can_act=false;offer.can_dismiss=false;
      session.context_id='updated-desktop-context';session.available_context.context_id=session.context_id;session.view.revision++;
      review=null;chat.context_epoch++;chat.round++;session.context.round=chat.round;session.context.context.debug_context.guide_run=chat.round;
      const old=chat.messages[0];old.archived=true;
      const newOffer={...offer,offer_id:`newer-offer-${serial}`,message_id:`newer-message-${serial}`,state:'pending',can_act:true,can_dismiss:true,context_epoch:chat.context_epoch,guide_run:chat.round};
      offer=newOffer;chat.messages.push({...old,id:offer.message_id,text:'新的測試仍需要核對。要拍照檢查目前接線嗎？',epoch:chat.context_epoch,round:chat.round,archived:false,test_help_offer:offer});chat.total++;
      events.push({op:'new-context',serial});return send(allState());
    }
    if(path.startsWith('/api/mobile/')&&request.headers.authorization!=='Bearer synthetic-test-help-token')return send({detail:'mobile_session_expired_or_invalid'},401);
    if(path==='/api/mobile/session')return send(session);
    if(path==='/api/mobile/conversation')return send(chat);
    if(path==='/api/mobile/stream'&&request.method==='DELETE')return send(session);
    if(path==='/api/mobile/wiring-review'&&request.method==='GET')return send(snapshot());
    if(/^\/api\/mobile\/wiring-review\/evidence\//.test(path))return send(picture,200,'image/svg+xml');
    if(path==='/api/mobile/wiring-review'&&request.method==='POST'){
      const invitation=body.invitation;
      if(!invitation||body.action||body.asset_id)return send({detail:'fixture_invitation_only'},409);
      const atStart={...invitation};const wait=delayNext;delayNext=0;
      if(wait)await new Promise(done=>setTimeout(done,wait));
      if(failNext){failNext=false;return send({detail:'test_help_busy'},409);}
      if(atStart.context_id!==session.context_id)return send({detail:'context_changed'},409);
      if(atStart.offer_id!==offer.offer_id||atStart.message_id!==offer.message_id||!['pending','started'].includes(offer.state)||!offer.can_act)return send({detail:'test_help_stale'},409);
      if(atStart.op==='later'){offer.state='dismissed';offer.can_act=false;offer.can_dismiss=false;events.push({op:'later',serial});return send(snapshot());}
      if(atStart.op!=='start')return send({detail:'fixture_invitation_action_not_allowed'},409);
      const reused=Boolean(offer.reusable_review&&review);if(!reused)review=freshReview();
      offer.state='started';offer.can_act=true;offer.reusable_review=true;offer.review_id=review.id;
      events.push({op:'start',reused,review_id:review.id,revision:review.revision,serial});
      return send(snapshot());
    }
    return send({detail:'No production route in this fixture'},404);
  });
  await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done);});
  return {url:`http://127.0.0.1:${server.address().port}/`,server,requests};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))console.log((await startPreview()).url);
