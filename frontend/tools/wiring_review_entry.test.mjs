import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as ReactDOM from 'react-dom';
import {renderToStaticMarkup} from 'react-dom/server';
import {photoSequence, framingGuide, expectedLocationHelpers, expectedLocationComponent} from './wiring_photo_flow_fixture.mjs';

// Run the production entry policy and component with isolated React lifecycles.
// This suite does not capture photographs, call a model, or operate hardware.
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(path, imports = {}) {
  const exports = {};
  const code = ts.transpileModule(read(path), {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React,
  }}).outputText;
  new Function('React', 'require', 'exports', code)(React, name => {
    if (name.endsWith('.css')) return {};
    if (name in imports) return imports[name];
    throw Error(`Unexpected import: ${name}`);
  }, exports);
  return exports;
}
const helpers = compile('../src/lib/wiringReviewEntry.ts');
const context = {project: {id: 'project', component_ids: ['hc-sr04', 'mrd-tf240-8p-cs'],
  wiring: [{id: 'echo', componentId: 'hc-sr04'}, {id: 'dc', componentId: 'mrd-tf240-8p-cs'}]},
  code: 'fixture', entry: {}, test_keys: {'hc-sr04': 'current-hc', 'mrd-tf240-8p-cs': 'current-tft'}};
const result = (extra = {}) => ({id: 'hc-test', component_id: 'hc-sr04', guide_key: 'current-hc',
  outcome: 'failed', reason: 'no_echo', invalidated: false, ...extra});
const session = (extra = {}) => ({id: 'debug-session', status: 'awaiting_capture', phase: 'awaiting_user',
  binding: {project_id: 'project'}, current_target: true, observations: [], test_results: [result()], ...extra});
const review = (extra = {}) => ({id: 'review-a', revision: 2, round: 1, component_id: 'hc-sr04',
  status: 'collecting', slots: {}, observations: [], results: [], reviews: {}, missing_roles: [],
  no_progress_count: 0, ...extra});

test('a normal conversation has a manual entry without a test recommendation', () => {
  assert.equal(helpers.recommendWiringReview(null, context, true), null);
  assert.equal(helpers.recommendWiringReview(session({test_results: []}), context, true), null);
  assert.equal(helpers.recommendWiringReview(session({test_results: [result({outcome: 'passed'})]}), context, true), null);
  assert.equal(helpers.recommendWiringReview(session({test_results: [result({reason: 'unexpected_error'})]}), context, true), null);
});

test('only relevant failed or inconclusive tests for the current project and wiring recommend checking', () => {
  for (const outcome of ['failed', 'inconclusive']) {
    assert.deepEqual(helpers.recommendWiringReview(session({test_results: [result({outcome})]}), context, true),
      {component_id: 'hc-sr04', source: 'test'});
  }
  const variants = [
    {binding: {project_id: 'other-project'}},
    {current_target: false},
    {camera_current: false},
    {test_results: [result({guide_key: 'old-hc'})]},
    {test_results: [result({invalidated: true})]},
    {test_results: [result({component_id: 'unknown-module'})]},
    {test_results: [result({outcome: 'running'})]},
    {test_results: [result({outcome: 'awaiting_confirmation'})]},
  ];
  for (const changed of variants) assert.equal(helpers.recommendWiringReview(session(changed), context, true), null, JSON.stringify(changed));
  assert.equal(helpers.recommendWiringReview(session(), context, false), null);
  assert.equal(helpers.recommendWiringReview(session(), {...context, project: null}, true), null);
});

test('newer successful evidence replaces a previous failed test recommendation', () => {
  const record = session({test_results: [result(), result({id: 'hc-pass', outcome: 'passed', reason: null})]});
  assert.equal(helpers.recommendWiringReview(record, context, true), null);
  const oldDiagnosis = {...record, diagnosis: {issues: [{reason: 'no_echo', next_action: 'target_then_wiring', component_id: 'hc-sr04'}]}};
  assert.equal(helpers.recommendWiringReview(oldDiagnosis, context, true), null,
    'an earlier no-echo diagnosis cannot overrule a newer passing test of the same wiring');
});

