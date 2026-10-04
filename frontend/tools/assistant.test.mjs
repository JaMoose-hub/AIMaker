import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsxRuntime from 'react/jsx-runtime';
import {maker, designFor} from './project_guide_fixture.mjs';

const code = ts.transpileModule(readFileSync(new URL('../src/lib/assistant.ts', import.meta.url), 'utf8'), {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS},
}).outputText;
const record = (kind='project') => ({id:kind==='demo'?'demo':'project', kind, project_id:'layout-fixture',
  messages:[],jobs:[],before:null,total:0,context_epoch:0,round:0,demo:null});
const historyCode = ts.transpileModule(readFileSync(new URL('../src/lib/assistantHistory.ts', import.meta.url), 'utf8'), {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS},
}).outputText;
const history = {};
new Function('exports', historyCode)(history);
const wiringReceipts = {};
new Function('exports', ts.transpileModule(readFileSync(new URL('../src/lib/wiringReceipt.ts', import.meta.url), 'utf8'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText)(wiringReceipts);
const analysisHelpers = {};
new Function('exports', ts.transpileModule(readFileSync(new URL('../src/lib/assistantAnalysis.ts', import.meta.url), 'utf8'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText)(analysisHelpers);
function harness(request, {demo=null, guard=async()=>true, brokenStorage=false, persisted=new Map()}={}) {
  const values=[], refs=[], calls=[]; let index=0, ref=0;
  let state={...maker.initialMaker(), design:designFor(), prompt:'original draft', code:'manual code'};
  globalThis.localStorage={getItem:key=>persisted.get(key)??null, removeItem:key=>persisted.delete(key),
    setItem(key,value){if(brokenStorage)throw Error('quota');persisted.set(key,value);}};
  persisted.set('boardvision.assistant.v1','project');persisted.set('boardvision.assistant-demo.v1','demo');
  if(demo)persisted.set('boardvision.assistant-demo.v1.open','true');
  const react={...React,useEffect(){},useCallback:fn=>fn,useRef:initial=>refs[ref++]??={current:initial},
    useState(initial){const i=index++;if(!(i in values))values[i]=i===3?record():i===4?demo:typeof initial==='function'?initial():initial;
      return[values[i],next=>values[i]=typeof next==='function'?next(values[i]):next];}};
  const exports={};
  const modules={react,'./maker':{...maker,makerRequest:async(path,body)=>{calls.push({path,body});return request(path,body);}},
    './i18n':{useI18n:()=>({locale:'en'})},'./makerMigration':{MAKER_STORAGE:'boardvision.maker.v1'},
    './wiringEdit':{prepareProjectWiringEdit:guard},'./componentTests':{componentTestKey:()=> 'test-key'},'./wiringReceipt':wiringReceipts,
    './assistantAnalysis':analysisHelpers};
  new Function('require','exports',code)(name=>modules[name],exports);
  const update=next=>{state=typeof next==='function'?next(state):next;};
  return {render(debugSession=null){index=0;ref=0;return exports.useAssistant(state,update,null,debugSession);},update,state:()=>state,calls,values,persisted,exports};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((y,n)=>{resolve=y;reject=n;});return{promise,resolve,reject};};
const offerFor=snapshot=>({id:'local-offer',projectId:snapshot.design.id,revision:snapshot.design.revision,
  componentId:'hc-sr04',guideKey:'test-key',guideRun:snapshot.guide.run??0,contextEpoch:0,mode:'wiring',
  text:'HC-SR04+ did not return enough readings. Check the wiring with photos?'});
const factsFor=snapshot=>({project_id:snapshot.design.id,project_revision:snapshot.design.revision,
  component_id:'hc-sr04',test_id:snapshot.debug.runId??null,reason:'no_echo',logs:['PRIVATE TEST LOG']});
const receiptFor=(body,change={})=>{
  const item=body.messages[0];
  const import_key=createHash('sha256').update(`[${[body.source_id,item.id,item.role,item.text].map(value=>JSON.stringify(value)).join(', ')}]`).digest('hex');
  return {...item,id:`server-${import_key.slice(0,12)}`,import_key,source:'legacy-debug',epoch:0,capability:'debug',...change};
};
const importReply=(body,change={})=>({...record(),messages:[receiptFor(body,change)],total:1,context_epoch:change.epoch??0});
const wiringQuestion = (changes={}) => ({id:'photo-prompt',role:'assistant',text:'請拍 Pi 第一側。',source:'legacy-debug',
  stage:'guide',capability:'wiring',epoch:0,round:0,created_at:1,
  wiring_flow:{flow_id:'flow-1',review_id:'review-1',revision:3,round:1,component_id:'hc-sr04',kind:'photo_request',
    role:'pi_side_a',current:true,can_act:true,actions:['capture']},...changes});
const wiringAction = {op:'capture',role:'pi_side_a',review_id:'review-1',revision:3,component_id:'hc-sr04'};
const runningAnalysis = {flow_id:'flow-1',session_id:'debug-1',review_id:'review-1',revision:3,round:1,started_at:100};

test('analysis feedback locks desktop sends without creating an outbox or consuming the draft',async()=>{
  const h=harness(()=>assert.fail('Analysis must prevent a new request'));
  h.render().acceptExternal({...record(),wiring_analysis:runningAnalysis});
  assert.equal(h.render().busy,true);assert.deepEqual(h.render().wiringAnalysis,{startedAt:100});
  assert.equal(await h.render().send(),false);assert.equal(h.state().prompt,'original draft');
  assert.equal(h.calls.length,0);assert.equal(h.persisted.has('boardvision.assistant.v1.outbox'),false);
});

test('analysis feedback releases the preserved draft only on an authoritative idle update',async()=>{
  const h=harness(()=>({...record(),wiring_analysis:null}));
  h.render().acceptExternal({...record(),wiring_analysis:runningAnalysis});
  assert.equal(await h.render().send(),false);
  h.render().acceptExternal({...record(),wiring_analysis:null});
  assert.equal(h.render().busy,false);assert.equal(h.state().prompt,'original draft');
  assert.equal(await h.render().send(),true);assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].body.text,'original draft');assert.equal(h.state().prompt,'');
});

test('analysis feedback ignores historical and cleared clocks while explicit idle wins over loaded messages',()=>{
  const pending={...wiringQuestion(),round:0,wiring_flow:{...wiringQuestion().wiring_flow,kind:'analysing',started_at:100}};
  assert.deepEqual(analysisHelpers.assistantWiringAnalysis({...record(),messages:[pending]}),{startedAt:100});
  for(const modified of [{archived:true},{epoch:1},{round:1},{role:'user'},
    {wiring_flow:{...pending.wiring_flow,current:false}}])
    assert.equal(analysisHelpers.assistantWiringAnalysis({...record(),messages:[{...pending,...modified}]}),null);
  assert.equal(analysisHelpers.assistantWiringAnalysis({...record(),wiring_analysis:null,messages:[pending]}),null);
  assert.equal(analysisHelpers.assistantWiringAnalysis({...record('demo'),wiring_analysis:runningAnalysis}),null);
});

test('analysis feedback shows real elapsed seconds and never guesses a missing start',()=>{
  assert.equal(analysisHelpers.analysisElapsedMs(100,165999),65999);
  assert.equal(analysisHelpers.formatAnalysisDuration(65999),'1:05');
  assert.equal(analysisHelpers.analysisElapsedMs(200,165999),0);
  for(const start of [null,undefined,NaN,Infinity,0,-1])assert.equal(analysisHelpers.analysisElapsedMs(start,165999),null);
  assert.deepEqual(analysisHelpers.assistantWiringAnalysis({...record(),wiring_analysis:{...runningAnalysis,started_at:null}}),{startedAt:null});
});
const wiringReply = (message=wiringQuestion()) => ({conversation:{...record(),messages:[{...message,wiring_flow:{...message.wiring_flow,current:false,can_act:false}},
  {...wiringQuestion(),id:'next-prompt',text:'接著拍 Pi 另一側。',wiring_flow:{...message.wiring_flow,revision:5,role:'pi_side_b'}}],total:2},
  debug_session_id:'debug-1',debug_session:{id:'debug-1',wiring_review:{id:'review-1',revision:5}}});
function wiringHarness(request) {
  const h=harness(request);h.render().acceptExternal({...record(),messages:[wiringQuestion()],total:1});return h;
}

test('wiring chat transport sends the exact message reference and accepts the next question without consuming a draft',async()=>{
  const h=wiringHarness(()=>wiringReply()),controller=h.render(),message=controller.project.messages[0];
  const result=await controller.wiringFlowAction(message,wiringAction);
  assert.ok(result);assert.equal(h.calls.length,1);assert.equal(h.calls[0].path,'assistant/conversations/project/wiring-flow');
  assert.equal(h.calls[0].body.message_id,'photo-prompt');assert.equal(h.calls[0].body.flow_id,'flow-1');
  assert.deepEqual(h.calls[0].body.action,wiringAction);assert.equal(h.state().prompt,'original draft');
  assert.equal(h.render().project.messages.at(-1).id,'next-prompt');
});
test('wiring chat transport rejects stale message revisions before requesting anything',async()=>{
  const h=wiringHarness(()=>assert.fail('No stale request'));
  const controller=h.render(),message=controller.project.messages[0];
  assert.equal(await controller.wiringFlowAction({...message,wiring_flow:{...message.wiring_flow,revision:2}},wiringAction),false);
  assert.equal(h.calls.length,0);
});
test('wiring chat transport preserves request identity on an upload or transport retry',async()=>{
  let attempt=0;const h=wiringHarness(()=>{if(attempt++===0)throw Error('upload_failed');return wiringReply();});
  assert.equal(await h.render().wiringFlowAction(wiringQuestion(),wiringAction),false);
  assert.ok(await h.render().wiringFlowAction(wiringQuestion(),wiringAction));
  assert.equal(h.calls[0].body.request_id,h.calls[1].body.request_id);assert.equal(h.state().prompt,'original draft');
});
test('wiring chat transport ignores a late reply after a cleared conversation',async()=>{
  const response=deferred(),h=wiringHarness(()=>response.promise);
  const waiting=h.render().wiringFlowAction(wiringQuestion(),wiringAction);
  h.render().acceptExternal({...record(),context_epoch:1});h.render();response.resolve(wiringReply());
  assert.equal(await waiting,false);assert.equal(h.render().project.context_epoch,1);assert.ok(!h.render().project.messages.some(m=>m.id==='next-prompt'));
});
test('wiring chat transport ignores a late reply after a guide or wiring change',async()=>{
  const response=deferred(),h=wiringHarness(()=>response.promise);
  const waiting=h.render().wiringFlowAction(wiringQuestion(),wiringAction);
  h.update(s=>({...s,guide:{...s.guide,confirmed:{}}}));h.render();response.resolve(wiringReply());
  assert.equal(await waiting,false);assert.equal(h.render().project.messages.at(-1).id,'photo-prompt');
});
test('wiring chat transport makes double clicks a single request',async()=>{
  const response=deferred(),h=wiringHarness(()=>response.promise),controller=h.render();
  const waiting=controller.wiringFlowAction(wiringQuestion(),wiringAction);
  assert.equal(await controller.wiringFlowAction(wiringQuestion(),wiringAction),false);assert.equal(h.calls.length,1);
  response.resolve(wiringReply());assert.ok(await waiting);
});
test('wiring chat transport passes the human confirmation context only on the explicit bound action',async()=>{
  const message=wiringQuestion({wiring_flow:{...wiringQuestion().wiring_flow,kind:'wire_review',wire_id:'wire-1',actions:['review']}});
  const h=wiringHarness(()=>wiringReply(message));h.render().acceptExternal({...record(),messages:[message],total:1});
  const context={project:h.state().design,code:'manual code',test_keys:{'hc-sr04':'confirmed-key'},guide_confirmations:{'wire-1':{at:'now'}}};
  assert.ok(await h.render().wiringFlowAction(message,{...wiringAction,op:'review',wire_id:'wire-1',decision:'confirmed'},context));
  assert.deepEqual(h.calls[0].body.context,context);assert.equal(h.calls[0].body.action.decision,'confirmed');
  assert.deepEqual(h.state().guide.confirmed,{});
});
test('wiring chat transport rejects an action absent from the current question',async()=>{
  const h=wiringHarness(()=>assert.fail('No unoffered action'));
  assert.equal(await h.render().wiringFlowAction(wiringQuestion(),{...wiringAction,op:'analyse'}),false);assert.equal(h.calls.length,0);
});
test('wiring receipt transport reads the exact completed human receipt after a lost ACK and flow advancement',async()=>{
  const message=wiringQuestion({session_id:'debug-1',wiring_flow:{...wiringQuestion().wiring_flow,kind:'wire_review',wire_id:'wire-1',actions:['review']}});
  const h=wiringHarness((path,body)=>{if(body)throw Error('lost acknowledgement');return {...wiringReply(message),receipt_state:'done',
    request_id:h.calls[0].body.request_id,guide_receipt:{request_id:h.calls[0].body.request_id}};});
  h.render().acceptExternal({...record(),messages:[message],total:1});
  const context={project:h.state().design,code:'manual code',test_keys:{'hc-sr04':'after'},guide_confirmations:{'wire-1':{at:'frozen-time'}}};
  assert.equal(await h.render({id:'debug-1',binding:{test_keys:{'hc-sr04':'before'}}}).wiringFlowAction(message,{...wiringAction,op:'review',wire_id:'wire-1',decision:'confirmed'},context),false);
  assert.equal(h.render().wiringReceiptPending,true);
  h.render().acceptExternal(wiringReply(message).conversation);h.render();
  const result=await h.render().recoverWiringFlow();assert.ok(result);
  assert.match(h.calls[1].path,/\/wiring-flow\/receipts\//);assert.equal(h.calls[1].body,undefined);
  assert.equal(result.outbox.context.guide_confirmations['wire-1'].at,'frozen-time');
  assert.deepEqual(h.state().guide.confirmed,{});
  h.render().acknowledgeWiringFlow(result.outbox.request_id);assert.equal(h.render().wiringReceiptPending,false);
});
test('wiring receipt transport retries a missing submission with its persisted original request and context',async()=>{
  const message=wiringQuestion({session_id:'debug-1',wiring_flow:{...wiringQuestion().wiring_flow,kind:'wire_review',wire_id:'wire-1',actions:['review']}});
  let posts=0;const h=wiringHarness((_path,body)=>{if(body){if(posts++===0)throw Error('upload never reached server');return {...wiringReply(message),guide_receipt:{request_id:body.request_id}};}
    return {...wiringReply(message),conversation:{...record(),messages:[message],total:1},receipt_state:'missing'};});
  h.render().acceptExternal({...record(),messages:[message],total:1});
  const context={project:h.state().design,code:'manual code',test_keys:{'hc-sr04':'after'},guide_confirmations:{'wire-1':{at:'original-time'}}};
  assert.equal(await h.render({id:'debug-1',binding:{}}).wiringFlowAction(message,{...wiringAction,op:'review',wire_id:'wire-1',decision:'confirmed'},context),false);
  assert.ok(await h.render().recoverWiringFlow(true));assert.equal(h.calls.length,3);
  assert.equal(h.calls[2].body.request_id,h.calls[0].body.request_id);assert.deepEqual(h.calls[2].body.context,h.calls[0].body.context);
  assert.ok(h.persisted.has('boardvision.assistant.v1.wiring-outbox'));assert.deepEqual(h.state().guide.confirmed,{});
});

test('known test help imports one short assistant invitation without a model request, draft changes or phone context changes',async()=>{
  const h=harness((_path,body)=>importReply(body)),controller=h.render(),snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
  const before=structuredClone(controller.mobileContext);
  const invitation=offerFor(snapshot),facts=factsFor(snapshot);
  const messageId=await controller.offerTestHelp(snapshot,invitation,facts);
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].path,'assistant/conversations/project/import');
  const body=h.calls[0].body;assert.match(body.source_id,/^test-help:[a-f0-9]{64}$/);
  assert.equal(messageId,receiptFor(body).id);
  assert.equal(body.kind,'legacy-debug');assert.equal(body.messages.length,1);
  assert.equal(body.messages[0].role,'assistant');assert.equal(body.messages[0].text,invitation.text);
  assert.doesNotMatch(JSON.stringify(body.messages),/PRIVATE TEST LOG|selected-test|session_id|capture_ids/);
  assert.equal(body.test_help.test_id,'selected-test');
  assert.equal(body.test_help.offer_id,invitation.id);
  assert.match(body.test_help.code_hash,/^[a-f0-9]{64}$/);
  assert.doesNotMatch(JSON.stringify(body.test_help),/PRIVATE TEST LOG|manual code/);
  assert.equal(h.state().prompt,'original draft');assert.equal(h.state().code,'manual code');
  assert.deepEqual(h.render().mobileContext,before);
});
test('invitation delivery retry reuses the issue receipt; new test and cleared chat have independent receipts',async()=>{
  let attempts=0,epoch=0;const h=harness((_path,body)=>{if(attempts++===0)throw Error('offline');return importReply(body,{epoch});});
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo'),invitation=offerFor(snapshot),facts=factsFor(snapshot);
  assert.equal(await h.render().offerTestHelp(snapshot,invitation,facts),false);
  assert.equal(await h.render().offerTestHelp(snapshot,{...invitation,id:'new-local-render'},facts),receiptFor(h.calls[1].body).id);
  assert.equal(h.calls[0].body.source_id,h.calls[1].body.source_id);
  const another=maker.enterDebug(h.state(),'hc-sr04','another-test','no_echo');
  assert.equal(await h.render().offerTestHelp(another,offerFor(another),factsFor(another)),receiptFor(h.calls[2].body).id);
  assert.notEqual(h.calls[2].body.source_id,h.calls[0].body.source_id);
  h.render().acceptExternal({...record(),context_epoch:1});
  epoch=1;
  assert.equal(await h.render().offerTestHelp(snapshot,{...invitation,contextEpoch:1},facts),receiptFor(h.calls[3].body,{epoch}).id);
  assert.notEqual(h.calls[3].body.source_id,h.calls[0].body.source_id);
  assert.equal(h.state().prompt,'original draft');
});
test('a late invitation hash cannot submit a changed project, guide round or cleared chat',async()=>{
  for(const change of ['project','round','epoch']) {
    const h=harness(()=>assert.fail('Stale invitation must not import'));
    const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
    const promise=h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot));
    if(change==='project')h.update(s=>({...s,design:{...s.design,revision:2}}));
    if(change==='round')h.update(s=>({...s,guide:{...s.guide,run:1}}));
    if(change==='epoch')h.render().acceptExternal({...record(),context_epoch:1});
    h.render();assert.equal(await promise,false);assert.equal(h.calls.length,0);
  }
});

