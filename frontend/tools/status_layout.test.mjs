import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, ScriptTarget, JsxEmit } from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import postcss from 'postcss';

test('telemetry wraps fixed-width slots without a scrollbar or clipping live values', () => {
  const css = postcss.parse(readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8'));
  const declarations = selector => {
    const values = {};
    css.walkRules(selector, rule => rule.walkDecls(d => { values[d.prop] = d.value; }));
    return values;
  };
  const metrics = declarations('.status-metrics');
  assert.equal(metrics.display, 'flex');
  assert.equal(metrics['flex-wrap'], 'wrap');
  assert.equal(metrics.overflow, 'visible');
  assert.equal(metrics['overflow-x'], undefined);
  assert.equal(metrics.height, undefined);
  assert.equal(metrics['font-variant-numeric'], 'tabular-nums');
  const slot = declarations('.status-metrics > *');
  assert.equal(slot.flex, '0 0 var(--metric-width)');
  assert.equal(slot['max-width'], '100%');
  assert.equal(slot['min-height'], '28px');
  const widths = [120, 110, 190, 90, 115, 220, 165, 215, 230];
  widths.forEach((width, index) => {
    assert.equal(declarations(`.status-metrics > :nth-child(${index + 1})`)['--metric-width'], `${width}px`);
  });
  // All nine stable slots fit one row in the reported 1708px desktop view.
  assert.equal(metrics.gap, '2px 10px');
  assert.ok(widths.reduce((sum, width) => sum + width, 0) + 8 * 10 <= 1600);
  assert.equal(declarations('.statusbar').padding, '5px 10px');
  assert.equal(declarations('.statusbar').gap, '4px 10px');
  const actions = declarations('.status-actions');
  assert.equal(actions['min-height'], '30px');
  assert.equal(actions['flex-wrap'], 'wrap');
  assert.equal(actions.overflow, 'visible');
  assert.equal(actions['overflow-x'], undefined);
});

test('wiring layout removes the pin query row while retaining guide highlights and Maker AI', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const api = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
  assert.doesNotMatch(app, /QueryBox|[Qq]ueryResult|querySet|handleQuery/);
  assert.doesNotMatch(api, /postQuery|\/api\/query/);
  assert.doesNotMatch(css, /\.query(?:box|-row|-input|-send|-result|-clear)/);
  assert.match(app, /const highlightIds = guideSet \?\? filterSet;/);
  assert.match(app, /<VideoView[\s\S]*highlightIds=\{highlightIds\}/);
  assert.match(app, /<ProjectGuidePanel/);
  assert.match(app, /<StatusBar/);
  assert.match(app, /<MakerAssistant/);
  assert.match(app, /<MakerModelMenu/);
});

