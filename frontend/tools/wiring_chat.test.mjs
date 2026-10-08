import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers, expectedLocationHelpers, expectedLocationComponent} from './wiring_photo_flow_fixture.mjs';

// Synthetic receipts only: no server, photograph capture, model or hardware.
const helpers = flowModule('../src/lib/wiringChat.ts', {'./wiringReview': reviewHelpers});
const photoStatusHelpers = flowModule('../src/lib/wiringPhotoStatus.ts', {'./wiringReview': reviewHelpers});
const framingComponent = flowModule('../src/components/WiringFramingGuide.tsx', {
  '../lib/useMaker': {useMakerText: () => (_zh, en) => en}, '../lib/wiringReview': reviewHelpers});
const entryComponent = flowModule('../src/components/WiringAnalysisEntry.tsx', {react: React,
  '../lib/useMaker': {useMakerText: () => (_zh, en) => en}, '../lib/wiringChat': helpers});
const analysisHelpers = flowModule('../src/lib/assistantAnalysis.ts', {});
const progressHelpers = flowModule('../src/lib/assistantProgress.ts', {});
const progressComponent = flowModule('../src/components/AssistantJobProgress.tsx', {react:React,
  '../lib/useMaker':{useMakerText:()=> (_zh,en)=>en},'./assistantJobProgress.css':{}});
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
    '../lib/wiringChat':helpers,'../lib/wiringReview':reviewHelpers,'../lib/wiringPhotoStatus':photoStatusHelpers,
    '../lib/wiringExpectedLocation':expectedLocationHelpers,'./WiringExpectedLocation':expectedLocationComponent(),
    './AssistantAnalysisTime':analysisComponent,'./WiringFramingGuide':framingComponent,'./wiringChat.css':{}});
  return{mod,hooks,values,render(props){index=0;ref=0;return mod.WiringChatMessage(props);}};
}
function elements(tree,type) { const out=[]; const visit=node=>{if(!node||typeof node!=='object')return;
  if(Array.isArray(node)){node.forEach(visit);return;}if(node.type===type)out.push(node);visit(node.props?.children);};visit(tree);return out; }
const deferred=()=>{let resolve;const promise=new Promise(y=>resolve=y);return{promise,resolve};};

function deliveredReview() {
  const roles=['pi_side_a','pi_side_b','component_header'];
  const slots=Object.fromEntries(roles.map(role=>[role,{...slot,role,capture_id:`photo-${role}`,sha256:`sha-${role}`,size:[4000,3000],
    crop:role==='pi_side_b'?[.2381,.2198,.8137,.8164]:null,
    photo_acceptance:{source:'human',capture_id:`photo-${role}`,sha256:`sha-${role}`,round:1}}]));
  const input=(view,crop,size)=>({role:'pi_side_b',view,crop,size,capture_id:slots.pi_side_b.capture_id,
    source_sha256:slots.pi_side_b.sha256,source_size:[4000,3000],supplied_sha256:`sent-${view}`});
  return review({status:'ready',analysis_revision:3,slots,model_receipt:{review_id:'review',wiring_round:1,
    capture_ids:roles.map(role=>slots[role].capture_id),capture_hashes:roles.map(role=>slots[role].sha256),
    reused_roles:['pi_side_a','component_header'],image_inputs:[input('overview',null,[2048,1536]),input('detail',[952,659,3255,2450],[2048,1593])]}});
}

test('row-plan capture requests show the right row and framing immediately without taking a photo', async () => {
  const h=harness(),calls=[];
  for (const [role,row,direction] of [['pi_side_a','inner','board centre'],['pi_side_b','outer','board edge']]) {
    const m=message({wiring_flow:flow({role,capture_plan:'pi_rows_v1',target_row:row})});
    const props={message:m,review:review({capture_plan:'pi_rows_v1'}),onAction:async(_m,action)=>{calls.push(action);return true;}};
    const tree=h.render(props),html=renderToStaticMarkup(tree);
    assert.match(html,new RegExp(`Capture Pi ${row} row`));
    assert.match(html,new RegExp(direction));
    assert.match(html,/class="wiring-chat-row-framing"/);
    assert.match(html,new RegExp(`highlight the ${row} row`));
    assert.ok(html.indexOf('<svg') < html.indexOf('<details'), 'The row diagram must be visible before optional tips');
    assert.equal(calls.length,role==='pi_side_a'?0:1);
    await elements(tree,'button').find(button=>button.props.children===`Capture Pi ${row} row`).props.onClick();
    assert.equal(calls.at(-1).role,role); assert.equal(calls.at(-1).op,'capture');
  }
  assert.equal(calls.length,2);
});

