import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';

function load(path, modules = {}) {
  const exports = {}, code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function('require', 'exports', code)(name => { if (!(name in modules)) throw Error(`Unexpected import: ${name}`); return modules[name]; }, exports);
  return exports;
}
const tune = load('../src/lib/phoneCameraTuning.ts'), rtc = load('../src/lib/mobileBrowserRtc.ts');
const normal = { level: 120, highlights: .01, shadows: .1, detail: 200, motion: 0, issues: [] };
function fixture({ modes = false, reports, quality = normal } = {}) {
  const writes = []; let cap = 12000, undo = null, current = true;
  let constraints = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { max: 30 }, facingMode: { ideal: 'environment' } };
  const values = { focusMode: 'manual' };
  const track = { readyState: 'live', getCapabilities: () => modes ? { focusMode: ['manual', 'continuous'] } : {},
    getSettings: () => ({ ...values }), getConstraints: () => structuredClone(constraints),
    async applyConstraints(value) { writes.push(value); constraints = structuredClone(value); Object.assign(values, value.advanced.at(-1)); } };
  const stream = { getVideoTracks: () => [track] }, stats = reports ?? [
    { measuredAtMs: Date.now() - 1000, sampleIntervalMs: 1000, qualityLimitationReason: 'bandwidth', sendFps: 15 },
    { measuredAtMs: Date.now(), sampleIntervalMs: 1000, qualityLimitationReason: 'bandwidth', sendFps: 16 }];
  let observed = 0;
  const io = { stream, current: () => current, stats: () => stats[Math.min(observed++, stats.length - 1)] ?? {}, readBitrate: () => cap,
    sample: async (_signal, observe) => { observe(); observe(); return structuredClone(quality); },
    adjustBitrate: async value => { writes.push({ bitrate: value }); cap = value; return cap; }, saveUndo: value => { undo = value; } };
  return { io, stream, track, writes, values, undo: () => undo, bitrate: () => cap, changeSource: () => { current = false; } };
}
const pixels = (width, height, value) => new Uint8ClampedArray(Array.from({ length: width * height }, (_, i) => [value(i), value(i), value(i), 255]).flat());

test('image hints separate dark / glare / low detail and do not assert wiring or true focus', () => {
  assert.deepEqual(tune.phoneFrameQuality(pixels(16, 16, () => 8), 16, 16).quality.issues, ['dark', 'detail']);
  assert.deepEqual(tune.phoneFrameQuality(pixels(16, 16, () => 255), 16, 16).quality.issues, ['glare', 'detail']);
  const sharp = tune.phoneFrameQuality(pixels(16, 16, i => (i + Math.floor(i / 16)) % 2 ? 160 : 60), 16, 16);
  assert.deepEqual(sharp.quality.issues, []);
  assert.ok(tune.phoneFrameQuality(pixels(16, 16, () => 120), 16, 16, new Uint8Array(256)).quality.issues.includes('motion'));
});

test('transport plans require two distinct fresh counter reports, never missing or cached FPS', () => {
  const now = 10000, slow = time => ({ measuredAtMs: time, sampleIntervalMs: 1000, sendFps: 10, qualityLimitationReason: 'bandwidth' });
  assert.equal(tune.phoneTransportPlan([slow(9000), slow(10000)], 12000, now).bitrate, 3000);
  for (const reports of [[slow(10000)], [slow(10000), slow(10000)], [slow(1000), slow(2000)],
    [{ ...slow(9000), sendFps: undefined }, slow(10000)], [{ ...slow(9000), sampleIntervalMs: 5000 }, slow(10000)]]) {
    assert.equal(tune.phoneTransportPlan(reports, 12000, now).bitrate, 12000);
  }
  assert.equal(tune.phoneTransportPlan([slow(9000), slow(10000)], null, now).bitrate, null);
});