test('test-help import receipt hash matches the fixed Python contract for Chinese and newline text',async()=>{
  const {testHelpImportKey}=harness(()=>assert.fail('Hashing cannot request anything')).exports;
  assert.equal(await testHelpImportKey('test-help:contract-chinese','HC-SR04+ 沒有讀到距離。\n要拍照檢查接線嗎？'),
    '7b5c08765b8b34401cdfcff8d776bf21d881ddd48e90a5ca059d2ca3d907b33d');
});
const historyMessage=index=>({id:`history-${index}`,role:'user',source:'mobile',text:`message ${index}`,created_at:index,
  epoch:0,round:0,stage:'guide',capability:'debug'});
test('a deduplicated invitation older than the last 50 messages is recovered in server order using existing paging',async()=>{
  let all,exact;
  const h=harness((path,body)=>{
    if(body){exact=receiptFor(body);all=Array.from({length:170},(_,i)=>historyMessage(i));all[10]=exact;
      return {...record(),messages:all.slice(120),before:120,total:170};}
    if(path.endsWith('?before=120&limit=100'))return {...record(),messages:all.slice(20,120),before:20,total:170};
    assert.equal(path,'assistant/conversations/project?before=20&limit=100');
    return {...record(),messages:all.slice(0,20),before:null,total:170};
  });
  h.render().acceptExternal({...record(),messages:Array.from({length:50},(_,i)=>historyMessage(i+120)),before:120,total:170});
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
  assert.equal(await h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot)),exact.id);
  assert.deepEqual(h.calls.map(call=>call.path),['assistant/conversations/project/import',
    'assistant/conversations/project?before=120&limit=100','assistant/conversations/project?before=20&limit=100']);
  const result=h.render().project;
  assert.deepEqual(result.messages.map(m=>m.id),all.map(m=>m.id));assert.equal(result.messages.at(-1).id,'history-169');
  assert.equal(result.before,null);assert.equal(result.total,170);assert.equal(result.messages[10].import_key,exact.import_key);
});
test('a cached exact receipt skips paging while a later identical-text receipt cannot replace its message identity',async()=>{
  let exact;
  const h=harness((path,body)=>{
    assert.ok(body,'No GET is necessary when the exact imported receipt is already cached');
    exact=receiptFor(body);
    const wrong={...exact,id:'different-test-same-text',import_key:'another-issue'};
    const cached={...record(),messages:[exact,...Array.from({length:70},(_,i)=>historyMessage(i)),wrong],total:72};
    h.render().acceptExternal(cached);h.render();
    return {...record(),messages:cached.messages.slice(22),before:22,total:72};
  });
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
  assert.equal(await h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot)),exact.id);
  assert.equal(h.calls.length,1);assert.equal(h.render().project.messages[0].id,exact.id);
  assert.equal(h.render().project.messages.at(-1).id,'different-test-same-text');
});
test('unknown, wrong-source, wrong-round or wrong-epoch receipts never publish a photo invitation from matching text',async()=>{
  for(const wrong of [{import_key:'different-issue'},{source:'mobile'},{role:'user'},{epoch:1},{round:1},{text:'different text'},{id:''}]) {
    const h=harness((_path,body)=>({...record(),messages:[receiptFor(body,wrong)],total:1}));
    const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo'),before=h.render().project;
    assert.equal(await h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot)),false);
    assert.equal(h.render().project,before);assert.match(h.render().error,/invitation could not be retrieved.*Retry Ask AI/);
    assert.equal(h.state().prompt,'original draft');
  }
});
test('late receipt paging cannot accept history after clearing chat, changing project, code, guide or starting a model job',async()=>{
  for(const change of ['epoch','project','code','round','conversation','model']) {
    const get=deferred(),requested=deferred();let exact;
    const h=harness((path,body)=>{
      if(body){exact=receiptFor(body);return {...record(),messages:[historyMessage(60)],before:60,total:61};}
      assert.equal(path,'assistant/conversations/project?before=60&limit=100');requested.resolve();return get.promise;
    });
    const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
    const pending=h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot));await requested.promise;
    assert.equal(h.render().busy,true);
    assert.equal(await h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot)),false,'The receipt lookup owns the flight lock');
    if(change==='epoch')h.render().acceptExternal({...record(),context_epoch:1});
    if(change==='project')h.update(s=>({...s,design:{...s.design,revision:2}}));
    if(change==='code')h.update(s=>({...s,code:'changed code'}));
    if(change==='round')h.update(s=>({...s,guide:{...s.guide,run:1}}));
    if(change==='conversation')h.render().activateConversation({...record(),id:'new-conversation'});
    if(change==='model')h.render().acceptExternal({...record(),jobs:[{id:'other-model-job',status:'running'}]});
    const before=h.render().project;
    get.resolve({...record(),messages:[exact],before:null,total:61});
    assert.equal(await pending,false);assert.equal(h.render().project,before);
    assert.ok(!h.render().project.messages.some(message=>message.id===exact.id));
    assert.equal(h.render().pending,false);assert.equal(h.state().prompt,'original draft');
  }
});
test('a receipt page with a nondecreasing cursor fails safely instead of fetching forever',async()=>{
  const h=harness((_path,body)=>({...record(),messages:body?[historyMessage(60)]:[historyMessage(30)],before:60,total:61}));
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
  assert.equal(await h.render().offerTestHelp(snapshot,offerFor(snapshot),factsFor(snapshot)),false);
  assert.equal(h.calls.length,2);assert.match(h.render().error,/invitation could not be retrieved/);
});

