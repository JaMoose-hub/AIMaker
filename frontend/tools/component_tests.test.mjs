import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {componentTests as logic, designFor, maker, renderGuide} from './project_guide_fixture.mjs';

function complete(design) {
  let session = maker.startProjectGuide(maker.emptyGuide());
  while (session.phase === 'active') session = maker.confirmProjectWire(design,session);
  return session;
}
function runFor(design, session, overrides={}) {
  return {id:'run-1',project_id:design.id,revision:design.revision,component_id:design.component_ids[0],
    guide_key:logic.componentTestKey(design,session,design.component_ids[0]),template_version:'v1',wiring_hash:'test',
    created_at:1000,finished_at:1005,outcome:'inconclusive',phase:'finished',reason:'no_echo',detail:'',logs:[],
    samples:{},latest:null,heartbeat_at:1000,exit_code:0,reserved:false,program_stopped:false,invalidated:false,
    options:['1234','2468','4567','7890'],...overrides};
}
const state = run => ({status:{connected:true,test_busy:run.reserved,active:run.reserved?run:null,results:[run]}});

test('each module requires every real manual confirmation, not review phase or camera',async()=>{
  for(const cid of ['hc-sr04','mrd-tf240-8p-cs']) {
    const design=designFor([cid]);
    let session=maker.startProjectGuide(maker.emptyGuide());
    for(let i=0;i<design.wiring.length;i++) {
      assert.equal(logic.componentComplete(design,session,cid),false);
      assert.ok(!(await renderGuide({design,session:{...session,phase:'review'}})).includes('component-test-card'));
      session=maker.confirmProjectWire(design,session);
    }
    assert.equal(logic.componentComplete(design,session,cid),true);
    const html=await renderGuide({design,session,poseReady:false,cloudAI:{available:false}});
    assert.ok(html.includes(`測試 ${cid==='hc-sr04'?'HC-SR04+':'MRD-TFT240'}`));
    assert.ok(html.includes('未測試')&&html.includes('稍後測試'));
    assert.ok(!html.includes('cloud-result')&&!html.includes('AI 檢查'));
  }
});

test('restart, changed profile, revision, pin and reconfirmed wire invalidate test key',()=>{
  const design=designFor(), session=complete(design), key=logic.componentTestKey(design,session,'hc-sr04');
  assert.notEqual(logic.componentTestKey(design,maker.restartProjectGuide(session),'hc-sr04'),key);
  assert.notEqual(logic.componentTestKey({...design,revision:2},session,'hc-sr04'),key);
  const modified=structuredClone(design);modified.wiring[0].boardPin='GPIO26';
  assert.notEqual(logic.componentTestKey(modified,session,'hc-sr04'),key);
  const restored=structuredClone(session);restored.confirmed[design.wiring[0].id].at='new-time';
  assert.notEqual(logic.componentTestKey(design,restored,'hc-sr04'),key);
  const pending=structuredClone(session);delete pending.confirmed[design.wiring[0].id];
  assert.equal(logic.componentComplete(design,pending,'hc-sr04'),false);
  assert.notEqual(logic.componentTestKey({...design,profile_versions:{'hc-sr04':{version:'new',sha256:'hash'}}},session,'hc-sr04'),key);
});

test('only edits to a module binding invalidate it; ordinary navigation preserves other results',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']),guide=complete(design);
  const before=logic.testBindings({design,guide});
  assert.deepEqual(logic.changedTestBindings(before,logic.testBindings({design,guide:{...guide,componentIndex:1,index:0,phase:'prepare'}})),[]);
  const changed=structuredClone(guide);
  delete changed.confirmed[design.wiring[0].id];
  assert.deepEqual(logic.changedTestBindings(before,logic.testBindings({design,guide:changed})).map(b=>b.component_id),['hc-sr04']);
  assert.equal(logic.changedTestBindings(before,logic.testBindings({design:{...design,revision:2},guide})).length,2);
  assert.equal(logic.changedTestBindings(before,logic.testBindings({design:null,guide})).length,2);
});

