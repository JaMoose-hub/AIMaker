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
