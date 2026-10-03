import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {maker, designFor} from './project_guide_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source, {compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
}}).outputText;
const app = ts.createSourceFile('App.tsx', read('../src/App.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function variable(name) {
  let found;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(app) === name) found = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(app); assert.ok(found, name); return found;
}

test('floating layout is derived from the existing workspace, never display-only or standalone mode', () => {
  const enabled = new Function('makerEnabled', 'maker', 'displayModeActive', 'project', 'emptyProjectGuide',
    `return ${variable('floatingGuide').getText(app)};`);
  assert.equal(enabled(true, {}, false, {}, false), true);
  assert.equal(enabled(true, {}, false, null, true), true);
  for (const args of [[false, {}, false, {}, false], [true, {standalone:true}, false, {}, false],
    [true, {}, true, {}, false], [true, {}, false, null, false]]) assert.equal(enabled(...args), false);
});

test('the shared floating toggle exposes its controlled panel and changes visibility only', () => {
  const factory = new Function('React', 'guideToggleRef', 'guideVisible', 'floatingGuide', 'config', 'profile',
    'handleGuideVisibilityChange', 'project', 'emptyProjectGuide', 'tr', 't',
    `${compile(`const control = ${variable('guideVisibilityControl').getText(app)};`)};return control;`);
  for (const visible of [false, true]) {
    const calls = [];
    const button = factory(React, {current:null}, visible, true, {}, {}, next => calls.push(next), {}, false, zh => zh, key => key);
    assert.equal(button.props['aria-expanded'], visible);
    assert.equal(button.props['aria-controls'], 'maker-floating-guide');
    assert.equal(button.props.disabled, false);
    assert.match(renderToStaticMarkup(button), visible ? /收合接線引導/ : /展開接線引導/);
    button.props.onClick(); assert.deepEqual(calls, [!visible]);
  }
  const disabled = factory(React, {}, false, true, null, {}, () => {}, {}, false, zh => zh, key => key);
  assert.equal(disabled.props.disabled, true);
});

test('closing returns focus from the guide without stealing focus from the camera or chat', () => {
  const handler = variable('handleGuideVisibilityChange').arguments[0].getText(app);
  const factory = new Function('document', 'guideToggleRef', 'setGuideVisible', 'window', 'GUIDE_VISIBILITY_STORAGE_KEY',
    `${compile(`const change = ${handler};`)};return change;`);
  for (const inside of [true, false]) for (const visible of [true, false]) {
    const calls = [], stored = [], focused = [];
    const document = {activeElement:{}, getElementById:id => {
      assert.equal(id, 'maker-floating-guide'); return {contains:() => inside};
    }};
    factory(document, {current:{focus:options => focused.push(options)}}, v => calls.push(v),
      {localStorage:{setItem:(...args) => stored.push(args)}}, 'guide-visible')(visible);
    assert.deepEqual(calls, [visible]); assert.deepEqual(stored, [['guide-visible', String(visible)]]);
    assert.deepEqual(focused, inside && !visible ? [{preventScroll:true}] : []);
  }
});

test('the hidden guide retains children and a stable accessible panel id', () => {
  const exports = {};
  new Function('require', 'exports', 'React', compile(read('../src/components/WiringWorkspace.tsx')))(name => ({
    react:React, '../lib/maker':maker, '../lib/componentHeaderGuide':{componentModelName:() => 'HC-SR04+'},
    '../lib/i18n':{useI18n:() => ({t:key => key})}, '../lib/useMaker':{useMakerText:() => zh => zh},
  })[name], exports, React);
  for (const visible of [true, false]) {
    const html = renderToStaticMarkup(React.createElement(exports.WiringWorkspace, {
      design:designFor(), guide:maker.emptyGuide(), visible, guideOnly:true, panelId:'maker-floating-guide',
      assistantOpen:false, onAssistantOpenChange() {}, onClose() {}, assistant:null,
    }, React.createElement('span', null, 'retained guide state')));
    assert.match(html, /id="maker-floating-guide"/); assert.match(html, /retained guide state/);
    assert.equal(/^<section[^>]* hidden=""/.test(html), !visible);
  }
});

test('floating panels are translucent absolute overlays; the camera and guide are not conditionally mounted', () => {
  const css = read('../src/floatingGuide.css'), source = read('../src/App.tsx');
  assert.match(css, /\.floating-guide-dock\s*\{[^}]*position: absolute; left: 14px; bottom: 14px/s);
  assert.match(css, /> :is\(\.wiring-workspace,\.maker-guide-empty\)\s*\{[^}]*position: absolute;[^}]*background: color-mix[^}]*backdrop-filter: blur/s);
  assert.match(source, /resizable=\{[^}]*!floatingGuide\}/);
  assert.equal((source.match(/<VideoView\b/g) ?? []).length, 1);
  assert.match(source, /panelId=\{floatingGuide \? 'maker-floating-guide' : undefined\}/);
  assert.doesNotMatch(source, /guideVisible\s*&&\s*<WiringWorkspace/);
});

function viewportHarness() {
  const exports = {}, layout = [], state = [], refs = [];
  let observed, disconnected = false;
  const element = {clientWidth:1183, clientHeight:629, clientTop:0, offsetHeight:629,
    getBoundingClientRect:() => ({height:628.8125})};
  const hooks = {
    useState(initial) {const i = state.length; state.push(initial); return [initial, update => state[i] = typeof update === 'function' ? update(state[i]) : update];},
    useRef(initial) {const ref = {current:refs.length ? initial : element}; refs.push(ref); return ref;},
    useLayoutEffect:fn => layout.push(fn), useEffect() {},
  };
  class Observer {
    constructor(callback) {this.callback = callback; observed = this;}
    observe(target) {assert.equal(target, element);}
    disconnect() {disconnected = true;}
  }
  const zoom = {fitCircuitScale:() => .5, readableCircuitScale:fit => fit};
  new Function('require', 'exports', 'React', 'ResizeObserver', compile(read('../src/components/CircuitViewport.tsx')))(name => ({
    react:hooks, '../lib/circuitZoom':zoom, '../lib/useMaker':{useMakerText:() => zh => zh},
  })[name], exports, React, Observer);
  const tree = exports.CircuitViewport({width:840, height:518, children:null});
  return {tree, element, state, layout, observer:() => observed, disconnected:() => disconnected};
}

test('diagram measurement keeps fractional height before paint and ignores horizontal scrollbar feedback', () => {
  const h = viewportHarness(), cleanup = h.layout[0]();
  assert.deepEqual(h.state[0], {width:1183, height:628.8125});
  const before = h.state[0];
  h.element.clientHeight = 614; h.observer().callback();
  assert.equal(h.state[0], before, 'horizontal scrollbar must not recalculate the fit baseline');
  cleanup(); assert.equal(h.disconnected(), true);
});

test('diagram stages use percentage minimums rather than rounded viewport pixels that trigger scrollbars', () => {
  const h = viewportHarness();
  const viewport = h.tree.props.children[1], stage = viewport.props.children;
  assert.deepEqual(stage.props.style, {width:420, height:259, minWidth:'100%', minHeight:'100%'});
  const css = read('../src/guideAi.css');
  assert.match(css, /#current-step-diagram \.circuit-zoom-fill > \.circuit-viewport\s*\{[^}]*scrollbar-gutter: stable both-edges/s);
});
