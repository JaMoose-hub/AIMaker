// Exercise the real App render tree and navigation handlers, not a copied layout.
// Child components and external hooks are inert; no Pi, camera or AI calls occur.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import ts from 'typescript';
import {maker, designFor, board} from './project_guide_fixture.mjs';

const code = ts.transpileModule(readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React},
}).outputText;
const fail = () => assert.fail('Rendering or navigation must not start hardware/cloud work');
function nodes(tree, predicate) {
  const found = [];
  function visit(node) {
    if (!React.isValidElement(node)) return;
    if (predicate(node)) found.push(node);
    for (const slot of ['children', 'navigation', 'left']) React.Children.forEach(node.props[slot], visit);
  }
  visit(tree);
  return found;
}
function harness({state = maker.initialMaker(), locale = 'en', boardId = 'raspberry-pi-5', displayMode = 'standard'} = {}) {
  const values = [], debugCalls = [];
  let cursor = 0, current = state;
  // These are App's local state slots; the external hooks below have no effects.
  const initial = {0: {board_id: boardId, camera_source: 'device', runtime_revision: 1}, 1: board, 14: displayMode};
  const react = {...React, useEffect() {}, useCallback: fn => fn, useMemo: fn => fn(),
    useRef: value => ({current: value}), useSyncExternalStore: (_subscribe, snapshot) => snapshot(),
    useState(value) {
      const i = cursor++;
      if (!(i in values)) values[i] = i in initial ? initial[i] : typeof value === 'function' ? value() : value;
      return [values[i], next => { values[i] = typeof next === 'function' ? next(values[i]) : next; }];
    },
  };
  const setState = next => {current = typeof next === 'function' ? next(current) : next;};
  const imports = {
    react,
    './lib/useMaker': {useMaker: () => ({state: current, setState, saved: true}), useMakerText: () => (zh, en) => locale === 'en' ? en : zh},
    './lib/useMakerAI': {useMakerAI: () => ({newProject: async () => {setState(maker.newMakerProject); return true;}})},
    './lib/maker': maker,
    './lib/i18n': {useI18n: () => ({t: key => key, tx: v => typeof v === 'string' ? v : v[locale], setLocale: fail, applyDefaultLocale: fail})},
    './lib/displayMode': {isDisplayOnlyMode: mode => mode !== 'standard', isOpticalHudMode: mode => mode === 'optical-hud-demo'},
    './lib/useGlassesStream': {useGlassesStream: () => ({status: null, pending: false, stop: fail})},
    './lib/debugSessions': {useDebugSession: (id, enabled) => {debugCalls.push({id, enabled}); return {record: null, resetVersion: 0};}},
    './lib/wsClient': {wsClient: {subscribe: fail, getSnapshot: () => ({runtime: null})}},
  };
  const require = name => {
    if (name in imports) return imports[name];
    if (name.startsWith('./components/')) return new Proxy({}, {get: (_target, key) => key});
    if (name.endsWith('.css')) return {};
    return new Proxy({}, {get: () => fail});
  };
  const module = {};
  new Function('React', 'require', 'exports', code)(React, require, module);
  const render = () => {cursor = 0; return module.default();};
  const find = (tree, type) => nodes(tree, n => n.type === type);
  const navigate = stage => {
    const nav = nodes(render(), n => n.type === 'nav')[0];
    React.Children.toArray(nav.props.children).find(n => n.key === `.$${stage}`).props.onClick();
    return render();
  };
  return {render, find, navigate, state: () => current, debugCalls};
}

