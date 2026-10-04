import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import ts from 'typescript';
import {maker,designFor,componentTests} from './project_guide_fixture.mjs';

// Execute real handlers and hook lifecycles with isolated API responses.
// These tests do not access a camera, cloud model, Pi or production storage.
const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function module(path,imports={}) {
  const exports={};new Function('require','exports',compile(read(path)))(name=>{
    if(name in imports)return imports[name];throw Error(`Unexpected import: ${name}`);
  },exports);return exports;
}
const guideHelpers=module('../src/lib/wiringReviewGuide.ts',{'./maker':maker,'./componentTests':componentTests});
const reviewHelpers=module('../src/lib/wiringReview.ts');
const tree=ts.createSourceFile('AiDebugPanel.tsx',read('../src/components/AiDebugPanel.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function actualHandler(name) {
  let found;
  function visit(node){if(ts.isFunctionDeclaration(node)&&node.name?.text===name)found=node;ts.forEachChild(node,visit);}
  visit(tree);assert.ok(found,`${name} must exist`);return compile(found.getText(tree));
}
const handlerSource=actualHandler('wiringReviewAction')+actualHandler('reviewWire');
const design={...designFor(['hc-sr04','mrd-tf240-8p-cs']),profile_versions:{
  'hc-sr04':{version:'fixture-hc',sha256:'a'.repeat(64)},'mrd-tf240-8p-cs':{version:'fixture-tft',sha256:'b'.repeat(64)},
}};
const hc=design.wiring.find(w=>w.componentId==='hc-sr04'),tft=design.wiring.find(w=>w.componentId==='mrd-tf240-8p-cs');
const confirmation=wire=>({signature:maker.wireSignature(wire),mode:'camera',at:'2026-10-04T00:00:00.000Z'});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return{promise,resolve};};
function makeState(confirmed={}) {
  return {...maker.initialMaker(),design,code:'synthetic draft',aiModel:'fixture-model',aiEffort:'low',
    guide:{...maker.emptyGuide(),componentIndex:1,index:2,phase:'review',inspection:true,run:3,confirmed},
    debug:{symptom:'no_echo'}};
}
function makeContext(state) {
  return {project:state.design,code:state.code,locale:'zh-TW',entry:state.debug,
    guide_confirmations:state.guide.confirmed,guide_run:state.guide.run,
    test_keys:Object.fromEntries(state.design.component_ids.map(id=>[id,componentTests.componentTestKey(state.design,state.guide,id)]))};
}
function reviewRecord(extra={}) {
  return {id:'review-session',status:'awaiting_capture',phase:'awaiting_user',purpose:'wiring_review',wiring_edit_ready:true,
    wiring_review:{id:'review-set',revision:4,component_id:hc.componentId},...extra};
}
function panelHarness({state=makeState(),record=reviewRecord(),current=true,action,create}={}) {
  const calls=[],changes=[],errors=[],working=[],latest={current:state};let countdowns=0;
  const session={pending:false,async create(...args){calls.push({kind:'create',args});return create?create(...args):reviewRecord({id:'collected-session'});},
    async action(...args){calls.push({kind:'action',args});return action?action(...args):reviewRecord({id:args[5]??record?.id});}};
  const bindings={...guideHelpers,...reviewHelpers,reviewFlight:{current:false},session,record,counting:false,state,phonePreview:false,
    active:Boolean(record&&!['complete','stopped','error'].includes(record.status)),current,
    reviewLatest:latest,actionContext:makeContext(state),responseMode:'fast',tr:(_zh,en)=>en,
    setReviewWorking:value=>working.push(value),setReviewError:value=>errors.push(value),
    onReviewGuideChange:(next,expected)=>changes.push({next,expected}),
    countdown:{async run(callback){countdowns++;return callback();}},chat:{followNext(){}}};
  const handlers=new Function(...Object.keys(bindings),`${handlerSource};return{wiringReviewAction,reviewWire};`)(...Object.values(bindings));
  return {...handlers,calls,changes,errors,working,state,latest,get countdowns(){return countdowns;}};
}

