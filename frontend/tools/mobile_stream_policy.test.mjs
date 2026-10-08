import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const exports = {};
new Function('exports', ts.transpileModule(readFileSync(new URL('../src/lib/mobileStreamPolicy.ts', import.meta.url), 'utf8'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText)(exports);
const { initialStreamQuality, nextStreamQuality, setBrowserStreamScale, rtcOperation } = exports;
const bad = stamp => ({ measuredAtMs: stamp, sampleIntervalMs: 1000, captureFps: 30, sendFps: 1, targetBitrateKbps: 30, qualityLimitationReason: 'none' });
const good = stamp => ({ ...bad(stamp), sendFps: 28, targetBitrateKbps: 6000 });
const feed = (state, stats, shortEdge = 1080) => nextStreamQuality(state, stats, stats.measuredAtMs, shortEdge);

test('sustained transport starvation can reduce 4K to 1080p, never below it', () => {
  let state = initialStreamQuality();
  for (let t = 1000; t <= 3000; t += 1000) state = feed(state, bad(t),2160);
  assert.equal(state.scale, 1.5);
  for (let t = 4000; t <= 12000; t += 1000) state = feed(state, bad(t),2160);
  assert.equal(state.scale, 1.5, 'cooldown prevents resizing every second');
  state = feed(state, bad(13000),2160); assert.equal(state.scale, 2);
  for (let t = 14000; t <= 45000; t += 1000) state = feed(state, bad(t),2160);
  assert.equal(state.scale, 2, 'never shrink below the bounded tier');
});

test('cached, missing, stale and reset samples cannot drive adaptation', () => {
  const state = feed(initialStreamQuality(), bad(1000));
  for (const stats of [bad(1000), bad(999), { ...bad(2000), sampleIntervalMs: 8000 }, { ...bad(2000), measuredAtMs: undefined }])
    assert.equal(nextStreamQuality(state, stats, 2000, 1080), state);
  assert.equal(nextStreamQuality(state, bad(2000), 5001, 1080), state);
  assert.equal(nextStreamQuality(state, bad(2000), 1999, 1080), state);
  let next = feed(state, bad(5000)); next = feed(next, bad(6000));
  assert.equal(next.scale, 1, 'a long measurement gap resets the consecutive streak');
});

test('slow camera or a single bad report cannot lower quality', () => {
  let state = initialStreamQuality();
  for (let t = 1000; t <= 8000; t += 1000) state = feed(state, { ...bad(t), captureFps: 5 });
  assert.equal(state.scale, 1);
  state = feed(state, bad(9000)); state = feed(state, good(10000));
  assert.equal(state.bad, 0); assert.equal(state.scale, 1);
});

test('recovery waits for sustained healthy counters and a longer cooldown', () => {
  let state = { ...initialStreamQuality(), scale: 2, changedAt: 1000 };
  for (let t = 2000; t <= 30000; t += 1000) state = feed(state, good(t),2160);
  assert.equal(state.scale, 2);
  state = feed(state, good(31000),2160); assert.equal(state.scale, 1.5);
  for (let t = 32000; t <= 61000; t += 1000) state = feed(state, good(t),2160);
  assert.equal(state.scale, 1);
});

test('native low resolution and disabled controls do not attempt unsafe tiers', () => {
  for (const [shortEdge, expected] of [[2160,2],[1620,1.5],[1080, 1], [720, 1], [480, 1]]) {
    let state = initialStreamQuality();
    for (let t = 1000; t <= 30000; t += 1000) state = feed(state, bad(t), shortEdge);
    assert.equal(state.scale, expected);
  }
  const state = { ...initialStreamQuality(), disabled: true };
  assert.equal(feed(state, bad(1000)), state);
});

test('scale changes use existing sender parameters and retain native track and bitrate', async () => {
  const track = {}, calls = []; let parameters = { encodings: [{ maxBitrate: 12000000, maxFramerate: 30 }], degradationPreference: 'maintain-resolution' };
  const sender = { track, getParameters: () => structuredClone(parameters), async setParameters(next) { calls.push(next); parameters = next; } };
  await setBrowserStreamScale(sender, 1.5);
  assert.equal(sender.track, track); assert.equal(calls.length, 1);
  assert.equal(parameters.encodings[0].maxBitrate, 12000000);
  assert.equal(parameters.encodings[0].scaleResolutionDownBy, 1.5);
});

test('ignored and unsupported scale controls are reported, never assumed applied', async () => {
  await assert.rejects(setBrowserStreamScale({ getParameters: () => ({ encodings: [] }) }, 2), /unsupported/);
  await assert.rejects(setBrowserStreamScale({ getParameters: () => ({ encodings: [{}] }), setParameters: async () => {} }, 2), /unsupported/);
});

test('hung browser operations have a bounded deadline', async () => {
  await assert.rejects(rtcOperation(new Promise(() => {}), 10), /timeout/);
  assert.equal(await rtcOperation(Promise.resolve(42), 10), 42);
});

test('a 4:3 source also respects the 1920-pixel long edge and repairs an obsolete scale',()=>{
  let state=initialStreamQuality();
  for(let t=1000;t<=30000;t+=1000)state=nextStreamQuality(state,bad(t),t,2160,2880);
  assert.equal(state.scale,1.5);assert.equal(2880/state.scale,1920);
  state=nextStreamQuality(state,bad(31000),31000,1080,1920);
  assert.equal(state.scale,1);
});