test('legacy side photos keep original labels and mismatched capture plans never borrow a review',()=>{
  const h=harness(),m=message(),r=review({capture_plan:'pi_rows_v1'});
  assert.equal(helpers.wiringFlowReview(m.wiring_flow,r),null);
  const html=renderToStaticMarkup(h.render({message:m,review:r,onAction:async()=>true}));
  assert.match(html,/Capture Pi first side/);
  assert.doesNotMatch(html,/Capture Pi inner row|wiring-chat-row-framing/);
  const historical=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({capture_plan:'pi_rows_v1',current:false})}),review:r}));
  assert.match(historical,/wiring-chat-history/);
  assert.doesNotMatch(historical,/wiring-chat-row-framing|<button/);
});

test('row-plan receipts label selected Pi photos while preserving the exact submitted crop and reused views',()=>{
  const h=harness(),r=deliveredReview();r.capture_plan='pi_rows_v1';r.model_receipt.capture_plan='pi_rows_v1';
  r.slots.pi_side_a.target_row='inner';r.slots.pi_side_b.target_row='outer';
  r.model_receipt.image_inputs.forEach(image=>{image.requested_row='outer';});
  const html=renderToStaticMarkup(React.createElement(h.mod.WiringPhotoDelivery,{review:r}));
  assert.match(html,/Pi inner row/);assert.match(html,/Pi outer row/);assert.match(html,/Module header/);
  assert.match(html,/AI analysed this crop · 2048 × 1593/);
  assert.equal((html.match(/Previous analysis reused/g)||[]).length,2);
  assert.doesNotMatch(html,/Pi first side|Pi other side/);
});

test('photo delivery UI shows verified cloud overview and crop sizes while reused views stay distinct',()=>{
  const h=harness(),r=deliveredReview(),before=structuredClone(r);
  const html=renderToStaticMarkup(React.createElement(h.mod.WiringPhotoDelivery,{review:r}));
  assert.match(html,/All 3 photos ready · AI analysis completed/);
  assert.match(html,/AI analysed this crop · 2048 × 1593/);
  assert.match(html,/Overview.*2048.*1536/);assert.match(html,/Selected crop.*2048.*1593/);
  assert.equal((html.match(/Previous analysis reused \(not resent this time\)/g)||[]).length,2);
  assert.match(html,/Ordinary text chat does not automatically resend images/);
  assert.doesNotMatch(html,/<button/);assert.deepEqual(r,before);
});

test('photo delivery UI says saved crop awaits analysis even when an older completed receipt remains',()=>{
  const h=harness(),r=deliveredReview();r.status='collecting';r.analysis_revision=null;r.slots.pi_side_b.crop=[.2,.2,.7,.7];
  const html=renderToStaticMarkup(React.createElement(h.mod.WiringPhotoDelivery,{review:r}));
  assert.match(html,/All 3 photos ready · awaiting analysis/);
  assert.match(html,/Crop saved; waiting to start analysis/);
  assert.doesNotMatch(html,/AI analysed this crop|AI analysis completed|Photo missing/);
});

test('historical and mismatched message receipts never borrow current photo delivery status',()=>{
  const h=harness(),r=deliveredReview();
  const row={wire_id:'gnd',expected:{component_pin:'GND',physical_pin:6},comparison:'unknown',next_step:'Trace both ends.',
    pi_candidates:[],component_candidates:[],diagnosis:{status:'uncertain',retake_roles:[]}};
  const m=message({wiring_flow:flow({kind:'wire_review',result:row,wire_id:'gnd',actions:[],can_act:false})});
  const current=renderToStaticMarkup(h.render({message:m,review:r}));
  assert.match(current,/AI analysed this crop/);
  for(const [message,review,inactive] of [[{...m,wiring_flow:{...m.wiring_flow,current:false}},r,false],
    [m,r,true],[m,{...r,revision:5},false]]) {
    const html=renderToStaticMarkup(h.render({message,review,inactive}));
    assert.doesNotMatch(html,/AI analysed this crop|Which images reached AI|AI analysis completed/);
  }
});

