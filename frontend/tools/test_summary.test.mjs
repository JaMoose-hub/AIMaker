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

test('stale guide result has one short instruction; history stays accessible but is not a current pass',async()=>{
  for(const cid of ['hc-sr04','mrd-tf240-8p-cs']) {
    const f=fixture(cid),before=structuredClone(f);
    const html=await renderGuide(f);
    const info=html.slice(html.indexOf('<div class="guide-panel-body"'),html.indexOf('<footer'));
    const visible=info.split('<details class="test-diagnostics">')[0];
    assert.match(visible,/待重測/);
    assert.match(visible,/舊結果已失效，請重新測試/);
    assert.doesNotMatch(visible,/本模組人工紀錄|上次測試紀錄|功能通過|無法判定/);
    assert.match(info,/<details class="test-diagnostics">[\s\S]*非目前接線證據/);
    assert.match(html,/改線前斷電/);
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
