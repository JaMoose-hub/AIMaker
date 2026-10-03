import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {systemText} from './system_text_fixture.mjs';
import {passiveCountdown,passiveChat} from './capture_ui_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const makerCatalog = JSON.parse(read('../../profiles/component-catalog.json'));
const sessionHelpers = {};
new Function('require', 'exports', ts.transpileModule(read('../src/lib/debugSessions.ts'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText)(() => ({}), sessionHelpers);
const {sameDebugTestKeys} = sessionHelpers;
const evidenceHelpers = {};
new Function('require', 'exports', ts.transpileModule(read('../src/lib/debugEvidence.ts'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText)(() => ({}), evidenceHelpers);
const photoModule = {};
new Function('React', 'require', 'exports', ts.transpileModule(read('../src/components/PhotoEvidenceCard.tsx'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React},
}).outputText)(React, name => name === 'react' ? React : name.includes('debugEvidence') ? evidenceHelpers : {useMakerText:()=>zh=>zh}, photoModule);
const source = read('../src/components/AiDebugPanel.tsx');
const tree = ts.createSourceFile('AiDebugPanel.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let declaration;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'AiDebugPanel') declaration = node;
  ts.forEachChild(node, visit);
}
visit(tree);
assert.ok(declaration);
const js = ts.transpileModule(declaration.getText(tree).replace(/^export\s+/, ''), {
  compilerOptions: {target:ts.ScriptTarget.ES2022, jsx:ts.JsxEmit.React},
}).outputText;
const makePanel = (effect = () => {}) => new Function('React','useMakerText','useState','useEffect','useLayoutEffect','useRef','isTerminal','epochTime','componentComplete','sameDebugTestKeys','PhotoEvidenceCard','DiagramEvidenceCard','debugEvidenceUrl','evidenceSessionId','makerCatalog','systemText','useCaptureCountdown','CaptureCountdown','useChatScroll',
  `${js}; return AiDebugPanel;`)(React, () => (zh) => zh, value => [value, () => {}], effect, effect, value => ({current:value}),
    status => ['complete','stopped','error'].includes(status), value => String(value), (_, guide) => guide.complete, sameDebugTestKeys,
    photoModule.PhotoEvidenceCard,()=>null,evidenceHelpers.debugEvidenceUrl,evidenceHelpers.evidenceSessionId,makerCatalog,systemText,passiveCountdown,()=>null,passiveChat);
const AiDebugPanel = makePanel();

const context = {project:{id:'project'}, code:'draft', test_keys:{'hc-sr04':'hc-key','mrd-tf240-8p-cs':'tft-key'}, entry:{}}; // gitleaks:allow -- synthetic wiring signatures, not credentials
const state = {design:{id:'project',component_ids:['hc-sr04','mrd-tf240-8p-cs']}, guide:{complete:true}, aiModel:'codex', aiEffort:'low', debug:{}};
const base = {
  id:'session',status:'awaiting_visual',phase:'tft_visual',symptom:'screen dark',instruction:'請查看螢幕',
  capture_task:null,observations:[{id:'observation',capture_ids:['photo'],target:'tft_screen',seen:'看到紅色畫面',visibility:'clear',suggested_action:'請確認實體畫面',created_at:1}],
  evidence:[{id:'photo',target:'tft_screen',frame_id:88,source:'device',captured_at:'2026-09-25T10:00:00Z'}], jobs:[],report:null,
  test_results:[{id:'hc',component_id:'hc-sr04',outcome:'passed'},{id:'tft',component_id:'mrd-tf240-8p-cs',outcome:'awaiting_confirmation'}],
  trial_result:null,camera_verdict:'read_current_frame',binding:{project_id:'project',code_hash:'hash',test_keys:context.test_keys},
  current_target:true,camera:{source:'device',runtime_revision:4},updated_at:1,
};
function render(record=base, options={}) {
  const session = {record,conversation:options.conversation,pending:false,error:'',create(){throw Error('render must not create')},action(){throw Error('render must not act')},async contextChanged(){if(options.onContextChanged)options.onContextChanged();else throw Error('render must not mutate')}};
  const Panel = options.effects ? makePanel(effect => options.effects.push(effect)) : AiDebugPanel;
  return renderToStaticMarkup(React.createElement(Panel,{state:{...state,guide:{complete:options.wired??true},debug:{symptom:options.symptom??''}},context,currentCodeHash:options.hash??'hash',repairCaseId:options.repairCaseId??null,repairAppliedHash:options.repairAppliedHash??null,repairCandidateReady:options.repairCandidateReady??false,session,
    webcamReady:options.webcamReady??true,eyeActive:options.eyeActive??false,cameraSource:options.cameraSource??'device',cameraRuntimeRevision:options.revision??4,
    variant:options.variant??'debug',cameraStatusInView:options.cameraStatusInView??false,actionsOnly:options.actionsOnly??false,
    headerControls:options.headerControls,onReturnWebcam(){},onCase(){},onRetest(){},onTrial(){},onReviewRepair(){},onManual(){},onWiring(){}}));
}

test('camera status lives in video without duplicating the chat warning or enabling capture',()=>{
  const options={variant:'wiring',actionsOnly:true,webcamReady:false,cameraStatusInView:true};
  const html=render(null,options);
  assert(!html.includes('請確認目前影像來源持續更新'));
  assert.match(html,/<button[^>]*class="assistant-capture"[^>]*disabled=""/);
  assert(html.includes('請到即時畫面確認連線'));
  assert(render(null,{...options,cameraStatusInView:false}).includes('請確認目前影像來源持續更新'));
  assert(render(null,{...options,eyeActive:true}).includes('返回 Webcam'));
});

test('Check for me sends a visual session request with the selected cloud model and current context',async()=>{
  let sendNode;
  function find(node) { if(ts.isFunctionDeclaration(node)&&node.name?.text==='send')sendNode=node;ts.forEachChild(node,find); }
  find(tree);
  const code=ts.transpileModule(sendNode.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  for(const entry of ['', '螢幕有亮但距離不動']) {
    const calls=[];
    const bindings={entry,counting:false,chat:passiveChat(),countdown:passiveCountdown(),active:false,canStart:true,canAct:false,canMessage:false,wiringMode:false,record:null,responseMode:'fast',context,actionContext:context,state,tr:zh=>zh,setEntry(){},session:{pending:false,
      create:async(...args)=>{calls.push(args);return {id:'new-session'};},
      action(){throw Error('Fresh checks must create a visual session');}}};
    const send=new Function(...Object.keys(bindings),`${code};return send;`)(...Object.values(bindings));
    await send();
    assert.equal(calls.length,1);
    assert.equal(calls[0][0],context);
    assert.equal(calls[0][2],state.aiModel);
    assert.equal(calls[0][3],state.aiEffort);
    assert.equal(calls[0][4],'fast');
    if(entry)assert.equal(calls[0][1],entry);
    else assert.match(calls[0][1],/查看目前 Webcam 畫面/);
  }
});

test('cloud observations show the observed scene, explanation, guidance and actual model',()=>{
  const html=render({...base,model:'selected-cloud-model',instruction:'將鏡頭往右移動，避開反光',observations:[{...base.observations[0],
    model:'actual-cloud-model',source:'codex_cloud',explanation:'畫面反光遮住螢幕文字',next_step:'將鏡頭往右移動，避開反光'}]});
  assert.match(html,/看到紅色畫面/);
  assert.match(html,/畫面反光遮住螢幕文字/);
  assert.match(html,/將鏡頭往右移動，避開反光/);
  assert.match(html,/actual-cloud-model/);
  assert.doesNotMatch(html,/<small>請確認實體畫面<\/small>/);
});

test('one actionable instruction is shown even when capture, observation and report repeat it',()=>{
  const instruction='將目標移到感測器正前方，再保持不動。';
  const html=render({...base,status:'awaiting_capture',phase:'guided_observation',instruction,
    capture_task:{target:'hc_target',instruction:'將目標移到感測器正前方，再保持不動',attempts:1},
    observations:[{...base.observations[0],next_step:instruction,explanation:instruction}],
    report:{confirmed:[],uncertain:[],next_step:instruction}});
  assert.equal(html.split('將目標移到感測器正前方').length-1,1);
  assert.doesNotMatch(html,/拍攝提示|取景目標|接著做/);
});

test('a distinct framing tip stays visible alongside the current task',()=>{
  const html=render({...base,status:'awaiting_capture',phase:'guided_observation',instruction:'將目標移遠一些。',
    capture_task:{target:'hc_target',instruction:'讓感測器與目標同時入鏡。',attempts:1}});
  assert.match(html,/將目標移遠一些/);
  assert.match(html,/拍攝提示: 讓感測器與目標同時入鏡/);
});

test('the displayed scene is paired with the image actually used by that observation',()=>{
  const html=render({...base,evidence:[...base.evidence,{...base.evidence[0],id:'newer-unreviewed-photo',frame_id:99}]});
  const image=html.match(/<img[^>]*>/)?.[0]??'';
  assert.match(image,/sessions\/session\/evidence\/photo/);
  assert.doesNotMatch(image,/newer-unreviewed-photo/);
});

test('Eye requires restore before AI session start and explains model photo transfer',()=>{
  const html=render(null,{webcamReady:false,eyeActive:true});
  assert.match(html,/返回 Webcam/);
  assert.match(html,/Webcam 照片與遮蔽密碼、金鑰後的診斷資料/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>幫我檢查<\/button>/);
});

test('photo records use a header action and stay mounted in a hidden tool view',()=>{
  const html=render();
  const head=html.slice(0,html.indexOf('<div class="ai-debug-conversation"'));
  assert.match(head,/<button[^>]*aria-expanded="false"[^>]*aria-controls="ai-debug-records"[^>]*>檢查紀錄<\/button>/);
  assert.match(head,/<button[^>]*aria-controls="debug-manual-tools"[^>]*>手動測試工具<\/button>/);
  assert.match(html,/<div id="ai-debug-records" class="debug-tool-view ai-debug-records" hidden="" role="region" aria-labelledby="ai-debug-records-heading">/);
  assert.match(html,/返回對話/);
  assert.match(html,/Webcam 照片與遮蔽密碼、金鑰後的診斷資料/);
  assert.match(html,/Photos|照片、測試與工作紀錄/);
  assert.doesNotMatch(html,/ai-debug-session-details/);
});

test('compact AI header omits repeated title and model copy but keeps its accessible name and actions',()=>{
  for (const variant of ['wiring','debug']) {
    for (const record of [null,base]) {
      const html=render(record,{variant});
      const head=html.slice(0,html.indexOf('<div class="ai-debug-conversation"'));
      assert.match(head,new RegExp(`aria-label="與 AI 一起${variant==='wiring'?'接線':'除錯'}"`));
      assert.doesNotMatch(head,/<h3|ai-debug-model|ai-debug-heading|沿用目前作品與接線資料/);
      assert.match(head,/aria-controls="ai-debug-records"/);
      assert.match(head,/aria-controls="debug-manual-tools"/);
      if(record)assert.match(head,new RegExp(variant==='wiring'?'停止本次檢查':'停止本次除錯'));
      else assert.doesNotMatch(head,/停止本次/);
    }
  }
});

test('mode controls share the action header without duplicating or removing tools',()=>{
  const headerControls=React.createElement('div',{className:'guide-ai-mode-picker',role:'group','aria-label':'Assistant focus'},
    React.createElement('button',{'aria-pressed':true},'Ask about wiring'),
    React.createElement('button',{'aria-pressed':false},"Something isn't working"));
  const html=render(base,{variant:'wiring',headerControls});
  const head=html.slice(html.indexOf('<div class="ai-debug-head">'),html.indexOf('<div class="ai-debug-conversation"'));
  assert.match(head,/guide-ai-mode-picker[\s\S]*Ask about wiring[\s\S]*ai-debug-head-actions/);
  assert.equal((html.match(/role="group" aria-label="Assistant focus"/g)||[]).length,1);
  for(const action of ['停止本次檢查','檢查紀錄','手動測試工具'])assert.ok(head.includes(action));
  assert.match(read('../src/App.tsx'),/headerControls=\{headerControls\}/);
  const page=read('../src/components/DebugPage.tsx');
  assert.match(page,/headerControls:manualOpen\?undefined:modePicker/);
  assert.match(page,/!assistant \|\| manualOpen \? modePicker : null/,'mode controls remain available in manual tools');
});

test('AI can inspect the camera before wiring confirmation and without a symptom',()=>{
  const html=render(null,{wired:false});
  assert.match(html,/可以先讓 AI 看畫面並引導排查/);
  assert.match(html,/<button[^>]*>幫我檢查<\/button>/);
  assert.doesNotMatch(html,/<button[^>]*disabled=""[^>]*>幫我檢查<\/button>/);
  const blocked=render({...base,status:'paused',phase:'wiring_required'},{wired:false});
  assert.match(blocked,/完成 02 接線確認/);
  assert.doesNotMatch(blocked,/重新檢查後繼續|手動拍照|已調整，讓 AI 再看/);
});

test('camera verdict, fixed test, and whole-project outcomes stay distinct',()=>{
  const html=render();
  assert.match(html,/鏡頭讀到本次畫面/);
  assert.match(html,/零件功能: 等待實體確認/);
  assert.match(html,/整體作品: 尚未通過/);
  assert.match(html,/前往螢幕目視確認/);
  assert.match(html,/完成確認後繼續/);
  assert.match(html,/sessions\/session\/evidence\/photo/);
  assert.match(html,/停止本次除錯/);
  assert.doesNotMatch(html,/ai-debug-sticky|aria-label="除錯操作"/);
  assert.equal((html.match(/>手動測試工具<\/button>/g) ?? []).length, 1);
  assert.equal((html.match(/>停止本次除錯<\/button>/g) ?? []).length, 1);
});

test('only actual human-confirmed runs display function and trial passes',()=>{
  const confirmed = {...base,test_results:base.test_results.map(run=>({...run,outcome:'passed'})),trial_result:{id:'trial',outcome:'passed'}};
  const html=render(confirmed);
  assert.match(html,/零件功能: 功能通過/);
  assert.match(html,/整體作品: 試跑通過/);
});

test('changed draft or camera marks an old session stale and disables progression',()=>{
  for(const [record,options] of [[base,{hash:'changed'}],[base,{revision:5}],[{...base,camera_current:false},{}]]) {
    const html=render(record,options);
    assert.match(html,/作品、接線、程式或相機已變更/);
    assert.match(html,/<button[^>]*disabled=""[^>]*>完成確認後繼續<\/button>/);
    assert.doesNotMatch(html,/零件功能: 功能通過/);
  }
});

test('another project on the same Pi is visible and can be stopped without advancing its tests',()=>{
  const html=render({...base,binding:{...base.binding,project_id:'other-project'}});
  assert.match(html,/另一個作品的 AI 除錯/);
  assert.match(html,/停止本次除錯/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>完成確認後繼續<\/button>/);
});

test('confirmed code repair can resume through existing case and trial flow',()=>{
  const repair={...base,status:'awaiting_repair',phase:'repair_ready',diagnosis:{case_id:'case-1',issues:[]}};
  const pending=render(repair,{hash:'new-code'});
  assert.match(pending,/作品、接線、程式或相機已變更/);
  assert.doesNotMatch(pending,/修復已確認，接回試跑/);
  const approved=render(repair,{hash:'new-code',repairCaseId:'case-1',repairAppliedHash:'new-code'});
  assert.match(approved,/修復已改變草稿/);
  assert.match(approved,/<button[^>]*>修復已確認，接回試跑<\/button>/);
  const changedAgain=render(repair,{hash:'manual-edit',repairCaseId:'case-1',repairAppliedHash:'new-code'});
  assert.doesNotMatch(changedAgain,/修復已確認，接回試跑/);
});

test('repair choices use the matching existing case and leave candidate approval to the user',()=>{
  const repair={...base,status:'awaiting_repair',phase:'repair_ready',diagnosis:{case_id:'case-1',issues:[]},budget:{model_calls:2,max_model_calls:6}};
  const waiting=render(repair,{repairCaseId:'older-case',repairCandidateReady:true});
  assert.match(waiting,/請 AI 分析程式邏輯/);
  assert.match(waiting,/<button[^>]*disabled=""[^>]*>查看診斷與修復提案<\/button>/);
  const candidate=render(repair,{repairCaseId:'case-1',repairCandidateReady:true});
  assert.doesNotMatch(candidate,/請 AI 分析程式邏輯/);
  assert.match(candidate,/<button[^>]*>查看診斷與修復提案<\/button>/);
});

test('AI photo review does not offer another capture and partial report stays renderable',()=>{
  const html=render({...base,status:'awaiting_capture',phase:'observing_photo',model_busy:true,
    model_capture_ids:['photo'],model_started_at:Date.now()/1000-12,
    report:{next_step:'保持不動'}});
  assert.match(html,/正在分析本次拍攝的畫面 · 12 秒/);
  assert.match(html,/雲端 AI 分析中/);
  assert.doesNotMatch(html,/<strong>等待拍攝<\/strong>/);
  assert.doesNotMatch(html,/手動拍照/);
  assert.match(html,/保持不動/);
});

test('cloud guided observation asks for an explicit fresh capture after the user adjusts',()=>{
  for(const phase of ['guided_observation','capture_needed']) {
    const html=render({...base,status:'awaiting_capture',phase,model_busy:false});
    assert.match(html,/照上方指示調整後，讓 AI 再看一次/);
    assert.match(html,/<button[^>]*class="guide-primary-action"[^>]*>已調整，讓 AI 再看<\/button>/);
    assert.doesNotMatch(html,/取景到位後會自動拍攝|手動拍照/);
  }
  const initial=render({...base,status:'awaiting_capture',phase:'initial_capture',observations:[],model_busy:false});
  assert.match(initial,/取景到位後會自動拍攝/);
  assert.match(initial,/手動拍照/);
});

test('a cloud question awaits a text reply rather than another photo',()=>{
  const html=render({...base,status:'awaiting_capture',phase:'awaiting_user',instruction:'目標移遠時讀值是否改變？',
    capture_task:null,model_busy:false},{symptom:'沒有改變'});
  assert.match(html,/<strong>等待你回覆<\/strong>/);
  assert.match(html,/目標移遠時讀值是否改變/);
  assert.match(html,/回覆 AI 的問題/);
  assert.match(html,/<button[^>]*>送出<\/button>/);
  assert.doesNotMatch(html,/等待拍攝|取景到位後會自動拍攝|手動拍照|已調整，讓 AI 再看|重新拍照分析/);
});

test('capture and model failures remain visible while awaiting a user retry',()=>{
  for(const [error,message] of [['camera_frame_not_new',/還沒有取得新的鏡頭影格/],['Codex request timed out',/雲端 AI 回應逾時/]]) {
    const html=render({...base,status:'awaiting_capture',phase:'capture_needed',observations:[],error,model_busy:false});
    assert.match(html,/<p class="pi-error" role="alert">/);
    assert.match(html,message);
    assert.match(html,/重新拍照分析/);
    assert.doesNotMatch(html,/取景到位後會自動拍攝/);
  }
});

test('backend-restarted session is read only and directs stop then a fresh case',()=>{
  const html=render({...base,status:'paused',phase:'backend_restarted',error:'backend_restarted',instruction:'後端重新啟動'}, {symptom:'螢幕沒畫面'});
  assert.match(html,/重啟後的舊紀錄/);
  assert.match(html,/此案件僅供檢視，不能接續自動測試/);
  assert.match(html,/停止本次除錯/);
  assert.doesNotMatch(html,/重新檢查後繼續/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>送出<\/button>/);
});

test('stopped sessions keep read-only evidence without stale stop requests or old errors',()=>{
  const html=render({...base,status:'stopped',phase:'stopped',instruction:'本次 AI 協作除錯已停止。',
    current_target:false,error:'wiring_confirmation_required'},{hash:'changed'});
  assert.match(html,/本次 AI 協作除錯已停止/);
  assert.match(html,/看到紅色畫面/);
  assert.match(html,/sessions\/session\/evidence\/photo/);
  assert.doesNotMatch(html,/請停止舊工作階段|請回到 02 完成逐腳接線確認|class="pi-error"/);
  const failed=render({...base,status:'error',phase:'error',error:'camera_frame_unavailable'});
  assert.match(failed,/尚未收到鏡頭畫面/);
});

test('merged wiring and debug reuse the same VideoView and component test owner',()=>{
  const app=read('../src/App.tsx');
  const page=read('../src/components/DebugPage.tsx');
  const video=read('../src/components/VideoView.tsx');
  assert.equal((app.match(/<VideoView\b/g)??[]).length,1);
  assert.match(app,/<GuidePaneLayout[\s\S]*?visible=\{makerStage === "guide"\}/);
  assert.match(app,/Boolean\(projectWire \|\| diagramInspection\) && makerStage === "guide" && maker\.guide\.mode === "2d"/);
  assert.match(read('../src/lib/useComponentTests.ts'), /componentTestStore/, 'component controls share the project store');
  assert.match(video,/toDisplay\(baseLetterbox, x \* videoWidth/);
  assert.match(video,/!debugView && !glassesLeaving/);
  assert.match(app,/debugCaptureTask=\{debugCaptureSession\?\.capture_task\}/);
  assert.match(app,/debugEvidence=\{debugCaptureSession\?\.evidence\?\.at\(-1\)\}/);
  assert.match(app,/debugFramingFeedback=\{debugCaptureSession\?\.framing_feedback\}/);
  assert.match(video,/low_edge_detail/);
  assert.match(video,/exposure_clipping/);
});

test('capture guidance remains available with original Pin overlays and respects camera source and mirrors',()=>{
  const videoTree=ts.createSourceFile('VideoView.tsx',read('../src/components/VideoView.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let callback;
  function find(node) {
    if(ts.isVariableDeclaration(node)&&node.name.getText(videoTree)==='debugCaptureBox') callback=node.initializer.arguments[0];
    ts.forEachChild(node,find);
  }
  find(videoTree);assert.ok(callback);
  const body=ts.transpileModule(`return (${callback.getText(videoTree)})();`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const box=new Function('debugView','debugCaptureTask','config','glassesLeaving','baseLetterbox','videoWidth','videoHeight','toDisplay',body);
  const geometry={};new Function('require','exports',ts.transpileModule(read('../src/lib/geometry.ts'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
  }).outputText)(()=>({}),geometry);
  const task={target:'overview',instruction:'Keep the target in view'};
  for(const mx of [false,true]) for(const my of [false,true]) {
    const transform=geometry.computeLetterbox([1920,1080],800,600,mx,my);
    const selected=box(false,task,{camera_source:'device'},false,transform,1920,1080,geometry.toDisplay);
    assert.ok(selected,'Wiring mode must display the requested capture region');
    for(const [key,value] of Object.entries({left:32,top:102,width:736,height:396})) assert.ok(Math.abs(selected[key]-value)<0.001);
    for(const [capture,source,leaving] of [[null,'device',false],[task,'xreal',false],[task,'device',true]]) {
      assert.equal(box(false,capture,{camera_source:source},leaving,transform,1920,1080,geometry.toDisplay),null);
    }
  }
  assert.match(read('../src/components/VideoView.tsx'),/debugCaptureBox \? <div className="debug-capture-feedback"/);
});

test('2D preference resumes after capture without hiding the requested shared camera',()=>{
  const appTree=ts.createSourceFile('App.tsx',read('../src/App.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let initializer;
  function find(node) {
    if(ts.isVariableDeclaration(node)&&node.name.getText(appTree)==='showWiringDiagram') initializer=node.initializer;
    ts.forEachChild(node,find);
  }
  find(appTree);assert.ok(initializer);
  const show=new Function('projectWire','makerStage','maker','displayModeActive','debugCaptureSession','diagramCaptureOverride','diagramCaptureKey','calibrateOpen = false','diagramInspection = null',`return ${initializer.getText(appTree)};`);
  const maker={guide:{mode:'2d'}};
  assert.equal(show({},'guide',maker,false,null),true);
  assert.equal(show({},'guide',maker,false,{capture_task:{target:'pi_header'}},null,'new-capture'),false);
  assert.equal(show({},'guide',maker,false,null),true);
  assert.equal(maker.guide.mode,'2d');
  assert.equal(show({},'guide',maker,true,null),false);
});

test('camera guidance clears when a session is stopped, stale or awaiting a text answer',()=>{
  const app=read('../src/App.tsx');
  const appTree=ts.createSourceFile('App.tsx',app,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let initializer;
  function find(node) {
    if(ts.isVariableDeclaration(node)&&node.name.getText(appTree)==='debugCaptureSession') initializer=node.initializer;
    ts.forEachChild(node,find);
  }
  find(appTree);
  assert.ok(initializer);
  const select=new Function('makerStage','aiDebug',`return ${initializer.getText(appTree)};`);
  const capturing={...base,status:'awaiting_capture',phase:'guided_observation',capture_task:{target:'hc_target',instruction:'靠近接頭'}};
  assert.equal(select('guide',{record:capturing}),capturing);
  const observing={...capturing,phase:'observing_photo',model_busy:true};
  assert.equal(select('guide',{record:observing}),observing);
  for(const record of [null,
    ...['stopped','complete','error','paused','testing'].map(status=>({...capturing,status})),
    ...['awaiting_user','context_changed','camera_changed','backend_restarted'].map(phase=>({...capturing,phase})),
    {...capturing,current_target:false},{...capturing,camera_current:false}]) {
    assert.equal(select('guide',{record}),null);
  }
  assert.equal(select('deploy',{record:capturing}),null, 'capture overlays stay in the merged wiring workspace');
});

test('persisted conversation renders once in chronological order with only its own image attachments',()=>{
  const messages=[
    {id:'u1',role:'user',text:'距離一直不動',created_at:1},
    {id:'a1',role:'assistant',text:'目標是否在正前方？',created_at:2,capture_ids:['photo'],model:'cloud-model',elapsed_ms:2450},
    {id:'u2',role:'user',text:'我剛把目標放回正前方',created_at:3},
    {id:'a2',role:'assistant',text:'把目標移遠一點後再確認讀值。',created_at:4,capture_ids:[],model:'cloud-model',elapsed_ms:1300},
  ];
  const html=render({...base,status:'awaiting_capture',phase:'awaiting_user',messages,instruction:messages.at(-1).text});
  assert.match(html,/role="log"[^>]*aria-label="AI 除錯對話"/);
  let previous=-1;
  for(const message of messages) {
    const position=html.indexOf(message.text);
    assert.ok(position>previous,'server message order must be retained');
    assert.equal(html.split(message.text).length-1,1,'no duplicated instruction or legacy observation');
    previous=position;
  }
  assert.doesNotMatch(html,/看到紅色畫面/);
  const lastBubble=html.slice(html.indexOf('data-message-id="a2"'),html.indexOf('class="ai-debug-current"'));
  assert.doesNotMatch(lastBubble,/<img/,'text-only replies must not appear to see another frame');
  assert.equal((html.match(/<img/g)??[]).length,1);
  assert.ok(html.indexOf('id="ai-debug-message"')>previous,'composer follows the conversation');
  assert.match(html,/2\.5 s/);
});

test('IME confirmation and Shift Enter do not send; plain Enter sends one message',()=>{
  let handler;
  function find(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='onComposerKeyDown')handler=node;ts.forEachChild(node,find);}
  find(tree);
  assert.ok(handler);
  const code=ts.transpileModule(handler.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  let sends=0,prevented=0;
  const composing={current:false};
  const onKeyDown=new Function('composing','send',`${code};return onComposerKeyDown;`)(composing,()=>{sends++;});
  const event=overrides=>({key:'Enter',shiftKey:false,keyCode:13,nativeEvent:{isComposing:false},preventDefault(){prevented++;},...overrides});
  onKeyDown(event({shiftKey:true}));
  onKeyDown(event({nativeEvent:{isComposing:true}}));
  onKeyDown(event({keyCode:229}));
  composing.current=true;
  onKeyDown(event({}));
  composing.current=false;
  assert.equal(sends,0);
  assert.equal(prevented,0);
  onKeyDown(event({}));
  assert.equal(sends,1);
  assert.equal(prevented,1);
});

test('text-only cloud work describes conversation processing and keeps composing available',()=>{
  const html=render({...base,model_busy:true,model_started_at:Date.now()/1000-35,model_capture_ids:[]});
  assert.match(html,/正在閱讀你的訊息與除錯紀錄/);
  assert.match(html,/這一輪需要較久時間/);
  assert.doesNotMatch(html,/正在分析本次拍攝的畫面/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>送出<\/button>/);
  assert.doesNotMatch(html,/<textarea[^>]*disabled/);
  assert.match(html,/>快速引導<\/option>/);
  assert.match(html,/>深入分析<\/option>/);
});

test('a fresh server camera revision does not invalidate a session while browser config catches up',()=>{
  const fresh={...base,status:'diagnosing',phase:'environment',camera_current:true,camera:{source:'device',runtime_revision:2},
    binding:{...base.binding,test_keys:{'mrd-tf240-8p-cs':'tft-key','hc-sr04':'hc-key'}}};
  for(const [record,revision,expected] of [[fresh,1,0],[fresh,2,0],[fresh,3,1],[{...fresh,camera_current:false},1,1]]) {
    const effects=[];let notifications=0;
    const html=render(record,{revision,effects,onContextChanged(){notifications++;}});
    for(const effect of effects)effect();
    assert.equal(notifications,expected,`revision ${revision}, current ${record.camera_current}`);
    if(expected===0)assert.doesNotMatch(html,/作品、接線、程式或相機已變更/);
  }
});

test('wire binding maps ignore property order but still detect changed, added and removed wires',()=>{
  assert.equal(sameDebugTestKeys({'hc':'a','tft':'b'},{'tft':'b','hc':'a'}),true);
  assert.equal(sameDebugTestKeys({'hc':'a','tft':'b'},{'tft':'c','hc':'a'}),false);
  assert.equal(sameDebugTestKeys({'hc':'a'},{'tft':'b','hc':'a'}),false);
  assert.equal(sameDebugTestKeys({'hc':'a','tft':'b'},{'hc':'a'}),false);
});

test('late stopped-session polls cannot replace the id or storage of a new session',async()=>{
  const hookTree=ts.createSourceFile('debugSessions.ts',read('../src/lib/debugSessions.ts'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
  let poll;
  function find(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='poll')poll=node;ts.forEachChild(node,find);}
  find(hookTree);assert.ok(poll);
  const code=ts.transpileModule(poll.getText(hookTree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  for(const failure of [false,true]) {
    let resolve,reject;
    const response=new Promise((ok,no)=>{resolve=ok;reject=no;});
    const writes=[];
    const controller=new AbortController(),epoch={current:0},flight={current:false},mounted={current:true};
    const bindings={epoch,flight,mounted,controller,sessionId:'stopped-old',projectId:'project',timer:0,POLL_MS:1500,
      makerRequest:()=>response,isTerminal:status=>status==='stopped',saveSession(...args){writes.push(['save',...args]);},
      forgetSession(...args){writes.push(['forget',...args]);},setSessionId(id){writes.push(['id',id]);},setRecord(next){writes.push(['record',next]);},setError(error){writes.push(['error',error]);},window:{setTimeout(){return 1;}}};
    const run=new Function(...Object.keys(bindings),`${code};return poll;`)(...Object.values(bindings));
    const pending=run();
    epoch.current++; // Creating the replacement invalidates this old GET.
    if(failure)reject(Object.assign(new Error('session_not_found'),{status:404}));else resolve({...base,id:'stopped-old',status:'stopped'});
    await pending;
    assert.deepEqual(writes,[],'outdated polls must not mutate any visible or persisted state');
  }
});

test('wiring questions start a text review while an explicit capture requests a new photo',async()=>{
  let sendNode,captureNode;
  function find(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='send')sendNode=node;if(ts.isFunctionDeclaration(node)&&node.name?.text==='captureStep')captureNode=node;ts.forEachChild(node,find);}
  find(tree);
  const calls=[];
  const bindings={entry:'ECHO 要接哪裡？',counting:false,chat:passiveChat(),countdown:passiveCountdown(),canCaptureWiring:true,active:false,canStart:true,canAct:false,canMessage:false,wiringMode:true,record:null,webcamReady:true,responseMode:'fast',actionContext:context,state,tr:zh=>zh,setEntry(){},session:{pending:false,create:async(...args)=>{calls.push(args);return {id:'created'};}}};
  for(const node of [sendNode,captureNode]){
    const code=ts.transpileModule(node.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
    await new Function(...Object.keys(bindings),`${code};return ${node.name.text};`)(...Object.values(bindings))();
  }
  assert.equal(calls.length,2);
  assert.deepEqual(calls[0][5],{purpose:'wiring_review'});
  assert.deepEqual(calls[1][5],{purpose:'wiring_review',initial_action:'capture'});
});

test('wiring text remains available without Webcam and does not imply any hardware operation',()=>{
  const html=render(null,{variant:'wiring',webcamReady:false,symptom:'這條線是接哪一腳？'});
  assert.match(html,/Pi 尚未開機也可以先討論/);
  assert.match(html,/仍可先詢問接法/);
  assert.match(html,/<button[^>]*>送出<\/button>/);
  assert.match(html,/<button[^>]*disabled=""[^>]*>拍攝這一步<\/button>/);
  assert.match(html,/<button[^>]*aria-controls="debug-manual-tools"[^>]*>手動測試工具<\/button>/);
  assert.doesNotMatch(html,/幫我檢查<\/button>/);
});

test('shared history retains old-check photo ownership and survives without a live session',()=>{
  const conversation={id:'conversation',messages:[{id:'historic',session_id:'older-check',role:'assistant',text:'先前這張圖看到接頭',capture_ids:['photo'],created_at:0}],
    evidence:[{...base.evidence[0],session_id:'older-check'}],diagrams:[]};
  for(const record of [base,null]){
    const html=render(record,{conversation});
    assert.match(html,/先前這張圖看到接頭/);
    const historic=html.slice(html.indexOf('data-message-id="historic"'),html.indexOf('</article>',html.indexOf('data-message-id="historic"')));
    assert.match(historic,/sessions\/older-check\/evidence\/photo/);
    assert.doesNotMatch(historic,/sessions\/session\/evidence\/photo/);
  }
  const expired=render(base,{conversation:{...conversation,evidence:[]}});
  const historic=expired.slice(expired.indexOf('data-message-id="historic"'),expired.indexOf('</article>',expired.indexOf('data-message-id="historic"')));
  assert.match(historic,/此輪照片已過期/);
  assert.doesNotMatch(historic,/<img/,'the current session must not impersonate missing historical evidence');
});

test('a fresh budget requires the explicit new-check action and stops the prior check first',async()=>{
  let declaration;
  function find(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='startNewCheck')declaration=node;ts.forEachChild(node,find);}
  find(tree);
  const code=ts.transpileModule(declaration.getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const calls=[];
  const bindings={canStart:true,counting:false,chat:passiveChat(),countdown:passiveCountdown(),active:true,record:{...base,purpose:'wiring_review'},entry:'',actionContext:context,state,responseMode:'fast',wiringMode:true,tr:zh=>zh,setEntry(){},
    session:{pending:false,action:async(name)=>{calls.push(name);return {status:'stopped'};},create:async(...args)=>{calls.push(['create',args[5]]);return {id:'new'};}}};
  const start=new Function(...Object.keys(bindings),`${code};return startNewCheck;`)(...Object.values(bindings));
  assert.deepEqual(calls,[]);
  await start();
  assert.deepEqual(calls,['stop',['create',{purpose:'wiring_review'}]]);
  const html=render({...base,status:'paused',phase:'model_limit',error:'model_call_limit_reached'});
  assert.match(html,/開始新一輪檢查/);
  assert.match(html,/保留對話與先前證據/);
});

test('rapid wiring confirmations retry the newest context after an earlier refresh finishes',async()=>{
  let callback;
  function find(node){if(ts.isCallExpression(node)&&node.expression.getText(tree)==='useEffect'&&node.arguments[0]?.getText(tree).includes('const changedKey ='))callback=node.arguments[0];ts.forEachChild(node,find);}
  find(tree);assert.ok(callback);
  const code=ts.transpileModule(`const refreshEffect = ${callback.getText(tree)};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const staleNotified={current:null},calls=[];
  let pending=false,finish;
  const session={async contextChanged(next){if(pending)return;pending=true;calls.push(next);await new Promise(resolve=>{finish=resolve;});pending=false;return base;}};
  const first={...context,test_keys:{hc:'first-confirmation'}},latest={...context,test_keys:{hc:'second-confirmation'}};
  function effect(next){const bindings={record:base,active:true,current:false,approvedRepairCode:false,sameProject:true,currentCodeHash:'hash',cameraSource:'device',cameraRuntimeRevision:4,context:next,actionContext:next,staleNotified,session};return new Function(...Object.keys(bindings),`${code};return refreshEffect;`)(...Object.values(bindings));}
  effect(first)();
  effect(latest)();
  await Promise.resolve();
  assert.equal(staleNotified.current,null,'an in-flight or skipped refresh cannot acknowledge newer wiring');
  finish();await Promise.resolve();await Promise.resolve();
  effect(latest)();
  assert.deepEqual(calls,[first,latest],'the second confirmation must not remain permanently stale');
  finish();await Promise.resolve();await Promise.resolve();
});