test('software and environment failures take priority over a wiring suggestion', () => {
  for (const reason of ['missing_dependency', 'spi_missing', 'device_permission', 'connection_lost', 'program_error', 'reader_error']) {
    const blocked = session({test_results: [result(), result({id: 'tft-env', component_id: 'mrd-tf240-8p-cs',
      guide_key: 'current-tft', reason})]});
    assert.equal(helpers.recommendWiringReview(blocked, context, true), null, reason);
    assert.equal(helpers.recommendWiringReview(session({diagnosis: {issues: [{reason, next_action: 'prepare_environment'}]}}), context, true), null, reason);
  }
  assert.equal(helpers.recommendWiringReview(session({hardware_blocker: 'environment_unknown'}), context, true), null);
  assert.equal(helpers.recommendWiringReview(session({phase: 'backend_restarted'}), context, true), null);
  assert.equal(helpers.recommendWiringReview(session({test_results: [result({reason: 'movement_not_confirmed'})]}), context, true), null,
    'target movement should be checked before recommending a wiring photo');
});

test('AI suggestions offer only the relevant component and only for the latest explicit inspect-wiring observation', () => {
  const inspect = {id: 'observation', target: 'hc_target', suggested_action: 'inspect_wiring'};
  const record = extra => session({test_results: [], observations: [inspect], ...extra});
  assert.deepEqual(helpers.recommendWiringReview(record(), context, true), {component_id: 'hc-sr04', source: 'ai'});
  assert.deepEqual(helpers.recommendWiringReview(record({observations: [{...inspect, target: 'tft_screen'}]}), context, true),
    {component_id: 'mrd-tf240-8p-cs', source: 'ai'});
  assert.equal(helpers.recommendWiringReview(record({observations: [{...inspect, target: 'overview'}]}), context, true), null);
  assert.deepEqual(helpers.recommendWiringReview(record({observations: [{...inspect, target: 'pi_header'}],
    wiring_target: {component_id: 'hc-sr04', wire_id: 'echo'}}), context, true), {component_id: 'hc-sr04', source: 'ai'});
  assert.equal(helpers.recommendWiringReview(record({observations: [inspect, {...inspect, id: 'newer', suggested_action: 'recapture'}]}), context, true), null);
  assert.equal(helpers.recommendWiringReview(record({binding: {project_id: 'other'}}), context, true), null);
  assert.equal(helpers.recommendWiringReview(record(), context, false), null);
});

test('diagnosis offers wiring review only when its next action and component support that evidence', () => {
  const issue = {reason: 'display_white', next_action: 'display_symptom', component_id: 'mrd-tf240-8p-cs'};
  const record = changed => session({test_results: [], diagnosis: {issues: [{...issue, ...changed}]}});
  assert.deepEqual(helpers.recommendWiringReview(record(), context, true), {component_id: 'mrd-tf240-8p-cs', source: 'test'});
  assert.equal(helpers.recommendWiringReview(record({next_action: 'analyse'}), context, true), null);
  assert.equal(helpers.recommendWiringReview(record({component_id: 'other-component'}), context, true), null);
});

test('review completion requires current explicit human confirmations for every observed row', () => {
  assert.equal(helpers.hasUnfinishedWiringReview(null), false);
  for (const status of ['collecting', 'analysing', 'ready', 'needs_human']) assert.equal(helpers.hasUnfinishedWiringReview(review({status})), true, status);
  for (const status of ['stale', 'error']) assert.equal(helpers.hasUnfinishedWiringReview(review({status})), false, status);
  const rows = [{wire_id: 'echo'}, {wire_id: 'gnd'}];
  const confirmed = {decision: 'confirmed', source: 'human', review_revision: 2};
  const completed = review({status: 'ready', results: rows, reviews: {echo: confirmed, gnd: confirmed}});
  assert.equal(helpers.hasUnfinishedWiringReview(completed), false);
  assert.equal(helpers.hasUnfinishedWiringReview({...completed, reviews: {echo: confirmed}}), true);
  assert.equal(helpers.hasUnfinishedWiringReview({...completed, reviews: {echo: confirmed, gnd: {...confirmed, decision: 'unsure'}}}), true);
  assert.equal(helpers.hasUnfinishedWiringReview({...completed, reviews: {echo: confirmed, gnd: {...confirmed, evidence_stale: true}}}), true);
});