test('collect-only entry creates a session and starts a review without capture, analysis or guide confirmation',async()=>{
  const h=panelHarness({record:null});await h.wiringReviewAction({op:'start',component_id:hc.componentId});
  assert.deepEqual(h.calls.map(call=>call.kind),['create','action']);
  assert.deepEqual(h.calls[0].args[5],{purpose:'wiring_review',initial_action:'collect'});
  assert.equal(h.calls[1].args[0],'wiring_review');assert.equal(h.calls[1].args[4].op,'start');
  assert.equal(h.calls[1].args[5],'collected-session');
  assert.equal(h.countdowns,0);assert.deepEqual(h.changes,[]);
});

test('an analysis result never writes a manual confirmation, even if AI reports matching colors',async()=>{
  const h=panelHarness({action:async()=>reviewRecord({wiring_review:{results:[{wire_id:hc.id,comparison:'similar'}]}})});
  await h.wiringReviewAction({op:'analyse',review_id:'review-set',revision:4});
  assert.deepEqual(h.calls.map(call=>call.args[4]?.op),['analyse']);
  assert.deepEqual(h.changes,[]);assert.deepEqual(h.state.guide.confirmed,{});assert.equal(h.countdowns,0);
});

test('accepting a photo submits its exact source identity without capture, model or physical confirmation',async()=>{
  const h=panelHarness();
  const payload={op:'accept_photo',review_id:'review-set',revision:4,role:'pi_side_a',capture_id:'source-photo',sha256:'source-hash'};
  await h.wiringReviewAction(payload);
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].args[0],'wiring_review');
  assert.deepEqual(h.calls[0].args[4],payload);
  assert.equal(h.countdowns,0);assert.deepEqual(h.changes,[]);assert.deepEqual(h.state.guide.confirmed,{});
});

test('rejected photo acceptance does not mutate physical guide confirmations',async()=>{
  const h=panelHarness({action:async()=>undefined});
  const result=await h.wiringReviewAction({op:'accept_photo',review_id:'review-set',revision:4,role:'pi_side_a',capture_id:'old-photo',sha256:'old-hash'});
  assert.equal(result,false);assert.equal(h.calls.length,1);assert.deepEqual(h.changes,[]);assert.equal(h.countdowns,0);
});

test('restarting a stale active session stops it and discards old review tokens before collect-only setup',async()=>{
  const h=panelHarness({current:false});
  await h.wiringReviewAction({op:'start',component_id:hc.componentId,review_id:'old-review',revision:99});
  assert.deepEqual(h.calls.map(call=>[call.kind,call.args[0]]),[
    ['action','stop'],['create',makeContext(h.state)],['action','wiring_review'],
  ]);
  assert.equal(h.calls[1].args[5].initial_action,'collect');
  assert.deepEqual(h.calls[2].args[4],{op:'start',component_id:hc.componentId});
  assert.equal(h.calls[2].args[5],'collected-session');assert.deepEqual(h.changes,[]);
});

test('a rejected crop action returns failure so a crop dialog does not mistake it for a successful save',async()=>{
  const h=panelHarness({action:async()=>undefined});
  const result=await h.wiringReviewAction({op:'crop',review_id:'review-set',revision:4,role:'pi_side_a',crop:[.1,.1,.9,.9]});
  assert.equal(result,false);assert.equal(h.calls.length,1);assert.deepEqual(h.changes,[]);
});

test('explicit human confirmation commits only after success and sends coherent guide/test bindings without moving the cursor',async()=>{
  const result=deferred(),h=panelHarness({state:makeState({[tft.id]:confirmation(tft)}),action:()=>result.promise});
  const task=h.reviewWire(hc.id,'confirmed');
  assert.equal(h.changes.length,0,'an in-flight request must not mark the wire confirmed');
  const submitted=h.calls[0].args;
  assert.equal(submitted[0],'wiring_review');
  assert.deepEqual(submitted[4],{op:'review',wire_id:hc.id,decision:'confirmed',review_id:'review-set',revision:4});
  assert.ok(submitted[1].guide_confirmations[hc.id]);
  result.resolve(reviewRecord());await task;
  assert.equal(h.changes.length,1);
  const {next,expected}=h.changes[0];assert.strictEqual(expected,h.state);
  assert.deepEqual({...next,confirmed:h.state.guide.confirmed},h.state.guide);
  assert.strictEqual(next.confirmed[tft.id],h.state.guide.confirmed[tft.id]);
  assert.strictEqual(submitted[1].guide_confirmations,next.confirmed);
  for(const id of design.component_ids)assert.equal(submitted[1].test_keys[id],componentTests.componentTestKey(design,next,id));
});

