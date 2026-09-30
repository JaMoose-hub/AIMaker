import assert from 'node:assert/strict';
import test from 'node:test';
import {board, piGuide, designFor, maker, componentTests, renderGuide} from './project_guide_fixture.mjs';
import {resultFixture} from './cloud_wiring_fixture.mjs';

const checkButtons = html => [...html.matchAll(/<button[^>]*class="cloud-wiring-button"[^>]*>/g)];
test('HC-SR04+ VCC points to inner row position one and ECHO is a direct step', async () => {
  const design = designFor();
  for (const pin of ['VCC', 'ECHO']) {
    const index = design.wiring.findIndex(w => w.componentPin === pin);
    const html = await renderGuide({design, session:{...maker.startProjectGuide(maker.emptyGuide()), index}});
    assert.ok(html.includes('HC-SR04+'));
    assert.ok(html.includes('3.3V'));
    assert.ok(!html.includes('class="wiring-divider"'));
    assert.ok(!html.includes('330Ω') && !html.includes('470Ω'));
    if (pin === 'VCC') {
      assert.ok(html.includes('<strong>第 1 支</strong>'));
      assert.ok(html.includes('內排（靠板中央）'));
      assert.ok(html.includes('3.3V · 實體 Pin 1'));
    }
  }
});

test('restart stays visible in the header in every phase without tracking or cloud access', async () => {
  for (const locale of ['zh-TW', 'en']) for (const phase of ['prepare', 'active', 'review']) {
    const html = await renderGuide({locale, session: {...maker.emptyGuide(), phase}, poseReady:false,
      cloudAI:{available:false, busy:true}, check:{busy:true}});
    const header = html.match(/<header class="guide-panel-header">([\s\S]*?)<\/header>/)?.[1];
    assert.ok(header);
    assert.equal((html.match(/class="guide-restart-action"/g) ?? []).length, 1);
    assert.match(header, /<button type="button" class="guide-restart-action"/);
    assert.ok(header.includes(locale === 'en' ? 'Restart' : '重新開始'));
    assert.ok(!header.match(/<button[^>]*guide-restart-action[^>]*disabled/));
    assert.ok(!header.includes('hidden=""'));
    assert.ok(!html.split('class="compact-guide-details"')[1].includes('guide-restart-action'));
  }
});

test('restart clears both active modules and returns to the first HC step without changing the project', () => {
  const design = designFor(['hc-sr04', 'mrd-tf240-8p-cs']);
  const state = {...maker.initialMaker(), design, code:'manual draft', guide:{...maker.emptyGuide(),
    componentIndex:1, index:3, phase:'active', run:2, confirmed:Object.fromEntries(design.wiring.map(w =>
      [w.id, {signature:maker.wireSignature(w), mode:'camera', at:'test'}]))}};
  const snapshot = structuredClone(state);
  const next = {...state, guide:maker.restartProjectGuide(state.guide)};
  assert.deepEqual(state, snapshot);
  assert.equal(next.design, design);
  assert.equal(next.code, 'manual draft');
  assert.deepEqual(next.selected, state.selected);
  assert.equal(next.guide.run, 3); // Invalidates a pending or previous AI result, including at the same step.
  assert.equal(next.guide.phase, 'prepare');
  assert.equal(next.guide.componentIndex, 0);
  assert.equal(next.guide.index, 0);
  assert.deepEqual(next.guide.confirmed, {});
  assert.equal(maker.currentWire(design, next.guide).id, 'hc-sr04:gnd');
});

test('started guide shows the real wiring target and no photo or premature module test', async () => {
  for (const locale of ['zh-TW', 'en']) {
    const html = await renderGuide({locale, session:maker.startProjectGuide(maker.emptyGuide())});
    assert.equal(checkButtons(html).length, 0);
    assert.ok(html.includes('<strong>GND</strong>') && html.includes(locale === 'en' ? '<strong>Position 3</strong>' : '<strong>第 3 支</strong>'));
    assert.ok(html.includes(locale === 'en' ? 'GND · Physical Pin 6' : 'GND · 實體 Pin 6'));
    assert.ok(!html.includes('cloud-result-target')); // no repeated target card inside AI results
    assert.ok(!html.includes('cloud-result-inline'));
    assert.match(html, /class="compact-guide-details" hidden=""/);
    assert.match(html, /<footer class="guide-panel-footer">.*guide-primary-action/s);
    assert.ok(!html.match(/<footer[^>]*>.*class="cloud-wiring-button"/s));
    assert.ok(!html.includes('component-test-card'));
  }
});