function entry(hooks = React, language = 'en') {
  return compile('../src/components/WiringReviewEntry.tsx', {react: hooks,
    'react-dom': ReactDOM,
    '../lib/useMaker': {useMakerText: () => (zh, en) => language === 'en' ? en : zh},
    '../lib/wiringReviewEntry': helpers,
  }).WiringReviewEntry;
}
function flatten(node, list = []) {
  if (!node || typeof node !== 'object') return list;
  if (Array.isArray(node)) { for (const item of node) flatten(item, list); return list; }
  list.push(node); flatten(node.props?.children ?? node.children, list); return list;
}

function mountEntry(initial = {}, configureHooks) {
  const fibers = new Map(), effects = [];
  let cursor = 0, dirty = true, props = initial, tree, activeFiber, visited;
  const hooks = {...React,
    useState(initialValue) { const i = cursor++;
      const slots = activeFiber.slots;
      if (!slots[i]) slots[i] = {value: typeof initialValue === 'function' ? initialValue() : initialValue};
      return [slots[i].value, next => {const value = typeof next === 'function' ? next(slots[i].value) : next;
        if (!Object.is(value, slots[i].value)) {slots[i].value = value; dirty = true;}}]; },
    useRef(initialValue) {const i = cursor++; return activeFiber.slots[i] ??= {current: initialValue};},
    useId() {const i = cursor++; return activeFiber.slots[i] ??= `fixture-${activeFiber.key}-${i}`;},
    useEffect(callback, deps) {const i = cursor++, slots = activeFiber.slots, before = slots[i];
      if (!before || !deps || deps.some((value, index) => !Object.is(value, before.deps[index]))) {
        const state = {deps, cleanup: before?.cleanup}; slots[i] = state;
        effects.push(() => {state.cleanup?.(); state.cleanup = callback();});
      }
    },
  };
  const Entry = entry(hooks);
  configureHooks?.(hooks);
  function call(component, nodeProps, key) {
    const before = activeFiber, beforeCursor = cursor;
    activeFiber = fibers.get(key) ?? {key, slots: []}; fibers.set(key, activeFiber); visited.add(key); cursor = 0;
    const output = component(nodeProps); activeFiber = before; cursor = beforeCursor;
    return output;
  }
  function materialize(node, path) {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((child, index) => materialize(child, `${path}.${index}`));
    if (node.$$typeof === Symbol.for('react.portal')) {
      return {...node, children: materialize(node.children, `${path}.portal`)};
    }
    if (typeof node.type === 'function') return materialize(call(node.type, node.props, path), `${path}.render`);
    const children = materialize(node.props?.children, `${path}.child`);
    return Array.isArray(children) ? React.cloneElement(node, {}, ...children) : React.cloneElement(node, {}, children);
  }
  function render() {for (let tries = 0; dirty; tries++) {
    assert.ok(tries < 20, 'entry lifecycle must settle'); dirty = false; visited = new Set();
    tree = materialize(call(Entry, props, 'entry'), 'root');
    for (const [key, fiber] of fibers) if (!visited.has(key)) {
      for (const slot of fiber.slots) slot?.cleanup?.(); fibers.delete(key);
    }
    for (const effect of effects.splice(0)) effect();
  } return tree;}
  render();
  return {hooks, get tree() {return render();}, get nodes() {return flatten(render());},
    update(next) {props = {...props, ...next}; dirty = true; return render();},
    click(predicate) {const node = flatten(render()).find(node => node.type === 'button' && predicate(node));
      assert.ok(node, 'requested entry button must exist'); node.props.onClick(); return render();},
    async settle() {for (let i = 0; i < 10; i++) {await Promise.resolve(); render();} return tree;},
    dispose() {for (const fiber of fibers.values()) for (const slot of fiber.slots) slot?.cleanup?.();},
  };
}

test('normal entry is collapsed and rendering cannot begin capture, analysis, or confirmation', () => {
  let childCalls = 0;
  const html = renderToStaticMarkup(React.createElement(entry(React, 'zh'), {
    review: null, resumable: false, recommendation: null, componentLabel: 'HC-SR04',
    children() {childCalls++; return React.createElement('div', {'data-test': 'review-child'});},
  }));
  assert.match(html, /檢查接線/);
  assert.doesNotMatch(html, /data-test="review-child"/);
  assert.equal(childCalls, 0, 'the complete review is not mounted until explicitly opened');
});

const entryButton = node => typeof node.props?.['aria-expanded'] === 'boolean';
const content = harness => harness.nodes.find(node => node.props?.className === 'wr-entry-content');