test('CPU load recommends an explicit 720p restart, while unknown or low resolution does not', () => {
  const reports = [9000, 10000].map(measuredAtMs => ({ measuredAtMs, sampleIntervalMs: 1000, sendFps: 15, qualityLimitationReason: 'cpu', width: 1080, height: 1920 }));
  assert.deepEqual(tune.phoneTransportPlan(reports, 8000, 10000), { bitrate: 8000, resolution: '720p' });
  assert.equal(tune.phoneTransportPlan(reports.map(r => ({ ...r, width: 720, height: 1280 })), 8000, 10000).resolution, null);
});

test('Safari without sensor capabilities can still lower the existing stream cap and restore it', async () => {
  const f = fixture(), result = await tune.tunePhoneCamera(f.io, new AbortController().signal);
  assert.equal(result.camera, 'unsupported'); assert.equal(result.bitrateChanged, true); assert.equal(f.bitrate(), 8000);
  assert.deepEqual(f.writes, [{ bitrate: 8000 }]);
  await tune.restorePhoneTune(f.io, f.undo()); assert.equal(f.bitrate(), 12000); assert.equal(f.undo(), null);
});

test('missing Safari bitrate readback and stable normal image keep every parameter untouched', async () => {
  const f = fixture(); f.io.readBitrate = () => null;
  const result = await tune.tunePhoneCamera(f.io, new AbortController().signal);
  assert.equal(result.bitrateChanged, false); assert.equal(result.camera, 'unsupported'); assert.deepEqual(f.writes, []);
  const absent = { getCapabilities() { throw Error('unsupported'); } };
  assert.deepEqual(tune.phoneAutomaticModes(absent), {});
  assert.deepEqual(tune.phoneAutomaticModes({ getCapabilities: () => ({ focusMode: ['continuous'] }), getSettings: () => ({}) }), {});
});

test('moving scene never triggers camera or bitrate adjustments', async () => {
  const f = fixture({ modes: true, quality: { ...normal, issues: ['motion'], motion: 25 } });
  const result = await tune.tunePhoneCamera(f.io, new AbortController().signal);
  assert.equal(result.bitrateChanged, false); assert.deepEqual(f.writes, []); assert.equal(f.undo(), null);
});

test('automatic mode changes retain source constraints and revert when quality does not improve', async () => {
  const f = fixture({ modes: true, reports: [] });
  const result = await tune.tunePhoneCamera(f.io, new AbortController().signal);
  assert.equal(result.camera, 'unchanged'); assert.equal(f.values.focusMode, 'manual'); assert.equal(f.undo(), null);
  for (const write of f.writes) {
    assert.deepEqual(write.width, { ideal: 1920 }); assert.deepEqual(write.frameRate, { max: 30 });
    assert.deepEqual(write.facingMode, { ideal: 'environment' });
  }
});

test('verified camera improvement can be restored without starting or replacing the track', async () => {
  const f = fixture({ modes: true, reports: [] }); let samples = 0;
  f.io.sample = async () => ({ ...normal, detail: ++samples === 1 ? 200 : 320 });
  const result = await tune.tunePhoneCamera(f.io, new AbortController().signal);
  assert.equal(result.camera, 'improved'); assert.equal(f.values.focusMode, 'continuous');
  await tune.restorePhoneTune(f.io, f.undo()); assert.equal(f.values.focusMode, 'manual');
});

test('cancel after a camera write drains and restores that write before resolving', async () => {
  const f = fixture({ modes: true }), abort = new AbortController(), apply = f.track.applyConstraints;
  f.track.applyConstraints = async value => { await apply(value); if (value.advanced.at(-1).focusMode === 'continuous') abort.abort(); };
  await assert.rejects(tune.tunePhoneCamera(f.io, abort.signal), error => error.name === 'AbortError');
  assert.equal(f.values.focusMode, 'manual'); assert.equal(f.bitrate(), 12000); assert.equal(f.undo(), null);
});

