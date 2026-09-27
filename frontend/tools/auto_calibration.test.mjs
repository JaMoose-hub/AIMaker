import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/autoCalibration.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { inspectAlignment, advanceAlignment, emptyAlignmentRun, postTuneAlignmentIssue } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

const now = 5000;
const distance = { state: 'checkingTrace', pitchPx: 25, minimumPx: 20, targetPx: 24,
  factor: 1, sampleFresh: true, boundaryUnverified: false };
const pose = (frameId, tsMs = frameId * 200) => ({
  board_id: 'raspberry-pi-5', runtime_revision: 2, video_size: [1280, 720], frame_id: frameId,
  ts_ms: tsMs, tracking: 'locked', outline: [[10, 10], [80, 10], [80, 60], [10, 60]],
  pins: Array.from({length: 40}, (_, index) => ({id: `P${index + 1}`, v: true})),
  pose_quality: { object_supported: true, outline_only: false,
    pin_alignment_offset_px: [0.5, -0.5],
    pin_regions: Object.fromEntries(Array.from({length: 40}, (_, index) =>
      [`P${index + 1}`, {supported: true}])) },
});
const inspect = (detection, extra = {}) => inspectAlignment({
  detection, distance, receivedAtMs: now - 100, now, synchronized: true, ...extra,
});

test('auto alignment needs fresh synchronized J8 evidence and adequate source pitch', () => {
  assert.equal(inspect(pose(5)).kind, 'supported');
  assert.equal(inspect(pose(5), { synchronized: false }).issue, 'realtimeRequired');
  assert.equal(inspect(null).issue, 'waitingFrame');
  assert.equal(inspect(pose(5), {receivedAtMs: now - 900}).issue, 'waitingFrame');
  assert.equal(inspect(pose(5), {receivedAtMs: now + 250, now: now + 250}).kind, 'supported');
  assert.equal(inspect({...pose(5), tracking: 'searching', pose_quality: {reason: 'pcb_boundary_unverified'}}).issue, 'boundary');
  assert.equal(inspect(pose(5), {distance: {...distance, pitchPx: 9}}).issue, 'moveCloser');
  assert.equal(inspect({...pose(5), pose_quality: {...pose(5).pose_quality,
    pin_regions: Object.fromEntries(Array.from({length: 40}, (_, index) =>
      [`P${index + 1}`, {supported: index < 12}]))}}).issue, 'poseUnverified');
  assert.equal(inspect({...pose(5), pose_quality: {...pose(5).pose_quality,
    pin_alignment_offset_px: [Number.NaN, 0]}}).issue, 'poseUnverified');
  // An unsynchronized raw detector rejection does not veto a valid video pose.
  assert.equal(inspect(pose(5), {distance: {...distance, boundaryUnverified: true}}).kind, 'supported');
});

test('low source pitch limits the post-tuning GPIO claim, not image tuning', () => {
  const source = readFileSync(new URL('../src/components/CameraAutoTune.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /preflightPiTuning/);
  assert.match(source, /requestCameraTuning\(action === "cancel"[\s\S]*?"raspberry-pi-5"/);
  assert.equal(postTuneAlignmentIssue({distance: {...distance, state: 'moveCloser', pitchPx: 14}, synchronized: true}), 'moveCloser');
  assert.equal(postTuneAlignmentIssue({distance, synchronized: false}), 'realtimeRequired');
  assert.equal(postTuneAlignmentIssue({distance, synchronized: true}), null);
  assert.equal(postTuneAlignmentIssue({distance: {...distance, state: 'moveCloser', sampleFresh: false, pitchPx: 14}, synchronized: true}), 'moveCloser');
});

test('one lucky lock, duplicate frame, pose loss or camera context change cannot complete calibration', () => {
  let run = emptyAlignmentRun();
  for (const [index, ts] of [[1, 1000], [2, 1200], [3, 1400], [4, 1600]]) {
    const evidence = inspect(pose(index, ts));
    const next = advanceAlignment(run, evidence);
    run = next.run;
    assert.equal(next.ready, index === 4);
    const duplicate = advanceAlignment(run, evidence);
    assert.equal(duplicate.ready, false);
    assert.deepEqual(duplicate.run, run);
  }
  const lost = advanceAlignment(run, {kind: 'issue', issue: 'boundary'});
  assert.equal(lost.ready, false);
  assert.equal(lost.run.count, 0);
  const changed = advanceAlignment(run, {...inspect(pose(5, 1800)), context: 'raspberry-pi-5:3:1280x720'});
  assert.equal(changed.run.count, 1);
  assert.equal(changed.ready, false);
  const scaleJump = advanceAlignment(run, {...inspect(pose(5, 1800)), pitchPx: 12});
  assert.equal(scaleJump.run.count, 1);
});