test('a late toolbar target moves only the explicit entry action into a real React portal', () => {
  let childCalls = 0;
  const toolbarTarget = {nodeType: 1};
  const h = mountEntry({review: null, resumable: false,
    children() {childCalls++; return React.createElement('div', {'data-test': 'review'});},
  });
  try {
    assert.equal(h.nodes.some(node => node.$$typeof === Symbol.for('react.portal')), false);
    assert.equal(h.nodes.filter(entryButton).length, 1);
    h.update({toolbarTarget});
    const portal = h.nodes.find(node => node.$$typeof === Symbol.for('react.portal'));
    assert.ok(portal, 'the production component must use the toolbar portal once its target is available');
    assert.equal(portal.containerInfo, toolbarTarget);
    assert.equal(h.nodes.filter(entryButton).length, 1, 'the toolbar action is not duplicated');
    assert.equal(content(h), undefined);
    assert.equal(childCalls, 0, 'moving the entry action does not begin the review');
    h.click(entryButton);
    assert.equal(h.nodes.some(node => node.$$typeof === Symbol.for('react.portal')), false,
      'collapse belongs beside the open review, not in the main toolbar');
    assert.ok(h.nodes.some(node => node.props?.className === 'wr-entry-collapse'));
    const action = h.nodes.find(entryButton);
    assert.equal(action.props['aria-expanded'], true);
    assert.equal(action.props['aria-controls'], content(h).props.id,
      'the toolbar action still identifies its original review content');
    assert.equal(content(h).props.hidden, false);
    h.click(entryButton);
    assert.equal(content(h).props.hidden, true);
    h.update({toolbarTarget: null});
    assert.equal(h.nodes.some(node => node.$$typeof === Symbol.for('react.portal')), false);
    assert.equal(h.nodes.filter(entryButton).length, 1);
    assert.equal(content(h).props.hidden, true, 'a target disappearing does not override an explicit collapse');
  } finally {h.dispose();}
});

test('the owner follows visible review state without starting any review operation', () => {
  const visible = [];
  const h = mountEntry({review: null, resumable: false, onExpandedChange: expanded => visible.push(expanded),
    children: () => React.createElement('div', {'data-test': 'review'})});
  try {
    assert.deepEqual(visible, [false]);
    h.click(entryButton); assert.deepEqual(visible, [false, true]);
    h.update({review: review(), resumable: true});
    assert.deepEqual(visible, [false, true], 'a current review does not duplicate the notification');
    h.click(entryButton); assert.deepEqual(visible, [false, true, false]);
    h.update({review: review({revision: 3, status: 'analysing'})});
    assert.deepEqual(visible, [false, true, false], 'a late update cannot reopen the collapsed review');
  } finally {h.dispose();}
});

test('a recommendation stays compact until the user opens it and scopes the review to that component', () => {
  const components = [];
  const h = mountEntry({review: null, resumable: false,
    recommendation: {component_id: 'hc-sr04', source: 'test'}, componentLabel: 'HC-SR04',
    children(componentId) {components.push(componentId); return React.createElement('div', {'data-test': 'review'});},
  });
  try {
    assert.equal(content(h), undefined); assert.deepEqual(components, []);
    assert.equal(h.nodes.find(entryButton).props['aria-expanded'], false);
    h.click(entryButton);
    assert.equal(content(h).props.hidden, false); assert.deepEqual(components, ['hc-sr04']);
  } finally {h.dispose();}
});

test('collapse and reopen retain the mounted child state without invoking a review action', () => {
  let actionCalls = 0, h;
  function Child() {
    const [draft, setDraft] = h.hooks.useState(0);
    return React.createElement('div', {'data-draft': draft},
      React.createElement('button', {'data-action': 'draft', onClick: () => setDraft(value => value + 1)}, 'Edit draft'),
      React.createElement('button', {'data-action': 'analyse', onClick: () => actionCalls++}, 'Analyse'));
  }
  h = mountEntry({review: null, resumable: false, recommendation: null,
    children() {return React.createElement(Child);}});
  try {
    h.click(entryButton); h.click(node => node.props['data-action'] === 'draft');
    assert.equal(h.nodes.find(node => node.props?.['data-draft'] !== undefined).props['data-draft'], 1);
    h.click(entryButton);
    assert.equal(content(h).props.hidden, true);
    assert.equal(h.nodes.find(node => node.props?.['data-draft'] !== undefined).props['data-draft'], 1);
    h.click(entryButton);
    assert.equal(content(h).props.hidden, false);
    assert.equal(h.nodes.find(node => node.props?.['data-draft'] !== undefined).props['data-draft'], 1);
    assert.equal(actionCalls, 0, 'opening, collapsing, and draft editing do not run analysis');
  } finally {h.dispose();}
});