test('changed scope rolls back the same camera, but replaced / stopped streams are not written', async () => {
  const f = fixture({ modes: true }), apply = f.track.applyConstraints;
  f.io.sourceCurrent = () => true;
  f.track.applyConstraints = async value => { await apply(value); if (value.advanced.at(-1).focusMode === 'continuous') f.changeSource(); };
  await assert.rejects(tune.tunePhoneCamera(f.io, new AbortController().signal), /source_changed/);
  assert.equal(f.values.focusMode, 'manual');
  const other = fixture(); other.changeSource();
  await assert.rejects(tune.restorePhoneTune(other.io, { stream: other.stream, modes: {}, bitrate: 12000 }), /source_changed/);
  assert.deepEqual(other.writes, []);
});

test('failed rollback remains explicit and retains the undo for a retry', async () => {
  const f = fixture({ modes: true }), abort = new AbortController(), apply = f.track.applyConstraints;
  f.track.applyConstraints = async value => {
    if (value.advanced.at(-1).focusMode === 'manual') throw Error('restore rejected');
    await apply(value); abort.abort();
  };
  await assert.rejects(tune.tunePhoneCamera(f.io, abort.signal), /restore_failed/); assert.ok(f.undo());
  f.track.applyConstraints = apply; await tune.restorePhoneTune(f.io, f.undo()); assert.equal(f.undo(), null);
});

function publisherScene() {
  const requests = [], writes = []; let acquired = 0, stopped = 0, parameters = { encodings: [{}] }, reject = false, ignore = false;
  const track = { kind: 'video', readyState: 'live', getSettings: () => ({ width: 1920, height: 1080 }), stop() { stopped++; } };
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const sender = { track, getParameters: () => structuredClone(parameters), async setParameters(value) {
    writes.push(structuredClone(value)); if (reject && value.encodings[0].maxBitrate === 8000000) throw Error('reject');
    if (!ignore || value.encodings[0].maxBitrate !== 8000000) parameters = structuredClone(value);
  } };
  const peer = { connectionState: 'connected', iceGatheringState: 'complete', localDescription: null,
    addTrack: () => sender, getSenders: () => [sender], createOffer: async () => ({ type: 'offer', sdp: 'synthetic' }),
    async setLocalDescription(value) { this.localDescription = value; }, async setRemoteDescription() {}, getStats: async () => new Map(), close() {} };
  const publisher = new rtc.BrowserPublisher({ request: async (path, options) => { requests.push({ path, ...options }); return path === 'stream' ? { generation: 1 } : { type: 'answer', sdp: 'synthetic' }; } }, () => {},
    { getUserMedia: async () => { acquired++; return stream; }, makePeer: () => peer,
      normalizeStream: async () => ({ stream, dispose() {}, readFrame: () => ({ sourceSize: [1920, 1080], outputSize: [1920, 1080], rotation: 0 }) }) });
  return { publisher, stream, requests, writes, acquired: () => acquired, stopped: () => stopped,
    reject: () => { reject = true; }, ignore: () => { ignore = true; }, sender };
}

test('real publisher bitrate adjustment retains one acquisition, negotiation, stream and track', async () => {
  const f = publisherScene();
  try {
    await f.publisher.start({ bitrateKbps: 12000 }); assert.equal(f.publisher.readLiveBitrate(f.stream), 12000);
    await f.publisher.adjustLiveBitrate(f.stream, 8000); assert.equal(f.publisher.readLiveBitrate(f.stream), 8000);
    await f.publisher.adjustLiveBitrate(f.stream, 12000); assert.equal(f.acquired(), 1); assert.equal(f.stopped(), 0);
    assert.equal(f.requests.filter(r => r.path === 'stream/offer').length, 1);
    assert.equal(f.requests.filter(r => r.method === 'DELETE').length, 0);
    await assert.rejects(f.publisher.adjustLiveBitrate({}, 8000), /source_changed/);
    await assert.rejects(f.publisher.adjustLiveBitrate(f.stream, 16000), /unsupported/);
  } finally { await f.publisher.stop(); }
});

test('ignored / rejected Safari sender settings are rolled back and never labelled successful', async () => {
  for (const failure of ['ignore', 'reject']) {
    const f = publisherScene();
    try { await f.publisher.start({ bitrateKbps: 12000 }); f[failure]();
      await assert.rejects(f.publisher.adjustLiveBitrate(f.stream, 8000)); assert.equal(f.publisher.readLiveBitrate(f.stream), 12000);
      assert.equal(f.acquired(), 1); assert.equal(f.stopped(), 0);
    } finally { await f.publisher.stop(); }
  }
});

