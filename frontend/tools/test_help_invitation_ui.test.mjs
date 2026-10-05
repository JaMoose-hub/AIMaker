import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {maker, componentTests, designFor} from './project_guide_fixture.mjs';
import {flowModule} from './wiring_photo_flow_fixture.mjs';

// Real panel event handlers with isolated transport/hook ports; no API, model or hardware.
const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
const state={...maker.initialMaker(),design,code:'synthetic-code',guide:{...maker.emptyGuide(),run:3}};
const keys=Object.fromEntries(design.component_ids.map(cid=>[cid,componentTests.componentTestKey(design,state.guide,cid)]));
const context={project:design,code:state.code,entry:{},test_keys:keys,guide_run:3};
const invite=(change={})=>({id:'invite-one',projectId:design.id,revision:design.revision,componentId:'hc-sr04',
  guideKey:keys['hc-sr04'],guideRun:3,contextEpoch:0,mode:'wiring',text:'This text is already in the assistant conversation.',...change});
const review=(change={})=>({id:'current-review',revision:2,round:1,component_id:'hc-sr04',status:'collecting',
  photo_flow_version:2,slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:[],reviews:{},missing_roles:[],no_progress_count:0,...change});
const record=(wiring_review=null)=>({id:'collect-session',status:'awaiting_capture',phase:'awaiting_user',purpose:'wiring_review',
  binding:{project_id:design.id,code_hash:'synthetic-hash',test_keys:keys},current_target:true,camera_current:true,
  observations:[],messages:[],evidence:[],wiring_review,updated_at:1,symptom:'synthetic symptom'});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return{resolve,promise};};
const flatten=(node,list=[])=>{if(!node)return list;if(Array.isArray(node)){node.forEach(child=>flatten(child,list));return list;}
  list.push(node);if(React.isValidElement(node))React.Children.toArray(node.props.children).forEach(child=>flatten(child,list));return list;};
function Entry(){return null;}
function harness({initialRecord=null,action,create,invitation=invite(),actionTarget={id:'current-assistant-message'},actionsOnly=true}={}) {
  const slots=[],effects=[],refs=[];let cursor=0,refCursor=0,effectCursor=0,dirty=true,tree;
  const calls=[],handled=[],guides=[];
  const hooks={...React,useState(initial){const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;
    return[slots[i],next=>{const value=typeof next==='function'?next(slots[i]):next;if(!Object.is(slots[i],value)){slots[i]=value;dirty=true;}}];},
    useRef(initial){return refs[refCursor++]??={current:initial};},useEffect(callback,deps){const i=effectCursor++,before=effects[i];
      if(!before||deps?.some((value,index)=>!Object.is(value,before.deps[index])))effects[i]={deps,callback,cleanup:before?.cleanup,pending:true};},useLayoutEffect(){}};
  const session={record:initialRecord,conversation:null,pending:false,error:'',resetVersion:0,
    async create(...args){calls.push({kind:'create',args});return create?create(...args):record();},
    async action(...args){calls.push({kind:'action',args});return action?action(...args):record(review());},
    contextChanged(){assert.fail('An invitation cannot change context automatically');}};
  let props={state,context,currentCodeHash:'synthetic-hash',session,webcamReady:false,eyeActive:false,cameraSource:'device',cameraRuntimeRevision:1,
    repairCaseId:null,repairAppliedHash:null,repairCandidateReady:false,onReturnWebcam(){},onCase(){},onRetest(){assert.fail('No hardware retest');},
    onTrial(){assert.fail('No trial');},onReviewRepair(){},onManual(){assert.fail('No manual hardware action');},onWiring(){},
    onReviewGuideChange:(...args)=>guides.push(args),testHelpInvitation:invitation,testHelpActionTarget:actionTarget,onTestHelpHandled:id=>handled.push(id),actionsOnly,variant:'wiring'};
  const sessionHelpers=flowModule('../src/lib/debugSessions.ts',{react:hooks,'./maker':maker});
  const evidenceHelpers=flowModule('../src/lib/debugEvidence.ts');
  const entryHelpers=flowModule('../src/lib/wiringReviewEntry.ts');
  const reviewHelpers=flowModule('../src/lib/wiringReview.ts');
  const guideHelpers=flowModule('../src/lib/wiringReviewGuide.ts',{'./maker':maker,'./componentTests':componentTests});
  const {AiDebugPanel}=flowModule('../src/components/AiDebugPanel.tsx',{react:hooks,
    'react-dom':{createPortal:(children,target)=>React.createElement('test-help-portal',{target},children)},'../lib/useMaker':{useMakerText:()=>zh=>zh},
    '../lib/systemText':{systemText:value=>value},'../lib/maker':maker,'../lib/debugSessions':sessionHelpers,'../lib/componentTests':componentTests,
    './PhotoEvidenceCard':{PhotoEvidenceCard:()=>null},'./DiagramEvidenceCard':{DiagramEvidenceCard:()=>null},'../lib/debugEvidence':evidenceHelpers,
    './AssistantMarkdown':{AssistantMarkdown:({text})=>React.createElement('div',null,text)},
    '../lib/useCaptureCountdown':{useCaptureCountdown:()=>({remaining:null,run(){assert.fail('Invitation must not capture');},cancel(){}})},
    './CaptureCountdown':{CaptureCountdown:()=>null},'../lib/useChatScroll':{useChatScroll:()=>({chatRef:{current:null},contentRef:{current:null},followNext(){},onScroll(){}})},
    './WiringReviewCard':{WiringReviewCard:()=>null},'./WiringReviewEntry':{WiringReviewEntry:Entry},'../lib/wiringReviewEntry':entryHelpers,
    '../lib/wiringReview':reviewHelpers,'../lib/wiringReviewGuide':guideHelpers});
  function render(){for(let loops=0;dirty;loops++){assert.ok(loops<20);dirty=false;cursor=0;refCursor=0;effectCursor=0;tree=AiDebugPanel(props);
    for(const effect of effects)if(effect.pending){effect.pending=false;effect.cleanup?.();effect.cleanup=effect.callback();}}
    return tree;}
  render();
  return {calls,handled,guides,session,get nodes(){return flatten(render());},update(next){props={...props,...next};dirty=true;return render();},
    button(label){return flatten(render()).find(node=>node.type==='button'&&node.props.children===label);},
    entry(){return flatten(render()).find(node=>node.type===Entry);},
    async settle(){for(let i=0;i<12;i++){await Promise.resolve();render();}},
    unmount(){effects.forEach(effect=>effect.cleanup?.());}};
}

