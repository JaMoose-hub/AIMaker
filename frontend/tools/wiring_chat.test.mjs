import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers} from './wiring_photo_flow_fixture.mjs';

// Synthetic receipts only: no server, photograph capture, model or hardware.
const helpers = flowModule('../src/lib/wiringChat.ts', {'./wiringReview': reviewHelpers});
const analysisHelpers = flowModule('../src/lib/assistantAnalysis.ts', {});
const analysisComponent = flowModule('../src/components/AssistantAnalysisTime.tsx', {react:React,
  '../lib/useMaker':{useMakerText:()=> (_zh,en)=>en},'../lib/assistantAnalysis':analysisHelpers});
const flow = (extra = {}) => ({flow_id:'flow',review_id:'review',revision:4,round:1,component_id:'hc-sr04',
  kind:'photo_request',role:'pi_side_a',current:true,can_act:true,actions:['capture'],...extra});
const message = (extra = {}) => ({id:'question',role:'assistant',text:'Please photograph the first Pi side.',
  source:'legacy-debug',created_at:1,stage:'guide',capability:'debug',epoch:0,round:1,wiring_flow:flow(),...extra});
const slot = {role:'pi_side_a',capture_id:'capture-a',image_url:'/fake-photo.svg',sha256:'a'.repeat(64),
  size:[800,600],crop:null,crop_source:'none',available:true};
const review = (extra = {}) => ({id:'review',revision:4,round:1,component_id:'hc-sr04',status:'collecting',
  slots:{pi_side_a:slot,pi_side_b:null,component_header:null},observations:[],results:[],reviews:{},
  missing_roles:[],no_progress_count:0,...extra});
function harness() {
  let index=0,ref=0;const values=[],refs=[];
  const hooks={...React,useEffect(){},useLayoutEffect(){},useCallback:fn=>fn,
    useRef:initial=>refs[ref++]??={current:initial},useState(initial){const i=index++;
      if(!(i in values))values[i]=typeof initial==='function'?initial():initial;
      return[values[i],next=>values[i]=typeof next==='function'?next(values[i]):next];}};
  const mod=flowModule('../src/components/WiringChatMessage.tsx',{react:hooks,'../lib/useMaker':{useMakerText:()=> (_zh,en)=>en},
    '../lib/wiringChat':helpers,'../lib/wiringReview':reviewHelpers,'./AssistantAnalysisTime':analysisComponent,'./wiringChat.css':{}});
  return{mod,hooks,values,render(props){index=0;ref=0;return mod.WiringChatMessage(props);}};
}
function elements(tree,type) { const out=[]; const visit=node=>{if(!node||typeof node!=='object')return;
  if(Array.isArray(node)){node.forEach(visit);return;}if(node.type===type)out.push(node);visit(node.props?.children);};visit(tree);return out; }
const deferred=()=>{let resolve;const promise=new Promise(y=>resolve=y);return{promise,resolve};};

test('analysis feedback messages retain completed duration without restarting historical clocks',()=>{
  const h=harness();
  const complete=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({kind:'analysing',current:false,
    started_at:1,elapsed_ms:65999})}),inactive:true}));
  assert.match(complete,/Analysis time/);assert.match(complete,/1:05/);assert.doesNotMatch(complete,/Analysing|Elapsed/);
  const unknown=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({kind:'analysing',current:false,started_at:1})}),inactive:true}));
  assert.doesNotMatch(unknown,/Analysing|Elapsed|Analysis time/);
});

test('current photo questions show the framing image immediately while historical guidance stays collapsed',()=>{
  const h=harness();
  for(const role of ['pi_side_a','pi_side_b','component_header']) {
    const current=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role})})}));
    assert.match(current,/<details class="wiring-chat-framing" open="">/);
    assert.match(current,/<svg class="wiring-chat-framing-image"[^>]*role="img"/);
    assert.match(current,/This is not a GPIO pin map/);
    const history=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role,current:false,can_act:false})})}));
    assert.doesNotMatch(history,/<details class="wiring-chat-framing" open=/);
    const inactive=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role})}),inactive:true}));
    assert.doesNotMatch(inactive,/<details class="wiring-chat-framing" open=/);
  }
});

test('colored human decisions retain explicit labels and only one user action confirms the matching wire',async()=>{
  const result={wire_id:'echo',expected:{physical_pin:18,bcm:24,component_pin:'Echo'},comparison:'unknown',next_step:'Trace the wire.',
    pi_candidates:[],component_candidates:[]};
  const h=harness(),calls=[];
  const props={message:message({wiring_flow:flow({kind:'wire_review',wire_id:'echo',result,actions:['review']})}),
    onAction:async(_m,a)=>{calls.push(a);return true;}};
  const buttons=elements(h.render(props),'button');
  assert.deepEqual(buttons.map(button=>button.props.className),['wiring-chat-decision is-confirmed','wiring-chat-decision is-needs-change','wiring-chat-decision is-unsure']);
  assert.deepEqual(buttons.map(button=>button.props.children),['Correct','Incorrect','Unsure']);
  assert.ok(buttons.every(button=>button.props['aria-label'])); assert.deepEqual(calls,[]);
  assert.ok(elements(h.render({...props,busy:true}),'button').every(button=>button.props.disabled));
  h.render(props); buttons[2].props.onClick(); await Promise.resolve(); await Promise.resolve();
  assert.equal(calls.length,1); assert.equal(calls[0].decision,'unsure'); assert.equal(calls[0].wire_id,'echo');
});