function panel(locale, controller, disabled = false) {
  const { PhoneCameraAutoTune } = load('../src/components/PhoneCameraAutoTune.tsx', { 'react/jsx-runtime': jsx,
    '../lib/i18n': { useI18n: () => ({ locale }) }, './phoneCameraAutoTune.css': {} });
  const callbacks = [], props = { controller, disabled, video: { current: 'existing-video' }, onResolution: value => callbacks.push(value) };
  return { tree: PhoneCameraAutoTune(props), callbacks };
}
const nodes = tree => !React.isValidElement(tree) ? [] : [tree, ...React.Children.toArray(tree.props.children).flatMap(nodes)];
const idle = () => ({ phase: 'idle', busy: false, result: null, error: '', canRestore: false, start() {}, cancel() {}, restore() {} });

test('bilingual mobile panel exposes one smart action and no unsupported hardware sliders', () => {
  for (const locale of ['en', 'zh-TW']) {
    const f = panel(locale, { ...idle(), result: { quality: normal, camera: 'unsupported', bitrate: 12000, bitrateChanged: false, resolution: null } });
    const html = renderToStaticMarkup(f.tree);
    assert.equal(nodes(f.tree).filter(n => n.type === 'input').length, 0); assert.equal(nodes(f.tree).filter(n => n.type === 'button').length, 1);
    assert.match(html, locale === 'en' ? /Smart adjustment/ : /智慧調整/);
    assert.match(html, locale === 'en' ? /does not verify GPIO/ : /不代表 GPIO/);
  }
});

test('cancel, restore retry and explicit resolution restart call only their own handlers', () => {
  const calls = [], c = { ...idle(), start: value => calls.push(value), cancel: () => calls.push('cancel'), restore: () => calls.push('restore') };
  nodes(panel('en', c).tree).find(n => n.type === 'button').props.onClick();
  const working = panel('en', { ...c, phase: 'checking', busy: true }, true);
  const buttons = nodes(working.tree).filter(n => n.type === 'button'); assert.equal(buttons[0].props.disabled, true); buttons[1].props.onClick();
  const failed = panel('en', { ...c, canRestore: true, error: 'phone_tune_restore_failed' });
  assert.match(renderToStaticMarkup(failed.tree), /Restore is unconfirmed/);
  nodes(failed.tree).filter(n => n.type === 'button')[1].props.onClick();
  const suggested = panel('en', { ...c, result: { quality: normal, camera: 'unsupported', bitrate: 12000, bitrateChanged: false, resolution: '720p' } });
  assert.deepEqual(suggested.callbacks, []); nodes(suggested.tree).filter(n => n.type === 'button').at(-1).props.onClick();
  assert.deepEqual(suggested.callbacks, ['720p']); assert.deepEqual(calls, ['existing-video', 'cancel', 'restore']);
});

function hookScene(core = {}) {
  const states = [], refs = [], effects = [], listeners = new Map(); let s = 0, r = 0, e = 0;
  const previousDocument = globalThis.document;
  globalThis.document = { visibilityState: 'visible', addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) };
  const react = { useState(initial) { const i = s++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
    return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
    useRef(initial) { return refs[r++] ??= { current: initial }; },
    useEffect(fn, deps) { const i = e++, old = effects[i]; if (!old || deps.some((d, j) => d !== old.deps[j])) {
      old?.cleanup?.(); effects[i] = { deps, pending: fn };
    } } };
  const hook = load('../src/lib/usePhoneCameraTune.ts', { react, './phoneCameraTuning': { ...tune, ...core } }).usePhoneCameraTune;
  const f = fixture(), input = { stream: f.stream, scope: 'session:context:1', busy: false, stats: {}, readBitrate: () => 12000, adjustBitrate: async v => v };
  return { input, render() { s = r = e = 0; const value = hook(input); for (const effect of effects) if (effect.pending) {
      const fn = effect.pending; delete effect.pending; effect.cleanup = fn();
    } return value; }, hide() { document.visibilityState = 'hidden'; listeners.get('visibilitychange')?.(); },
    unmount() { for (const effect of effects) effect.cleanup?.(); }, cleanup() { this.unmount(); globalThis.document = previousDocument; } };
}
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const goodResult = () => ({ quality: normal, camera: 'unsupported', bitrate: 8000, bitrateChanged: true, resolution: null });