test('rendering an invitation offers only compact choices without repeating its conversation text or creating a session',()=>{
  const h=harness();assert.ok(h.button('拍照檢查'));assert.ok(h.button('稍後'));
  assert.equal(h.nodes.filter(node=>node.props?.className==='ai-debug-actions test-help-invitation').length,1);
  assert.ok(!h.nodes.some(node=>typeof node==='string'&&node.includes(invite().text)));
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,[]);assert.deepEqual(h.guides,[]);
});

test('wiring chat shell retains only the two invitation buttons in the message portal',()=>{
  const h=harness();h.update({chatGuidance:true});
  assert.ok(h.button('拍照檢查'));assert.ok(h.button('稍後'));
  assert.equal(h.nodes.filter(node=>node.type==='test-help-portal').length,1);
  assert.ok(!h.nodes.some(node=>node.type==='section'||node.type==='textarea'||node.type===Entry));
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.guides,[]);
  h.update({testHelpInvitation:null,session:{...h.session,record:record(review())}});
  assert.equal(h.nodes.length,0);
});
test('wiring chat shell acknowledges start without revealing or mounting a review panel',async()=>{
  const h=harness();let starts=0;h.update({chatGuidance:true,onTestHelpAction:async()=>{starts++;return record(review());}});
  h.button('拍照檢查').props.onClick();await h.settle();
  assert.equal(starts,1);assert.deepEqual(h.handled,['invite-one']);
  assert.equal(h.entry(),undefined);assert.deepEqual(h.calls,[]);assert.deepEqual(h.guides,[]);
});
test('shared conversation actions render only once in the exact message host and wait for a ready host without tool fallback',()=>{
  const first={id:'first-message-host'},second={id:'second-message-host'},h=harness({actionTarget:null});
  assert.equal(h.button('拍照檢查'),undefined);assert.equal(h.button('稍後'),undefined);
  assert.ok(!h.nodes.some(node=>node.type==='test-help-portal'));
  h.update({testHelpActionTarget:first});
  assert.equal(h.nodes.filter(node=>node.type==='test-help-portal').length,1);
  assert.equal(h.nodes.find(node=>node.type==='test-help-portal').props.target,first);
  assert.equal(h.nodes.filter(node=>node.props?.className==='ai-debug-actions test-help-invitation').length,1);
  const priorStart=h.button('拍照檢查');
  h.update({testHelpActionTarget:null});assert.equal(h.button('拍照檢查'),undefined);
  h.update({testHelpActionTarget:second});
  assert.equal(h.nodes.filter(node=>node.type==='test-help-portal').length,1);
  assert.equal(h.nodes.find(node=>node.type==='test-help-portal').props.target,second);
  h.update({testHelpInvitation:null});
  assert.ok(!h.nodes.some(node=>node.type==='test-help-portal'));assert.equal(h.button('拍照檢查'),undefined);
  priorStart.props.onClick();assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,[]);assert.deepEqual(h.guides,[]);
});
test('a standalone panel without a message host keeps its local invitation fallback without a duplicate portal',()=>{
  const h=harness({actionTarget:null,actionsOnly:false});
  assert.ok(h.button('拍照檢查'));assert.ok(h.button('稍後'));
  assert.ok(!h.nodes.some(node=>node.type==='test-help-portal'));
  assert.equal(h.nodes.filter(node=>node.props?.className==='ai-debug-actions test-help-invitation').length,1);
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,[]);
});
test('Later clears only the exact invitation and cannot create, capture, analyse or confirm',()=>{
  const h=harness();h.button('稍後').props.onClick();assert.deepEqual(h.handled,['invite-one']);
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.guides,[]);assert.equal(h.entry().props.revealRequest,null);
});
test('a current invitation keeps the old stopped operation out of focus while preserving its history',()=>{
  const old={...record(),status:'stopped',phase:'stopped'},h=harness({initialRecord:old});
  h.update({operationCard:React.createElement('strong',null,'OLD STOPPED OPERATION')});
  assert.ok(!h.nodes.some(node=>node==='OLD STOPPED OPERATION'));
  h.button('稍後').props.onClick();h.update({testHelpInvitation:null});
  assert.ok(h.nodes.some(node=>node==='OLD STOPPED OPERATION'));
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,['invite-one']);assert.equal(h.session.record,old);
});
test('explicit Start creates collect-only then starts once, revealing the returned review only after success',async()=>{
  const pending=deferred(),h=harness({action:()=>pending.promise});
  const start=h.button('拍照檢查');start.props.onClick();start.props.onClick();await h.settle();
  assert.deepEqual(h.calls.map(call=>call.kind),['create','action']);assert.deepEqual(h.handled,[]);
  assert.deepEqual(h.calls[0].args[5],{purpose:'wiring_review',initial_action:'collect'});
  assert.deepEqual(h.calls[1].args[4],{op:'start',component_id:'hc-sr04'});
  pending.resolve(record(review()));await h.settle();
  assert.deepEqual(h.handled,['invite-one']);assert.deepEqual(h.entry().props.revealRequest,{token:'invite-one',reviewId:'current-review',componentId:'hc-sr04'});
  assert.deepEqual(h.guides,[]);assert.ok(h.calls.every(call=>call.kind==='create'||call.args[0]==='wiring_review'));
});
test('Continue reuses the exact current component review and retains selected photos and confirmations without any session action',async()=>{
  const existing=review({slots:{pi_side_a:{capture_id:'selected',photo_acceptance:{capture_id:'selected',round:1,source:'human'}}},reviews:{echo:{decision:'confirmed'}}});
  const before=structuredClone(existing),h=harness({initialRecord:record(existing)});
  assert.ok(h.button('繼續照片核對'));assert.equal(h.button('拍照檢查'),undefined);
  h.button('繼續照片核對').props.onClick();await h.settle();
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,['invite-one']);assert.deepEqual(existing,before);
  assert.equal(h.entry().props.revealRequest.reviewId,existing.id);assert.deepEqual(h.guides,[]);
});
test('setup and stale project/component/revision/wiring/round invitations have no photo choices or automatic actions',()=>{
  for(const change of [{mode:'setup'},{projectId:'other'},{componentId:'unknown'},{revision:0},{guideKey:'old-key'},{guideRun:2}]) {
    const h=harness({invitation:invite(change)});assert.equal(h.button('拍照檢查'),undefined);assert.equal(h.button('稍後'),undefined);assert.deepEqual(h.calls,[]);
  }
});
test('retained Start or Later callbacks cannot act on a replaced invitation or guide',()=>{
  for(const change of ['invite','guide']) {
    const h=harness(),start=h.button('拍照檢查'),later=h.button('稍後');
    if(change==='invite')h.update({testHelpInvitation:invite({id:'new-invitation'})});
    else h.update({state:{...state,guide:{...state.guide,run:4}}});
    start.props.onClick();later.props.onClick();assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,[]);
  }
});
test('a retained Start uses the latest session binding instead of the record captured by its old render',async()=>{
  const h=harness(),start=h.button('拍照檢查');
  const newest={...record(),id:'newest-collect-session'};h.session.record=newest;h.update({});
  start.props.onClick();await h.settle();
  assert.deepEqual(h.calls.map(call=>call.kind),['action']);
  assert.equal(h.calls[0].args[0],'wiring_review');assert.equal(h.calls[0].args[5],'newest-collect-session');
  assert.deepEqual(h.handled,['invite-one']);
});
test('failed or late Start keeps the invitation and cannot reveal or clear a newer target',async()=>{
  for(const late of [false,true]) {
    const pending=deferred(),h=harness({action:()=>pending.promise});h.button('拍照檢查').props.onClick();await h.settle();
    if(late)h.update({testHelpInvitation:invite({id:'new-invitation'})});
    pending.resolve(late?record(review()):undefined);await h.settle();
    assert.deepEqual(h.handled,[]);assert.equal(h.entry().props.revealRequest,null);assert.ok(h.button('拍照檢查'));
  }
});
test('a failed explicit Start exposes a retryable error without selecting photos, confirming wires or clearing the invitation',async()=>{
  const h=harness({action(){throw new Error('synthetic start failure');}});
  h.button('拍照檢查').props.onClick();await h.settle();
  assert.ok(h.nodes.some(node=>node.props?.role==='alert'&&node.props.children==='synthetic start failure'));
  assert.ok(h.button('拍照檢查'));assert.deepEqual(h.handled,[]);assert.deepEqual(h.guides,[]);
  assert.equal(h.entry().props.revealRequest,null);
  assert.ok(h.calls.every(call=>call.kind==='create'||call.args[0]==='wiring_review'));
});
test('an invitation alone never reuses a foreign or stale review and phone preview cannot act',()=>{
  for(const existing of [review({component_id:'mrd-tf240-8p-cs'}),review({status:'stale'}),review({status:'error'})]) {
    const h=harness({initialRecord:record(existing)});assert.ok(h.button('拍照檢查'));assert.equal(h.button('繼續照片核對'),undefined);assert.deepEqual(h.calls,[]);
  }
  const h=harness(),start=h.button('拍照檢查');h.update({phonePreview:true});start.props.onClick();assert.deepEqual(h.calls,[]);
});