test('short pin finding keeps detailed BCM collapsed and photo positions never submit decisions',()=>{
  const h=harness(),calls=[];
  const observed={id:'pi_side_a:actual',capture_id:slot.capture_id,role:'pi_side_a',pin_id:'GPIO18',physical_pin:12,pin_label:'GPIO18',box:[.4,.3,.5,.6]};
  const expected={...observed,id:'pi_side_a:expected',pin_id:'GPIO17',physical_pin:11,box:[.2,.3,.3,.6]};
  const result={wire_id:'trig',expected:{board_pin:'GPIO17',physical_pin:11,bcm:17,component_pin:'TRIG'},comparison:'similar',next_step:'Trace the wire.',
    pi_candidates:[],component_candidates:[],diagnosis:{status:'suspected',observed_component_pin:'TRIG',observed_physical_pin:12,
      board_connector_id:observed.id,component_connector_id:'component_header:trig',retake_roles:[]}};
  const props={message:message({wiring_flow:flow({kind:'wire_review',wire_id:'trig',result,actions:['review']})}),
    review:review({status:'ready',observations:[observed,expected]}),onAction:async()=>{calls.push('action');return true;}};
  let tree=h.render(props);
  const html=renderToStaticMarkup(tree);
  assert.match(html,/Possible wrong pin/);assert.match(html,/Photo suggests: TRIG.*Pi Pin 12/);
  assert.match(html,/<details><summary>View pin and color evidence<\/summary><small>BCM 17<\/small>/);
  const button=elements(tree,'button').find(node=>node.props.children==='View position in photo');
  button.props.onClick(); tree=h.render(props);
  assert.equal(elements(tree,'rect').length,2);
  assert.deepEqual(elements(tree,'text').map(node=>node.props.children),['Pin 12','Pin 11']);
  elements(tree,'img')[0].props.onError(); tree=h.render(props);
  assert.equal(elements(tree,'rect').length,0);
  assert.match(renderToStaticMarkup(tree),/Photo unavailable/);
  assert.deepEqual(calls,[]);
});

test('module label identity remains visible in chat when contact is hidden and never identifies a Pi pin',()=>{
  const h=harness();
  const candidate={id:'component_header:echo',role:'component_header',capture_id:'module-photo',pin_id:null,
    physical_pin:null,pin_label:null,module_pin_id:'ECHO',module_pin_evidence:'ECHO label aligns with the third housing.',
    color:'blue',color_visibility:'clear',contact:'uncertain',evidence:'Insertion point hidden behind the board.'};
  const result={wire_id:'echo',expected:{component_pin:'ECHO',physical_pin:12},comparison:'unknown',next_step:'Check plug contact.',
    pi_candidates:[],component_candidates:[candidate],diagnosis:{status:'uncertain',retake_roles:[]}};
  const renderResult=row=>renderToStaticMarkup(h.render({message:message({wiring_flow:flow({kind:'wire_review',result:row,
    wire_id:'echo',actions:[],can_act:false})}),review:review({status:'ready'})}));
  const before=structuredClone(candidate),html=renderResult(result);
  assert.match(html,/ECHO.*blue/);assert.match(html,/Label position identified; plug contact unconfirmed/);
  assert.match(html,/ECHO label aligns with the third housing/);
  assert.doesNotMatch(html,/pin unconfirmed|connected correctly|aria-pressed="true"/);
  const withPi=renderResult({...result,pi_candidates:[{...candidate,id:'pi-side',role:'pi_side_a',
    module_pin_id:'MUST_NOT_IDENTIFY_PI',module_pin_evidence:'MUST_NOT_EXPLAIN_PI'}]});
  assert.doesNotMatch(withPi,/MUST_NOT_IDENTIFY_PI|MUST_NOT_EXPLAIN_PI/);
  assert.match(withPi,/pin unconfirmed/);assert.deepEqual(candidate,before);
});