for (const locale of ['en', 'zh-TW']) test(`New project → 02 uses the empty guide, never 03 or legacy tools (${locale})`, async () => {
  const design = designFor();
  const h = harness({locale, state: {...maker.initialMaker(), design, code: 'previous code', debug: {panelOpen: true, caseId: 'old'}}});
  const assistant = h.find(h.render(), 'MakerAssistant')[0];
  assert.equal(await assistant.props.onNewProject(), true);
  assert.equal(h.state().design, null);
  const tree = h.navigate('guide');
  assert.match(tree.props.className, /maker-wiring-full-width/);
  for (const component of ['PiDeployPanel', 'WiringGuidePanel', 'DebugPage', 'aside']) assert.equal(h.find(tree, component).length, 0, component);
  assert.equal(h.find(tree, 'VideoView').length, 1);
  assert.equal(h.find(tree, 'GuidePaneLayout')[0].props.resizable, true);
  assert.equal(h.debugCalls.at(-1).enabled, false);
  const empty = nodes(tree, n => n.props.className?.includes('maker-guide-empty'))[0];
  assert.equal(empty.props.hidden, false);
  assert.equal(h.find(empty, 'h2')[0].props.children, locale === 'en' ? 'No confirmed project yet' : '尚未確認作品');
  const before = h.state();
  h.find(empty, 'button')[0].props.onClick();
  assert.equal(h.state().stage, 'design');
  for (const field of ['design', 'candidate', 'code', 'guide', 'conversation']) assert.equal(h.state()[field], before[field]);
  assert.equal(h.find(h.render(), 'PiDeployPanel').length, 0);
  assert.equal(h.find(h.render(), 'MakerAssistant').length, 1);
});

test('02 after restoring an empty project or with an unconfirmed preview cannot show deployment or legacy wiring', () => {
  for (const state of [maker.restoreMaker(JSON.stringify({...maker.initialMaker(), stage: 'guide'})),
    {...maker.initialMaker(), stage: 'guide', candidate: designFor()}]) {
    const h = harness({state});
    const tree = h.navigate('guide');
    assert.match(tree.props.className, /maker-wiring-full-width/);
    assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 1);
    assert.equal(h.find(tree, 'PiDeployPanel').length, 0);
    assert.equal(h.find(tree, 'WiringGuidePanel').length, 0);
    for (const field of ['design', 'candidate', 'code', 'guide']) assert.equal(h.state()[field], state[field]);
  }
});

test('03 is the only Maker stage that renders one deployment panel, with or without a project', () => {
  for (const design of [null, designFor()]) {
    const h = harness({state: {...maker.initialMaker(), design, code: 'manual draft'}});
    for (const stage of ['design', 'guide', 'deploy', 'guide', 'design']) {
      const tree = h.navigate(stage), panels = h.find(tree, 'PiDeployPanel');
      assert.equal(panels.length, stage === 'deploy' ? 1 : 0, stage);
      if (panels.length) {
        assert.equal(panels[0].props.project, design ?? undefined);
        assert.equal(panels[0].props.draft, design ? 'manual draft' : undefined);
      }
    }
  }
});

test('confirmed-project wiring, AI and guide state remain bound to the original project', () => {
  const design = designFor(), guide = {...maker.emptyGuide(), index: 2};
  const h = harness({state: {...maker.initialMaker(), design, guide, debug: {panelOpen: true}}});
  const tree = h.navigate('guide');
  const workspace = h.find(tree, 'WiringWorkspace')[0];
  assert.equal(workspace.props.design, design);
  assert.equal(workspace.props.guide, guide);
  assert.equal(workspace.props.assistant.type, 'DebugPage');
  assert.equal(h.find(tree, 'ProjectGuidePanel')[0].props.session, guide);
  assert.equal(h.debugCalls.at(-1).enabled, true);
  assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 0);
});

test('non-Maker controllers, standalone wiring and HUD keep their board guide without a deployment panel', () => {
  for (const options of [{boardId: 'arduino-uno'}, {state: {...maker.initialMaker(), standalone: true, stage: 'guide'}}, {displayMode: 'optical-hud-demo'}]) {
    const h = harness(options), tree = h.render();
    assert.equal(h.find(tree, 'WiringGuidePanel').length, 1);
    assert.equal(h.find(tree, 'PiDeployPanel').length, 0);
    assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 0);
  }
});