test('unsure retracts an earlier human confirmation only after hardware reconciliation, preserving unrelated lines',async()=>{
  const h=panelHarness({state:makeState({[hc.id]:confirmation(hc),[tft.id]:confirmation(tft)})});
  await h.reviewWire(hc.id,'unsure');
  assert.deepEqual(h.calls.map(call=>call.args[0]),['prepare_wiring','wiring_review']);
  assert.equal(h.calls[1].args[4].decision,'unsure');
  assert.ok(!(hc.id in h.calls[1].args[1].guide_confirmations));
  assert.equal(h.changes.length,1);
  assert.strictEqual(h.changes[0].next.confirmed[tft.id],h.state.guide.confirmed[tft.id]);
});

test('needs-change prepares hardware even when the wire has never been confirmed',async()=>{
  const h=panelHarness();await h.reviewWire(hc.id,'needs_change');
  assert.deepEqual(h.calls.map(call=>call.args[0]),['prepare_wiring','wiring_review']);
  assert.equal(h.calls[1].args[4].decision,'needs_change');assert.deepEqual(h.changes,[]);
});

test('unsure cannot clear confirmation while hardware stop is unreconciled',async()=>{
  const h=panelHarness({state:makeState({[hc.id]:confirmation(hc)}),action:async()=>reviewRecord({wiring_edit_ready:false})});
  await h.reviewWire(hc.id,'unsure');
  assert.deepEqual(h.calls.map(call=>call.args[0]),['prepare_wiring']);
  assert.deepEqual(h.changes,[]);assert.ok(h.errors.at(-1));
});

test('capturing one requested view calls the capture action once and never automatically analyses or confirms',async()=>{
  const h=panelHarness();await h.wiringReviewAction({op:'capture',review_id:'review-set',revision:4,role:'pi_side_b'});
  assert.equal(h.countdowns,1);assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].args[4].op,'capture');assert.equal(h.calls[0].args[4].role,'pi_side_b');
  assert.deepEqual(h.changes,[]);
});

test('a failed result or changed local guide cannot commit a delayed human confirmation',async()=>{
  for(const scenario of ['failed','guide-changed']) {
    const result=deferred(),h=panelHarness({action:()=>result.promise});
    const task=h.reviewWire(hc.id,'confirmed');
    if(scenario==='guide-changed')h.latest.current={...h.state,guide:{...h.state.guide,run:4}};
    result.resolve(scenario==='failed'?undefined:reviewRecord());await task;
    assert.deepEqual(h.changes,[],scenario);
  }
});

test('a physical change invalidates that component after preparation and leaves other component confirmations intact',async()=>{
  const h=panelHarness({state:makeState(Object.fromEntries(design.wiring.map(w=>[w.id,confirmation(w)])))});
  await h.wiringReviewAction({op:'changed',component_id:hc.componentId,review_id:'review-set',revision:4});
  assert.deepEqual(h.calls.map(call=>call.args[0]),['prepare_wiring','wiring_review']);
  const next=h.changes[0].next;
  assert.ok(design.wiring.filter(w=>w.componentId===hc.componentId).every(w=>!(w.id in next.confirmed)));
  assert.strictEqual(next.confirmed[tft.id],h.state.guide.confirmed[tft.id]);assert.equal(next.run,h.state.guide.run);
});

const hookCode=compile(read('../src/lib/debugSessions.ts'));
const history=project=>({id:`conversation-${project}`,project_id:project,messages:[],check_ids:[]});
const hookSession=(id,project)=>({id,status:'awaiting_capture',phase:'awaiting_user',binding:{project_id:project},
  conversation_id:`conversation-${project}`,current_target:true,capture_task:null,observations:[],evidence:[],jobs:[],updated_at:1});
