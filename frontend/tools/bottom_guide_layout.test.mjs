import assert from 'node:assert/strict';
import test from 'node:test';
import {componentTests, designFor, maker, renderTestCard} from './project_guide_fixture.mjs';

function fixture(cid = 'hc-sr04') {
  const design = designFor([cid]);
  let session = maker.startProjectGuide(maker.emptyGuide());
  while (session.phase === 'active') session = maker.confirmProjectWire(design, session);
  const run = {id: 'layout-test', project_id: design.id, revision: design.revision, component_id: cid,
    guide_key: componentTests.componentTestKey(design, session, cid), created_at: 1, heartbeat_at: 1,
    outcome: 'failed', phase: 'finished', reason: 'no_echo', reserved: false, invalidated: false,
    detail: '', samples: {}, logs: [], options: ['1234', '2468', '4567', '7890']};
  return {design, session, run, view: 'actions', inlineActions: true,
    tests: {pending: false, status: {connected: true, active: null, results: [run]}}};
}

test('bottom keeps retest but removes review wiring and unsolicited help from saved failures', async () => {
  const f = fixture(), before = structuredClone(f);
  const html = await renderTestCard({...f, onDebug() { throw Error('Rendering must not ask AI'); }});
  assert.match(html, /guide-secondary-test-action[^>]*aria-label="重新測試 HC-SR04\+"/);
  assert.doesNotMatch(html, /component-test-debug-action|guide-review-wiring-action|查看接線|查看本零件接線/);
  assert.doesNotMatch(html, /test-more-actions|其他操作/);
  assert.deepEqual(f, before);
});

test('a failure finished in this visit offers help, without calling it during render', async () => {
  const f = fixture(); f.run.finished_at = Date.now() / 1000 + 1;
  const html = await renderTestCard({...f, onDebug() { throw Error('Only an explicit click may ask AI'); }});
  assert.match(html, /component-test-debug-action/);
  assert.doesNotMatch(html, /查看本零件接線|test-more-actions/);
});

test('normal, passed, cancelled and invalid tests do not offer bottom-bar AI help', async () => {
  const states = [
    {outcome: 'passed', reason: null},
    {outcome: 'running', phase: 'awaiting_near', reserved: true, reason: null},
    {outcome: 'awaiting_confirmation', phase: 'awaiting_visual', reserved: true, reason: null},
    {outcome: 'inconclusive', reason: 'cancelled'},
    {outcome: 'failed', invalidated: true},
  ];
  for (const state of states) {
    const f = fixture(); Object.assign(f.run, state, {finished_at: Date.now() / 1000 + 1});
    if (f.run.reserved) f.tests.status.active = f.run;
    const html = await renderTestCard({...f, onDebug() { throw Error('No implicit help'); }});
    assert.doesNotMatch(html, /component-test-debug-action/, JSON.stringify(state));
  }
  const f = fixture(); f.tests.status.results = [];
  assert.doesNotMatch(await renderTestCard({...f, onDebug() {}}), /component-test-debug-action/);
});

test('only a fresh failed preflight job may offer bottom-bar help', async () => {
  const f = fixture(); f.tests.status.results = [];
  const job = {id: 'preflight-job', kind: 'test', state: 'failed', project_id: f.design.id,
    component_id: f.run.component_id, guide_key: f.run.guide_key, created_at: 1,
    reason: 'missing_dependency', error: 'Missing driver'};
  f.tests.status.execution = {jobs: [job]};
  assert.doesNotMatch(await renderTestCard({...f, onDebug() {}}), /component-test-debug-action/);
  job.created_at = Date.now() / 1000 + 1;
  assert.match(await renderTestCard({...f, onDebug() {}}), /component-test-debug-action/);
});

test('a current live test problem can ask for help but a foreign test cannot', async () => {
  const f = fixture(); Object.assign(f.run, {reserved: true, phase: 'awaiting_near', outcome: 'running', reason: 'connection_lost'});
  f.tests.status.active = f.run;
  assert.match(await renderTestCard({...f, onDebug() {}}), /component-test-debug-action/);
  f.run.project_id = 'another-project';
  const html = await renderTestCard({...f, onDebug() {}});
  assert.doesNotMatch(html, /component-test-debug-action/);
  assert.match(html, /停止本次測試/);
});

test('initial test remains primary and disconnected test cannot start', async () => {
  const f = fixture(); f.tests.status.results = []; f.tests.status.connected = false;
  const html = await renderTestCard(f);
  assert.match(html, /guide-primary-action" disabled=""[^>]*aria-label="測試 HC-SR04\+"/);
  assert.match(html, /連接 Pi 後測試/);
});

test('inline controls never hide Stop or offer sampling after a lost connection', async () => {
  const f = fixture(); Object.assign(f.run, {reserved: true, phase: 'awaiting_near', outcome: 'running', reason: 'connection_lost'});
  f.tests.status.active = f.run;
  const html = await renderTestCard(f);
  assert.match(html, /停止本次測試/);
  assert.doesNotMatch(html, /test-more-actions|準備好了，取樣|guide-secondary-test-action/);
});

test('display test retains all required choices and starts with confirmation disabled', async () => {
  const f = fixture('mrd-tf240-8p-cs');
  Object.assign(f.run, {reserved: true, phase: 'awaiting_visual', outcome: 'awaiting_confirmation', reason: null});
  f.tests.status.active = f.run;
  const html = await renderTestCard(f);
  assert.equal((html.match(/type="radio"/g) ?? []).length, 4);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /disabled="">確認顯示結果/);
  assert.match(html, /停止本次測試/);
  assert.match(html, /全黑/); assert.match(html, /白屏/); assert.match(html, /亂碼／顏色異常/);
});

test('legacy test surfaces keep their original More actions and label', async () => {
  const f = fixture(), html = await renderTestCard({...f, inlineActions: false});
  assert.match(html, /test-more-actions/);
  assert.match(html, />重新測試 HC-SR04\+<\/button>/);
  assert.doesNotMatch(html, /guide-secondary-test-action|is-inline-test-actions/);
});