test('each supported module uses its profile target and divider is not a direct-wire arrow', async () => {
  for (const cid of ['hc-sr04', 'mrd-tf240-8p-cs']) {
    const design = designFor([cid]);
    for (const [index, wire] of design.wiring.entries()) {
      const session = {...maker.initialMaker().guide, index, phase: 'active'};
      const html = await renderGuide({design, session});
      assert.ok(html.includes(`data-wiring-target="${cid}:${wire.componentPin}"`));
      assert.ok(html.includes(`<strong>${wire.componentPin}</strong>`));
      const location = piGuide.piHeaderLocation(board.pins.find(p => p.id === wire.boardPin));
      assert.ok(html.includes(`<strong>第 ${location.number} 支</strong>`));
      assert.ok(html.includes(location.row === 'inner' ? '內排（靠板中央）' : '外排（靠板邊緣）'));
      assert.ok(html.includes(`實體 Pin ${location.physical}`));
      assert.ok(html.includes('遠離 USB-A／網路孔端起算，第一支算 1'));
      const row = html.match(/<ol class="pi-row-count"[^>]*>([\s\S]*?)<\/ol>/)?.[1];
      assert.equal((row.match(/<li/g) ?? []).length, 20);
      assert.equal((row.match(/aria-current="step"/g) ?? []).length, 1);
      assert.match(row, new RegExp(`<li aria-current="step"><span[^>]+><\\/span>${location.number}<\\/li>`));
      if (wire.connectionKind === 'divider') {
        assert.ok(html.includes('ECHO 需分壓，不可直連 GPIO'));
        assert.ok(html.includes('330Ω') && html.includes('470Ω'));
        assert.ok(html.includes('class="guide-pin-link" aria-hidden="true">⇢'));
      }
    }
  }
});

test('profile loading fallback keeps the real pin rather than inventing a row', async () => {
  const html = await renderGuide({pinsById:new Map(), session:maker.startProjectGuide(maker.emptyGuide())});
  assert.ok(html.includes('<strong>Pin 6</strong>'));
  assert.ok(!html.includes('pi-row-count'));
});

test('old cloud state cannot render photos or start requests in the guide', async () => {
  const cases = [
    [{busy:true, job:{status:'checking', images:[], result:null, inspection:{phase:'board', stages:[]}}}, '2/3 · 檢查 Pi 接頭'],
    [{error:'fixture error'}, '檢查未完成'],
    [{stale:true, job:{status:'completed', images:[], result:resultFixture}}, '先前照片，請重新檢查'],
    [{job:{status:'completed', images:[], result:resultFixture}}, '這一步還看不清楚'],
  ];
  for (const [check, title] of cases) {
    const session = {...maker.initialMaker().guide, phase:'active'};
    const before = structuredClone(session);
    const html = await renderGuide({check, session});
    assert.deepEqual(session, before);
    assert.ok(!html.includes(title));
    assert.equal(checkButtons(html).length, 0);
    assert.ok(html.includes('我已接好，下一步'));
  }
});

test('review remains a manual record, while unavailable AI does not block manual start', async () => {
  const design = designFor();
  let session = maker.startProjectGuide(maker.initialMaker().guide);
  session = maker.confirmProjectWire(design, session);
  const html = await renderGuide({design, session:{...session, phase:'review'}});
  assert.ok(html.includes('本模組人工紀錄') && html.includes('1 / 4'));
  assert.equal(checkButtons(html).length, 0);
  const unavailable = await renderGuide({poseReady:false, cloudAI:{available:false}});
  assert.equal(checkButtons(unavailable).length,0);
  assert.match(unavailable, /class="guide-primary-action">開始接線/);
  const started = await renderGuide({session:maker.startProjectGuide(maker.emptyGuide()), poseReady:false, cloudAI:{available:false}});
  assert.equal(checkButtons(started).length, 0);
  assert.ok(!started.includes('請先在上方登入 ChatGPT'));
});