test('shared invitation Start adopts the authoritative receipt without another local session action',async()=>{
  const h=harness(),pending=deferred(),shared=[];
  h.update({onTestHelpAction:(invitation,op)=>{shared.push({invitation,op});return pending.promise;}});
  const start=h.button('拍照檢查');start.props.onClick();start.props.onClick();await h.settle();
  assert.equal(shared.length,1);assert.equal(shared[0].op,'start');assert.deepEqual(h.calls,[]);assert.deepEqual(h.handled,[]);
  pending.resolve(record(review()));await h.settle();
  assert.deepEqual(h.handled,['invite-one']);assert.equal(h.entry().props.revealRequest.reviewId,'current-review');
  assert.deepEqual(h.calls,[]);assert.deepEqual(h.guides,[]);
});

test('shared invitation Later waits for persisted consent and is available when Start is unavailable',async()=>{
  const h=harness({invitation:invite({canAct:false,canDismiss:true})}),pending=deferred(),shared=[];
  h.update({onTestHelpAction:(invitation,op)=>{shared.push({invitation,op});return pending.promise;}});
  assert.equal(h.button('拍照檢查').props.disabled,true);assert.equal(h.button('稍後').props.disabled,false);
  const later=h.button('稍後');later.props.onClick();later.props.onClick();await h.settle();
  assert.equal(shared.length,1);assert.equal(shared[0].op,'later');assert.deepEqual(h.handled,[]);
  pending.resolve(true);await h.settle();assert.deepEqual(h.handled,['invite-one']);
  assert.deepEqual(h.calls,[]);assert.equal(h.entry().props.revealRequest,null);
});

test('shared invitation failed or late consent cannot reveal or clear a newer message',async()=>{
  for(const scenario of ['failure','replacement']) {
    const h=harness(),pending=deferred();h.update({onTestHelpAction:()=>pending.promise});
    h.button('拍照檢查').props.onClick();await h.settle();
    if(scenario==='replacement')h.update({testHelpInvitation:invite({id:'new-invitation'})});
    pending.resolve(scenario==='failure'?false:record(review()));await h.settle();
    assert.deepEqual(h.handled,[]);assert.deepEqual(h.calls,[]);assert.equal(h.entry().props.revealRequest,null);
    assert.ok(h.button('拍照檢查'));
  }
});
