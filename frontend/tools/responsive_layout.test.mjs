import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import postcss from 'postcss';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../src/responsive.css'));
function rule(selector, property, value, media) {
  let found = false;
  css.walkRules(r => {
    if (!r.selector.includes(selector)) return;
    if (media && !(r.parent.type === 'atrule' && r.parent.params === media)) return;
    r.walkDecls(property, d => { if (d.value === value) found = true; });
  });
  assert.ok(found, `${selector}: ${property}=${value} ${media ?? ''}`);
}

test('shared responsive rules load last without replacing any workflow state or camera tree', () => {
  const main = read('../src/main.tsx');
  assert.ok(main.indexOf('"./responsive.css"') > main.indexOf('"./debug.css"'));
  const app = read('../src/App.tsx');
  assert.match(app, /\["design", "blueprint", "guide", "debug", "deploy"\]/);
  assert.match(app, /<VideoView/);
  assert.doesNotMatch(css.toString(), /(?:body|html)\s*\{[^}]*overflow(?:-x)?:\s*hidden/);
});

test('all five navigation buttons remain visible and wrap into three columns on phones', () => {
  rule('.maker-nav', 'grid-template-columns', 'repeat(5, minmax(0, 1fr))', '(max-width: 1500px)');
  rule('.maker-nav', 'grid-template-columns', 'repeat(3, minmax(0, 1fr))', '(max-width: 600px)');
  rule('.maker-nav button', 'white-space', 'normal');
  rule('.maker-layout:not(.display-mode-active) :is(button', 'min-height', '44px');
});

test('desktop panes follow available height and short or narrow windows use document scrolling', () => {
  rule('.maker-studio.maker-resizable', 'grid-template-rows', 'minmax(0, 1fr)', '(min-width: 961px) and (min-height: 601px)');
  rule('.maker-preview, .maker-splitter)', 'height', '100%', '(min-width: 961px) and (min-height: 601px)');
  rule('body:has(.maker-layout:not(.display-mode-active))', 'overflow', 'auto', '(max-width: 960px), (max-height: 600px)');
  rule('.maker-layout .maker-studio.maker-resizable', 'grid-template-columns', 'minmax(0, 1fr)', '(max-width: 960px)');
  rule('.maker-design-container, .maker-deploy-main, .debug-page)', 'overflow', 'visible', '(max-width: 960px), (max-height: 600px)');
  rule('.compact-guide > .guide-panel-body', 'max-height', 'none');
});

test('guide toggle and video occupy separate rows without altering overlay coordinates', () => {
  rule('.video-guide-stage > .guide-visibility-toggle', 'position', 'static');
  rule('.video-guide-stage > .guide-visibility-toggle', 'transform', 'none');
  rule('> .video-shell', 'grid-row', '2', '(min-width: 961px)');
  rule('> .compact-guide', 'grid-row', '1 / 3', '(min-width: 961px)');
  rule('.mirror-controls .realtime-toggle', 'white-space', 'normal', '(max-width: 600px)');
  rule('.pin-calibration-toggle', 'width', '88px', '(max-width: 600px)');
  assert.doesNotMatch(css.toString(), /\.video-img|\.overlay-svg|computeLetterbox/);
});

test('menus and dialogs stay bounded and code or pin diagrams scroll locally', () => {
  rule('.maker-model-popover, .pi-execution-popover', 'width', 'min(420px, 100%)', '(max-width: 960px)');
  rule('.maker-model-popover, .pi-execution-popover', 'left', '0');
  rule('.maker-diagram-dialog, .maker-product)', 'max-height', 'calc(100dvh - 24px)');
  rule('.pi-deploy-panel pre', 'overflow', 'auto');
  rule('.pi-row-count', 'overflow-x', 'auto');
  rule('.calibrate-panel-card', 'overflow', 'auto');
});

test('telemetry slot widths are owned by base styles; user controls wrap on small screens', () => {
  assert.doesNotMatch(css.toString(), /\.status-metrics\s*\{/);
  rule('.status-actions', 'flex-wrap', 'wrap', '(max-width: 960px)');
  rule('.debug-status-grid', 'grid-template-columns', 'repeat(2, minmax(0, 1fr))', '(max-width: 600px)');
  rule('.debug-status-grid', 'grid-template-columns', 'minmax(0, 1fr)', '(max-width: 380px)');
});