const hookContext=project=>({project:{id:project},code:'fixture',test_keys:{},entry:{}});
function hookHarness(post,initial=null) {
  const slots=[],effects=[],calls=[],storage=new Map(),timers=new Map();
  let nextTimer=0,cursor=0,dirty=true,project='current',value;
  const window={localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,v)=>storage.set(key,v),removeItem:key=>storage.delete(key)},
    addEventListener(){},removeEventListener(){},setTimeout(callback){timers.set(++nextTimer,callback);return nextTimer;},clearTimeout:id=>timers.delete(id)};
  const react={
    useState(initial){const index=cursor++;if(!slots[index])slots[index]={value:typeof initial==='function'?initial():initial};
      return[slots[index].value,next=>{const resolved=typeof next==='function'?next(slots[index].value):next;
        if(!Object.is(resolved,slots[index].value)){slots[index].value=resolved;dirty=true;}}];},
    useRef(initial){const index=cursor++;return slots[index]??={current:initial};},
    useEffect(callback,deps){const index=cursor++,previous=slots[index];
      if(!previous||deps.some((dep,i)=>!Object.is(dep,previous.deps[i]))){const effect={deps,cleanup:previous?.cleanup};slots[index]=effect;
        effects.push(()=>{effect.cleanup?.();effect.cleanup=callback();});}},
  };
  const exports={};new Function('require','exports','window','crypto',hookCode)(name=>name==='react'?react:{
    async makerRequest(path,body){calls.push({path,body});if(body)return post(path,body);
      if(path==='debug/sessions')return{active:initial};
      if(path.startsWith('debug/conversations?'))return{conversation:history(decodeURIComponent(path.split('=')[1]))};
      if(initial&&path===`debug/sessions/${initial.id}`)return initial;
      throw Error(`Unexpected GET: ${path}`);},
  },exports,window,{randomUUID});
  function render(){for(let count=0;dirty;count++){assert.ok(count<20);dirty=false;cursor=0;value=exports.useDebugSession(project,true);
    for(const effect of effects.splice(0))effect();}}
  async function settle(){for(let i=0;i<30;i++){await Promise.resolve();render();}}
  render();return{calls,storage,get value(){render();return value;},settle,
    async switchProject(next){project=next;dirty=true;render();await settle();},
    dispose(){for(const slot of slots)slot?.cleanup?.();timers.clear();}};
}

test('the real hook transports collect-only setup and a bound capture action without implicit extra POSTs',async()=>{
  const created=hookSession('fresh','current'),h=hookHarness(async()=>created);
  try {
    await h.settle();const snapshot=h.value;
    const result=await snapshot.create(hookContext('current'),'check','fixture','low','fast',{purpose:'wiring_review',initial_action:'collect'});
    const payload={op:'capture',review_id:'set',revision:2,role:'component_header'};
    await snapshot.action('wiring_review',hookContext('current'),undefined,'fast',payload,result.id);
    const posts=h.calls.filter(call=>call.body);assert.equal(posts.length,2);
    assert.equal(posts[0].body.initial_action,'collect');assert.equal(posts[0].body.purpose,'wiring_review');
    assert.equal(posts[1].path,'debug/sessions/fresh/actions');assert.deepEqual(posts[1].body.wiring_review,payload);
    assert.ok(posts.every(call=>call.body.request_id));
  } finally {h.dispose();}
});

test('a late collect-only create after switching project returns no result to chain further actions',async()=>{
  const result=deferred(),h=hookHarness(()=>result.promise);
  try {
    await h.settle();const pending=h.value.create(hookContext('current'),'check','fixture','low','fast',{purpose:'wiring_review',initial_action:'collect'});
    await h.switchProject('other');result.resolve(hookSession('late','current'));
    assert.equal(await pending,undefined);await h.settle();assert.notEqual(h.value.record?.id,'late');
    assert.ok(![...h.storage.values()].includes('late'));assert.equal(h.calls.filter(call=>call.body).length,1);
  } finally {h.dispose();}
});