const source = readFileSync(new URL('../src/components/StatusBar.tsx', import.meta.url), 'utf8');
const freshnessSource = readFileSync(new URL('../src/lib/traceFreshness.ts', import.meta.url), 'utf8');
const stripImports = code => code.replace(/^import[\s\S]*?;\r?\n/gm, '');
const freshnessJs = transpileModule(stripImports(freshnessSource), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 },
}).outputText;
const freshness = {};
new Function('exports', freshnessJs)(freshness);
const distanceSource = readFileSync(new URL('../src/lib/boardDistance.ts', import.meta.url), 'utf8');
const distanceJs = transpileModule(stripImports(distanceSource), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 },
}).outputText;
const distance = {};
new Function('exports', 'isWireTraceFresh', distanceJs)(distance, freshness.isWireTraceFresh);
let snapshot;
let motionSnapshot;
const js = transpileModule(stripImports(source), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022, jsx: JsxEmit.React },
}).outputText;
const exports = {};
new Function('exports', 'React', 'useState', 'useEffect', 'useRef', 'useSyncExternalStore',
  'useI18n', 'useDetections', 'getMotionDisplay', 'subscribeMotionDisplay',
  'advanceBoardStatus', 'currentPitchSample', 'distanceScaleAdvice', 'hasCurrentBoardBody',
  'pinDisplayNameWithNumber', 'CameraAutoTune', js)(
  exports, React, React.useState, React.useEffect, React.useRef, React.useSyncExternalStore,
  () => ({ t: key => key }), () => snapshot, () => motionSnapshot, () => () => {},
  distance.advanceBoardStatus, distance.currentPitchSample, distance.distanceScaleAdvice,
  distance.hasCurrentBoardBody,
  () => '', ({ alignment }) => React.createElement('span', {
    'data-camera-auto': alignment ? 'pi-alignment' : 'camera-only',
  }),
);
test('telemetry retains the same slots when confidence and geometry disappear', () => {
  const frames = [
    { detection: null, connected: false, detectionsPerSec: 0 },
    { detection: { tracking: 'locked', confidence: .09, video_size: [1920,1080], geometry: {pitch_px:9,px_per_mm:3}, pose_quality: {inliers:4,reproj_px:1} }, connected: true, detectionsPerSec: 9 },
    { detection: { tracking: 'locked', confidence: 1, video_size: [1920,1080], geometry: {pitch_px:100,px_per_mm:39}, pose_quality: {inliers:120,reproj_px:10} }, connected: true, detectionsPerSec: 100 },
  ];
  const markup = frames.map(frame => {
    snapshot = frame;
    return renderToStaticMarkup(React.createElement(exports.StatusBar, { pinsById: new Map(), accuracy: null }));
  });
  const tags = html => html.match(/<\/?[a-z]+/g);
  assert.deepEqual(tags(markup[0]), tags(markup[1]));
  assert.deepEqual(tags(markup[1]), tags(markup[2]));
  assert.match(markup[0], /—/);
  assert.match(markup[2], /status.waitingFrame/);
  assert.ok(markup.every(html => html.includes('status-metrics') && html.includes('status-actions')));
});

test('distance guide uses live source pixels, the worker gate, and fresh matching traces', () => {
  const accuracy = { pitch_px: 10.28, min_pitch_px: 18, min_px_per_mm: 8 };
  const detection = {
    board_id: 'raspberry-pi-5', runtime_revision: 2, tracking: 'locked', frame_id: 100,
    video_size: [1920, 1080], geometry: { pitch_px: 15.3, px_per_mm: 6.02 }, pins: [],
  };
  const now = Date.now();
  const advice = (detectionArg, traceArg = null, accuracyArg = accuracy, connected = true, extra = {}) =>
    distance.distanceScaleAdvice({
      connected, detection: detectionArg, rawDetection: detectionArg, trace: traceArg,
      traceReceivedAtMs: now, accuracy: accuracyArg,
      currentSample: distance.currentPitchSample(detectionArg, now, new Map(), now),
      lastSample: null, now, boardId: detection.board_id, runtimeRevision: 2,
      videoSize: [1920, 1080], ...extra,
    });
  const tooSmall = advice(detection);
  assert.equal(tooSmall.state, 'moveCloser');
  assert.equal(tooSmall.pitchPx, 15.3);
  assert.ok(Math.abs(tooSmall.minimumPx - 20.32) < 0.001);
  assert.ok(Math.abs(tooSmall.targetPx - 24.384) < 0.001);
  assert.ok(Math.abs(tooSmall.factor - 24.384 / 15.3) < 0.001);
  assert.equal(advice(detection, null, accuracy, false).state, 'offline');
  assert.equal(advice({ ...detection, tracking: 'searching' }).state, 'searching');
  assert.equal(advice({ ...detection, pose_quality: { outline_only: true } }).state, 'waiting');
  assert.equal(advice({ ...detection, tracking: 'searching', body: { confidence: .6 },
    pose_quality: { stability: 'pcb_boundary_unverified' } }).state, 'boardUnverified');

  const large = { ...detection, geometry: { pitch_px: 26, px_per_mm: 10.24 } };
  assert.equal(advice(large).state, 'checkingTrace'); // A pose alone cannot pass the worker gate.
  const trace = {
    board_id: detection.board_id, board_tracking: 'locked', frame_id: 99,
    video_size: [1920, 1080], geometry: { pitch_px: 26, px_per_mm: 10.24 },
  };
  assert.equal(advice(large, trace).state, 'scaleReady');
  assert.equal(advice(large, { ...trace, board_id: 'other-board' }).state, 'checkingTrace');
  assert.equal(advice(large, { ...trace, frame_id: 54 }).state, 'checkingTrace');
  assert.equal(advice(large, { ...trace, video_size: [1280, 720] }).state, 'checkingTrace');
  assert.equal(advice(large, { ...trace, board_tracking: 'stale' }).state, 'checkingTrace');
  assert.equal(advice(large, trace, accuracy, true, { traceReceivedAtMs: now - 2000 }).state, 'checkingTrace');

  const blocked = {
    ...trace, suppressed_reason: 'scale_below_minimum',
    geometry: { pitch_px: 19, px_per_mm: 7.48, min_pitch_px: 22, min_px_per_mm: 9 },
  };
  const blockedAdvice = advice({ ...detection, geometry: { pitch_px: 19, px_per_mm: 7.48 } }, blocked);
  assert.equal(blockedAdvice.state, 'moveCloser');
  assert.equal(blockedAdvice.pitchPx, 19);
  assert.ok(Math.abs(blockedAdvice.minimumPx - 22.86) < 0.001);
  assert.equal(advice(large, blocked).state, 'addMargin');
  assert.equal(advice(large, null, null).state, 'waiting');
  assert.equal(advice({ ...detection, geometry: { pitch_px: 22, px_per_mm: 8.66 } }).state, 'addMargin');
});