function sharedOffer(h, changes={}) {
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','selected-test','no_echo');
  const invitation={...offerFor(snapshot),messageId:'exact-reminder'};
  const offer={offer_id:invitation.id,message_id:invitation.messageId,state:'pending',can_act:true,can_dismiss:true,
    component_id:invitation.componentId,reusable_review:false,project_id:invitation.projectId,project_revision:invitation.revision,
    guide_run:invitation.guideRun,context_epoch:invitation.contextEpoch,guide_key:invitation.guideKey,test_id:'selected-test',reason:'no_echo',mode:'wiring'};
  h.render().acceptExternal({...record(),messages:[{id:invitation.messageId,role:'assistant',text:invitation.text,source:'legacy-debug',
    epoch:0,round:0,stage:'guide',test_help_offer:offer,...changes}]});
  h.render();return {invitation,offer};
}

test('shared photo consent calls one authoritative action and publishes its exact receipt without model or local session creation',async()=>{
  let offer;
  const session={id:'shared-review',wiring_review:{id:'review',component_id:'hc-sr04'}};
  const h=harness((path,body)=>{
    assert.equal(path,'assistant/conversations/project/test-help');assert.equal(body.op,'start');
    return {offer:{...offer,state:'started'},debug_session:session};
  });
  const bound=sharedOffer(h);offer=bound.offer;
  const result=await h.render().testHelpAction(bound.invitation,'start');
  assert.equal(result.debug_session,session);assert.equal(h.calls.length,1);
  assert.deepEqual(h.calls[0].body,{op:'start',offer_id:bound.invitation.id,message_id:'exact-reminder'});
  assert.equal(h.render().project.messages[0].test_help_offer.state,'started');
  assert.equal(h.state().prompt,'original draft');assert.equal(h.state().code,'manual code');
});