test('edit invalidation targets exact old run bindings, not another tabs newer test',async()=>{
  const design=designFor(),guide=complete(design),bindings=logic.testBindings({design,guide});
  const old=runFor(design,guide),newer={...old,id:'newer-run',guide_key:'newer-wiring'};
  const originalFetch=globalThis.fetch,calls=[];
  globalThis.fetch=async(path,options)=>{
    calls.push({path,options});
    return {ok:true,json:async()=>({results:[old,newer]})};
  };
  try { await logic.invalidateEditedBindings(bindings); }
  finally { globalThis.fetch=originalFetch; }
  assert.equal(calls.length,2);
  assert.equal(calls[1].path,'/api/pi/component-tests/run-1/action');
  assert.equal(JSON.parse(calls[1].options.body).action,'invalidate');
});

test('switching back to a skipped completed module enables retest without clearing records',async()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']),guide=complete(design),before=structuredClone(guide.confirmed);
  const tft=logic.selectTestModule(design,guide,1);
  assert.equal(tft.phase,'prepare');
  const hc=logic.selectTestModule(design,tft,0);
  assert.equal(hc.phase,'review');
  assert.deepEqual(hc.confirmed,before);
  assert.equal(logic.componentTestKey(design,hc,'hc-sr04'),logic.componentTestKey(design,guide,'hc-sr04'));
  const html=await renderGuide({design,session:hc});
  assert.ok(html.includes('測試 HC-SR04+'));
});

test('failed and skipped results preserve manual progress and never label pass',async()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']),session=complete(design),before=structuredClone(session);
  for(const outcome of ['failed','inconclusive']) {
    const html=await renderGuide({design,session,tests:state(runFor(design,session,{outcome}))});
    assert.ok(html.includes('稍後測試，繼續'));
    assert.ok(!html.includes('class="test-outcome passed"'));
    assert.deepEqual(session,before);
  }
});

test('TFT completed process is awaiting visual confirmation, with colors, options and symptoms',async()=>{
  const design=designFor(['mrd-tf240-8p-cs']),session=complete(design);
  const run=runFor(design,session,{outcome:'awaiting_confirmation',phase:'awaiting_visual',reserved:true,reason:null});
  const html=await renderGuide({design,session,tests:state(run)});
  assert.ok(html.includes('等待使用者確認'));
  assert.equal((html.match(/type="radio"/g)||[]).length,4);
  assert.ok(html.includes('type="checkbox"'));
  assert.ok(html.includes('<button disabled="">確認顯示結果'));
  for(const text of ['全黑','白屏','亂碼／顏色異常','停止本次測試']) assert.ok(html.includes(text));
  assert.ok(!html.includes('class="test-outcome passed"'));
  assert.ok(html.includes('沒看到數字請勿猜選'));
});

test('TFT code viewing explains physical-screen hold without revealing the code or early confirmation',async()=>{
  const design=designFor(['mrd-tf240-8p-cs']),session=complete(design);
  const run=runFor(design,session,{outcome:'running',phase:'display_code',reserved:true,reason:null});
  const html=await renderGuide({design,session,tests:state(run)});
  assert.ok(html.includes('至少保留 15 秒') && html.includes('請看實體螢幕'));
  assert.ok(!html.includes('type="radio"') && !html.includes('class="test-outcome passed"'));
  assert.ok(html.includes('停止本次測試'));
});

test('stale or invalidated TFT can stop but cannot submit visual success',async()=>{
  const design=designFor(['mrd-tf240-8p-cs']),session=complete(design);
  for(const changes of [{guide_key:'old-wiring'},{invalidated:true}]) {
    const run=runFor(design,session,{outcome:'awaiting_confirmation',phase:'awaiting_visual',reserved:true,...changes});
    const html=await renderGuide({design,session,tests:state(run)});
    assert.ok(html.includes('停止本次測試'));
    assert.ok(!html.includes('type="radio"'));
    assert.ok(html.includes('舊結果失效'));
  }
});

test('disconnected Pi offers connect in same card and never starts on render',async()=>{
  const design=designFor(),session=complete(design);
  const html=await renderGuide({design,session,tests:{status:{connected:false,active:null,results:[],test_busy:false}}});
  assert.ok(html.includes('連線 Pi'));
  assert.match(html,/<button class="guide-primary-action" disabled="">測試 HC-SR04\+/);
});