test('unlocated expected pin and stale photo revision cannot fabricate a position marker',()=>{
  const h=harness();
  const observed={id:'pi_side_a:actual',capture_id:slot.capture_id,pin_id:'GPIO18',physical_pin:12,box:[.4,.3,.5,.6]};
  const result={wire_id:'trig',expected:{board_pin:'GPIO17',physical_pin:11,bcm:17,component_pin:'TRIG'},comparison:'unknown',next_step:'Trace.',
    pi_candidates:[],component_candidates:[],diagnosis:{status:'suspected',observed_component_pin:'TRIG',observed_physical_pin:12,
      board_connector_id:observed.id,retake_roles:[]}};
  const props={message:message({wiring_flow:flow({kind:'wire_review',wire_id:'trig',result,actions:['review']})}),review:review({observations:[observed]})};
  elements(h.render(props),'button').find(node=>node.props.children==='View position in photo').props.onClick();
  assert.equal(elements(h.render(props),'rect').length,1);
  const changed=h.render({...props,review:{...props.review,revision:5}});
  assert.equal(elements(changed,'rect').length,0);
  assert.ok(!elements(changed,'button').some(node=>node.props.children==='View position in photo'));
});

test('analysis feedback messages retain completed duration without restarting historical clocks',()=>{
  const h=harness();
  const complete=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({kind:'analysing',current:false,
    started_at:1,elapsed_ms:65999})}),inactive:true}));
  assert.match(complete,/Analysis time/);assert.match(complete,/1:05/);assert.doesNotMatch(complete,/Analysing|Elapsed/);
  const unknown=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({kind:'analysing',current:false,started_at:1})}),inactive:true}));
  assert.doesNotMatch(unknown,/Analysing|Elapsed|Analysis time/);
});

test('photo questions keep optional framing collapsed and retire old instructions without losing them',()=>{
  const h=harness();
  for(const role of ['pi_side_a','pi_side_b','component_header']) {
    const current=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role})})}));
    assert.match(current,/<details class="wiring-chat-framing">/);
    assert.match(current,/Photo <!-- -->[123]<!-- --> \/ 3|Photo [123] \/ 3/);
    assert.match(current,/<svg class="wiring-chat-framing-image"[^>]*role="img"/);
    assert.match(current,/This is not a GPIO pin map/);
    const history=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role,current:false,can_act:false})})}));
    assert.match(history,/<details class="wiring-chat-history">/);
    assert.match(history,/Please photograph the first Pi side/);
    assert.doesNotMatch(history,/<details class="wiring-chat-framing" open=/);
    const inactive=renderToStaticMarkup(h.render({message:message({wiring_flow:flow({role})}),inactive:true}));
    assert.doesNotMatch(inactive,/<details class="wiring-chat-framing" open=/);
  }
});

test('shared missing view gives one primary retake while wire confirmation remains optional and exact',async()=>{
  const h=harness(),calls=[];
  const row=pin=>({wire_id:pin,expected:{component_pin:pin,physical_pin:6},comparison:'unknown',evidence:'Long pin evidence.',
    next_step:'Trace both ends.',pi_candidates:[],component_candidates:[],diagnosis:{status:'uncertain',retake_roles:['component_header']}});
  const rows=[row('GND'),row('TRIG')];
  const props={message:message({wiring_flow:flow({kind:'wire_review',wire_id:'GND',result:rows[0],actions:['capture','review']})}),
    review:review({results:rows}),onAction:async(_m,a)=>{calls.push(a);return true;}};
  const tree=h.render(props),overview=elements(tree,h.mod.WiringReviewOverview)[0];
  assert.equal(overview.props.summary.headline,'The module connection positions are not yet confirmed.');
  assert.equal(overview.props.summary.results.length,2);
  const manual=elements(tree,'details').find(e=>e.props.className==='wiring-chat-manual');
  assert.equal(manual.props.open,undefined);assert.equal(elements(manual,'button').length,3);
  const retake=elements(overview,'button');assert.equal(retake.length,1);assert.deepEqual(calls,[]);
  retake[0].props.onClick();await Promise.resolve();
  assert.equal(calls.length,1);assert.equal(calls[0].op,'capture');assert.equal(calls[0].role,'component_header');
  assert.equal(calls[0].revision,4);
});