test('shared Later remains available while a model runs and only dismisses the invitation',async()=>{
  let offer;
  const h=harness((_path,body)=>{
    assert.equal(body.op,'later');return {offer:{...offer,state:'dismissed',can_act:false,can_dismiss:false}};
  });
  const bound=sharedOffer(h);offer={...bound.offer,can_act:false};
  const original=h.render().project;
  h.render().acceptExternal({...original,messages:original.messages.map(m=>({...m,test_help_offer:offer})),jobs:[{id:'running-model',status:'running'}]});
  h.render();
  assert.equal(await h.render().testHelpAction(bound.invitation,'start'),false);
  assert.ok(await h.render().testHelpAction(bound.invitation,'later'));
  assert.equal(h.calls.length,1);assert.equal(h.render().project.messages[0].test_help_offer.state,'dismissed');
  assert.equal(h.render().project.jobs[0].status,'running');assert.equal(h.state().prompt,'original draft');
});

test('shared action cannot dispatch from an old, archived, wrong-source or replaced reminder',async()=>{
  for(const change of [{epoch:1},{round:1},{archived:true},{source:'mobile'},{role:'user'},
    {test_help_offer:{offer_id:'replaced',can_act:true,can_dismiss:true,state:'pending',mode:'wiring'}}]) {
    const h=harness(()=>assert.fail('A mismatched reminder cannot invoke any action'));
    const {invitation}=sharedOffer(h,change);
    assert.equal(await h.render().testHelpAction(invitation,'start'),false);
    assert.equal(await h.render().testHelpAction(invitation,'later'),false);assert.equal(h.calls.length,0);
  }
});

test('late shared action receipts cannot overwrite a cleared context, edited code or replacement offer',async()=>{
  for(const change of ['epoch','code','offer','dismissed']) {
    const response=deferred(),h=harness(()=>response.promise),bound=sharedOffer(h);
    const pending=h.render().testHelpAction(bound.invitation,'start');
    const previous=h.render().project;
    if(change==='epoch')h.render().acceptExternal({...previous,context_epoch:1});
    if(change==='code')h.update(s=>({...s,code:'changed code'}));
    if(change==='offer'||change==='dismissed')h.render().acceptExternal({...previous,messages:previous.messages.map(m=>({...m,
      test_help_offer:change==='offer'?{...bound.offer,offer_id:'new-offer'}:{...bound.offer,state:'dismissed'}}))});
    const current=h.render().project;
    response.resolve({offer:{...bound.offer,state:'started'},debug_session:{id:'old-review'}});
    assert.equal(await pending,false);assert.equal(h.render().project,current);
  }
});

