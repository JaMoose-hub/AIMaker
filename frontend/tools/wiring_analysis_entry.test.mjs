import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers} from './wiring_photo_flow_fixture.mjs';
import {maker, designFor} from './project_guide_fixture.mjs';

// Exercise the real 02 entry and shared-chat rendering with synthetic receipts.
// No photographs, model requests, or hardware operations are performed here.
const wiringChat = flowModule('../src/lib/wiringChat.ts', {'./wiringReview': reviewHelpers});
const progress = flowModule('../src/lib/assistantProgress.ts');
const history = flowModule('../src/lib/assistantHistory.ts');
const useMaker = {useMakerText: () => (zh, en) => en};
const components = [{id: 'hc-sr04', label: 'HC-SR04+'}, {id: 'mrd-tf240-8p-cs', label: 'MRD-TFT240'}];
const flow = (change = {}) => ({flow_id: 'flow', review_id: 'review', revision: 4, round: 1,
  component_id: 'hc-sr04', kind: 'photo_request', role: 'pi_side_a', current: true, can_act: true,
  actions: ['capture'], ...change});
const message = (change = {}) => ({id: 'current-question', role: 'assistant', text: 'Photograph the first Pi side.',
  source: 'legacy-debug', epoch: 0, round: 1, stage: 'guide', capability: 'wiring', wiring_flow: flow(change)});
function loadEntry(hooks = React) {
  return flowModule('../src/components/WiringAnalysisEntry.tsx', {react: hooks,
    '../lib/useMaker': useMaker, '../lib/wiringChat': wiringChat});
}
function elements(tree, type) {
  const out = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {node.forEach(visit); return;}
    if (node.type === type) out.push(node);
    visit(node.props?.children);
  }
  visit(tree); return out;
}
function harness() {
  const values = [], refs = []; let index = 0, ref = 0;
  const hooks = {...React, useRef: initial => refs[ref++] ??= {current: initial},
    useState(initial) {const i = index++; if (!(i in values)) values[i] = typeof initial === 'function' ? initial() : initial;
      return [values[i], next => values[i] = typeof next === 'function' ? next(values[i]) : next];}};
  const {WiringAnalysisEntry} = loadEntry(hooks);
  return {render(props) {index = 0; ref = 0; return WiringAnalysisEntry({components, busy: false, aiReady: true,
    onStart: async () => true, onShow() {}, ...props});}};
}
const deferred = () => {let resolve; const promise = new Promise(done => resolve = done); return {promise, resolve};};
const settle = async () => {await Promise.resolve(); await Promise.resolve(); await Promise.resolve();};

test('shared chat does not mount the removed standalone wiring analysis entry in any workflow stage', () => {
  const noScroll = () => ({chatRef: null, contentRef: null, onScroll() {}, followNext() {}, showMessage() {}, showLatest() {}, unread: 0});
  const {UnifiedAssistant} = flowModule('../src/components/UnifiedAssistant.tsx', {
    react: React, '../lib/useMaker': useMaker, '../lib/i18n': {useI18n: () => ({locale: 'en', tx: x => typeof x === 'string' ? x : x.en})},
    '../lib/maker': maker, '../lib/assistant': {currentAssistantMedia: () => null}, '../lib/assistantHistory': history,
    '../lib/useChatScroll': {useChatScroll: noScroll}, '../lib/assistantProgress': progress,
    './WiringAnalysisEntry': loadEntry(), './ProjectConcept': {ProjectConcept: () => null},
    './MakerModelMenu': {MakerModelMenu: () => null}, './MobileCompanion': {MobileCompanion: () => null, MobileAttachmentCards: () => null},
    './ConversationGuideDock': {ConversationGuideHost: () => null},
    './AssistantMarkdown': {AssistantMarkdown: () => null}, './AssistantAnalysisTime': {AssistantAnalysisTime: () => null},
    './AssistantJobProgress': {AssistantJobProgress: () => null}, './WiringChatMessage': {WiringChatMessage: () => null, WiringReceiptStatus: () => null},
  });
  const conversation = {id: 'project', kind: 'project', context_epoch: 0, before: null, messages: [], jobs: [], round: 1};
  let calls = 0;
  const render = (stage, demoOpen = false, changes = {}) => renderToStaticMarkup(React.createElement(UnifiedAssistant, {
    state: {...maker.initialMaker(), design: designFor(), stage, guide: {...maker.initialMaker().guide, run: 1}},
    setState() {}, onNewProject: async () => false, onStartWiringReview: async () => {calls++; return true;},
    controller: {record: changes.conversation ?? conversation, mobileContext: {round: 1}, busy: false, demoOpen, draft: 'Preserve this draft'},
    wiringReviewActive: changes.wiringReviewActive,
    legacy: {busy: false, ai: {logged_in: true}, aiOptions: {selectionValid: true}},
  }));
  const html = render('guide');
  assert.doesNotMatch(html, /wiring-analysis-entry|Wiring photo analysis|Check wiring with photos/);
  assert.doesNotMatch(html, /No Pi connection needed/); assert.match(html, /Preserve this draft/);
  assert.equal((html.match(/<textarea/g) || []).length, 1); assert.equal((html.match(/role="log"/g) || []).length, 1);
  for (const variant of [['design'], ['deploy'], ['guide', true]]) assert.doesNotMatch(render(...variant), /Wiring photo analysis/);
  const stopped = render('guide', false, {wiringReviewActive: false,
    conversation: {...conversation, messages: [message()]}});
  assert.doesNotMatch(stopped, /wiring-analysis-entry|Check wiring with photos|Continue photos/);
  const active = render('guide', false, {conversation: {...conversation, messages: [message()]}});
  assert.doesNotMatch(active, /wiring-analysis-entry|Wiring photo analysis/,
    'an existing review must stay in the conversation instead of recreating a toolbar');
  assert.equal(calls, 0, 'showing the entry must not start a review or a model request');
});

