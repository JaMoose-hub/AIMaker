import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {maker,componentTests,designFor,renderTestCard} from './project_guide_fixture.mjs';

const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
const session={...maker.emptyGuide(),phase:'review',confirmed:Object.fromEntries(design.wiring.map(w=>
  [w.id,{signature:maker.wireSignature(w),mode:'camera',at:'saved'}]))};
const run={id:'exact-test',project_id:design.id,revision:1,component_id:'hc-sr04',
  guide_key:componentTests.componentTestKey(design,session,'hc-sr04'),outcome:'inconclusive',reason:'no_echo',
  created_at:1,finished_at:2,phase:'finished',reserved:false,invalidated:false,logs:['not enough fresh echoes'],
  samples:{near:{count:2,median_cm:14.9}},detail:'insufficient samples',exit_code:null,options:[]};
function load(path,imports={}) {
  const code=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',code)(name=>{
    if(name in imports)return imports[name];throw Error(`Unmocked import ${name}`);
  },exports,React);return exports;
}
const {componentTestHelpText,componentTestHelpRequest,componentTestHelpInvitation,currentTestHelpInvitation,testHelpSourceIdentity}=load('../src/lib/componentTestHelp.ts',{'./componentTests':componentTests});
const evidence={componentId:'hc-sr04',run,reason:run.reason,historical:true,stale:false};