test('prepare hides step targets and AI even with restored progress or a previous cloud result', async () => {
  for(const locale of ['zh-TW','en']) for(const cid of ['hc-sr04','mrd-tf240-8p-cs']) {
    const design=designFor([cid]);
    let saved=maker.confirmProjectWire(design,maker.startProjectGuide(maker.emptyGuide()));
    const session={...saved,phase:'prepare',restored:true};
    const before=structuredClone(session), capture={};
    const html=await renderGuide({design,session,locale,capture,check:{busy:true,job:{status:'completed',images:[],result:resultFixture}}});
    assert.deepEqual(session,before);
    assert.equal(capture.cloudReady,false);
    for(const marker of ['guide-connection-card','guide-pin-pair','pi-row-locator','component-row-locator','data-wiring-target=', 'guide-module-review','cloud-result-inline']) assert.ok(!html.includes(marker), marker);
    assert.equal(checkButtons(html).length,0);
    assert.ok(html.includes('guide-prepare-message'));
    assert.ok(html.includes(locale==='en'?'Start wiring →':'開始接線 →'));
    assert.match(html, /<progress[^>]*value="1"/);
  }
});

test('start, review, next module and restart show steps only during active wiring', async () => {
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  let session=maker.emptyGuide();
  const snapshots=[{...session},maker.startProjectGuide(session)];
  session=maker.startProjectGuide(session);
  while(session.phase==='active') session=maker.confirmProjectWire(design,session);
  snapshots.push(session);
  const nextModule={...session,componentIndex:1,index:0,phase:'prepare',checks:[]};
  snapshots.push(nextModule,maker.startProjectGuide(nextModule),maker.restartProjectGuide(nextModule));
  for(const state of snapshots) {
    const capture={}, before=structuredClone(state);
    const html=await renderGuide({design,session:state,capture});
    const active=state.phase==='active';
    assert.equal(html.includes('guide-connection-card'),active);
    assert.equal(html.includes('data-wiring-target='),active);
    assert.equal(checkButtons(html).length,0);
    assert.equal(capture.cloudReady,false);
    assert.equal(html.includes('guide-prepare-message'),state.phase==='prepare');
    assert.equal(html.includes('guide-module-review'),state.phase==='review');
    assert.deepEqual(state,before);
  }
});

function completeModule(design, componentIndex = 0, mode = 'camera') {
  let session = {...maker.startProjectGuide(maker.emptyGuide()), componentIndex, mode, run:3, restored:true, checks:['saved']};
  while (session.phase === 'active') session = maker.confirmProjectWire(design, session);
  return session;
}

test('back from a completed module returns to its last step without changing confirmations or test keys', () => {
  const design = designFor(['hc-sr04', 'mrd-tf240-8p-cs']);
  for (const [componentIndex, cid] of design.component_ids.entries()) for (const mode of ['camera', '2d']) {
    const session = completeModule(design, componentIndex, mode), before = structuredClone(session);
    const steps = design.wiring.filter(w => w.componentId === cid);
    const back = maker.previousProjectWire(design, session);
    assert.deepEqual(session, before);
    assert.deepEqual(back, {...session, phase:'active'});
    assert.equal(back.index, steps.length - 1);
    assert.equal(back.confirmed, session.confirmed);
    assert.notEqual(back.inspection, true);
    assert.equal(componentTests.componentTestKey(design, back, cid), componentTests.componentTestKey(design, session, cid));
    assert.deepEqual(maker.confirmProjectWire(design, back), session);
  }
});

test('back and next on a confirmed step preserve its timestamp and other modules', () => {
  const design = designFor(['hc-sr04', 'mrd-tf240-8p-cs']);
  const hc = completeModule(design), tft = completeModule(design, 1, '2d');
  const session = {...tft, phase:'active', index:2, confirmed:{...hc.confirmed, ...tft.confirmed}};
  const back = maker.previousProjectWire(design, session);
  assert.deepEqual(back, {...session, index:1});
  const forward = maker.confirmProjectWire(design, back);
  assert.deepEqual(forward, session);
  for (const cid of design.component_ids) {
    assert.equal(componentTests.componentTestKey(design, back, cid), componentTests.componentTestKey(design, session, cid));
  }
  for (const [id, confirmation] of Object.entries(session.confirmed)) assert.equal(forward.confirmed[id], confirmation);
});