test('summary history stays frozen and legacy fallback cannot borrow another revision',()=>{
  const h=harness(),row={wire_id:'gnd',expected:{component_pin:'GND',physical_pin:6},comparison:'unknown',evidence:'old',
    pi_candidates:[],component_candidates:[],diagnosis:{status:'uncertain',retake_roles:['pi_side_a']}};
  const old=flow({kind:'wire_review',result:row,current:false,can_act:false,actions:[]});
  const live=review({revision:5,results:[{...row,diagnosis:{status:'no_issue_seen'}}]});
  assert.equal(helpers.wiringChatSummary(old,live,(_zh,en)=>en).results[0],row);
  const single=helpers.wiringChatSummary({...old,result:{...row,diagnosis:{status:'no_issue_seen'}}},live,(_zh,en)=>en);
  assert.equal(single.headline,'No obvious mismatch seen for GND; check it yourself.');
  const frozen={schema_version:2,headline:'Saved finding',next_step:'Saved step',results:[row],evidence:'Saved evidence',retake_role:'pi_side_a',counts:{uncertain:1,suspected:0,no_issue_seen:0}};
  assert.equal(helpers.wiringChatSummary({...old,summary:frozen},live,(_zh,en)=>en),frozen);
  const tree=h.render({message:message({wiring_flow:{...old,summary:frozen}}),review:live,onAction:async()=>{throw Error('No historical actions');}});
  assert.equal(elements(tree,'button').length,0);
  assert.equal(h.mod.wiringMessageHasBody(message({wiring_flow:old})),true);
  assert.equal(h.mod.wiringMessageHasBody(message({role:'user',wiring_flow:old})),false);
});

test('visible uncovered pins remain an observation and do not become a blurry-photo retake or a confirmation',()=>{
  const h=harness(),row={wire_id:'gnd',expected:{component_pin:'GND',physical_pin:6},comparison:'unknown',
    pi_candidates:[],component_candidates:[],diagnosis:{status:'uncertain',retake_roles:[]}};
  const original={schema_version:2,headline:'模組四支針腳完整裸露，未見接頭套接。',
    next_step:'先斷電，對照接線圖核對接頭是否插妥。',retake_role:null,counts:{uncertain:4,suspected:0,no_issue_seen:0},
    results:[row],evidence:'模組四支針腳完整裸露，未見接頭套接。',observation:'模組四支針腳完整裸露，未見接頭套接。',observation_role:'component_header'};
  const m=message({wiring_flow:flow({kind:'wire_review',wire_id:'gnd',result:row,summary:original,actions:['review','capture']})});
  const tree=h.render({message:m,onAction:async()=>{throw Error('Rendering must not act');}});
  const overview=elements(tree,h.mod.WiringReviewOverview)[0];
  assert.equal(overview.props.summary,original);
  assert.equal(elements(overview,'button').length,0);
  assert.match(renderToStaticMarkup(overview),/模組四支針腳完整裸露，未見接頭套接/);
  assert.doesNotMatch(renderToStaticMarkup(overview),/看不清楚|Retake|Correct<\/button>/);
  const legacy={...original,schema_version:undefined,retake_role:'component_header',headline:'零件接頭的腳位還看不清楚。'};
  const corrected=helpers.wiringChatSummary({...m.wiring_flow,summary:legacy},null,zh=>zh);
  assert.equal(corrected.headline,'零件端的接線位置尚未確認。');
  assert.equal(legacy.headline,'零件接頭的腳位還看不清楚。','Old receipts are not rewritten');
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
  assert.match(markup,/Start analysis/);
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
    './AssistantMarkdown':{AssistantMarkdown:({text})=>React.createElement('div',null,text)},
    './ConversationGuideDock':{ConversationGuideHost:()=>null},
    './MobileCompanion':{MobileCompanion:()=>null,MobileAttachmentCards:()=>null},'./WiringChatMessage':h.mod,
    './AssistantAnalysisTime':analysisComponent,'../lib/assistantProgress':progressHelpers,'./AssistantJobProgress':progressComponent,
    './WiringAnalysisEntry':entryComponent});
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