test('hook synchronously blocks duplicate tune / restore and capture conflicts before React re-renders', async () => {
  const pending = deferred(); let calls = 0;
  const f = hookScene({ tunePhoneCamera: async () => { calls++; await pending.promise; return goodResult(); } });
  try { const c = f.render(), first = c.start({}); assert.equal(c.isRunning(), true);
    await c.start({}); await c.restore(); assert.equal(calls, 1);
    pending.resolve(); await first; assert.equal(f.render().busy, false);
    f.input.blocked = () => true; await f.render().start({}); assert.equal(calls, 1);
  } finally { f.cleanup(); }
});

test('hook cancels when external photo work starts, when hidden, and when unmounted', async () => {
  for (const action of ['busy', 'hide', 'unmount']) {
    let signal; const pending = deferred();
    const f = hookScene({ tunePhoneCamera: async (_io, abort) => { signal = abort; await pending.promise; throw new DOMException('cancel', 'AbortError'); } });
    try { const operation = f.render().start({});
      if (action === 'busy') { f.input.busy = true; f.render(); } else f[action]();
      assert.equal(signal.aborted, true); pending.resolve(); await operation;
    } finally { f.cleanup(); }
  }
});

test('hook discards stale workspace results and source-specific restore after stream replacement', async () => {
  const pending = deferred();
  const f = hookScene({ tunePhoneCamera: async (io) => { io.saveUndo({ stream: io.stream, modes: {}, bitrate: 12000 }); await pending.promise; return goodResult(); } });
  try { const operation = f.render().start({}); f.input.scope = 'new-context'; f.render(); pending.resolve(); await operation;
    assert.equal(f.render().result, null); assert.equal(f.render().canRestore, true);
    f.input.stream = fixture().stream; assert.equal(f.render().canRestore, false);
  } finally { f.cleanup(); }
});

test('hook retains restore backup after failure and clears it only after verified retry', async () => {
  let fail = true;
  const f = hookScene({ tunePhoneCamera: async io => { io.saveUndo({ stream: io.stream, modes: {}, bitrate: 12000 }); return goodResult(); },
    restorePhoneTune: async io => { if (fail) throw Error('phone_tune_restore_failed'); io.saveUndo(null); } });
  try { await f.render().start({}); await f.render().restore();
    assert.equal(f.render().error, 'phone_tune_restore_failed'); assert.equal(f.render().canRestore, true);
    fail = false; await f.render().restore(); assert.equal(f.render().canRestore, false); assert.equal(f.render().error, 'restored');
  } finally { f.cleanup(); }
});

test('fresh frame sampling rejects a paused or replaced source before reading pixels', async () => {
  const oldDocument = globalThis.document; globalThis.document = { visibilityState: 'visible' };
  const f = fixture(); let reads = 0;
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage() { reads++; }, getImageData() { throw Error('not reached'); } }) };
  const video = { srcObject: f.stream, videoWidth: 1920, videoHeight: 1080, readyState: 2, paused: true,
    ownerDocument: { createElement: () => canvas } };
  try { await assert.rejects(tune.samplePhoneFrames(video, f.stream, new AbortController().signal, () => {}), /frame_unavailable/);
    video.paused = false; video.srcObject = {};
    await assert.rejects(tune.samplePhoneFrames(video, f.stream, new AbortController().signal, () => {}), /frame_unavailable/);
    assert.equal(reads, 0); assert.equal(canvas.width, 0);
  } finally { globalThis.document = oldDocument; }
});
