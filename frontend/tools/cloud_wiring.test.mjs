import assert from "node:assert/strict";
import test from "node:test";
import { cloudWiring as m, renderDetails, resultFixture } from './cloud_wiring_fixture.mjs';
test('staged checks disclose progress without displaying intermediate findings as a pass', async () => {
  for (const [phase, title] of [['component', '1/3 · 檢查零件接頭'], ['board', '2/3 · 檢查 Pi 接頭'], ['route', '3/3 · 核對線路']]) {
    const job = {status: 'checking', result: resultFixture, images: [], inspection: {phase, effort: 'low', max_calls: 3, stages: []}};
    assert.equal(m.cloudWiringCopy({job, busy: true}, 'zh-TW').title, title);
    const html = await renderDetails(resultFixture, 'zh-TW', {job, busy: true});
    assert.ok(html.includes(title));
    assert.ok(!html.includes('Fixture: exact Pi pin unclear'));
  }
});
test('per-pin appearance renders independently of exact target identity in both languages', async () => {
  const result = structuredClone(resultFixture);
  const observation = {connectors: [], target_identity: 'uncertain', target_pin_tip: 'not_visible', target_connector_id: null, evidence: 'fixture'};
  result.visual_observations = {board: observation, component: observation};
  result.pin_contacts = {component: [
    {position: 'first slot', pin_id: 'TRIG', appearance: 'bare_tip', connector_id: null},
    {position: 'next slot', pin_id: 'GND', appearance: 'housing', connector_id: 'C1'},
  ]};
  for (const [lang, bare, plugged] of [['zh-TW', '裸針', '接頭覆蓋'], ['en', 'Bare pin', 'Housing covers pin']]) {
    const html = await renderDetails(result, lang);
    assert.ok(html.includes(`<dt>TRIG</dt><dd>${bare}</dd>`) && html.includes(`<dt>GND</dt><dd>${plugged}</dd>`));
  }
  assert.equal(result.verdict, 'uncertain');
});
test('contact photos and actual reasoning effort are disclosed without a new viewpoint claim', async () => {
  const job = {status: 'completed', model: 'test-model', result: resultFixture,
    capture: {captured_at: new Date().toISOString(), same_frame: true, mode: 'pin_crops'},
    inspection: {phase: 'completed', effort: 'low', max_calls: 3, stages: [{stage: 'component'}, {stage: 'board'}]},
    images: [{name: 'component_contact', url: '/test-contact.png'}]};
  const html = await renderDetails(resultFixture, 'zh-TW', {job});
  assert.ok(html.includes('零件接合處裁切（同張照片）') && html.includes('<dt>推理強度</dt><dd>low</dd>'));
  assert.ok(html.includes('<dt>分段檢查</dt><dd>2 / 3</dd>'));
});
test("cloud check sends only target/profile/model, not code, passwords or chat", () => {
  const d = { id: "project", revision: 4, catalog_version: "1", profile_versions: {}, code: "secret", password: "secret", conversation: "secret" };
  const w = { id: "hc-sr04:gnd", componentId: "hc-sr04", boardPin: "GND_P6", componentPin: "GND", connectionKind: "direct" };
  const original = JSON.stringify(d);
  const request = m.cloudWiringRequest(d, w, { model: "vision", effort: "low" }, "en");
  assert.equal(request.project_revision, 4);
  assert.equal(request.component_id, "hc-sr04");
  assert.equal(JSON.stringify(request).includes("secret"), false);
  assert.equal(JSON.stringify(d), original);
});
test("old, moved or lost-pose photo is historical even if cloud says matched", () => {
  const job = { capture: { captured_at: new Date(1000).toISOString() }, stale: false, result: { verdict: "looks_matched" } };
  assert.equal(m.cloudPhotoExpired(job, 2000, false), false);
  assert.equal(m.cloudPhotoExpired(job, 32000, false), true);
  assert.equal(m.cloudPhotoExpired(job, 2000, true), true);
  assert.equal(m.cloudPhotoExpired({ ...job, stale: true }, 2000, false), true);
});