test('unfinished evidence resumes once; polling the same review cannot override the user collapse', () => {
  const h = mountEntry({review: review(), resumable: true, recommendation: null,
    children() {return React.createElement('div', {'data-test': 'review'});}});
  try {
    assert.equal(content(h).props.hidden, false);
    h.click(entryButton); assert.equal(content(h).props.hidden, true);
    h.update({review: review({revision: 3, status: 'analysing'})});
    assert.equal(content(h).props.hidden, true, 'a poll does not force the same round back open');
    h.update({review: review({revision: 4, status: 'ready', results: [{wire_id: 'echo'}]})});
    assert.equal(content(h).props.hidden, true, 'a late analysis result also respects collapse');
    h.update({review: review({id: 'new-round', round: 2})});
    assert.equal(content(h).props.hidden, false, 'a genuinely new unfinished round has its own resume state');
  } finally {h.dispose();}
});

test('completed manual review remains compact on restore and later polls until explicitly opened', () => {
  let childCalls = 0;
  const completed = review({status: 'ready', results: [{wire_id: 'echo'}],
    reviews: {echo: {decision: 'confirmed', source: 'human', review_revision: 2}}});
  const h = mountEntry({review: completed, resumable: true,
    recommendation: {component_id: 'hc-sr04', source: 'test'},
    children() {childCalls++; return React.createElement('div', {'data-test': 'review'});}});
  try {
    assert.equal(content(h), undefined); assert.equal(childCalls, 0);
    h.update({review: {...completed, revision: 3}});
    assert.equal(content(h), undefined); assert.equal(childCalls, 0);
    h.click(entryButton); assert.equal(content(h).props.hidden, false);
    h.click(entryButton); h.update({review: {...completed, revision: 4}});
    assert.equal(content(h).props.hidden, true);
  } finally {h.dispose();}
});

test('an explicit invitation reveal waits for its exact review, opens once, and respects later collapse and polling',()=>{
  let actions=0;
  const h=mountEntry({review:review(),resumable:true,children(){return React.createElement('div',{'data-test':'first-photo'},
    React.createElement('button',{onClick:()=>actions++},'Capture'));}});
  try {
    h.click(entryButton);assert.equal(content(h).props.hidden,true);
    h.update({revealRequest:{token:'invitation-one',reviewId:'next-review',componentId:'hc-sr04'}});
    assert.equal(content(h).props.hidden,true,'another review cannot be opened by this invitation');
    h.update({review:review({id:'next-review'})});assert.equal(content(h).props.hidden,false);
    h.click(entryButton);assert.equal(content(h).props.hidden,true);
    h.update({review:review({id:'next-review',revision:8})});assert.equal(content(h).props.hidden,true);
    h.update({revealRequest:{token:'invitation-two',reviewId:'next-review',componentId:'hc-sr04'}});
    assert.equal(content(h).props.hidden,false,'a new explicit invitation can reopen the current review');
    assert.equal(actions,0,'revealing the first photo does not capture or analyse');
  } finally {h.dispose();}
});

const observedReview = () => review({status: 'ready', results: [{wire_id: 'echo',
  expected: {physical_pin: 12, bcm: 18, component_pin: 'Echo', connection_kind: 'direct'},
  pi_candidates: [], component_candidates: [], comparison: 'unknown', next_step: 'Follow the same wire.'}]});
