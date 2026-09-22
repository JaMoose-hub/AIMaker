import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {maker,componentTests,designFor,renderGuide} from './project_guide_fixture.mjs';

// Execute the real event/effect bodies with deterministic DOM and hook ports.
// Browser acceptance additionally verifies React's actual commit/scroll behavior.
function debugFunction(name, bindings) {
  const source=readFileSync(new URL('../src/components/DebugPage.tsx',import.meta.url),'utf8');
  const tree=ts.createSourceFile('DebugPage.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let match;
  function visit(node) {if(ts.isFunctionDeclaration(node)&&node.name?.text===name)match=node;ts.forEachChild(node,visit);}
  visit(tree); assert.ok(match,`${name} must exist`);
  const js=ts.transpileModule(match.getText(tree).replace(/^export\s+/,''),{compilerOptions:{target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText;
  return new Function(...Object.keys(bindings),`${js};return ${name};`)(...Object.values(bindings));
}

function renderDebug({record=null,connected=true,trial=null,locale='zh-TW',selected='hc-sr04',design=designFor(['hc-sr04','mrd-tf240-8p-cs'])}={}) {
  const state={...maker.initialMaker(),design,code:'',debug:{source:'guide',componentId:'hc-sr04',selectedComponentId:selected,runId:'technical-run-id',symptom:'no_echo'}};
  const Page=debugFunction('DebugPage',{
    React,useMakerText:()=> (zh,en)=>locale==='zh-TW'?zh:en,
    useState:value=>[value,()=>{}],useEffect(){},useMemo:fn=>fn(),useRef:()=>({current:null}),
    usePiConnection:()=>({status:{connected},networkError:false,pending:false}),
    useDebug:()=>({record,pending:false,error:'',trials:{active:trial,results:[]},action(){throw Error('Render cannot run an action');}}),
    componentTestKey:componentTests.componentTestKey,testReasons:componentTests.testReasons,
    TargetedTest:({before,after,report})=>React.createElement('div',{className:'debug-workspace'},before,React.createElement('section',{'data-testid':'targeted-test'}),after,React.createElement('aside',{className:'debug-results'},report)),codeHash:()=>Promise.resolve(''),
  });
  return renderToStaticMarkup(React.createElement(Page,{state,onCase(){},onCode(){},onWiring(){},onDeploy(){},onSelect(){}}));
}

const freshRecord={id:'case',status:'ready',progress:'finished',rounds:0,binding:{code_hash:'',project_id:'layout-fixture',test_keys:Object.fromEntries(['hc-sr04','mrd-tf240-8p-cs'].map(id=>[id,componentTests.componentTestKey(designFor(['hc-sr04','mrd-tf240-8p-cs']),maker.initialMaker().guide,id)]))},evidence:{tests:[],pi:{program:'stopped'}}};

test('recommendations and report evidence follow the selected component',()=>{
  const record={...freshRecord,issues:[{reason:'no_echo',component_id:'hc-sr04'},{reason:'stale_result',component_id:'mrd-tf240-8p-cs'}],evidence:{tests:[{component_id:'hc-sr04',logs:['HC_ONLY_LOG']},{component_id:'mrd-tf240-8p-cs',logs:['TFT_ONLY_LOG']}]}};
  for(const selected of ['hc-sr04','mrd-tf240-8p-cs']) {
    const html=renderDebug({record,selected});
    const problem=html.match(/<section class="debug-problem">[\s\S]*?<\/section>/)?.[0] ?? '';
    const report=html.slice(html.indexOf('<details class="workflow-details debug-report">'));
    if(selected==='hc-sr04') {
      assert.match(problem,/先讓 HC-SR04\+ 測到距離/);assert.doesNotMatch(problem,/MRD-TFT240/);
      assert.match(report,/HC_ONLY_LOG/);assert.doesNotMatch(report,/TFT_ONLY_LOG/);
    } else {
      assert.match(problem,/MRD-TFT240/);assert.doesNotMatch(problem,/先讓 HC-SR04/);
      assert.match(report,/TFT_ONLY_LOG/);assert.doesNotMatch(report,/HC_ONLY_LOG/);
    }
  }
});

test('AI details are nested and closed even when a long saved analysis exists',()=>{
  const record={...freshRecord,analysis:{facts:'technical-facts '.repeat(80),possible_causes:'possible-cause',next_step:'raw-next-step'}};
  const html=renderDebug({record});
  assert.match(html,/AI 已完成分析/);
  assert.match(html,/目前沒有可直接套用的修改/);
  assert.match(html,/<details class="debug-analysis-details"><summary>查看完整 AI 分析（進階）/);
  assert.match(html,/technical-facts/,'the full record remains available');
  const unknown=renderDebug({record:{...freshRecord,issues:[{reason:'INTERNAL_UNMAPPED_CODE',next_action:'analyse'}]}});
  const problem=unknown.match(/<section class="debug-problem">[\s\S]*?<\/section>/)?.[0] ?? '';
  assert.doesNotMatch(problem,/INTERNAL_UNMAPPED_CODE/);
});

test('component choices only include modules used by the project',()=>{
  const empty=renderDebug({design:null});
  assert.doesNotMatch(empty,/class="debug-symptom" aria-controls="debug-targeted-retest"/);
  assert.match(empty,/先建立作品/);
  const hcOnly=renderDebug({design:designFor(['hc-sr04'])});
  const choices=hcOnly.slice(hcOnly.indexOf('class="debug-symptom-picker"'),hcOnly.indexOf('<section data-testid="targeted-test"'));
  assert.match(choices,/測不到距離/);
  assert.doesNotMatch(choices,/沒有畫面，或顏色不對/);
});

test('trial tools start folded, but active trials and visual confirmation open on restore',()=>{
  assert.match(renderDebug(),/<details class="debug-tool"><summary><strong>零件都好了/);
  for(const [reserved,outcome] of [[true,'running'],[false,'awaiting_confirmation']]) {
    const trial={id:'run',project_id:'layout-fixture',binding:freshRecord.binding,outcome,reserved,created_at:1};
    const html=renderDebug({trial});
    assert.match(html,/<details class="debug-tool" open=""><summary><strong>零件都好了/);
    assert.match(html,reserved?/停止本次試跑/:/送出本次目視確認/);
  }
});

test('real component workspace uses one controller with controls left and results right',()=>{
  for(const active of [null,{id:'live'}]) {
    const Card=debugFunction('TargetedTest',{
      React,useMakerText:()=>zh=>zh,useRef:()=>({current:null}),useEffect(){},componentComplete:componentTests.componentComplete,
      useComponentTests:()=>({status:{active},action(){throw Error('Rendering must not operate hardware');}}),
      ComponentTestCard:()=>React.createElement('button',null,active?'停止本次測試':'測試零件'),
    });
    const html=renderToStaticMarkup(React.createElement(Card,{design:designFor(),guide:maker.emptyGuide(),cid:'hc-sr04',focusRequest:0,onWiring(){}}));
    if(active) { assert.doesNotMatch(html,/<details class="debug-tool"/);assert.match(html,/停止本次測試/); }
    else assert.match(html,/接線未確認/);
    assert.match(html,/class="debug-controls"/);
    assert.match(html,/class="debug-results"/);
  }
});

test('friendly debug starts with a next step and keeps engineering reports in closed details',()=>{
  const html=renderDebug();
  assert.match(html,/哪個地方沒有正常運作/);
  assert.match(html,/測不到距離，或數字不對/);
  assert.match(html,/沒有畫面，或顏色不對/);
  assert.match(html,/作品沒有反應，或出現錯誤/);
  assert.match(html,/<details class="debug-overview"><summary>/);
  assert.match(html,/先做一次快速檢查/);
  assert.match(html,/<details class="debug-agent workflow-details"><summary>/);
  assert.match(html,/<details class="workflow-details debug-report"><summary>/);
  const summary=html.slice(0,html.indexOf('<details class="workflow-details debug-report">'));
  assert.doesNotMatch(summary,/technical-run-id|問題來源/);
  assert.match(html,/technica/); // short run ID retained, not removed
  const english=renderDebug({locale:'en'});
  assert.match(english,/Check for me/);
  assert.match(english,/Detailed check report/);
});

test('no echo suggests a target, while setup errors never recommend rewiring',()=>{
  const noEcho=renderDebug({record:{...freshRecord,issues:[{reason:'no_echo',next_action:'target_then_wiring',component_id:'hc-sr04'}]}});
  assert.match(noEcho,/先讓 HC-SR04\+ 測到距離/);
  assert.match(noEcho,/一本書或平整物體/);
  assert.match(noEcho,/現在不能判定接錯線/);
  const setup=renderDebug({record:{...freshRecord,issues:[{reason:'missing_dependency',next_action:'prepare_environment',fact:'missing-package'}]}});
  assert.match(setup,/先把 Pi 的測試工具準備好/);
  assert.match(setup,/請勿為此改接線/);
  assert.match(setup,/missing-package/);
});

test('stale diagnoses and disconnected Pi cannot look like a current successful check',()=>{
  const stale=renderDebug({record:{...freshRecord,binding:{...freshRecord.binding,code_hash:'old'},issues:[{reason:'no_echo',component_id:'hc-sr04'}]}});
  assert.match(stale,/作品有更新，再檢查一次/);
  assert.doesNotMatch(stale,/先讓 HC-SR04\+ 測到距離|前往此零件重測/);
  const offline=renderDebug({record:freshRecord,connected:false});
  assert.match(offline,/還沒連上/);
  assert.doesNotMatch(offline,/class="debug-problem"|目前沒有找到阻礙執行的問題/);
});

test('disconnected debug has no duplicate connection card, but retains tests, reports and active controls',()=>{
  for(const locale of ['zh-TW','en']) {
    for(const record of [null,freshRecord,{...freshRecord,binding:{...freshRecord.binding,code_hash:'old'}}]) {
      const trial={id:'run',project_id:'layout-fixture',binding:freshRecord.binding,outcome:'running',reserved:true,created_at:1};
      const html=renderDebug({record,connected:false,locale,trial});
      assert.doesNotMatch(html,/class="debug-problem"|先連上你的 Pi|重新連線 Pi|First, connect your Pi|Reconnect Pi/);
      assert.match(html,/data-testid="targeted-test"/);
      assert.match(html,/<details class="workflow-details debug-report">/);
      assert.match(html,locale==='zh-TW'?/停止本次試跑/:/Stop this trial/);
    }
  }
});

test('connection-only diagnosis stays in the report even if toolbar status has not updated yet',()=>{
  for(const connected of [true,false]) {
    const html=renderDebug({connected,record:{...freshRecord,issues:[{reason:'connection_lost',next_action:'reconnect',fact:'connection-evidence'}]}});
    const main=html.slice(0,html.indexOf('<details class="workflow-details debug-report">'));
    assert.doesNotMatch(main,/class="debug-problem"|connection-evidence|目前沒有找到阻礙執行的問題/);
    assert.match(html,/connection-evidence/);
  }
});

test('real test and code problems remain visible without a duplicate reconnect recommendation',()=>{
  for(const [reason,next_action,component_id,title] of [
    ['no_echo','target_then_wiring','hc-sr04',/先讓 HC-SR04\+ 測到距離/],
    ['missing_dependency','prepare_environment',undefined,/先把 Pi 的測試工具準備好/],
    ['syntax_error','analyse',undefined,/程式有一段寫法需要修正/],
  ]) {
    for(const connected of [true,false]) {
      const html=renderDebug({connected,record:{...freshRecord,issues:[{reason:'connection_lost',next_action:'reconnect'},{reason,next_action,component_id}]}});
      assert.match(html,/class="debug-problem"/);
      assert.match(html,title);
      assert.doesNotMatch(html,/重新連線 Pi|先連上你的 Pi/);
      if(connected&&component_id)assert.match(html,/重測 HC-SR04\+/);
    }
  }
});

test('diagnosis in progress asks the user to wait rather than suggesting a result',()=>{
  const html=renderDebug({record:{...freshRecord,status:'diagnosing',progress:'environment'}});
  const problem=html.match(/<section class="debug-problem">[\s\S]*?<\/section>/)?.[0] ?? '';
  assert.match(problem,/檢查完成後會告訴你下一步/);
  assert.doesNotMatch(problem,/目前沒有找到|可以做一次 60 秒試跑/);
});

test('next steps distinguish software, runtime records and setup problems',()=>{
  const renderIssue=(reason,next_action)=>renderDebug({record:{...freshRecord,issues:[{reason,next_action}]}});
  assert.match(renderIssue('telemetry_unknown','trial'),/前往 60 秒試跑/);
  assert.match(renderIssue('syntax_error','analyse'),/看看 AI 可以怎麼幫忙/);
  assert.match(renderIssue('spi_missing','prepare_environment'),/查看需要處理的項目/);
  assert.match(renderIssue('resource_busy','execution_manager'),/查看上方「執行管理」/);
});

test('trial stop and physical confirmation stay visible, outside collapsed AI and reports',()=>{
  const trial={id:'run',project_id:'layout-fixture',binding:freshRecord.binding,outcome:'running',reserved:true,created_at:1};
  const active=renderDebug({trial});
  const card=active.slice(active.indexOf('<section class="debug-trial"'),active.indexOf('<details class="workflow-details debug-report">'));
  assert.match(card,/停止本次試跑/);
  const confirmation=renderDebug({trial:{...trial,reserved:false,outcome:'awaiting_confirmation'}});
  assert.match(confirmation,/我已觀察本次實體反應/);
  assert.match(confirmation,/<button disabled="">送出本次目視確認/);
});

test('retest navigation responds again for the already selected module without starting tests',()=>{
  const selected=[]; let request=0;
  const open=debugFunction('openRetest',{
    state:{design:designFor(['hc-sr04','mrd-tf240-8p-cs'])},
    onSelect:id=>selected.push(id),setProgramSelected(){},setRetestFocusRequest:update=>{request=update(request);},
  });
  open('hc-sr04');open('hc-sr04');open('mrd-tf240-8p-cs');open('unknown');
  assert.deepEqual(selected,['hc-sr04','hc-sr04','mrd-tf240-8p-cs']);
  assert.equal(request,3);
});

test('retest card focuses after selection; initial render and telemetry polls never steal focus',()=>{
  const calls=[];let previousDeps, pendingEffect;
  const details={open:false};
  const ref={current:{querySelector:()=>details,focus:options=>calls.push(['focus',options]),scrollIntoView:options=>calls.push(['scroll',options])}};
  const Card=debugFunction('TargetedTest',{
    useMakerText:()=>zh=>zh,useRef:()=>ref,componentComplete:componentTests.componentComplete,
    useEffect:(effect,deps)=>{if(!previousDeps||deps.some((value,index)=>value!==previousDeps[index]))pendingEffect=effect;previousDeps=deps;},
    useComponentTests:()=>({status:{active:null,results:[]},start(){throw Error('Navigation must not start hardware');}}),
    ComponentTestCard:()=>null,React:{createElement:(type,props,...children)=>({type,props,children})},
  });
  const render=(cid,focusRequest)=>{const view=Card({design:designFor(['hc-sr04','mrd-tf240-8p-cs']),guide:maker.emptyGuide(),cid,focusRequest,onWiring(){throw Error('Must not edit wiring');}});if(pendingEffect){const effect=pendingEffect;pendingEffect=null;effect();}return view;};
  assert.equal(render('hc-sr04',0).props.className,'debug-workspace');
  assert.equal(calls.length,0);
  const view=render('hc-sr04',1);
  assert.equal(view.props.className,'debug-workspace');
  assert.deepEqual(calls,[['focus',{preventScroll:true}]]);
  render('hc-sr04',1);assert.equal(calls.length,1);
  render('hc-sr04',2);assert.equal(calls.length,2);
  render('mrd-tf240-8p-cs',3);assert.equal(calls.length,3);
});

test('five-stage debug navigation restores old deploy and no-project debug',()=>{
  for(const stage of ['design','blueprint','guide','debug','deploy']) {
    const state={...maker.initialMaker(),design:designFor(),stage};
    assert.equal(maker.restoreMaker(JSON.stringify(state)).stage,stage);
  }
  assert.equal(maker.restoreMaker(JSON.stringify({...maker.initialMaker(),stage:'debug'})).stage,'debug');
  const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.match(app,/\["design", "blueprint", "guide", "debug", "deploy"\]/);
  assert.match(app,/onDebug=\{openDebug\}/);
});

test('logic-only draft changes preserve component test bindings and debug context',()=>{
  const state={...maker.initialMaker(),design:designFor(),debug:{caseId:'case',componentId:'hc-sr04',runId:'run',source:'guide'}};
  const before=componentTests.testBindings(state);
  const changed={...state,code:'new application logic',stage:'debug'};
  assert.deepEqual(componentTests.testBindings(changed),before);
  assert.deepEqual(maker.restoreMaker(JSON.stringify(changed)).debug,state.debug);
});

test('retest selection is separate from the original diagnostic evidence',()=>{
  const state={...maker.initialMaker(),design:designFor(['hc-sr04','mrd-tf240-8p-cs']),debug:{caseId:'case',componentId:'hc-sr04',selectedComponentId:'mrd-tf240-8p-cs',runId:'hc-run',source:'guide',symptom:'no_echo'}};
  const restored=maker.restoreMaker(JSON.stringify(state));
  assert.equal(restored.debug.selectedComponentId,'mrd-tf240-8p-cs');
  assert.equal(restored.debug.componentId,'hc-sr04');
  assert.equal(restored.debug.runId,'hc-run');
  const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.match(app,/onSelect=\{selectedComponentId=>setMaker\(s=>\(\{\.\.\.s,debug:\{\.\.\.s.debug,selectedComponentId\}\}\)\)\}/);
});

test('inspect wiring shows return/edit actions without consuming confirmations',async()=>{
  const design=designFor();
  const guide={...maker.emptyGuide(),phase:'active',inspection:true};
  const before=JSON.stringify(guide);
  const html=await renderGuide({design,session:guide});
  assert.match(html,/返回除錯/);assert.match(html,/我要修改此零件接線/);
  assert.doesNotMatch(html,/我已接好，下一步/);
  assert.equal(JSON.stringify(guide),before);
});

test('debug requests do not auto post/retry on mount and fixed telemetry slots exist',()=>{
  const hook=readFileSync(new URL('../src/lib/debug.ts',import.meta.url),'utf8');
  const effect=hook.slice(hook.indexOf('useEffect('),hook.indexOf('async function action'));
  assert.doesNotMatch(effect,/"POST"|request_id|action:"/);
  assert.match(effect,/controller.abort\(\)/);assert.match(effect,/version === epoch.current/);
  assert.match(effect,/Promise.allSettled/); // historical case failure must not hide active trial controls
  const css=readFileSync(new URL('../src/debug.css',import.meta.url),'utf8');
  assert.match(css,/grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(css,/font-variant-numeric:tabular-nums/);
  const page=readFileSync(new URL('../src/components/DebugPage.tsx',import.meta.url),'utf8');
  assert.match(page,/確認草稿變更/);assert.match(page,/visualRun!==trial.id/);
  assert.doesNotMatch(page,/cloud-wiring|photo-check/);
});
