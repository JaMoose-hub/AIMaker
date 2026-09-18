import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, ScriptTarget, JsxEmit } from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const source = readFileSync(new URL('../src/components/StatusBar.tsx', import.meta.url), 'utf8');
let snapshot;
const js = transpileModule(source.replace(/^import .*?;\r?\n/gm, ''), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022, jsx: JsxEmit.React },
}).outputText;
const exports = {};
new Function('exports', 'React', 'useState', 'useI18n', 'useDetections', 'pinDisplayNameWithNumber', 'CameraAutoTune', js)(
  exports, React, () => [false, () => {}], () => ({ t: key => key }), () => snapshot, () => '', () => null,
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
  assert.match(markup[2], /100%/);
  assert.ok(markup.every(html => html.includes('status-metrics') && html.includes('status-actions')));
});