test('motion-frame J8 pitch guides distance while raw detector searches; short loss keeps only labelled last measurement', () => {
  const pinsById = new Map();
  const pins = [];
  for (let index = 1; index <= 40; index++) {
    const id = `P${index}`;
    pinsById.set(id, { id, header: 'J8', index });
    pins.push({ id, x: 100 + (index % 2) * 20, y: 200 + Math.floor((index - 1) / 2) * 15,
      v: true });
  }
  const now = Date.now();
  const motionPose = { board_id: 'raspberry-pi-5', runtime_revision: 2, frame_id: 104,
    tracking: 'locked', video_size: [1920, 1080], pins };
  const sample = distance.currentPitchSample(motionPose, now, pinsById, now);
  assert.equal(sample.pitchPx, 15);
  assert.equal(distance.projectedPinPitch({ ...motionPose,
    pins: pins.filter(pin => pin.id === 'P1' || pin.id === 'P5') }, pinsById), null);
  const raw = { ...motionPose, frame_id: 101, tracking: 'searching', pins: [],
    body: { confidence: .52 }, pose_quality: { stability: 'pcb_boundary_unverified' } };
  const args = { connected: true, detection: motionPose, rawDetection: raw, trace: null,
    traceReceivedAtMs: 0, accuracy: { min_pitch_px: 18, min_px_per_mm: 8 },
    currentSample: sample, lastSample: sample, now,
    boardId: motionPose.board_id, runtimeRevision: 2, videoSize: [1920, 1080] };
  const live = distance.distanceScaleAdvice(args);
  assert.equal(live.state, 'moveCloser');
  assert.equal(live.boundaryUnverified, true);
  assert.equal(live.sampleFresh, true);
  const brieflyLost = distance.distanceScaleAdvice({ ...args, detection: null, currentSample: null, now: now + 900 });
  assert.equal(brieflyLost.state, 'moveCloser');
  assert.equal(brieflyLost.sampleFresh, false);
  assert.equal(distance.distanceScaleAdvice({ ...args, detection: null, currentSample: null,
    now: now + 2600 }).state, 'waitingFrame');
  assert.equal(distance.distanceScaleAdvice({ ...args, detection: null, currentSample: null,
    runtimeRevision: 3, now: now + 900 }).state, 'waitingFrame');
});