test('explicit test help sends the frozen debug context without clearing the draft or inheriting another session/photo',async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);
  h.update(s=>({...s,stage:'guide'}));
  h.render().acceptExternal({...record(),active_media:{asset_ids:['old-photo'],capture_id:'old-capture',attachments:[],epoch:0,round:0}});
  const controller=h.render({id:'another-debug-session',status:'diagnosing'});
  const mobileBefore=structuredClone(controller.mobileContext);
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','exact-test','no_echo');
  const facts={project_id:snapshot.design.id,project_revision:snapshot.design.revision,component_id:'hc-sr04',test_id:'exact-test',
    reason:'no_echo',outcome:'inconclusive',samples:{near:{count:0,median_cm:null}},logs:['Private test log'],
    expected_wiring:snapshot.design.wiring.filter(w=>w.componentId==='hc-sr04')};
  const visible='Please help troubleshoot this HC-SR04+ function test.';
  const send=controller.sendTestHelp(snapshot,visible,facts);
  assert.equal(h.calls.length,1);
  const request=h.calls[0];assert.equal(request.path,'assistant/conversations/project/messages');
  assert.equal(request.body.target,'debug');assert.equal(request.body.context.debug_context.entry.runId,'exact-test');
  assert.equal(request.body.context.debug_context.entry.componentId,'hc-sr04');
  assert.equal(request.body.context.debug_session_id,null);assert.equal(request.body.inherit_media,false);
  assert.equal(request.body.text,visible);assert.doesNotMatch(request.body.text,/exact-test|Private test log|\{/);
  assert.deepEqual(request.body.context.component_test_help,facts);
  facts.samples.near.count=99;facts.logs[0]='Changed';
  assert.equal(request.body.context.component_test_help.samples.near.count,0);
  assert.equal(request.body.context.component_test_help.logs[0],'Private test log');
  assert.deepEqual(h.render({id:'another-debug-session',status:'diagnosing'}).mobileContext,mobileBefore);
  assert.equal('component_test_help' in h.render().mobileContext.context,false);
  assert.deepEqual(request.body.asset_ids,[]);assert.equal(request.body.capture_id,null);
  assert.equal(await controller.sendTestHelp(snapshot,'Duplicate'),false);
  h.render().setDraft('new typing while help sends');
  pending.resolve(record());assert.equal(await send,true);
  assert.equal(h.state().prompt,'new typing while help sends');assert.equal(h.state().code,'manual code');
  assert.equal(h.calls.length,1);
});
test('test help retries an uncertain send with the same id and preserves an existing composer draft',async()=>{
  let attempts=0;const h=harness(()=>{if(attempts++===0)throw Error('offline');return record();});
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','exact-test','no_echo');
  const facts={project_id:snapshot.design.id,project_revision:snapshot.design.revision,component_id:'hc-sr04',test_id:'exact-test',logs:['hidden']};
  assert.equal(await h.render().sendTestHelp(snapshot,'Test help',facts),false);
  const requestId=h.calls[0].body.request_id;
  assert.equal(h.state().prompt,'original draft');
  assert.equal(await h.render().sendTestHelp(snapshot,'Test help',facts),true);
  assert.equal(h.calls[1].body.request_id,requestId);assert.equal(h.state().prompt,'original draft');
  assert.deepEqual(h.calls[1].body.context.component_test_help,facts);
});
test('background test facts cannot be sent under another project, component, revision or run',async()=>{
  const h=harness(()=>assert.fail('Mismatched hidden facts must not send'));
  const snapshot=maker.enterDebug(h.state(),'hc-sr04','exact-test','no_echo');
  const facts={project_id:snapshot.design.id,project_revision:snapshot.design.revision,component_id:'hc-sr04',test_id:'exact-test'};
  for(const wrong of [{project_id:'other'},{project_revision:99},{component_id:'mrd-tf240-8p-cs'},{test_id:'other-run'}])
    assert.equal(await h.render().sendTestHelp(snapshot,'Test help',{...facts,...wrong}),false);
  assert.equal(h.calls.length,0);assert.equal(h.state().prompt,'original draft');
});
test('preflight help without a test run replaces an older issue and keeps diagnostic errors out of the chat',async()=>{
  const h=harness(()=>record());
  h.update(s=>maker.enterDebug(s,'mrd-tf240-8p-cs','old-tft-test','black'));
  const snapshot=maker.enterDebug(h.state(),'hc-sr04',undefined,'test_failed');
  const facts={project_id:snapshot.design.id,project_revision:snapshot.design.revision,component_id:'hc-sr04',test_id:null,
    reason:null,outcome:'inconclusive',detail:'Private preflight error'};
  assert.equal(await h.render().sendTestHelp(snapshot,'Please help check this HC-SR04+ test.',facts),true);
  const sent=h.calls[0].body;
  assert.equal(sent.context.debug_context.entry.componentId,'hc-sr04');assert.equal(sent.context.debug_context.entry.runId,undefined);
  assert.equal(sent.context.component_test_help.detail,'Private preflight error');
  assert.doesNotMatch(sent.text,/Private|old-tft-test|\{/);
});
test('test help cannot submit a replaced project, code, wiring round or demo',async()=>{
  const h=harness(()=>assert.fail('Stale test help must not send'));
  const base=h.state(),snapshot=maker.enterDebug(base,'hc-sr04','exact-test','no_echo');
  for(const mutate of [s=>({...s,design:{...s.design,revision:2}}),s=>({...s,code:'changed'}),s=>({...s,guide:{...s.guide,run:1}})]) {
    h.update(mutate(base));assert.equal(await h.render().sendTestHelp(snapshot,'Old help'),false);
  }
  h.update(base);h.render().setDemoOpen(true);assert.equal(await h.render().sendTestHelp(snapshot,'Demo help'),false);
  assert.equal(h.calls.length,0);
});

test('accepted send clears only the submitted draft and freezes stage/version/code',async()=>{
  for(const newDraft of ['', 'new typed draft']) {
    const pending=deferred(),h=harness(()=>pending.promise);h.update(s=>({...s,stage:'deploy'}));
    const sent=h.render().send();
    assert.equal(h.calls.length,1);assert.equal(h.calls[0].body.stage,'deploy');
    assert.equal(h.calls[0].body.context.debug_context.code,'manual code');
    if(newDraft)h.render().setDraft(newDraft);
    h.update(s=>({...s,stage:'guide'}));
    pending.resolve(record());assert.equal(await sent,true);
    assert.equal(h.state().prompt,newDraft);assert.equal(h.state().stage,'guide');
    assert.equal(h.state().code,'manual code');
  }
});

test('mobile workspace publication follows stage, code, guide round, context and chosen model without conversation recursion',()=>{
  const h=harness(()=>record());
  const first=h.render().mobileContext;
  h.update(s=>({...s,stage:'guide',code:'changed code',aiModel:'chosen-model',aiEffort:'high',guide:{...s.guide,run:2}}));
  const second=h.render().mobileContext;
  assert.equal(second.conversation_id,'project');assert.equal(second.stage,'guide');assert.equal(second.round,2);
  assert.equal(second.context.debug_context.code,'changed code');assert.equal(second.design.model,'chosen-model');
  assert.notDeepEqual(second,first);
  assert.deepEqual(h.render().mobileContext,second,'An unrelated render must not invent a new workspace');
  h.render().setDraft('unfinished chat input');
  assert.deepEqual(h.render().mobileContext,second,'Editing the chat draft does not change the published workspace');
  h.render().acceptExternal({...record(),context_epoch:2});
  const cleared=h.render().mobileContext;
  assert.equal(cleared.context.assistant_context_epoch,2);
  assert.notDeepEqual(cleared,second,'Clearing conversation context republishes the workspace');
});

test('phone workspace excludes only the desktop debug session binding while desktop sends retain it',async()=>{
  const h=harness(()=>record());
  h.update(s=>({...s,stage:'guide',debug:{...s.debug,caseId:'case',image:{id:'evidence-image',frame_id:77},debug_session_id:'nested-evidence-reference'}}));
  const {assistantWorkspacePayload,assistantMobileWorkspacePayload}=h.exports;
  const first={id:'debug-A',status:'awaiting_capture'},second={id:'debug-B',status:'diagnosing'};
  const desktop=assistantWorkspacePayload(h.state(),'en',undefined,first);
  const phone=assistantMobileWorkspacePayload(h.state(),'en',undefined,first);
  const expected=structuredClone(desktop);delete expected.context.debug_session_id;
  assert.deepEqual(phone,expected,'Every field except the top-level desktop session binding is preserved');
  assert.equal(desktop.context.debug_session_id,'debug-A');
  assert.equal(phone.context.debug_context.entry.debug_session_id,'nested-evidence-reference');
  assert.deepEqual(phone.context.debug_context.entry.image,{id:'evidence-image',frame_id:77});
  assert.ok(phone.context.debug_context.wiring_target.wire_id);
  const published=h.render(first).mobileContext;
  for(const session of [second,{...first,status:'stopped'},{...first,status:'complete'},null]) {
    assert.deepEqual(h.render(session).mobileContext,published,'Starting, replacing or stopping debug does not republish the phone project');
    assert.deepEqual(assistantMobileWorkspacePayload(h.state(),'en',undefined,session),phone);
  }
  assert.equal(assistantWorkspacePayload(h.state(),'en',undefined,second).context.debug_session_id,'debug-B');
  assert.equal(assistantWorkspacePayload(h.state(),'en',undefined,{...first,status:'stopped'}).context.debug_session_id,null);
  await h.render(second).send('debug');
  assert.equal(h.calls[0].body.context.debug_session_id,'debug-B');
  assert.deepEqual(h.calls[0].body.context.debug_context,desktop.context.debug_context);
});

test('phone workspace still changes for actual guide round, revision, wiring target and cleared context',()=>{
  const h=harness(()=>record());const original=h.state(),first=h.render({id:'debug-A',status:'diagnosing'}).mobileContext;
  for(const change of [
    value=>({...value,guide:{...value.guide,run:1}}),
    value=>({...value,design:{...value.design,revision:value.design.revision+1}}),
    value=>({...value,guide:{...value.guide,index:value.guide.index+1}}),
  ]) {
    h.update(change(original));const next=h.render({id:'debug-B',status:'stopped'}).mobileContext;
    assert.notDeepEqual(next,first);
    assert.equal('debug_session_id' in next.context,false);
  }
  h.update(original);h.render().acceptExternal({...record(),context_epoch:1});
  const cleared=h.render().mobileContext;assert.equal(cleared.context.assistant_context_epoch,1);assert.notDeepEqual(cleared,first);
  const mobile=h.exports.assistantMobileWorkspacePayload;
  assert.notDeepEqual(mobile(original,'en',undefined,null,'wiring'),mobile(original,'en',undefined,null,'debug'));
});

test('failed delivery preserves text and the idempotency key survives a reload',async()=>{
  const h=harness(async()=>{throw Error('offline');});
  assert.equal(await h.render().send(),false);assert.equal(h.state().prompt,'original draft');
  const id=h.calls[0].body.request_id;
  const reloaded=harness(async()=>record(),{persisted:h.persisted});
  await reloaded.render().send();assert.equal(reloaded.calls[0].body.request_id,id);
  assert.equal(reloaded.state().prompt,'');
});

test('an unacknowledged text retry freezes its displayed photo and payload across new captures and reload',async()=>{
  const media=name=>({asset_ids:[name],capture_id:`capture-${name}`,epoch:0,round:0,
    attachments:[{asset_id:name,filename:`${name}.jpg`,image_url:`/${name}`} ]});
  const h=harness(async()=>{throw Error('offline');});
  h.render().acceptExternal({...record(),active_media:media('first')});
  assert.equal(await h.render().send(),false);
  const original=structuredClone(h.calls[0].body);
  assert.deepEqual(original.asset_ids,['first']);assert.equal(original.capture_id,'capture-first');assert.equal(original.inherit_media,false);
  h.render().acceptExternal({...record(),active_media:media('second')});
  assert.equal(h.render().mediaReference.attachments[0].filename,'first.jpg');
  assert.equal(await h.render().send(),false);assert.deepEqual(h.calls[1].body,original);
  const reloaded=harness(async()=>{throw Error('offline');},{persisted:h.persisted});
  reloaded.render().acceptExternal({...record(),active_media:media('second')});
  assert.equal(reloaded.render().mediaReference.capture_id,'capture-first');
  await reloaded.render().send();assert.deepEqual(reloaded.calls[0].body,original);
  reloaded.render().setDraft('A different follow-up');
  assert.equal(reloaded.render().mediaReference.capture_id,'capture-second');
  await reloaded.render().send();assert.notEqual(reloaded.calls[1].body.request_id,original.request_id);
  assert.deepEqual(reloaded.calls[1].body.asset_ids,['second']);
});

test('a text-only retry also freezes the absence of media when a photo arrives later',async()=>{
  const h=harness(async()=>{throw Error('offline');});
  await h.render().send();const first=structuredClone(h.calls[0].body);
  assert.equal(first.inherit_media,false);assert.equal(first.asset_ids,undefined);
  h.render().acceptExternal({...record(),active_media:{asset_ids:['later'],capture_id:'later-photo',epoch:0,round:0,attachments:[]}});
  assert.equal(h.render().mediaReference,null);
  await h.render().send();assert.deepEqual(h.calls[1].body,first);
});

test('legacy outboxes preserve their original no-media request fingerprint on retry',async()=>{
  const h=harness(async()=>{throw Error('offline');});await h.render().send();
  const saved=JSON.parse(h.persisted.get('boardvision.assistant.v1.outbox'));
  h.persisted.set('boardvision.assistant.v1.outbox',JSON.stringify({key:saved.key,id:saved.id}));
  const original={...h.calls[0].body};delete original.inherit_media;
  const reloaded=harness(async()=>record(),{persisted:h.persisted});
  await reloaded.render().send();assert.deepEqual(reloaded.calls[0].body,original);
});

test('double submit has one request, new project rejects a late result',async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);
  const first=h.render().send(),second=h.render().send();
  assert.equal(await second,false);assert.equal(h.calls.length,1);
  h.render().activateConversation({...record(),id:'new-project'});
  h.update(s=>({...s,design:null,prompt:'new project draft'}));
  pending.resolve({...record(),jobs:[{id:'job',status:'completed',version:{project_id:'layout-fixture',revision:1},result:designFor()}]});
  await first;assert.equal(h.state().design,null);assert.equal(h.state().candidate,null);
  assert.equal(h.state().prompt,'new project draft');
});