test('wiring analysis entry starts only the explicitly selected module and leaves the composer to its owner', async () => {
  const h = harness(), calls = [], props = {preferredId: 'hc-sr04', onStart: async id => {calls.push(id); return true;}};
  let tree = h.render(props); assert.deepEqual(calls, []);
  elements(tree, 'select')[0].props.onChange({target: {value: 'mrd-tf240-8p-cs'}});
  tree = h.render(props); assert.equal(elements(tree, 'select')[0].props.value, 'mrd-tf240-8p-cs');
  elements(tree, 'button')[0].props.onClick(); await settle();
  assert.deepEqual(calls, ['mrd-tf240-8p-cs']); assert.equal(elements(h.render(props), 'textarea').length, 0);
});

test('wiring analysis entry blocks a duplicate start and exposes a failed submission for an explicit retry', async () => {
  const h = harness(), response = deferred(), calls = [];
  const props = {onStart: async id => {calls.push(id); return calls.length === 1 ? response.promise : true;}};
  const button = elements(h.render(props), 'button')[0]; button.props.onClick(); button.props.onClick();
  assert.equal(calls.length, 1); assert.equal(elements(h.render(props), 'button')[0].props.disabled, true);
  response.resolve(false); await settle();
  let tree = h.render(props); assert.match(renderToStaticMarkup(tree), /Not completed/);
  assert.equal(elements(tree, 'button')[0].props.disabled, false);
  elements(tree, 'button')[0].props.onClick(); await settle();
  tree = h.render(props); assert.equal(calls.length, 2); assert.doesNotMatch(renderToStaticMarkup(tree), /Not completed/);
});

test('wiring analysis entry resumes the exact photo question or views busy analysis without starting another review', () => {
  const h = harness(), shown = [], calls = [], props = {busy: true, aiReady: false,
    onStart: async id => {calls.push(id); return true;}, onShow: item => shown.push(item.id)};
  for (const kind of ['photo_request', 'analysing']) {
    const current = message({kind}), tree = h.render({...props, message: current});
    assert.equal(elements(tree, 'select')[0].props.disabled, true); assert.equal(elements(tree, 'button')[0].props.disabled, false);
    elements(tree, 'button')[0].props.onClick();
  }
  assert.deepEqual(shown, ['current-question', 'current-question']); assert.deepEqual(calls, []);
});

test('wiring analysis entry analyses only through the current bound question and shows the received photo count', async () => {
  const h = harness(), calls = [], current = message({kind: 'analysis_request', role: undefined, actions: ['analyse']});
  const review = {id: 'review', revision: 4, round: 1, component_id: 'hc-sr04', slots: {
    pi_side_a: {available: true}, pi_side_b: {available: true}, component_header: {available: true}}};
  const props = {message: current, review, onAnalyse: async (item, action) => {calls.push({item, action}); return true;},
    onStart: async () => assert.fail('Analysis must not create a review')};
  const tree = h.render(props); assert.match(renderToStaticMarkup(tree), /3\/3 photos received/);
  assert.equal(elements(tree, 'button')[0].props.children, 'Start analysis'); assert.deepEqual(calls, []);
  elements(tree, 'button')[0].props.onClick(); await settle();
  assert.equal(calls[0].item, current); assert.deepEqual(calls[0].action,
    {op: 'analyse', review_id: 'review', revision: 4, component_id: 'hc-sr04'});
  assert.equal(elements(h.render({...props, onAnalyse: undefined}), 'button')[0].props.disabled, true);
  assert.equal(elements(h.render({...props, busy: true}), 'button')[0].props.disabled, true);
  const failed = message({kind: 'error', role: undefined, actions: ['analyse']});
  const retry = h.render({...props, message: failed});
  assert.equal(elements(retry, 'button')[0].props.children, 'Retry analysis');
  elements(retry, 'button')[0].props.onClick(); await settle();
  assert.equal(calls[1].item, failed); assert.deepEqual(calls[1].action, calls[0].action);
});

test('wiring analysis entry explains missing AI readiness and rejects missing modules or busy starts', () => {
  const h = harness(); let calls = 0;
  for (const blocked of [{aiReady: false}, {busy: true}, {components: []}]) {
    const tree = h.render({...blocked, onStart: async () => {calls++; return true;}});
    const button = elements(tree, 'button')[0]; assert.equal(button.props.disabled, true); button.props.onClick();
    if (blocked.aiReady === false) assert.match(renderToStaticMarkup(tree), /Sign in to AI and select a model below/);
  }
  assert.equal(calls, 0);
});
