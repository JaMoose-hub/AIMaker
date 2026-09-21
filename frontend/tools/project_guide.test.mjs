import assert from 'node:assert/strict';
import test from 'node:test';
import {board, piGuide, designFor, maker, renderGuide} from './project_guide_fixture.mjs';
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