test("overview checks need no localization and do not become stale just because pins were never found", () => {
  const job = {capture: {captured_at: new Date(1000).toISOString(), mode: 'overview'}, stale: false};
  assert.equal(m.cloudPhotoExpired(job, 2000, true), false);
  assert.equal(m.cloudPhotoExpired(job, 32000, true), true);
  assert.equal(m.cloudPhotoExpired({...job, stale: true}, 2000, false), true);
});

test("slow cloud calls have a full reading window after completion, not capture", () => {
  for (const mode of ['overview', 'context_crops', 'pin_crops']) {
    for (const latency of [47000, 119000]) {
      const started = 1000;
      const completed = started + latency;
      const job = {status: 'checking', capture: {captured_at: new Date(started).toISOString(), mode}, stale: false};
      assert.equal(m.cloudPhotoExpired(job, completed, false), false);
      const result = {...job, status: 'completed', completed_at: new Date(completed).toISOString()};
      assert.equal(m.cloudPhotoExpired(result, completed, false), false);
      assert.equal(m.cloudPhotoExpired(result, completed + 30000, false), false);
      assert.equal(m.cloudPhotoExpired(result, completed + 30001, false), true);
      assert.equal(m.cloudPhotoExpired({...result, stale: true}, completed, false), true);
      assert.equal(m.cloudPhotoExpired(result, completed, true), mode === 'pin_crops');
    }
  }
});

test("in-flight scene loss stays stale and legacy or malformed timestamps fail predictably", () => {
  const job = {status: 'checking', capture: {captured_at: new Date(1000).toISOString()}, stale: false};
  assert.equal(m.cloudPhotoExpired(job, 48000, true), true);
  assert.equal(m.cloudPhotoExpired({...job, stale: true}, 48000, false), true);
  assert.equal(m.cloudPhotoExpired({...job, status: 'completed', completed_at: 'invalid'}, 48000, false), true);
  assert.equal(m.cloudPhotoExpired({...job, status: 'completed', capture: {captured_at: 'invalid'}}, 48000, false), true);
  assert.equal(m.cloudPhotoExpired({...job, status: 'completed', completed_at: new Date(48000).toISOString()}, 48000, false), false);
});

test('cloud localization progress and source-crop mode are explicit, not a pose success', async () => {
  const job = {status: 'checking', model: 'test-model', result: null, images: [],
    capture: {captured_at: new Date().toISOString(), same_frame: true, mode: 'context_crops'},
    inspection: {phase: 'localization', max_calls: 4, effort: 'low', stages: []}};
  assert.match(m.cloudWiringCopy({job, busy: true}, 'zh-TW').title, /1\/4.*特寫/);
  job.inspection.phase = 'component';
  assert.match(m.cloudWiringCopy({job, busy: true}, 'zh-TW').title, /2\/4/);
  const html = await renderDetails(null, 'zh-TW', {job, busy: true});
  assert.ok(html.includes('非精準定位'));
});

test('breadboard hole evidence renders without changing a verdict or manual progress', async () => {
  const result = structuredClone(resultFixture);
  const connector = {id: 'B1', contact: 'breadboard_link', position: 'fixture', evidence: 'fixture',
    wire_color: {name: 'yellow', visibility: 'clear', evidence: 'fixture'},
    breadboard: {pin_hole: {column: 'B', row: 12}, wire_hole: {column: 'E', row: 12}, evidence: 'Fixture strip'}};
  const observation = {connectors: [connector], target_connector_id: null, target_identity: 'uncertain', target_pin_tip: 'not_visible', evidence: 'fixture'};
  result.visual_observations = {board: observation, component: observation};
  result.pin_contacts = {component: [{position: 'fixture', pin_id: null, appearance: 'breadboard', connector_id: 'B1'}]};
  const html = await renderDetails(result, 'zh-TW');
  assert.ok(html.includes('經麵包板連接') && html.includes('麵包板孔位'));
  assert.match(html, /B.*12.*→.*E.*12/);
  assert.equal(result.verdict, 'uncertain');
});