test('board wording does not flash LOCKED on a single good frame or say missing when its body is visible', () => {
  const base = { board_id: 'raspberry-pi-5', frame_id: 0, tracking: 'searching',
    pins: [], body: { confidence: .55 } };
  let run = { context: '', frameId: -1, count: 0 };
  for (let frameId = 1; frameId <= 12; frameId++) {
    const detection = frameId % 3 === 0
      ? { ...base, frame_id: frameId, tracking: 'locked', pins: [{ id: 'P1', v: true }] }
      : { ...base, frame_id: frameId };
    const next = distance.advanceBoardStatus(run, 'pi:2:motion', detection, true);
    run = next.run;
    assert.equal(next.statusKey, 'status.posePending');
  }
  run = distance.advanceBoardStatus(run, 'pi:2:motion', { ...base, frame_id: 13 }, true).run;
  for (let frameId = 14; frameId <= 17; frameId++) {
    const next = distance.advanceBoardStatus(run, 'pi:2:motion',
      { ...base, frame_id: frameId, tracking: 'locked', pins: [{ id: 'P1', v: true }] }, true);
    run = next.run;
    assert.equal(next.statusKey, frameId === 17 ? 'status.locked' : 'status.posePending');
  }
  const lost = distance.advanceBoardStatus(run, 'pi:2:motion',
    { ...base, frame_id: 18 }, true);
  assert.equal(lost.statusKey, 'status.posePending');
  assert.equal(lost.poseLocked, false);
  const switched = distance.advanceBoardStatus(run, 'pi:3:motion',
    { ...base, frame_id: 19, tracking: 'locked', pins: [{ id: 'P1', v: true }] }, true);
  assert.equal(switched.statusKey, 'status.posePending');
  assert.equal(distance.advanceBoardStatus(switched.run, 'pi:3:motion', null, false).statusKey,
    'status.waitingFrame');
});

test('status and distance advice follow the synchronized video frame, not a contradictory raw packet', () => {
  const now = Date.now();
  const boardId = 'raspberry-pi-5';
  const raw = { board_id: boardId, runtime_revision: 2, frame_id: 100,
    tracking: 'searching', video_size: [1920, 1080], pins: [],
    body: { confidence: .55 }, pose_quality: { stability: 'pcb_boundary_unverified' } };
  const motionPose = { ...raw, frame_id: 105, tracking: 'locked',
    geometry: { pitch_px: 15.3, px_per_mm: 6.02 }, pins: [{ id: 'P1', v: true }] };
  snapshot = { detection: raw, connected: true, detectionReceivedAtMs: now,
    detectionsPerSec: 8, wireTrace: null, wireTraceReceivedAtMs: 0 };
  motionSnapshot = { board_id: boardId, runtime_revision: 2, frame_id: 105,
    detection: motionPose, receivedAt: now };
  const render = () => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    webcamTuningVisible: true, boardId, runtimeRevision: 2,
    pinsById: new Map(), accuracy: { min_pitch_px: 18, min_px_per_mm: 8,
      status: 'warning', warnings: [] },
  }));
  const html = render();
  assert.match(html, /status.posePending/);
  assert.match(html, /distanceAssistant.moveCloser/);
  assert.match(html, /distanceAssistant.boundaryUnverified/);
  assert.doesNotMatch(html, /status.searching/);
  motionSnapshot = null; // realtime mode active, but no synchronized image yet
  const waiting = render();
  assert.match(waiting, /distanceAssistant.waitingFrame/);
  assert.doesNotMatch(waiting, /distanceAssistant.scaleReady/);
  motionSnapshot = undefined;
});

test('a live camera revision updates status before the config refresh, without reviving old frames', () => {
  const now = Date.now();
  const boardId = 'raspberry-pi-5';
  const detection = { board_id: boardId, runtime_revision: 3, frame_id: 201,
    tracking: 'locked', confidence: .63, video_size: [1920, 1080],
    pins: [{ id: 'P1', v: true }] };
  motionSnapshot = undefined;
  snapshot = { connected: true, runtime: { board_id: boardId, runtime_revision: 3 },
    detection, detectionReceivedAtMs: now, detectionsPerSec: 17 };
  const render = () => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    boardId, runtimeRevision: 2, pinsById: new Map(), accuracy: null,
  }));
  assert.match(render(), /status.posePending/);
  assert.match(render(), /63%/);
  assert.doesNotMatch(render(), /status.searching/);
  snapshot = { ...snapshot, detection: { ...detection, runtime_revision: 2 } };
  assert.match(render(), /status.waitingFrame/);
  assert.doesNotMatch(render(), /63%/);
  motionSnapshot = undefined;
});