test('back resumes the displayed paused step or the last restored completed step', () => {
  const design = designFor();
  const partial = maker.confirmProjectWire(design, maker.startProjectGuide(maker.emptyGuide()));
  const paused = {...partial, phase:'review'};
  assert.deepEqual(maker.previousProjectWire(design, paused), {...paused, phase:'active'});
  const saved = {...completeModule(design), phase:'prepare', index:0};
  assert.deepEqual(maker.previousProjectWire(design, saved), {...saved, phase:'active', index:design.wiring.length - 1});
});

test('back cannot start unprepared wiring, leave the first step or edit an AI inspection', () => {
  const design = designFor();
  for (const session of [maker.emptyGuide(), maker.startProjectGuide(maker.emptyGuide()),
    {...maker.emptyGuide(), confirmed:{[design.wiring[0].id]:{signature:'obsolete', at:'old', mode:'camera'}}}]) {
    assert.equal(maker.previousProjectWire(design, session), session);
  }
  const completed = completeModule(design);
  assert.equal(maker.previousProjectWire({...design, wiring:[]}, completed), completed);
  const inspection = maker.reviewProjectWire(design, completed, 'hc-sr04', undefined, 'debug');
  assert.equal(maker.previousProjectWire(design, inspection), inspection);
  assert.equal(maker.confirmProjectWire(design, inspection), inspection);
  assert.deepEqual(maker.resumeProjectGuide(inspection), {...completed, inspection:false});
});

test('normal back is labelled as a previous step, while confirmed steps can go straight to next', async () => {
  const design = designFor(), session = completeModule(design);
  for (const locale of ['zh-TW', 'en']) {
    const overview = await renderGuide({design, session, locale});
    const footer = overview.match(/<footer class="guide-panel-footer">([\s\S]*?)<\/footer>/)[1];
    assert.ok(footer.includes(locale === 'en' ? '>Back</button>' : '>上一步</button>'));
    assert.ok(!footer.includes(locale === 'en' ? '>Review</button>' : '>回看</button>'));
    const active = await renderGuide({design, session:maker.previousProjectWire(design, session), locale});
    assert.match(active, /guide-connection-card/);
    assert.ok(active.includes(locale === 'en' ? '>Next →</button>' : '>下一步 →</button>'));
    for (const copy of ['Connected · Next', '我已接好，下一步', 'Resume wiring', '返回接線', 'Edit this component wiring', '我要修改此零件接線']) assert.ok(!active.includes(copy), copy);
    const fresh = await renderGuide({design, session:maker.startProjectGuide(maker.emptyGuide()), locale});
    assert.ok(fresh.includes(locale === 'en' ? '>Connected · Next →</button>' : '>我已接好，下一步 →</button>'));
  }
});

test('navigating confirmed steps keeps the matching passed test result available', async () => {
  const design = designFor(), session = completeModule(design);
  const result = {id:'navigation-test', component_id:'hc-sr04', project_id:design.id, revision:design.revision,
    guide_key:componentTests.componentTestKey(design, session, 'hc-sr04'), outcome:'passed', phase:'finished',
    invalidated:false, reserved:false, samples:{}, logs:[], created_at:1700000000};
  const tests = {status:{connected:true, active:null, results:[result], test_busy:false}};
  const before = structuredClone(tests);
  const back = maker.previousProjectWire(design, session);
  for (const state of [session, back, maker.previousProjectWire(design, back), maker.confirmProjectWire(design, back)]) {
    assert.equal(result.guide_key, componentTests.componentTestKey(design, state, 'hc-sr04'));
    const html = await renderGuide({design, session:state, tests});
    assert.match(html, /功能通過/);
    assert.doesNotMatch(html, /稍後測試，前往部署/);
  }
  assert.deepEqual(tests, before);
});