test("cloud color labels distinguish insulation colors, partial visibility and missing observations", () => {
  assert.equal(m.cloudWireColorLabel({name: 'brown', visibility: 'clear'}, 'zh-TW'), '棕色');
  assert.equal(m.cloudWireColorLabel({name: 'orange', visibility: 'partial'}, 'zh-TW'), '橘色（局部可見）');
  assert.equal(m.cloudWireColorLabel({name: 'unknown', visibility: 'clear'}, 'en'), 'Color uncertain');
  assert.equal(m.cloudWireColorLabel({name: 'black', visibility: 'not_visible'}, 'en'), 'Not visible');
  assert.equal(m.cloudWireColorLabel(undefined, 'zh-TW'), '未看清');
});

test("cloud color label formatting never mutates the observation or wiring result", () => {
  const color = Object.freeze({name: 'yellow', visibility: 'clear', evidence: 'Visible insulation'});
  assert.equal(m.cloudWireColorLabel(color, 'en'), 'yellow');
  assert.equal(color.evidence, 'Visible insulation');
});

test('details render independent colors and path evidence in both languages', async () => {
  const zh = await renderDetails(resultFixture, 'zh-TW');
  assert.ok(zh.includes('<dt>Pi 端</dt><dd>棕色</dd>') && zh.includes('橘色（局部可見）'));
  assert.ok(zh.includes('色差待確認') && zh.includes('詳細判讀與模型資訊'));
  assert.ok(zh.includes('Fixture: obstruction in overview'));
  const en = await renderDetails(resultFixture, 'en');
  assert.ok(en.includes('<dt>Pi end</dt><dd>brown</dd>') && en.includes('orange (partly visible)'));
  assert.ok(en.includes('Color comparison uncertain') && en.includes('Evidence and model details'));
});

test('details still render older in-flight responses without color or path fields', async () => {
  const {wire_colors, wire_path, ...legacy} = resultFixture;
  const html = await renderDetails(legacy, 'zh-TW');
  assert.ok(html.includes('Fixture: exact Pi pin unclear'));
  assert.ok(!html.includes('雲端線色判讀'));
});

test('fixed template places conclusion, target, observation and next step before collapsed evidence', async () => {
  const html = await renderDetails(resultFixture, 'zh-TW');
  const order = ['這一步還看不清楚', '本步目標', '看到什麼', '下一步', '詳細判讀與模型資訊'];
  for (let i = 1; i < order.length; i++) assert.ok(html.indexOf(order[i - 1]) < html.indexOf(order[i]));
  assert.ok(html.includes('HC-SR04 · GND') && html.includes('Pi · Pin 6 · GND'));
  assert.ok(!html.includes('<details open') && !html.includes(' open=""'));
});

test('all verdicts have distinct visual-only conclusions and an actionable next step', () => {
  for (const [verdict, tone] of [['looks_matched', 'success'], ['suspected_issue', 'issue'], ['uncertain', 'warning'], ['needs_review', 'warning']]) {
    const result = {...resultFixture, verdict};
    const before = JSON.stringify(result);
    const copy = m.cloudWiringCopy({job: {result}, stale: false}, 'zh-TW');
    assert.equal(copy.tone, tone);
    assert.ok(copy.title && copy.next && !copy.title.includes('電氣通過'));
    assert.equal(JSON.stringify(result), before);
  }
});