test('body-only confidence is labelled as unlocated, while a live motion frame survives a WS reconnect', () => {
  const now = Date.now();
  const boardId = 'raspberry-pi-5';
  const bodyOnly = { board_id: boardId, runtime_revision: 2, frame_id: 202,
    tracking: 'searching', confidence: 0, video_size: [1920, 1080], pins: [],
    body: { confidence: .55, frame_id: 202, age_ms: 100 } };
  const render = () => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    boardId, runtimeRevision: 2, pinsById: new Map(), accuracy: null,
  }));
  snapshot = { connected: true, runtime: { board_id: boardId, runtime_revision: 2 },
    detection: bodyOnly, detectionReceivedAtMs: now, detectionsPerSec: 17 };
  motionSnapshot = undefined;
  assert.match(render(), /status.posePending/);
  assert.match(render(), /55%/);
  assert.match(render(), /status.bodyConfidenceTooltip/);
  snapshot = { ...snapshot, connected: false };
  motionSnapshot = { board_id: boardId, runtime_revision: 2, frame_id: 202,
    detection: bodyOnly, receivedAt: now };
  assert.match(render(), /status.posePending/);
  assert.match(render(), /55%/);
  assert.match(render(), /status.disconnected/);
  motionSnapshot = { ...motionSnapshot, runtime_revision: 3,
    detection: { ...bodyOnly, runtime_revision: 3 } };
  assert.match(render(), /status.posePending/); // HTTP frame can advance before config during WS reconnect.
  motionSnapshot = undefined;
});

test('distance guide appears only in webcam controls and retains an honest warning', () => {
  snapshot = { detection: null, connected: false, detectionsPerSec: 0 };
  const render = webcamTuningVisible => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    webcamTuningVisible, pinsById: new Map(), accuracy: null,
  }));
  assert.doesNotMatch(render(false), /distance-assistant/);
  const html = render(true);
  assert.match(html, /<details class="distance-assistant">/);
  assert.match(html, /distanceAssistant.offline/);
  assert.match(html, /distanceAssistant.limit/);
});

test('Pi webcam exposes auto alignment inside the distance guide; other boards keep camera-only tuning', () => {
  snapshot = { detection: null, connected: false, detectionsPerSec: 0 };
  motionSnapshot = undefined;
  const render = boardId => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    webcamTuningVisible: true, boardId, runtimeRevision: 2,
    pinsById: new Map(), accuracy: null,
  }));
  const pi = render('raspberry-pi-5');
  assert.match(pi, /<details class="distance-assistant">[\s\S]*data-camera-auto="pi-alignment"[\s\S]*<\/details>/);
  assert.doesNotMatch(pi, /data-camera-auto="camera-only"/);
  const other = render('other-board');
  assert.match(other, /data-camera-auto="camera-only"/);
  assert.doesNotMatch(other, /data-camera-auto="pi-alignment"/);
  motionSnapshot = undefined;
});

test('a stopped camera cannot leave a stale scale-ready claim on screen', () => {
  const detection = {
    board_id: 'raspberry-pi-5', runtime_revision: 2, tracking: 'locked', frame_id: 100, confidence: 1,
    video_size: [1920, 1080], geometry: { pitch_px: 26, px_per_mm: 10.24 }, pins: [{ id: 'P1', v: true }],
  };
  const wireTrace = {
    board_id: detection.board_id, board_tracking: 'locked', frame_id: 99,
    video_size: [1920, 1080], geometry: { pitch_px: 26, px_per_mm: 10.24 },
  };
  const render = () => renderToStaticMarkup(React.createElement(exports.StatusBar, {
    webcamTuningVisible: true, pinsById: new Map(),
    accuracy: { min_pitch_px: 18, min_px_per_mm: 8, status: 'ready', warnings: [] },
  }));
  snapshot = { detection, wireTrace, wireTraceReceivedAtMs: Date.now(), connected: true,
    detectionsPerSec: 8, detectionReceivedAtMs: Date.now() };
  assert.match(render(), /distanceAssistant.scaleReady/);
  snapshot = { ...snapshot, detectionsPerSec: 0, detectionReceivedAtMs: Date.now() - 5000 };
  assert.match(render(), /distanceAssistant.waitingFrame/);
  assert.doesNotMatch(render(), /distanceAssistant.scaleReady/);
});
