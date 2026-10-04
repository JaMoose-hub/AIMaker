import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {componentTests,designFor,maker,renderGuide} from './project_guide_fixture.mjs';

function fixture(cid='hc-sr04',phase='awaiting_near') {
  const design=designFor([cid]);
  let session=maker.startProjectGuide(maker.emptyGuide());
  while(session.phase==='active') session=maker.confirmProjectWire(design,session);
  const run={id:'dock-test',project_id:design.id,revision:design.revision,component_id:cid,
    guide_key:componentTests.componentTestKey(design,session,cid),created_at:Date.now()/1000,heartbeat_at:Date.now()/1000,
    reserved:true,invalidated:false,outcome:'running',phase,reason:null,detail:'',samples:{},logs:[],options:['1234','2468','4567','7890']};
  return {design,session,floating:true,embedded:true,tests:{status:{connected:true,active:run,results:[run]}},run};
}
const beforeDetails = html => html.split('<details class="test-diagnostics">')[0];

test('collapse control shares the existing module header in prepare, wiring and test phases', async()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  for(const session of [maker.emptyGuide(),maker.startProjectGuide(maker.emptyGuide()),fixture().session]) {
    const html=await renderGuide({design,session,embedded:true,floating:true,
      visibilityControl:createElement('button',{'aria-label':'收合接線引導','aria-expanded':true},'收合')});
    const header=html.match(/<header class="guide-panel-header guide-panel-header-embedded">([\s\S]*?)<\/header>/)?.[1];
    assert.ok(header);
    assert.match(header,/guide-module-track/);
    assert.match(header,/guide-restart-action/);
    const restart=header.match(/<button[^>]*class="guide-restart-action guide-icon-action"[\s\S]*?<\/button>/)?.[0];
    assert.ok(restart);
    assert.match(restart,/aria-label="重新開始接線引導"/);
    assert.match(restart,/title="清除本輪接線/);
    assert.match(restart,/<svg aria-hidden="true"/);
    assert.equal(restart.replace(/<[^>]*>/g,''),'','restart icon keeps its name in accessibility attributes');
    assert.match(header,/aria-label="收合接線引導" aria-expanded="true"/);
    assert.equal((html.match(/aria-label="收合接線引導"/g)||[]).length,1);
  }
});

test('dock has one mounted test card with visible sampling and stop, without duplicate side controls',async()=>{
  const f=fixture(),before=structuredClone(f);
  const html=await renderGuide(f),visible=beforeDetails(html);
  assert.equal((html.match(/data-view="dock"/g)||[]).length,1);
  assert.doesNotMatch(html,/data-view="actions"|guide-test-controls|test-more-actions/);
  assert.match(visible,/15 cm/);assert.match(visible,/準備好了，取樣 5 秒/);assert.match(visible,/停止本次測試/);
  assert.deepEqual(f,before);
});
test('dock stale history is not a current pass and disconnected start is disabled',async()=>{
  const f=fixture();Object.assign(f.run,{reserved:false,invalidated:true,outcome:'passed',finished_at:2,created_at:1});
  f.tests.status.active=null;f.tests.status.connected=false;
  const html=await renderGuide(f),visible=beforeDetails(html);
  assert.match(visible,/待重測/);assert.doesNotMatch(visible,/功能通過/);
  assert.match(visible,/<button class="guide-primary-action" disabled=""[^>]*>連接 Pi 後測試/);
  assert.match(html,/<details class="test-diagnostics">[\s\S]*非目前接線證據/);
});
test('dock never collapses TFT code choices, abnormal options or stop into diagnostics',async()=>{
  const f=fixture('mrd-tf240-8p-cs','awaiting_visual');f.run.outcome='awaiting_confirmation';
  const visible=beforeDetails(await renderGuide(f));
  assert.equal((visible.match(/type="radio"/g)||[]).length,4);
  assert.match(visible,/沒看到請勿猜選/);assert.match(visible,/name="test-code-dock-test"/);
  assert.match(visible,/<button disabled="">確認顯示結果/);
  for(const text of ['停止本次測試','全黑','白屏','亂碼／顏色異常']) assert.ok(visible.includes(text));
});
test('lost or stale active tests keep Stop but disallow advancing samples',async()=>{
  for(const overrides of [{reason:'connection_lost'},{invalidated:true}]) {
    const f=fixture();Object.assign(f.run,overrides);
    const visible=beforeDetails(await renderGuide(f));
    assert.match(visible,/停止本次測試/);assert.doesNotMatch(visible,/準備好了，取樣/);
  }
});
test('active wiring keeps real endpoints and required TFT warning without starting a test',async()=>{
  for(const cid of ['hc-sr04','mrd-tf240-8p-cs']) {
    const design=designFor([cid]),session=maker.startProjectGuide(maker.emptyGuide());
    const html=await renderGuide({design,session,floating:true,embedded:true});
    assert.match(html,/data-wiring-target=/);assert.match(html,/guide-primary-action/);
    assert.doesNotMatch(html,/data-view="dock"/);
    if(cid==='mrd-tf240-8p-cs')assert.match(html,/BLK 留空/);
  }
});
test('bottom dock uses full width and content height, with a single column on narrow screens',()=>{
  const css=readFileSync(new URL('../src/floatingGuide.css',import.meta.url),'utf8');
  assert.match(css,/position: static; flex: 0 0 auto/);assert.match(css,/width: 100%; height: auto/);
  assert.match(css,/var\(--bg-panel\) 56%, transparent/);
  assert.match(css,/grid-template-columns: minmax\(0,1fr\) minmax\(190px,26%\)/);
  assert.match(css,/@media \(max-width: 700px\)[\s\S]*grid-template-columns: minmax\(0,1fr\); grid-template-rows: auto auto auto/);
  assert.match(css,/backdrop-filter: blur\(3px\)/);
  assert.doesNotMatch(css,/height: min\((280|340|420)px|height: 100%|blur\(16px\)/);
});