test('next step identifies the uncertain or wrong endpoint without inventing a pin', () => {
  for (const [pi, module, verdict, expected] of [
    ['other', 'target', 'suspected_issue', 'Pi 端'], ['target', 'empty', 'suspected_issue', '零件端'],
    ['other', 'empty', 'suspected_issue', '兩端'], ['occluded', 'target', 'uncertain', 'Pi 端'],
    ['target', 'uncertain', 'uncertain', '零件端'], ['occluded', 'uncertain', 'uncertain', '兩端'],
    ['target', 'target', 'uncertain', '中段'],
  ]) {
    const result = {...resultFixture, verdict, board_endpoint: {state: pi}, component_endpoint: {state: module}};
    assert.ok(m.cloudWiringCopy({job: {result}, stale: false}, 'zh-TW').next.includes(expected));
  }
});

test('old success cannot be shown as current success during stale, busy, failure or poll recovery', async () => {
  const result = {...resultFixture, verdict: 'looks_matched'};
  for (const overrides of [{stale: true}, {busy: true}, {error: 'Timeout'}, {error: 'Polling error', readAgain: true}]) {
    const html = await renderDetails(result, 'zh-TW', overrides);
    assert.ok(!html.includes('tone-success'));
    assert.ok(!html.includes('<h3 role="status">照片外觀符合'));
  }
  const copy = m.cloudWiringCopy({job: {result}, stale: false, error: 'Polling error', readAgain: true}, 'zh-TW');
  assert.ok(copy.next.includes('不會重新送出照片'));
  const stale = await renderDetails(result, 'zh-TW', {stale: true});
  assert.ok(stale.includes('先前照片看到的內容'));
});

test('display text replaces internal photo IDs without changing negation or observations', () => {
  assert.equal(m.cloudEvidenceText('pi_pins 無法確認；component_pins 可見棕線。', 'zh-TW'), 'Pi 排針特寫 無法確認；零件腳位特寫 可見棕線。');
  assert.equal(m.cloudEvidenceText('pi_overview: wire not traceable', 'en'), 'overview photo: wire not traceable');
  assert.equal(m.cloudEvidenceText('component_reading: wire', 'en'), 'module reading view: wire');
});

test('reading copies are shown as derived photos instead of extra camera captures', async () => {
  const images = ['pi_overview', 'pi_pins', 'component_pins', 'pi_reading', 'component_reading'].map(name => ({name, url: `/fixture/${name}`}));
  const html = await renderDetails(resultFixture, 'zh-TW', {job: {result: resultFixture, images}});
  assert.ok(html.includes('零件特寫旋正放大（同張照片）') && html.includes('(5)'));
});

test('photos stay separately addressable and rendering never adds an automatic check', async () => {
  const images = ['pi_overview', 'pi_pins', 'component_pins'].map(name => ({name, url: `/api/guidance/cloud-checks/fixture/images/${name}`}));
  let requests = 0;
  const html = await renderDetails(resultFixture, 'zh-TW', {job: {result: resultFixture, images}, onCheck: () => requests++});
  assert.equal(requests, 0);
  for (const image of images) assert.ok(html.includes(`href="${image.url}"`));
  assert.ok(html.includes('查看檢查照片') && html.includes('(3)') && html.includes('重新檢查'));
});

test('compact findings identify observed pins and never equate matching colors with the same wire', () => {
  assert.equal(m.cloudEndpointLabel({state: 'other', observed_pin: 'GPIO18'}, 'zh-TW'), '疑似插在 GPIO18');
  assert.equal(m.cloudEndpointLabel({state: 'occluded', observed_pin: null}, 'en'), 'Connector obscured');
  assert.equal(m.cloudPathLabel({...resultFixture, same_wire: 'uncertain'}, 'zh-TW'), '部分路徑未辨清');
  assert.equal(m.cloudPathLabel({...resultFixture, same_wire: 'different'}, 'zh-TW'), '疑似不同條線');
  assert.notEqual(m.cloudPathLabel({...resultFixture, same_wire: 'consistent'}, 'zh-TW'), '可追蹤為同一條線');
  assert.equal(m.cloudPathLabel({...resultFixture, same_wire: 'consistent', wire_path: {visibility: 'traceable'}}, 'zh-TW'), '可追蹤為同一條線');
});