test('merge keeps loaded older history after polling, updates archive and context',()=>{
  const {mergeConversation}=harness(()=>record()).exports;
  const messages=Array.from({length:80},(_,i)=>({id:String(i),round:0,epoch:0,capability:'debug',text:String(i)}));
  const merged=mergeConversation({...record(),messages,before:null,total:80},{...record(),round:1,context_epoch:1,messages:messages.slice(30),before:30,total:80});
  assert.equal(merged.messages.length,80);assert.equal(merged.before,null);
  assert.equal(merged.context_epoch,1);assert.ok(merged.messages.every(m=>m.archived));
  const growing=mergeConversation({...record(),messages:messages.slice(0,49),total:49},
    {...record(),messages:messages.slice(10,60),total:60,before:10});
  assert.equal(growing.messages.length,60);assert.equal(growing.before,null);
});

test('Demo builtin confirmation is isolated and deduplicated; leaving does not cancel',async()=>{
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:null,checklist:{},state:'checklist_pending'}};
  const h=harness(async()=>({...demo,demo:{...demo.demo,confirmed_revision:1,result:designFor()}}),{demo});
  const before=h.state();await h.render().confirmDemo('builtin');
  assert.equal(h.calls[0].path,'assistant/conversations/demo/confirm');
  assert.equal(h.calls[0].body.generation,null);assert.equal(h.calls[0].body.mode,'builtin');
  const id=h.calls[0].body.request_id;await h.render().confirmDemo('builtin');assert.equal(h.calls[1].body.request_id,id);
  h.render().setDemoOpen(false);assert.equal(h.state(),before);assert.equal(h.calls.length,2);
});

test('adoption is guarded by active work, backup, confirmed revision and stale project',async()=>{
  const result=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:1,result,state:'result_pending'}};
  for(const reason of ['hardware','storage','revision','stale']) {
    let h;
    h=harness(async()=>({...record(),id:'adopted'}),{demo:reason==='revision'?{...demo,demo:{...demo.demo,revision:2}}:demo,
      brokenStorage:reason==='storage',guard:async()=>{if(reason==='hardware')throw Error('hardware_work_active');
        if(reason==='stale'){h.update(s=>({...s,prompt:'changed'}));h.render();}return true;}});
    const before=h.state();assert.equal(await h.render().adoptDemo(),false,reason);
    assert.equal(h.state().design,before.design,reason);assert.equal(h.state().code,before.code,reason);
  }
});

test('adoption saves a backup and new conversation; never mutates the Demo result',async()=>{
  const result=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:1,result,state:'result_pending'}};
  const h=harness(async(path,body)=>({...record(),id:body.id,project_id:body.project_id}),{demo});
  const before=h.state();assert.equal(await h.render().adoptDemo(),true);
  assert.deepEqual(JSON.parse(h.persisted.get('boardvision.maker.v1.before-demo-adoption')),before);
  assert.equal(h.state().stage,'design');assert.equal(h.state().designView,'blueprint');
  assert.notEqual(h.state().design.id,result.id);assert.equal(result.id,'layout-fixture');
  assert.equal(h.render().demo.demo.result,result);
});

test('storage unavailable does not erase the active draft on a failed request',async()=>{
  const h=harness(async()=>{throw Error('offline');},{brokenStorage:true});
  await h.render().send();assert.equal(h.state().prompt,'original draft');assert.equal(h.render().storageError,true);
});

function chatComponents(locale) {
  const modules = {react:React, 'react/jsx-runtime':jsxRuntime,
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='en'?en:zh},
    '../lib/i18n':{useI18n:()=>({locale,tx:value=>typeof value==='string'?value:value[locale]})},
    '../lib/maker':maker, './ProjectConcept':{ProjectConcept:()=>null},
    '../lib/assistant':harness(()=>record()).exports,
    '../lib/assistantHistory':history, '../lib/assistantAnalysis':analysisHelpers,
    './MobileCompanion':{MobileCompanion:()=>null,MobileAttachmentCards:()=>null},
    '../lib/useChatScroll':{useChatScroll:()=>({chatRef:null,contentRef:null,unread:false})}};
  for (const name of ['AIModelControls','MakerModelMenu','AssistantAnalysisTime','UnifiedAssistant','AssistantWorkspace']) {
    const exports={};
    const compiled=ts.transpileModule(readFileSync(new URL(`../src/components/${name}.tsx`,import.meta.url),'utf8'),{
      compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
    }).outputText;
    new Function('require','exports',compiled)(key=>modules[key],exports);
    modules[`./${name}`]=exports;
  }
  return modules;
}