test('only a current authoritative receipt exposes its permitted stage actions',()=>{
  assert.equal(helpers.wiringFlowCanAct(flow(),'capture'),true);
  for(const extra of [{current:false},{can_act:false},{revision:-1},{round:NaN},{review_id:''},
    {kind:'photo',actions:['capture']},{kind:'analysing',actions:['analyse']},{kind:'__proto__'},{actions:null}]) {
    assert.equal(helpers.wiringFlowCanAct(flow(extra),'capture'),false,JSON.stringify(extra));
  }
  assert.equal(helpers.wiringFlowCanAct(flow({kind:'complete',actions:['changed']}),'review'),false);
  assert.equal(helpers.wiringFlowCanAct(flow({kind:'wire_review',actions:['review']}),'review'),true);
});

test('explicit capture, crop and manual decisions bind exact refs and reject mismatched targets',()=>{
  assert.deepEqual(helpers.boundWiringChatAction(flow(),{op:'capture',role:'pi_side_a',revision:999}),
    {op:'capture',role:'pi_side_a',review_id:'review',revision:4,component_id:'hc-sr04'});
  assert.equal(helpers.boundWiringChatAction(flow(),{op:'capture',role:'pi_side_b'}),null);
  assert.equal(helpers.boundWiringChatAction(flow(),{op:'analyse'}),null);
  const editing=flow({kind:'analysis_request',actions:['crop']});
  assert.equal(helpers.boundWiringChatAction(editing,{op:'crop',role:'pi_side_a',capture_id:'a',crop:[.8,0,.2,1]}),null);
  assert.equal(helpers.boundWiringChatAction(editing,{op:'crop',role:'pi_side_a',capture_id:'a',crop:null}).revision,4);
  const checking=flow({kind:'wire_review',wire_id:'echo',actions:['review']});
  assert.equal(helpers.boundWiringChatAction(checking,{op:'review',wire_id:'other',decision:'confirmed'}),null);
  assert.equal(helpers.boundWiringChatAction(checking,{op:'review',wire_id:'echo',decision:'unsure'}).decision,'unsure');
});

test('photo evidence and crop controls require the same review, revision, component and round',()=>{
  assert.equal(helpers.wiringFlowReview(flow(),review())?.slots.pi_side_a.capture_id,'capture-a');
  for(const extra of [{id:'old-review'},{revision:3},{round:2},{component_id:'tft'},{status:'stale'}])
    assert.equal(helpers.wiringFlowReview(flow(),review(extra)),null);
  const h=harness(),m=message({wiring_flow:flow({kind:'analysis_request',actions:['crop','analyse']})});
  const markup=renderToStaticMarkup(h.render({message:m,review:review({revision:3}),onAction:async()=>true}));
  assert.doesNotMatch(markup,/fake-photo|Original photo for cropping/);
  assert.match(markup,/Start review/);
});

test('unknown pins and multiple color candidates remain advisory and require explicit manual decisions',()=>{
  const result={wire_id:'echo',expected:{physical_pin:18,bcm:24,component_pin:'Echo'},comparison:'ambiguous',next_step:'Trace the blue wire.',
    pi_candidates:[{id:'A',capture_id:'a',physical_pin:null,pin_label:null,color:'blue',evidence:'Partly hidden.'},
      {id:'B',capture_id:'b',physical_pin:null,pin_label:null,color:'blue',evidence:'Another connector.'}],component_candidates:[]};
  const h=harness(),calls=[],tree=h.render({message:message({wiring_flow:flow({kind:'wire_review',wire_id:'echo',result,actions:['review']})}),
    onAction:async(_m,a)=>{calls.push(a);return true;}});
  const markup=renderToStaticMarkup(tree);
  assert.match(markup,/Several color candidates/);assert.match(markup,/Connector A（pin unconfirmed）/);assert.match(markup,/Connector B（pin unconfirmed）/);
  assert.match(markup,/does not mean unplugged/);assert.equal(elements(tree,'button').length,3);assert.deepEqual(calls,[]);
  assert.equal(markup.indexOf('Several color candidates')<markup.indexOf('Pi observation'),true);
  assert.match(markup,/aria-label="I personally confirmed this connection"/);assert.match(markup,/>Correct<\/button>/);
  assert.doesNotMatch(markup,/wires_json|same_wire|electrically correct/);
});