function retestHarness(initial) {
  const calls = {actions: [], reviews: [], retests: []};
  let h, hooks, Card, activeReview = initial;
  function StatefulCard() {
    const [draft, setDraft] = hooks.useState(0);
    return React.createElement('div', {'data-draft': draft},
      React.createElement('button', {'data-action': 'draft', onClick: () => setDraft(value => value + 1)}, 'Edit draft'),
      React.createElement(Card, {review: activeReview, componentId: 'hc-sr04',
        components: [{id: 'hc-sr04', label: 'HC-SR04'}], captureReady: false,
        onAction: action => calls.actions.push(action),
        onReview(wireId, decision) {
          calls.reviews.push({wireId, decision});
          activeReview = {...activeReview, revision: activeReview.revision + 1,
            reviews: {...activeReview.reviews, [wireId]: {decision, source: 'human', review_revision: activeReview.revision + 1}}};
          h.update({review: activeReview});
        },
        onRetest: componentId => calls.retests.push(componentId),
      }));
  }
  h = mountEntry({review: initial, resumable: true, children: () => React.createElement(StatefulCard)}, injected => {
    hooks = injected;
    Card = compile('../src/components/WiringReviewCard.tsx', {react: hooks,
      '../lib/wiringExpectedLocation':expectedLocationHelpers,'./WiringExpectedLocation':expectedLocationComponent('en',hooks),
      './WiringPhotoSequence': {WiringPhotoSequence:photoSequence(hooks)},
      './WiringFramingGuide': {WiringFramingGuide:framingGuide()},
      '../lib/useMaker': {useMakerText: () => (_zh, en) => en},
      '../lib/wiringReview': compile('../src/lib/wiringReview.ts'),
    }).WiringReviewCard;
  });
  return {h, calls, update(next) {activeReview = next; h.update({review: next});}};
}

for (const restored of [true, false]) {
  test(`${restored ? 'restored' : 'asynchronously received'} unfinished review remains open after the last human confirmation, retaining child state and explicit retest`, async () => {
    const {h, calls, update} = retestHarness(restored ? observedReview() : null);
    try {
      if (!restored) {
        assert.equal(content(h), undefined);
        update(observedReview());
      }
      assert.equal(content(h).props.hidden, false);
      h.click(node => node.props['data-action'] === 'draft');
      h.click(node => node.props.children === 'I checked: connected correctly');
      await h.settle();
      assert.deepEqual(calls.reviews, [{wireId: 'echo', decision: 'confirmed'}]);
      assert.equal(content(h).props.hidden, false, 'completion must not automatically hide the retest action');
      assert.equal(h.nodes.find(node => node.props?.['data-draft'] !== undefined).props['data-draft'], 1,
        'the already mounted child is retained when the last wire becomes confirmed');
      const retest = h.nodes.find(node => node.type === 'button' && node.props.children === 'Retest this module');
      assert.ok(retest); assert.equal(retest.props.disabled, false);
      assert.deepEqual(calls.retests, [], 'completion itself does not operate hardware');
      assert.deepEqual(calls.actions, []);
      h.click(node => node.props.children === 'Retest this module');
      assert.deepEqual(calls.retests, ['hc-sr04'], 'the retained retest remains usable by an explicit click');
    } finally {h.dispose();}
  });
}

test('one wire is shown at a time; navigation changes no confirmation and retest waits for all wires', async () => {
  const initial = observedReview();
  initial.results.push({...initial.results[0], wire_id:'trig', expected:{...initial.results[0].expected, component_pin:'Trig', physical_pin:16, bcm:23}});
  const {h, calls} = retestHarness(initial);
  const displayed = () => h.nodes.filter(node => node.props?.className === 'wr-wire');
  try {
    assert.equal(displayed().length,1); assert.match(renderToStaticMarkup(displayed()[0]), /Echo/);
    h.click(node => node.props.children === 'Next wire');
    assert.equal(displayed().length,1); assert.match(renderToStaticMarkup(displayed()[0]), /Trig/);
    assert.deepEqual(calls, {actions:[],reviews:[],retests:[]});
    h.click(node => node.props.children === 'I checked: connected correctly'); await h.settle();
    assert.deepEqual(calls.reviews,[{wireId:'trig',decision:'confirmed'}]);
    assert.equal(h.nodes.some(node => node.type === 'button' && node.props.children === 'Retest this module'),false);
    h.click(node => node.props.children === 'Previous wire');
    h.click(node => node.props.children === 'I checked: connected correctly'); await h.settle();
    assert.deepEqual(calls.reviews,[{wireId:'trig',decision:'confirmed'},{wireId:'echo',decision:'confirmed'}]);
    assert.ok(h.nodes.some(node => node.type === 'button' && node.props.children === 'Retest this module'));
    assert.deepEqual(calls.actions,[]); assert.deepEqual(calls.retests,[]);
  } finally {h.dispose();}
});