test('analysis feedback keeps one composer and disables desktop submission with a visible clock',()=>{
  const {UnifiedAssistant}=chatComponents('zh-TW')['./UnifiedAssistant'];
  const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
    state:{...maker.initialMaker(),stage:'guide'},setState(){},onNewProject(){},
    controller:{record:record(),draft:'保留草稿',demoOpen:false,busy:true,wiringAnalysis:{startedAt:Date.now()/1000-12}},
    legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
  }));
  assert.match(html,/分析中/);assert.match(html,/已用 0:12/);assert.match(html,/草稿會保留/);
  assert.match(html,/<button[^>]*class="[^"]*assistant-send[^"]*"[^>]*disabled/);
  assert.equal((html.match(/<textarea/g)||[]).length,1);assert.match(html,/保留草稿/);
});

test('AI design demo in the chat menu is offered only in stage 01',()=>{
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    for(const stage of ['design','guide','deploy']) {
      const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
        state:{...maker.initialMaker(),stage},setState(){},onNewProject(){},
        controller:{record:record(),draft:'',demoOpen:false,busy:false},
        legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
      }));
      assert.equal(html.includes(locale==='en'?'Try AI design demo':'體驗 AI 設計 Demo'),stage==='design');
    }
  }
});

test('desktop shows the paired phone message and reply across wiring rounds without exposing cleared context',()=>{
  const {mergeConversation}=harness(()=>record()).exports;
  const older={id:'phone-greeting',role:'user',text:'安安',source:'mobile',created_at:1,stage:'guide',capability:'answer',round:2,epoch:0};
  const reply={...older,id:'greeting-reply',role:'assistant',text:'安安！',created_at:2};
  const cleared={...older,id:'cleared',text:'CLEARED-CONTEXT',epoch:-1};
  const next=mergeConversation(null,{...record(),round:3,messages:[older,reply,cleared],total:3});
  const merged=mergeConversation(next,{...next});
  assert.equal(merged.messages[0].archived,true,'Existing round provenance remains intact');
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
      state:{...maker.initialMaker(),stage:'guide',guide:{run:3}},setState(){},onNewProject(){},
      controller:{record:merged,draft:'',demoOpen:false,mobileContext:{round:3},busy:false},
      legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
    }));
    assert.match(html,/安安/);assert.match(html,/安安！/);
    assert.doesNotMatch(html,/CLEARED-CONTEXT/);
    assert.match(html,locale==='en'?/Previous round; not evidence for this round/:/上一輪紀錄，不作為本輪證據/);
  }
});

test('shared history keeps server message identities while cleared history requires an explicit view',()=>{
  const value={context_epoch:1,round:3,messages:[
    {id:'old-round',epoch:1,round:2,stage:'guide',capability:'answer'},
    {id:'archived',epoch:1,round:3,archived:true},
    {id:'cleared',epoch:0,round:2,stage:'guide',capability:'answer'},
  ]};
  const before=structuredClone(value);
  assert.deepEqual(history.conversationMessages(value).map(m=>m.id),['old-round','archived']);
  assert.deepEqual(history.conversationMessages(value,true).map(m=>m.id),['old-round','archived','cleared']);
  assert.equal(history.conversationMessageNote(value.messages[0],value),'previous_round');
  assert.equal(history.conversationMessageNote(value.messages[2],value),'previous_context');
  assert.deepEqual(value,before,'Displaying history cannot rewrite its source context');
});

test('photo invitation actions belong only to the exact receipt even when a later same-text reminder is current',()=>{
  const text='Check this component with photos?';
  const message={role:'assistant',text,source:'legacy-debug',created_at:1,stage:'guide',capability:'answer',round:3,epoch:2};
  const messages=[
    {...message,id:'old-context',epoch:1},
    {...message,id:'old-round',round:2},
    {...message,id:'archived',archived:true},
    {...message,id:'ordinary',source:'mobile'},
    {...message,id:'user',role:'user'},
    {...message,id:'older-reminder'},
    {...message,id:'current-reminder'},
  ];
  const next={...record(),context_epoch:2,round:3,messages,total:messages.length};
  const before=structuredClone(next);
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
      state:{...maker.initialMaker(),stage:'guide',guide:{run:3}},setState(){},onNewProject(){},
      controller:{record:next,draft:'Keep my draft',demoOpen:false,mobileContext:{round:3},busy:false},
      legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
      testHelpFocus:'active-offer',testHelpText:text,testHelpMessageId:'older-reminder',
      onTestHelpActionTargetChange(){assert.fail('Rendering alone cannot dispatch an action');},
    }));
    const articles=[...html.matchAll(/<article[^>]*data-message-id="([^"]+)"[^>]*>([\s\S]*?)<\/article>/g)];
    assert.deepEqual(articles.filter(([, , body])=>body.includes('assistant-message-actions')).map(([,id])=>id),['older-reminder']);
    assert.match(html,/Keep my draft/);
    assert.doesNotMatch(html,/data-message-id="old-context"/);
  }
  assert.deepEqual(next,before,'Showing an action host cannot modify observations or history');
});

test('cleared, expired, mismatched, missing and Demo invitations leave conversation messages without action hosts',()=>{
  const text='Check this component with photos?';
  const next={...record(),context_epoch:2,round:3,messages:[
    {id:'reminder',role:'assistant',text,source:'legacy-debug',created_at:1,stage:'guide',round:3,epoch:2},
  ],total:1};
  const {UnifiedAssistant}=chatComponents('en')['./UnifiedAssistant'];
  const base={state:{...maker.initialMaker(),stage:'guide',guide:{run:3}},setState(){},onNewProject(){},
    controller:{record:next,draft:'Keep my draft',demoOpen:false,mobileContext:{round:3},busy:false},
    legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
    testHelpFocus:'active-offer',testHelpText:text,testHelpMessageId:'reminder',onTestHelpActionTargetChange(){assert.fail('No action should run');},
  };
  const variants=[
    {...base,testHelpFocus:undefined},
    {...base,testHelpMessageId:undefined},
    {...base,testHelpMessageId:'missing-receipt'},
    {...base,testHelpText:'Different issue'},
    {...base,onTestHelpActionTargetChange:undefined},
    {...base,controller:{...base.controller,demoOpen:true}},
    {...base,controller:{...base.controller,record:{...next,context_epoch:3}}},
    {...base,controller:{...base.controller,mobileContext:{round:4}}},
    {...base,controller:{...base.controller,record:null}},
  ];
  for(const props of variants) {
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,props));
    assert.doesNotMatch(html,/assistant-message-actions/);
    assert.match(html,/Keep my draft/);
  }
});

test('model and reasoning controls live inside the single composer across stages, locales and Demo',()=>{
  const model={id:'fake-model',name:'Fixture model',efforts:['low','high'],default_effort:'low',excluded_efforts:[]};
  for(const locale of ['en','zh-TW']) for(const stage of ['design','guide','deploy']) for(const demoOpen of [false,true]) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const state={...maker.initialMaker(),stage,aiModel:model.id};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{state,setState(){},onNewProject(){},
      controller:{record:record(),draft:'keep my draft',demoOpen,busy:false},
      legacy:{ai:{logged_in:true},busy:false,aiOptions:{options:{models:[model]},selectedModel:model,selectionValid:true}}}));
    assert.equal((html.match(/class="maker-model-menu is-compact"/g)||[]).length,1);
    assert.match(html,/class="assistant-input"[\s\S]*<\/textarea><div class="assistant-input-actions"><details class="maker-model-menu is-compact"[\s\S]*<\/details><button type="submit"/);
    assert.match(html,/<summary title="[^"]*Fixture model" aria-label="[^"]*Fixture model"><svg[^>]*aria-hidden="true"/);
    assert.doesNotMatch(html,/unified-composer-footer|class="maker-model-value"/);
    assert.match(html,/Fixture model/);
    assert.match(html,locale==='en'?/Reasoning effort/:/推理強度/);
    assert.match(html,/keep my draft/);
  }
});