test('a late review action after project switch cannot return a successful manual-confirmation receipt',async()=>{
  const result=deferred(),h=hookHarness(()=>result.promise,hookSession('old','current'));
  try {
    await h.settle();const pending=h.value.action('wiring_review',hookContext('current'),undefined,'fast',{op:'review',wire_id:'wire',decision:'confirmed'});
    await h.switchProject('other');result.resolve(hookSession('late-confirmation','current'));
    assert.equal(await pending,undefined);await h.settle();assert.notEqual(h.value.record?.id,'late-confirmation');
  } finally {h.dispose();}
});

test('context invalidation supersedes an in-flight review action without exposing its old confirmation result',async()=>{
  const result=deferred(),current=hookSession('old','current');
  const h=hookHarness((_path,body)=>body.action==='context_changed'?{...current,phase:'context_updated'}:result.promise,current);
  try {
    await h.settle();const pending=h.value.action('wiring_review',hookContext('current'),undefined,'fast',{op:'review',wire_id:'wire',decision:'confirmed'});
    const fresh=await h.value.contextChanged({...hookContext('current'),code:'changed draft'});
    assert.equal(fresh.phase,'context_updated');result.resolve({...current,phase:'late-confirmed'});
    assert.equal(await pending,undefined);await h.settle();assert.equal(h.value.record.phase,'context_updated');
  } finally {h.dispose();}
});

test('unmounting a pending collect or review call returns no receipt and cannot save a late session pointer',async()=>{
  for(const kind of ['collect','review']) {
    const result=deferred(),initial=kind==='review'?hookSession('existing','current'):null;
    const h=hookHarness(()=>result.promise,initial);await h.settle();
    const pending=kind==='collect'
      ? h.value.create(hookContext('current'),'check','fixture','low','fast',{purpose:'wiring_review',initial_action:'collect'})
      : h.value.action('wiring_review',hookContext('current'),undefined,'fast',{op:'review',wire_id:'wire',decision:'confirmed'});
    h.dispose();result.resolve(hookSession('late-unmounted','current'));
    assert.equal(await pending,undefined,kind);assert.ok(![...h.storage.values()].includes('late-unmounted'));
  }
});

test('adopting a shared review retains photos and human decisions without any POST or reset',async()=>{
  const h=hookHarness(()=>assert.fail('adoption must not dispatch'));
  try {
    await h.settle();const existing={...hookSession('shared-current','current'),wiring_review:{id:'review-current',round:2,
      slots:{pi_side_a:{capture_id:'human-selected'}},reviews:{echo:{decision:'confirmed'}}}};
    const before=structuredClone(existing);assert.equal(h.value.adoptReview(existing),true);await h.settle();
    assert.deepEqual(h.value.record,before);assert.ok([...h.storage.values()].includes('shared-current'));
    assert.equal(h.calls.filter(call=>call.body).length,0);
  }finally{h.dispose();}
});

test('shared review adoption rejects foreign stale busy or unmounted receipts without replacing the current record',async()=>{
  const initial=hookSession('old','current'),pending=deferred(),h=hookHarness(()=>pending.promise,initial);
  await h.settle();const valid={...hookSession('new','current'),wiring_review:{id:'review-current'}};
  for(const change of [{binding:{project_id:'foreign'}},{conversation_current:false},{current_target:false},
    {status:'stopped'},{status:'complete'},{status:'error'},{phase:'backend_restarted'},{wiring_review:null}]) {
    assert.equal(h.value.adoptReview({...valid,...change}),false);
  }
  const task=h.value.create(hookContext('current'),'check','fixture','low','fast',{purpose:'wiring_review',initial_action:'collect'});
  assert.equal(h.value.adoptReview(valid),false);const retained=h.value.adoptReview;h.dispose();
  assert.equal(retained(valid),false);pending.resolve(valid);assert.equal(await task,undefined);
  assert.ok(![...h.storage.values()].includes('new'));assert.equal(h.value.record.id,'old');
});
