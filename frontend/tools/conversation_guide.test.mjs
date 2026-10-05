// Real guide transitions with fake presentation/test inputs. No AI, Pi or camera.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import { maker, designFor, componentTests } from './project_guide_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
function load(path, imports) {
  const code = ts.transpileModule(read(path), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  new Function('require', 'exports', code)(name => {
    if (name.endsWith('.css')) return {};
    assert.ok(name in imports, `Unmocked ${name}`); return imports[name];
  }, exports);
  return exports;
}
function nodes(tree, testNode) {
  const found = [];
  function visit(node) {
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (!node || typeof node !== 'object') return;
    if (testNode(node)) found.push(node);
    Object.values(node.props ?? {}).flat(Infinity).forEach(visit);
  }
  visit(tree); return found;
}
const hooks = { ...React, useId: () => 'fixture', useEffect() {}, useMemo: fn => fn(), useRef: value => ({ current: value }), useState: value => [typeof value === 'function' ? value() : value, () => {}] };
const tr = (zh, en) => en;
const common = { react: hooks, 'react/jsx-runtime': jsx, '../lib/maker': maker, '../lib/useMaker': { useMakerText: () => tr }, '../lib/i18n': { useI18n: () => ({ t: key => key, tx: value => typeof value === 'string' ? value : value.en }) } };

function workspace(toolbar = true, visible = true) {
  const calls = [], effects = [];
  const { WiringWorkspace } = load('../src/components/WiringWorkspace.tsx', { ...common,
    react: { ...hooks, useEffect: fn => effects.push(fn) },
    'react-dom': { createPortal: (child, host) => { calls.push(host); return React.createElement('portal', {}, child); } },
    '../lib/componentHeaderGuide': { componentModelName: () => 'HC-SR04+' },
  });
  const tree = WiringWorkspace({ design: designFor(), guide: maker.emptyGuide(), visible, guideOnly: true, toolbar,
    panelId: 'maker-floating-guide', assistantOpen: false, onAssistantOpenChange: () => calls.push('open-ai'), onClose() {},
    onReveal: () => calls.push('show-guide'), children: React.createElement('owned-guide', {}),
  });
  return { tree, calls, effects };
}
test('left toolbar owns one guide without a chat portal or implicit AI action', () => {
  const f = workspace();
  f.effects.forEach(fn => fn());
  assert.deepEqual(f.calls, []);
  assert.equal(nodes(f.tree, n => n.type === 'owned-guide').length, 1);
  assert.equal(f.tree.props.className, 'wiring-task-toolbar');
  assert.equal(nodes(f.tree, n => n.props?.className === 'wiring-task-reveal')[0].props.hidden, true);
});
test('collapsed/phone work view can reveal the same guide without starting it', () => {
  const f = workspace(true, false);
  const launcher = nodes(f.tree, n => n.props?.className === 'wiring-task-reveal')[0];
  assert.equal(launcher.props.hidden, false);
  nodes(launcher, n => n.type === 'button')[0].props.onClick();
  assert.deepEqual(f.calls, ['show-guide']);
  assert.equal(nodes(f.tree, n => n.props?.id === 'maker-floating-guide')[0].props.hidden, true);
});
test('collapsed toolbar retains the guide and test owner', () => {
  const f = workspace(true, false);
  f.effects.forEach(fn => fn());
  assert.deepEqual(f.calls, []); assert.equal(nodes(f.tree, n => n.type === 'owned-guide').length, 1);
});
test('legacy guide stays unchanged when toolbar presentation is disabled', () => {
  const f = workspace(false);
  assert.equal(f.calls.length, 0);
  assert.equal(f.tree.type, 'section'); assert.equal(f.tree.props.className, 'wiring-workspace');
  assert.equal(nodes(f.tree, n => n.type === 'owned-guide').length, 1);
});

function guideFixture() {
  const design = designFor(['hc-sr04', 'mrd-tf240-8p-cs']), calls = [];
  let session = maker.emptyGuide();
  const tests = { status: { connected: true, active: null, results: [], test_busy: false }, pending: false,
    start: () => calls.push('test'), invalidate: () => calls.push('invalidate') };
  const { ProjectGuidePanel } = load('../src/components/ProjectGuidePanel.tsx', { ...common,
    './ConversationGuideDock': { useConversationGuideDock: () => ({ target: { element: {} } }) },
    '../lib/componentTests': componentTests, '../lib/useComponentTests': { useComponentTests: () => tests },
    '../lib/componentWiringGuides': { guideFor: () => ({ name: { en: 'Module' }, safety: { en: 'Manual confirmation only' }, unresolved: [] }) },
    '../lib/componentHeaderGuide': { componentHeaderGuideText: () => null, componentModelName: id => id },
    '../lib/piHeaderGuide': { piHeaderGuideText: () => null }, './CompactGuide': { CompactGuide: 'compact' },
    './ComponentTestCard': { ComponentTestCard: 'test-card' }, './ComponentRowLocator': { ComponentRowLocator: 'locator' },
  });
  const render = () => ProjectGuidePanel({ design, session, visible: true, embedded: true, floating: true, toolbar: true, disabled: false,
    pinsById: new Map(), onChange: next => { session = next; }, onTargetChange() {}, onVisibleChange() {}, onDeploy: () => calls.push('deploy') });
  return { render, calls, tests, design, session: () => session, setSession: next => { session = next; } };
}
test('start and every Next use the original guide cursor and never start a test or AI', () => {
  const f = guideFixture();
  nodes(f.render().props.actions, n => n.type === 'button' && String(n.props.children).includes('Start wiring'))[0].props.onClick();
  for (let index = 0; index < 4; index++) {
    assert.equal(f.session().index, index); assert.equal(f.session().phase, 'active');
    const next = nodes(f.render().props.actions, n => n.type === 'button' && JSON.stringify(n.props.children).includes('Next'))[0];
    next.props.onClick();
  }
  assert.equal(f.session().phase, 'review'); assert.equal(Object.keys(f.session().confirmed).length, 4);
  assert.deepEqual(f.calls, []);
});
test('tests appear only after confirmations; test controls stay outside the scrolling body', () => {
  const f = guideFixture();
  assert.equal(nodes(f.render(), n => n.type === 'test-card').length, 0);
  f.setSession({ ...maker.emptyGuide(), phase: 'review', confirmed: Object.fromEntries(f.design.wiring.filter(w => w.componentId === 'hc-sr04').map(w => [w.id, { signature: maker.wireSignature(w) }])) });
  const tree = f.render();
  const controls = nodes(tree.props.actions, n => n.type === 'test-card');
  assert.equal(controls.length, 1); assert.equal(controls[0].props.view, 'actions');
  assert.equal(controls[0].props.inlineActions, true);
  assert.equal(nodes(tree.props.children, n => n.type === 'test-card')[0].props.view, 'instructions');
  assert.equal(controls[0].props.tests, f.tests); assert.deepEqual(f.calls, []);
});
test('running test retains Stop controls even while the guide is in preparation', () => {
  const f = guideFixture(); f.tests.status.active = { id: 'run-1', reserved: true };
  assert.equal(nodes(f.render().props.actions, n => n.type === 'test-card').length, 1);
  assert.equal(nodes(f.render().props.actions, n => n.type === 'button' && String(n.props.children).includes('Start wiring')).length, 0);
  assert.equal(nodes(f.render().props.children, n => n.props?.className === 'guide-prepare-message').length, 0);
  assert.deepEqual(f.calls, []);
});
test('back, module switching and the original guide target remain bound to the same session', () => {
  const f = guideFixture(); f.setSession({ ...maker.startProjectGuide(maker.emptyGuide()), index: 2 });
  let tree = f.render();
  nodes(tree.props.actions, n => n.type === 'button' && n.props.children === 'Back')[0].props.onClick();
  assert.equal(f.session().index, 1);
  tree = f.render();
  const tabs = nodes(tree.props.progress, n => n.type === 'button'); tabs[1].props.onClick();
  assert.equal(f.session().componentIndex, 1);
  tree = f.render();
  if (f.session().phase === 'prepare') nodes(tree.props.actions, n => n.type === 'button' && String(n.props.children).includes('Start wiring'))[0].props.onClick();
  assert.match(f.render().props.targetId, /^mrd-tf240-8p-cs:/); assert.deepEqual(f.calls, []);
});
test('chat keeps one composer, no guide history actions and no new camera/test polling owner', () => {
  const source = read('../src/components/UnifiedAssistant.tsx'), dock = read('../src/components/ConversationGuideDock.tsx');
  assert.equal((source.match(/<ConversationGuideHost/g) ?? []).length, 1);
  assert.equal((source.match(/<form /g) ?? []).length, 1);
  assert.doesNotMatch(dock, /fetch\(|setInterval\(|makerRequest|confirmProjectWire|useComponentTests|localStorage/);
  assert.match(source, /enabled=\{!controller.demoOpen && state.stage === "guide" && Boolean\(state.design\)\}/);
});
test('bottom guide exposes module switching and restart without a More menu or hidden test controls', () => {
  const { CompactGuide } = load('../src/components/CompactGuide.tsx', common);
  const tree = CompactGuide({ contextKey: 'same-run', phase: 'review', visible: true, title: 'HC-SR04+', toolbar: true,
    progress: React.createElement('module-switch'), headerActions: React.createElement('restart'),
    children: React.createElement('test-result'), actions: React.createElement('test-controls'), details: React.createElement('records'), onClose() {} });
  const heading = nodes(tree, n => n.props?.className === 'guide-toolbar-heading')[0];
  assert.equal(nodes(heading, n => n.type === 'module-switch').length, 1);
  assert.equal(nodes(heading, n => n.type === 'restart').length, 1);
  assert.equal(nodes(tree, n => n.props?.className === 'guide-toolbar-more' || n.props?.className === 'guide-toolbar-details').length, 0);
  assert.equal(nodes(tree, n => n.type === 'records').length, 0);
  assert.equal(nodes(heading, n => n.type === 'test-controls').length, 0);
  assert.equal(nodes(tree, n => n.type === 'test-controls').length, 1);
});

test('bottom guide follows the one stable image owner in DOM and layout order', () => {
  const app = read('../src/App.tsx'), css = read('../src/components/WiringTaskToolbar.css');
  assert.ok(app.indexOf('<VideoView') < app.indexOf('<WiringWorkspace guideOnly'), 'reading and keyboard order follow the image');
  assert.equal((app.match(/<VideoView\b/g) ?? []).length, 1);
  assert.equal((app.match(/<ProjectGuidePanel\b/g) ?? []).length, 1);
  assert.match(css, /has-task-toolbar > \.video-workspace\s*\{\s*order: 0; flex: 1 1 0;/);
  assert.match(css, /has-task-toolbar > \.wiring-task-toolbar\s*\{\s*order: 1;/);
  assert.doesNotMatch(css, /\.guide-toolbar-more|\.guide-toolbar-details/);
});