test('compact model trigger keeps a descriptive sign-in name and leaves standalone menus unchanged',()=>{
  const {MakerModelMenu}=chatComponents('en')['./MakerModelMenu'];
  const props={state:maker.initialMaker(),setState(){},assistant:{ai:{logged_in:false},aiOptions:{},busy:false}};
  const compact=renderToStaticMarkup(React.createElement(MakerModelMenu,{...props,compact:true}));
  assert.match(compact,/aria-label="Choose AI model and reasoning effort · Select model \/ sign in"/);
  const regular=renderToStaticMarkup(React.createElement(MakerModelMenu,props));
  assert.match(regular,/class="maker-model-value"/);
  assert.doesNotMatch(regular,/maker-model-brain/);
});

test('wiring quick questions use one disclosure; other stages retain inline suggestions',()=>{
  for(const locale of ['en','zh-TW']) for(const stage of ['design','guide','deploy']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const state={...maker.initialMaker(),design:designFor(),stage};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{state,setState(){},onNewProject(){},
      controller:{record:record(),draft:'keep my draft',demoOpen:false,busy:false},
      legacy:{ai:{logged_in:true},busy:false,aiOptions:{selectionValid:true}}}));
    if(stage==='guide') {
      assert.match(html,/<details class="assistant-suggestions"><summary>/);
      assert.doesNotMatch(html,/class="assistant-quick"/);
      assert.match(html,/class="assistant-wire-context"/);
    } else {
      assert.match(html,/class="assistant-quick"/);
      assert.doesNotMatch(html,/class="assistant-suggestions"/);
    }
    assert.match(html,/keep my draft/);
  }
});

test('orb toggle exposes its action and unread state without conditionally unmounting either pane',()=>{
  const previousWindow=globalThis.window;
  globalThis.window={matchMedia:()=>({matches:false})};
  try {
    for(const locale of ['en','zh-TW']) for(const aiOpen of [true,false]) {
      const {AssistantWorkspace}=chatComponents(locale)['./AssistantWorkspace'];
      const html=renderToStaticMarkup(React.createElement(AssistantWorkspace,{aiOpen,onAiOpen(){},latestReply:'new-reply',
        children:React.createElement('div',{id:'camera-kept'}),assistant:React.createElement('textarea',{defaultValue:'draft kept'})}));
      assert.match(html,new RegExp(`aria-expanded="${aiOpen}"`));
      assert.match(html,/aria-controls="assistant-chat-content"/);
      assert.match(html,/id="assistant-chat-content"/);
      assert.match(html,/class="assistant-orb" aria-hidden="true"/);
      assert.match(html,/class="assistant-orb-core"/);
      assert.match(html,/class="assistant-orb-chevron"/);
      assert.match(html,/id="camera-kept"/);
      assert.match(html,/>draft kept<\/textarea>/);
      const label=aiOpen ? (locale==='en'?'Collapse AI conversation':'收合 AI 對話')
        : (locale==='en'?'Open AI conversation, new reply':'展開 AI 對話，有新回覆');
      assert.ok(html.includes(`aria-label="${label}"`));
      assert.equal(html.includes('assistant-orb-unread'),!aiOpen);
    }
  } finally { globalThis.window=previousWindow; }
});

test('redesigned send icon preserves its accessible name, busy indicator and every disable guard',()=>{
  const {UnifiedAssistant}=chatComponents('en')['./UnifiedAssistant'];
  const base={state:maker.initialMaker(),setState(){},onNewProject(){},
    controller:{record:record(),draft:'keep my draft',demoOpen:false,busy:false},
    legacy:{ai:{logged_in:true},busy:false,aiOptions:{selectionValid:true}}};
  for(const scenario of ['ready','busy','legacyBusy','noRecord','empty','noParts','signedOut','invalidModel']) {
    const props={...base,state:{...base.state},controller:{...base.controller},legacy:{...base.legacy}};
    if(scenario==='busy')props.controller.busy=true;
    if(scenario==='legacyBusy')props.legacy.busy=true;
    if(scenario==='noRecord')props.controller.record=null;
    if(scenario==='empty')props.controller.draft='  ';
    if(scenario==='noParts')props.state.selected=[];
    if(scenario==='signedOut')props.legacy.ai={logged_in:false};
    if(scenario==='invalidModel')props.legacy.aiOptions={selectionValid:false};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,props));
    const button=html.match(/<button type="submit" class="assistant-send"[\s\S]*?<\/button>/)[0];
    assert.equal(button.includes('disabled=""'),scenario!=='ready');
    assert.match(button,/<span class="sr-only">Send<\/span>/);
    assert.equal(button.includes('assistant-send-pending'),scenario==='busy');
    if(scenario==='ready')assert.match(button,/<svg[^>]*aria-hidden="true"/);
  }
});

test('text follow-up visibly references only inherited media from the current context and wiring round',()=>{
  const active={asset_ids:['new-asset'],capture_id:'new-capture',epoch:2,round:3,
    attachments:[{asset_id:'old-asset',filename:'old-photo.jpg',image_url:'/old'},
      {asset_id:'new-asset',filename:'latest-photo.jpg',image_url:'/new'}]};
  const base={...record(),context_epoch:2,round:3,active_media:active};
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const render=(next=base,round=3,demoOpen=false)=>renderToStaticMarkup(React.createElement(UnifiedAssistant,{
      state:{...maker.initialMaker(),guide:{run:round}},setState(){},onNewProject(){},
      controller:{record:next,draft:'What about this wire?',demoOpen,mobileContext:{round},busy:false},
      legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
    }));
    const html=render();assert.match(html,/latest-photo.jpg/);assert.doesNotMatch(html,/old-photo.jpg/);
    assert.match(html,locale==='en'?/This message references: /:/此訊息引用：/);
    assert.ok(html.indexOf('assistant-media-reference')<html.indexOf('id="unified-prompt"'));
    assert.match(render({...base,round:1}),/latest-photo.jpg/,'Fresh photo can replace media before record round reconciles');
    for(const hidden of [render({...base,context_epoch:4}),render(base,4),render(base,3,true),render({...base,active_media:null}),render({...base,active_media:{...active,asset_ids:[]}})])
      assert.doesNotMatch(hidden,/assistant-media-reference/);
    const fresh=render({...base,active_media:{...active,asset_ids:['fresh'],capture_id:'fresh-capture',attachments:[{asset_id:'fresh',filename:'newly-captured.jpg',image_url:'/fresh'}]}});
    assert.match(fresh,/newly-captured.jpg/);assert.doesNotMatch(fresh,/latest-photo.jpg/);
  }
});

test('moving model controls keeps original model selection and compatible effort without changing project or draft',()=>{
  const {AIModelControls}=chatComponents('en')['./AIModelControls'];
  const model={id:'different-model',efforts:['medium','high'],default_effort:'medium',excluded_efforts:[]};
  let state={...maker.initialMaker(),aiModel:'old',aiEffort:'low',prompt:'keep draft',design:designFor()};
  const before=state;
  const tree=AIModelControls({state,setState:next=>{state=next(state);},busy:false,
    ai:{options:{models:[model]},selectedModel:model,selectionValid:true}});
  const selects=[];
  function visit(node){if(!React.isValidElement(node))return;if(node.type==='select')selects.push(node);React.Children.forEach(node.props.children,visit);}
  visit(tree);
  selects[0].props.onChange({target:{value:model.id}});
  assert.equal(state.aiModel,model.id);assert.equal(state.aiEffort,'medium');
  assert.equal(state.prompt,before.prompt);assert.equal(state.design,before.design);
});
