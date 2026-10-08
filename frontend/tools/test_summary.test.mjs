import assert from 'node:assert/strict';
import test from 'node:test';
import {componentTests, designFor, maker, renderGuide, renderTestCard} from './project_guide_fixture.mjs';

function fixture(cid='hc-sr04') {
  const design=designFor([cid]);
  let session=maker.startProjectGuide(maker.emptyGuide());
  while(session.phase==='active') session=maker.confirmProjectWire(design,session);
  const run={id:'old-run',project_id:design.id,revision:design.revision,component_id:cid,
    guide_key:componentTests.componentTestKey(design,session,cid),template_version:'fixture',wiring_hash:'fixture',
    created_at:1,finished_at:2,outcome:'passed',phase:'finished',reason:null,detail:'',logs:[],samples:{},
    latest:null,heartbeat_at:1,exit_code:0,reserved:false,invalidated:true,program_stopped:false,
    options:['1234','2345','3456','4567']};
  return {design,session,run,tests:{status:{connected:false,active:null,results:[run]}}};
}

test('stale guide result has one short instruction without compact diagnostics or a repeated safety footer',async()=>{
  for(const cid of ['hc-sr04','mrd-tf240-8p-cs']) {
    const f=fixture(cid),before=structuredClone(f);
    const html=await renderGuide(f);
    const info=html.slice(html.indexOf('<div class="guide-panel-body"'),html.indexOf('<footer'));
    const visible=info.split('class="compact-guide-details" hidden=""')[0];
    assert.match(visible,/待重測/);
    assert.match(visible,/舊結果已失效，請重新測試/);
    assert.doesNotMatch(visible,/本模組人工紀錄|上次測試紀錄|功能通過|無法判定/);
    assert.doesNotMatch(info,/test-diagnostics|test-safety-note/);
    const history=await renderTestCard({...f,view:'all'});
    assert.match(history,/test-diagnostics/);
    assert.match(history,/非目前接線證據/);
    assert.match(history,/test-safety-note/);
    assert.deepEqual(f,before);
  }
});

test('TFT last-wire bottom guide removes the three marked rows in both languages without changing result or actions',async()=>{
  for(const locale of ['zh-TW','en']) {
    const f=fixture('mrd-tf240-8p-cs');
    f.session=maker.previousProjectWire(f.design,f.session);
    Object.assign(f.run,{invalidated:false,outcome:'failed',reason:'display_white',created_at:Date.now()/1000+60,finished_at:Date.now()/1000+60});
    f.run.guide_key=componentTests.componentTestKey(f.design,f.session,'mrd-tf240-8p-cs');
    const before=structuredClone(f);
    const html=await renderGuide({...f,locale,floating:true,embedded:true});
    const visible=html.split('class="compact-guide-details" hidden=""')[0];
    assert.match(visible,/<strong>VCC<\/strong>/);
    assert.match(visible,/<strong>Pin 17<\/strong>/);
    assert.doesNotMatch(visible,/guide-pin-caution|BLK 留空|Leave BLK unconnected|test-diagnostics|test-safety-note|測試詳情|Test details/);
    assert.match(visible,locale==='zh-TW'?/未通過/:/Not passed/);
    assert.match(visible,/SPI/);
    assert.match(html,locale==='zh-TW'?/下一步/:/Next/);
    assert.deepEqual(f,before);
  }
});

test('guide keeps the primary test action visible and hides AI help for stale non-problem history',async()=>{
  const f=fixture();
  const html=await renderTestCard({...f,view:'actions',onDebug(){throw Error('No hardware work during render');}});
  const [visible,more]=html.split('<details class="test-more-actions">');
  assert.match(visible,/<button class="guide-primary-action" disabled=""[^>]*>連接 Pi 後測試/);
  assert.doesNotMatch(visible,/component-test-debug-action|查看本零件接線/);
  assert.doesNotMatch(html,/前往除錯|請 AI 幫忙|component-test-debug-action/);
  assert.match(more,/查看本零件接線/);
});

test('live and disconnected test stop controls never move into secondary actions',async()=>{
  const f=fixture();
  f.run={...f.run,reserved:true,invalidated:false,outcome:'running',phase:'awaiting_near',reason:'connection_lost'};
  f.tests.status.active=f.run;
  f.tests.status.results=[f.run];
  const html=await renderTestCard({...f,view:'actions'});
  const visible=html.split('<details class="test-more-actions">')[0];
  assert.match(visible,/停止本次測試/);
  assert.doesNotMatch(visible,/準備好了|>測試 HC-SR04/);
});