test('test help keeps a readable message and freezes exact facts and wiring only in background context',()=>{
  const stopped={...evidence,reason:'cancelled',run:{...structuredClone(run),reason:'cancelled'}},before=structuredClone(stopped);
  const {text,context}=componentTestHelpRequest(design,stopped,'zh-TW');
  assert.match(text,/請 AI 幫忙除錯 HC-SR04\+/);assert.doesNotMatch(text,/test_id|historical|預期接法|\{|test stopped/);
  assert.ok(text.length<250);assert.equal(componentTestHelpText(design,stopped,'zh-TW'),text);
  assert.equal(context.test_id,'exact-test');assert.equal(context.historical,true);
  assert.equal(context.authority,'test_record_advisory');
  const ground=context.expected_wiring.find(w=>w.componentPin==='GND');
  assert.equal(ground.boardPin,'GND_P6');assert.match(ground.boardLabel,/^Pin 6\b/);
  assert.ok(context.expected_wiring.every(w=>w.componentId==='hc-sr04'));
  assert.equal(context.evidence_limits.stopped_test_is_not_hardware_fault,true);
  assert.match(context.requested_help,/Do not start hardware tests/);assert.deepEqual(stopped,before);
  assert.notStrictEqual(context.samples,stopped.run.samples);assert.notStrictEqual(context.expected_wiring[0],design.wiring[0]);
  stopped.run.samples.near.count=999;assert.equal(context.samples.near.count,2);
});
test('another project or component test cannot be submitted as the selected component',()=>{
  for(const wrong of [{project_id:'other'},{component_id:'mrd-tf240-8p-cs'}])
    assert.throws(()=>componentTestHelpText(design,{...evidence,run:{...run,...wrong}},'en'),/target_changed/);
});
test('background evidence retains preflight and stale limits and bounded logs without exposing them in chat',()=>{
  const preflight=componentTestHelpRequest(design,{...evidence,run:null,reason:'missing_dependency',error:'Missing driver'},'en');
  assert.equal(preflight.context.test_id,null);assert.equal(preflight.context.detail,'Missing driver');
  assert.doesNotMatch(preflight.text,/Missing driver|test_id|\{/);
  const old=componentTestHelpRequest(design,{...evidence,stale:true,run:{...run,logs:Array.from({length:99},(_,i)=>`${i} ${'x'.repeat(500)}`),detail:'d'.repeat(5000)}},'en');
  assert.equal(old.context.invalidated,true);assert.equal(old.context.logs.length,6);
  assert.match(old.context.logs.at(-1),/^98 x/);assert.equal(old.context.logs.at(-1).length,400);
  assert.equal(old.context.detail.length,1200);assert.doesNotMatch(old.text,/98 x|invalidated/);
  assert.ok(JSON.stringify(old.context).length<12000);assert.match(old.context.requested_help,/Do not start hardware tests/);
});
test('known visual test symptoms offer a short photo question instead of a broad diagnosis',()=>{
  for(const [componentId,reason] of [['hc-sr04','no_echo'],['mrd-tf240-8p-cs','display_black'],['mrd-tf240-8p-cs','display_white'],['mrd-tf240-8p-cs','display_abnormal']]) {
    const selected={...evidence,componentId,reason,run:{...run,component_id:componentId,reason,logs:['RAW PRIVATE LOG']}};
    const invitation=componentTestHelpInvitation(design,selected,'zh-TW',{
      id:'offer',guideKey:componentTests.componentTestKey(design,session,componentId),guideRun:0,contextEpoch:1});
    assert.equal(invitation.mode,'wiring');assert.match(invitation.text,/一起檢查接線嗎/);
    assert.match(invitation.text,/Pi 兩側/);assert.ok(invitation.text.length<160);
    assert.doesNotMatch(invitation.text,/\n|足夠的距離資料|逐條核對|JSON|RAW PRIVATE|exit_code|旋轉|套件版本|哪一支接錯/);
    const english=componentTestHelpInvitation(design,selected,'en',{
      id:'offer',guideKey:invitation.guideKey,guideRun:0,contextEpoch:1});
    assert.match(english.text,/check the wiring together\?/);assert.doesNotMatch(english.text,/\n|enough distance readings/);
    assert.equal(currentTestHelpInvitation(invitation,design,session,1),true);
    for(const [project,guide,epoch] of [[{...design,revision:2},session,1],[design,{...session,run:1},1],[design,{...session,confirmed:{}},1],[design,session,2],[null,session,1]])
      assert.equal(currentTestHelpInvitation(invitation,project,guide,epoch),false);
  }
});
test('environment errors give their specific next step without inviting a wiring photo',()=>{
  for(const reason of ['missing_dependency','spi_missing','connection_lost','device_permission']) {
    const invitation=componentTestHelpInvitation(design,{...evidence,reason,run:null,
      error:"ModuleNotFoundError: No module named 'luma'"},'zh-TW',{id:'setup',guideKey:run.guide_key,guideRun:0,contextEpoch:0});
    assert.equal(invitation.mode,'setup');assert.doesNotMatch(invitation.text,/拍照|Pi 兩側|ModuleNotFoundError/);
    if(reason==='missing_dependency')assert.match(invitation.text,/luma\.lcd 2\.13\.0/);
  }
});

test('the invitation source changes on same-wiring retest, a passed result or invalidation',()=>{
  const base={status:{active:null,results:[run]},error:null};
  const identity=testHelpSourceIdentity(base,design,session,'hc-sr04');
  for(const change of [{id:'new-test',outcome:'running',reserved:true},{outcome:'passed',reason:null},{invalidated:true}])
    assert.notEqual(testHelpSourceIdentity({...base,status:{...base.status,results:[{...run,...change}]}},design,session,'hc-sr04'),identity);
  assert.notEqual(testHelpSourceIdentity({...base,status:{...base.status,active:{...run,id:'new-active',outcome:'running',reserved:true}}},design,session,'hc-sr04'),identity);
  assert.notEqual(testHelpSourceIdentity({...base,status:{...base.status,execution:{jobs:[{id:'new-job',kind:'test',project_id:design.id,component_id:'hc-sr04',guide_key:run.guide_key,state:'queued'}]}}},design,session,'hc-sr04'),identity);
});

test('normal telemetry and other component jobs do not replace the invitation source',()=>{
  const base={status:{active:null,results:[run]},error:null};
  const identity=testHelpSourceIdentity(base,design,session,'hc-sr04');
  const other={...run,id:'tft-test',component_id:'mrd-tf240-8p-cs',outcome:'passed'};
  const updated={...run,heartbeat_at:100,logs:['new log'],samples:{near:{count:100,median_cm:20}}};
  assert.equal(testHelpSourceIdentity({...base,status:{active:other,results:[updated,other],execution:{jobs:[{id:'tft-job',kind:'test',project_id:design.id,component_id:other.component_id,guide_key:componentTests.componentTestKey(design,session,other.component_id),state:'queued'}]}}},design,session,'hc-sr04'),identity);
  for(const error of ['missing_dependency',null,'connection_lost'])
    assert.equal(testHelpSourceIdentity({...base,error},design,session,'hc-sr04'),identity);
});

test('a failed preflight source changes with its job state or a newer queued job',()=>{
  const job={id:'preflight',kind:'test',project_id:design.id,component_id:'hc-sr04',guide_key:run.guide_key,state:'failed',run_id:null};
  const base={status:{active:null,results:[],execution:{jobs:[job]}},error:'missing_dependency'};
  const identity=testHelpSourceIdentity(base,design,session,'hc-sr04');
  for(const jobs of [[{...job,state:'finished'}],[job,{...job,id:'retry',state:'queued'}]])
    assert.notEqual(testHelpSourceIdentity({...base,status:{...base.status,execution:{jobs}}},design,session,'hc-sr04'),identity);
});
test('dock exposes one AI-help button beside Retest, outside test details',async()=>{
  const tests={status:{connected:true,active:null,results:[run]},error:null,pending:false};
  const html=await renderTestCard({design,session,tests,view:'dock',onDebug(){throw Error('No requests during render');}});
  assert.equal((html.match(/class="component-test-debug-action"/g)??[]).length,1);
  assert.match(html,/<div class="test-actions">[\s\S]*重新測試 HC-SR04\+[\s\S]*請 AI 幫忙/);
  assert.ok(html.indexOf('請 AI 幫忙')<html.indexOf('class="test-diagnostics"'));
  const passed=await renderTestCard({design,session,tests:{...tests,status:{...tests.status,results:[{...run,outcome:'passed',reason:null}]}},view:'dock',onDebug(){}});
  assert.doesNotMatch(passed,/請 AI 幫忙/);
});

function cardHarness(onDebug,testRun=run) {
  const states=[],refs=[];let cursor=0,refCursor=0,cleanup,effectStarted=false;
  let current={design,session,view:'dock',tests:{status:{connected:true,active:null,results:[testRun]},pending:false,error:null}};
  const hooks={...React,useEffect:effect=>{if(!effectStarted){cleanup=effect();effectStarted=true;}},useRef:initial=>refs[refCursor++]??={current:initial},useState:initial=>{
    const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
    return [states[i],next=>{states[i]=typeof next==='function'?next(states[i]):next;}];
  }};
  const fail=()=>assert.fail('AI-help must not operate hardware');
  const {ComponentTestCard}=load('../src/components/ComponentTestCard.tsx',{
    react:hooks,'../lib/useMaker':{useMakerText:()=>zh=>zh},'../lib/componentTests':componentTests,'./ComponentTestCard.css':{},
  });
  const render=(updates={})=>{current={...current,...updates};cursor=0;refCursor=0;return ComponentTestCard({...current,onDebug,onViewWiring:fail,
    tests:{...current.tests,start:fail,action:fail,invalidate:fail}});};
  const find=(node,predicate)=>{
    if(!React.isValidElement(node))return null;if(predicate(node))return node;
    for(const child of React.Children.toArray(node.props.children)){const found=find(child,predicate);if(found)return found;}
    return null;
  };
  return {render,find,unmount(){cleanup?.();}};
}
test('one explicit help click passes exact evidence; double clicks are blocked and failed sends stay retryable',async()=>{
  let resolve;const pending=new Promise(r=>{resolve=r;}),calls=[];
  const h=cardHarness((...args)=>{calls.push(args);return pending;}),before=structuredClone(run);
  const button=h.find(h.render(),n=>n.props.className==='component-test-debug-action');
  assert.equal(calls.length,0);button.props.onClick();button.props.onClick();
  assert.equal(calls.length,1);assert.equal(calls[0][0],'hc-sr04');assert.equal(calls[0][1],run.id);
  assert.strictEqual(calls[0][3].run,run);
  assert.equal(h.find(h.render(),n=>n.props.className==='component-test-debug-action').props.disabled,true);
  resolve(false);for(let i=0;i<5;i++)await Promise.resolve();
  assert.ok(h.find(h.render(),n=>n.props.role==='alert'));
  assert.equal(h.find(h.render(),n=>n.props.className==='component-test-debug-action').props.disabled,false);
  assert.deepEqual(run,before);
});
test('foreign component results do not expose a help button bound to the wrong test',()=>{
  const h=cardHarness(()=>assert.fail('Wrong test target'),{...run,component_id:'mrd-tf240-8p-cs'});
  assert.equal(h.find(h.render(),n=>n.props.className==='component-test-debug-action'),null);
});

test('untested, normal progress, success, cancellation and invalid history never expose AI help from a reason alone',async()=>{
  const states=[
    {status:{connected:false,active:null,results:[]},error:'connection_lost'},
    {status:{connected:false,active:null,results:[]},error:'executor_restart_required'},
    {status:{connected:true,active:null,results:[{...run,outcome:'passed',reason:'no_echo'}]},error:'connection_lost'},
    {status:{connected:true,active:{...run,reserved:true,outcome:'running',reason:'no_echo'},results:[]}},
    {status:{connected:true,active:{...run,reserved:true,outcome:'awaiting_confirmation',reason:'no_echo'},results:[]}},
    ...[{reason:'cancelled'},{invalidated:true},{guide_key:'old-wiring'},{revision:0},{project_id:'other-project'},{component_id:'mrd-tf240-8p-cs'}]
      .map(change=>({status:{connected:true,active:null,results:[{...run,...change}]},error:null})),
  ];
  for(const tests of states) for(const view of ['all','controls','dock']) {
    const before=structuredClone(tests);
    const html=await renderTestCard({design,session,tests,view,onDebug(){assert.fail('Rendering must not submit help');}});
    assert.doesNotMatch(html,/component-test-debug-action/);
    assert.deepEqual(tests,before);
  }
});

test('saved exact failures remain eligible, while a new queued test hides the previous result help',async()=>{
  const old={...run,created_at:1,finished_at:2};
  const tests={status:{connected:true,active:null,results:[old]},error:null};
  const historical=await renderTestCard({design,session,tests,view:'dock',onDebug(){}});
  assert.match(historical,/上次測試紀錄/);assert.match(historical,/component-test-debug-action/);
  for(const state of ['queued','preflight','running','awaiting_confirmation','blocked']) {
    const html=await renderTestCard({design,session,tests:{...tests,status:{...tests.status,execution:{jobs:[{
      id:'new-test',kind:'test',state,project_id:design.id,component_id:'hc-sr04',guide_key:run.guide_key,created_at:3,
    }]}}},view:'dock',onDebug(){}});
    assert.doesNotMatch(html,/component-test-debug-action/);
  }
});

test('only a latest failed execution job for the exact wiring can request preflight help',async()=>{
  const failed={id:'preflight-failure',kind:'test',state:'failed',project_id:design.id,component_id:'hc-sr04',
    guide_key:run.guide_key,created_at:4,reason:'missing_dependency',error:'Missing driver'};
  const tests={status:{connected:true,active:null,results:[],execution:{jobs:[failed]}},error:null};
  assert.match(await renderTestCard({design,session,tests,view:'dock',onDebug(){}}),/component-test-debug-action/);
  for(const change of [{state:'cancelled'},{reason:'cancelled'},{guide_key:'old'},{project_id:'other'},{component_id:'mrd-tf240-8p-cs'}]) {
    assert.doesNotMatch(await renderTestCard({design,session,tests:{...tests,status:{...tests.status,execution:{jobs:[{...failed,...change}]}}},view:'dock',onDebug(){}}),/component-test-debug-action/);
  }
  assert.doesNotMatch(await renderTestCard({design,session,tests:{...tests,status:{...tests.status,execution:{jobs:[failed,{...failed,id:'newer-pass',state:'finished',created_at:5}]}}},view:'dock',onDebug(){}}),/component-test-debug-action/);
});

test('current live connection or stalled-state evidence can ask for help without treating normal progress as failure',async()=>{
  for(const reason of ['connection_lost','remote_state_unknown','no_progress']) {
    const active={...run,reserved:true,outcome:'running',reason};
    const tests={status:{connected:false,active,results:[],execution:{jobs:[{id:'live-job',kind:'test',state:'running',
      project_id:design.id,component_id:'hc-sr04',guide_key:run.guide_key}]}},error:null};
    assert.match(await renderTestCard({design,session,tests,view:'dock',onDebug(){}}),/component-test-debug-action/);
    assert.doesNotMatch(await renderTestCard({design,session,tests:{...tests,status:{...tests.status,active:{...active,invalidated:true}}},view:'dock',onDebug(){}}),/component-test-debug-action/);
  }
  const active={...run,reserved:true,outcome:'running',reason:null};
  assert.match(await renderTestCard({design,session,tests:{status:{connected:false,active,results:[]},error:'API request failed'},view:'dock',onDebug(){}}),/component-test-debug-action/);
});

test('retained button callbacks cannot submit a changed target, nonproblem state, busy state or unmounted card',()=>{
  for(const change of ['component','revision','replacement-run','passed','invalidated','busy','unmount']) {
    const calls=[],h=cardHarness((...args)=>calls.push(args));
    const button=h.find(h.render(),n=>n.props.className==='component-test-debug-action');assert.ok(button);
    if(change==='component')h.render({session:{...session,componentIndex:1}});
    if(change==='revision')h.render({design:{...design,revision:2}});
    if(change==='replacement-run')h.render({tests:{status:{connected:true,active:null,results:[{...run,id:'newer-test'}]},error:null,pending:false}});
    if(change==='passed')h.render({tests:{status:{connected:true,active:null,results:[{...run,outcome:'passed',reason:null}]},error:null,pending:false}});
    if(change==='invalidated')h.render({tests:{status:{connected:true,active:null,results:[{...run,invalidated:true}]},error:null,pending:false}});
    if(change==='busy')h.render({tests:{status:{connected:true,active:null,results:[run]},error:null,pending:true}});
    if(change==='unmount')h.unmount();
    button.props.onClick();assert.equal(calls.length,0,change);
  }
});

test('a failed help send cannot leave its retry alert on a passed or replacement test',async()=>{
  for(const replacement of [{...run,outcome:'passed',reason:null},{...run,id:'replacement-test'}]) {
    const h=cardHarness(async()=>false);
    h.find(h.render(),n=>n.props.className==='component-test-debug-action').props.onClick();
    for(let i=0;i<5;i++)await Promise.resolve();
    assert.ok(h.find(h.render(),n=>n.props.role==='alert'));
    const next=h.render({tests:{status:{connected:true,active:null,results:[replacement]},error:null,pending:false}});
    assert.equal(h.find(next,n=>n.props.role==='alert'),null);
  }
});