test('no-echo, reader failure, missing dependency and busy diagnostics give distinct next actions',async()=>{
  const design=designFor(),session=complete(design);
  for(const [reason,text] of [['no_echo','平整目標物'],['reader_error','不是判定沒有回波或接錯線'],['missing_dependency','不必重接線'],['resource_busy','不會強制停止無關程式']]) {
    const html=await renderGuide({design,session,tests:state(runFor(design,session,{reason}))});
    assert.ok(html.includes(text));
    assert.match(html,/<details><summary>診斷與環境設定/);
  }
});

test('missing TFT driver is named on the main card before hardware testing starts',async()=>{
  const design=designFor(['mrd-tf240-8p-cs']),session=complete(design);
  const run=runFor(design,session,{reason:'missing_dependency',failed_phase:'preflight',detail:"ModuleNotFoundError: No module named 'luma'"});
  const html=await renderGuide({design,session,tests:state(run)});
  const mainCard=html.slice(0,html.indexOf('<details><summary>診斷與環境設定'));
  assert.ok(mainCard.includes('缺少 luma.lcd 2.13.0'));
  assert.ok(mainCard.includes('本次尚未啟動硬體測試'));
  assert.ok(mainCard.includes('虛擬環境補裝'));
  assert.ok(!mainCard.includes('class="test-outcome passed"'));
});

test('dependency hints do not guess unknown packages or turn log content into commands',()=>{
  for(const [module,pkg] of [['luma.lcd.device','luma.lcd 2.13.0'],['PIL','Pillow'],['spidev','spidev'],['gpiozero','gpiozero'],['_lgpio','lgpio']]) {
    const message=logic.missingDependencyMessage(`ModuleNotFoundError: No module named '${module}'`,'preflight');
    assert.ok(message[0].includes(pkg)&&message[1].includes(pkg));
  }
  for(const detail of ['python: not found',"ModuleNotFoundError: No module named 'untrusted_package'","ModuleNotFoundError: No module named 'constructor'","ModuleNotFoundError: No module named '__proto__'","ModuleNotFoundError: No module named 'luma;curl bad'"]) {
    assert.equal(logic.missingDependencyMessage(detail,'preflight'),null);
  }
  assert.ok(!logic.missingDependencyMessage("ModuleNotFoundError: No module named 'luma'",'display_red')[0].includes('尚未啟動'));
});

test('heartbeat loss and foreign active test retain stop control without retest',async()=>{
  const design=designFor(),session=complete(design);
  for(const overrides of [{reason:'no_progress'},{project_id:'other',component_id:'mrd-tf240-8p-cs'}]) {
    const run=runFor(design,session,{reserved:true,outcome:'running',...overrides});
    const html=await renderGuide({design,session,tests:state(run)});
    assert.ok(html.includes('停止本次測試'));
    assert.ok(!html.includes('>重新測試 HC-SR04+'));
  }
});

test('saved pass is labelled history and changed wiring is not passed',async()=>{
  const design=designFor(),session=complete(design),run=runFor(design,session,{outcome:'passed',reason:null});
  let html=await renderGuide({design,session:{...session,restored:true},tests:state(run)});
  assert.ok(html.includes('先前保存，非目前接線證據'));
  html=await renderGuide({design,session:maker.restartProjectGuide(session),tests:state(run)});
  assert.ok(!html.includes('class="test-outcome passed"'));
});

test('refresh with completed wires keeps test/result navigation instead of asking to wire again',async()=>{
  const design=designFor(),session={...complete(design),phase:'prepare',index:0,restored:true};
  const html=await renderGuide({design,session});
  assert.ok(!html.includes('guide-prepare-message'));
  assert.ok(html.includes('稍後測試，前往部署'));
  assert.ok(html.includes('測試 HC-SR04+'));
});

test('guide no longer imports/submits photo checks, but AI design and deployment remain',()=>{
  const guide=readFileSync(new URL('../src/components/ProjectGuidePanel.tsx',import.meta.url),'utf8');
  assert.ok(!/CloudWiring|useGuidedPose|cloudWiringRequest/.test(guide));
  const hook=readFileSync(new URL('../src/lib/useComponentTests.ts',import.meta.url),'utf8');
  assert.ok(!/wiring\/check|cloud|image/i.test(hook));
  const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.ok(app.includes('useMakerAI')&&app.includes('PiDeployPanel'));
});