test('render does not capture; explicit capture runs once and stale callbacks cannot target a newer message',async()=>{
  const h=harness(),calls=[],wait=deferred();let props={message:message(),onAction:async(m,a)=>{calls.push({m,a});return wait.promise;}};
  const tree=h.render(props),button=elements(tree,'button')[0];assert.deepEqual(calls,[]);
  button.props.onClick();button.props.onClick();assert.equal(calls.length,1);
  assert.equal(calls[0].a.role,'pi_side_a');assert.equal(calls[0].a.revision,4);
  assert.equal(elements(h.render(props),'button')[0].props.disabled,true);
  wait.resolve(true);await wait.promise;await Promise.resolve();
  h.render({...props,message:message({id:'new-question',wiring_flow:flow({revision:5,role:'pi_side_b'})})});
  button.props.onClick();assert.equal(calls.length,1,'Old question cannot operate the new photo request');
});

test('analysis is explicit, false responses remain retryable and no rendering confirms wiring',async()=>{
  const h=harness(),calls=[];const props={message:message({wiring_flow:flow({kind:'analysis_request',actions:['analyse']})}),
    onAction:async(_m,a)=>{calls.push(a);return false;}};
  const tree=h.render(props);assert.deepEqual(calls,[]);elements(tree,'button')[0].props.onClick();
  await Promise.resolve();await Promise.resolve();assert.equal(calls.length,1);assert.equal(calls[0].op,'analyse');
  const after=h.render(props);assert.match(renderToStaticMarkup(after),/Action did not complete/);
  assert.equal(elements(after,'button')[0].props.disabled,false);assert.doesNotMatch(JSON.stringify(calls),/confirmed|hardware|retest/);
});

test('history photo viewing and unavailable images never grant a physical confirmation or retry action',()=>{
  const h=harness(),calls=[];const tree=h.render({message:message({role:'user',session_id:'session / a',wiring_flow:flow({kind:'photo',
    current:false,can_act:false,actions:[],capture_id:'capture / a'})}),onAction:async(_m,a)=>{calls.push(a);return true;}});
  const markup=renderToStaticMarkup(tree);assert.match(markup,/session%20%2F%20a\/evidence\/capture%20%2F%20a/);
  assert.match(markup,/View original wiring photo/);assert.equal(elements(tree,'button').length,0);assert.deepEqual(calls,[]);
});

test('the unified assistant keeps photo guidance in ordinary messages, one composer, and the invitation host',()=>{
  const h=harness();const m=message();const ordinary={...message({id:'normal'}),text:'Why is GPIO input high?',wiring_flow:undefined};
  const invite={...message({id:'invite'}),text:'Check wiring with photos?',wiring_flow:undefined};
  const compiled=flowModule('../src/components/UnifiedAssistant.tsx',{react:h.hooks,
    '../lib/useChatScroll':{useChatScroll:()=>({chatRef:null,contentRef:null,onScroll(){},followNext(){},showMessage(){},showLatest(){},unread:0})},
    '../lib/useMaker':{useMakerText:()=> (_zh,en)=>en},'../lib/i18n':{useI18n:()=>({locale:'en',tx:v=>v})},
    '../lib/maker':{currentWire:()=>null,fillStarterPrompt:s=>s,makerCatalog:{modules:[]}},'../lib/assistant':{currentAssistantMedia:()=>null},
    '../lib/assistantHistory':{conversationMessages:r=>r.messages,conversationMessageNote:()=>null},
    './ProjectConcept':{ProjectConcept:()=>null},'./MakerModelMenu':{MakerModelMenu:()=>null},
    './MobileCompanion':{MobileCompanion:()=>null,MobileAttachmentCards:()=>null},'./WiringChatMessage':h.mod,
    './AssistantAnalysisTime':analysisComponent});
  const calls=[];const controller={record:{id:'chat',context_epoch:0,before:null,messages:[ordinary,invite,m],jobs:[]},
    mobileContext:{round:1},draft:'',busy:false,demoOpen:false};
  const markup=renderToStaticMarkup(React.createElement(compiled.UnifiedAssistant,{state:{stage:'guide',guide:{run:1},selected:['hc-sr04']},
    setState(){},controller,legacy:{busy:false,ai:{logged_in:true},aiOptions:{selectionValid:true}},onNewProject:async()=>false,
    testHelpFocus:'offer',testHelpText:invite.text,testHelpMessageId:'invite',onTestHelpActionTargetChange(){},
    onWiringFlowAction:async(_m,a)=>{calls.push(a);return true;}}));
  assert.match(markup,/Why is GPIO input high\?/);assert.match(markup,/data-message-id="question"/);
  assert.match(markup,/data-wiring-flow="photo_request"/);assert.match(markup,/assistant-message-actions/);
  assert.equal((markup.match(/<textarea/g)||[]).length,1);assert.equal((markup.match(/role="log"/g)||[]).length,1);
  assert.doesNotMatch(markup,/wiring-review-card|wr-photo-dialogue|photo-sequence/);assert.deepEqual(calls,[]);
});
