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
  assert.match(app, /\["design", "guide", "deploy"\]/);
  assert.match(app, /<VideoView/);
  assert.doesNotMatch(css.toString(), /(?:body|html)\s*\{[^}]*overflow(?:-x)?:\s*hidden/);
});

test('all four navigation buttons remain visible and wrap into two columns on phones', () => {
  rule('.maker-nav', 'grid-template-columns', 'repeat(3, minmax(0, 1fr))', '(max-width: 1500px)');
  rule('.maker-nav', 'grid-template-columns', 'repeat(2, minmax(0, 1fr))', '(max-width: 600px)');
  rule('.maker-nav button', 'white-space', 'normal');
  rule('.maker-layout:not(.display-mode-active) :is(button', 'min-height', '44px');
});

test('desktop panes follow available height and short or narrow windows use document scrolling', () => {
  rule('.maker-studio.maker-resizable', 'grid-template-rows', 'minmax(0, 1fr)', '(min-width: 961px) and (min-height: 601px)');
  assert.match(read('../src/maker.css'), /\.maker-design-stage \{[^}]*display: flex/);
  rule('.maker-design-stage > .maker-studio', 'flex', 'none', '(max-width: 960px), (max-height: 600px)');
  rule('.maker-preview, .maker-splitter)', 'height', '100%', '(min-width: 961px) and (min-height: 601px)');
  rule('body:has(.maker-layout:not(.display-mode-active))', 'overflow', 'auto', '(max-width: 960px), (max-height: 600px)');
  rule('.maker-layout .maker-studio.maker-resizable', 'grid-template-columns', 'minmax(0, 1fr)', '(max-width: 960px)');
  rule('.maker-design-stage, .maker-deploy-main, .debug-page)', 'overflow', 'visible', '(max-width: 960px), (max-height: 600px)');
  rule('.compact-guide > .guide-panel-body', 'max-height', 'none');
});

test('guide toggle and camera controls share a row above the measured video', () => {
  rule('.video-guide-stage > .guide-visibility-toggle', 'position', 'static');
  rule('.video-guide-stage > .guide-visibility-toggle', 'transform', 'none');
  rule('.video-guide-stage > .video-workspace', 'display', 'contents', '(min-width: 961px)');
  rule('.video-workspace > .video-control-toolbar', 'grid-row', '1', '(min-width: 961px)');
  rule('.video-workspace > .video-control-toolbar', 'justify-self', 'end', '(min-width: 961px)');
  rule('.video-workspace > :is(.video-shell, .maker-2d-main)', 'grid-row', '2', '(min-width: 961px)');
  rule('> .compact-guide', 'grid-row', '1 / 3', '(min-width: 961px)');
  rule('.mirror-controls .realtime-toggle', 'white-space', 'normal', '(max-width: 600px)');
  rule('.video-control-toolbar', 'justify-content', 'flex-start', '(max-width: 600px)');
  const view = read('../src/components/VideoView.tsx');
  const styles = read('../src/styles.css');
  assert.ok(view.indexOf('className="video-control-toolbar"') < view.indexOf('className={`video-shell'), 'controls precede the image/overlay container');
  assert.match(view, /ref=\{containerRef\}[\s\S]*className=\{`video-shell/);
  assert.match(styles, /\.video-control-toolbar \{[^}]*flex-wrap: wrap/);
  assert.doesNotMatch(styles, /\.mirror-controls \{[^}]*position: absolute/);
  assert.doesNotMatch(read('../src/maker.css'), /\.maker-2d \.video-workspace \{ display: none; \}/);
  assert.match(read('../src/maker.css'), /\.video-workspace > \.video-shell\[hidden\] \{ display: none; \}/);
  assert.doesNotMatch(css.toString(), /\.video-img|\.overlay-svg|computeLetterbox/);
});

test('desktop wiring panes resize through a separate grid track while narrow layouts stay stacked', () => {
  const desktop='(min-width: 961px) and (min-height: 601px)';
  rule('.video-guide-stage.guide-resizable', 'grid-template-columns', 'minmax(0, 1fr) 18px var(--guide-column-width)', desktop);
  rule('.video-guide-stage.guide-resizable > .compact-guide', 'grid-column', '3', desktop);
  rule('.video-guide-stage.guide-resizable > .guide-resize-handle', 'grid-column', '2', desktop);
  rule('.guide-resize-handle', 'display', 'none');
  const app=read('../src/App.tsx');
  assert.match(app, /<GuidePaneLayout[\s\S]*<VideoView[\s\S]*<ProjectGuidePanel/);
});

test('debug camera and chat share toolbar/content tracks without fixed header offsets', () => {
  const desktop='(min-width: 961px) and (min-height: 601px)';
  rule('.main:has(> .debug-chat-page)', 'grid-template-rows', 'auto auto minmax(0, 1fr)', desktop);
  rule(':is(.video-guide-stage, .debug-chat-page)', 'grid-template-rows', 'subgrid', desktop);
  rule(':is(.video-guide-stage, .debug-chat-page)', 'grid-row', '2 / 4', desktop);
  rule('.debug-chat-page > .debug-chat-heading', 'grid-row', '1', desktop);
  rule('.debug-chat-page > .debug-page-content', 'grid-row', '2', desktop);
  rule('.debug-chat-page > .debug-page-content', 'overflow', 'auto', desktop);
  rule('.debug-chat-page .ai-debug-chat', 'max-height', 'none', desktop);
  rule('.maker-layout.maker-stage-debug:not(.display-mode-active) .debug-chat-page', 'padding', '0', desktop);
});

test('debug tools occupy their own view instead of stacking beneath the composer', () => {
  const desktop='(min-width: 961px) and (min-height: 601px)';
  rule('.debug-chat-page .ai-debug-conversation', 'flex', '1 1 0', desktop);
  rule('.debug-chat-page .debug-tool-view', 'overflow', 'auto', desktop);
  rule(':is(.debug-chat-view,.debug-tool-view,.ai-debug-conversation)[hidden]', 'display', 'none', desktop);
  assert.match(read('../src/debug.css'), /\.debug-page :is\(\.debug-chat-view,\.debug-tool-view,\.ai-debug-conversation\)\[hidden\] \{ display:none; \}/);
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