test('main findings are short structured rows; full AI prose is only inside the evidence disclosure', async () => {
  const html = await renderDetails(resultFixture, 'zh-TW');
  const disclosure = html.indexOf('class="cloud-result-disclosure"');
  assert.ok(html.indexOf('cloud-result-findings') < disclosure);
  assert.ok(html.indexOf(resultFixture.summary) > disclosure);
  assert.ok(html.indexOf('部分路徑未辨清') < disclosure);
});

test('an empty target is not presented as an unreadable wire color', async () => {
  const result = structuredClone(resultFixture);
  result.board_endpoint = {state: 'empty', observed_pin: 'GND_P6', evidence: 'Target tip is bare'};
  result.wire_colors.board = {name: 'unknown', visibility: 'not_visible', evidence: 'No target wire'};
  result.verdict = 'suspected_issue';
  const html = await renderDetails(result, 'zh-TW');
  assert.ok(html.includes('<dd>目標插孔未見接頭</dd>'));
  assert.ok(!html.includes('目標插孔未見接頭 · 未看清'));
  assert.ok(html.includes('未見目標接線'));
});

test('candidate colors and connector contact survive unknown target association', async () => {
  const observation = {target_identity: 'uncertain', target_pin_tip: 'not_visible', target_connector_id: null,
    evidence: 'Fixture: exact target unreadable', connectors: [
      {id: 'a', position: 'Left end', contact: 'covers_pin', wire_color: {name: 'brown', visibility: 'clear', evidence: 'Brown wire'}, evidence: 'Housing covers one tip'},
      {id: 'b', position: 'Above header', contact: 'detached', wire_color: {name: 'orange', visibility: 'clear', evidence: 'Orange wire'}, evidence: 'Gap beyond tip'},
    ]};
  const unknown = {name: 'unknown', visibility: 'not_visible', evidence: 'Target association unclear'};
  const result = {...resultFixture, visual_observations: {board: observation, component: observation},
    wire_colors: {...resultFixture.wire_colors, board: unknown}};
  assert.equal(m.cloudEndpointFinding(result.board_endpoint, unknown, observation, 'zh-TW'), '腳位未辨清 · 已見接頭：棕色');
  const html = await renderDetails(result, 'zh-TW');
  assert.ok(html.includes('已見接頭：棕色'));
  assert.ok(html.includes('已看見接線，Pi 腳位待確認'));
  assert.ok(html.includes('目標線尚未對應（見下方接頭觀察）'));
  assert.ok(html.includes('棕色 · 接頭覆住針尖') && html.includes('橘色 · 接頭懸空'));
  assert.ok(html.indexOf('Pi 端接頭觀察') > html.indexOf('詳細判讀與模型資訊'));
  const en = await renderDetails(result, 'en');
  assert.ok(en.includes('Visible connectors: brown') && en.includes('Detached connector'));
  observation.connectors.forEach(c => c.contact = 'uncertain');
  assert.equal(m.cloudEndpointFinding(result.board_endpoint, unknown, observation, 'zh-TW'), '腳位未辨清 · 候選線：棕色、橘色');
});

test('a visible route between candidates is not hidden by uncertain target pin identity', () => {
  const result = {...resultFixture, visual_observations: {}, wire_path: {visibility: 'traceable'}};
  assert.equal(m.cloudPathLabel(result, 'zh-TW'), '線路可追蹤，端點對應待確認');
  assert.equal(result.verdict, 'uncertain');
});

test('contradictory model observations have a visible explanation and never trigger a check', async () => {
  const result = {...resultFixture, consistency_issues: ['board']};
  const html = await renderDetails(result, 'zh-TW');
  assert.ok(html.includes('AI 的接頭觀察與腳位結論不一致'));
});
