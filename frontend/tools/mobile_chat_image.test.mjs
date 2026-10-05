import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';

function load(file, modules = {}) {
  const exports = {};
  const js = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function('require', 'exports', js)(name => {
    assert.ok(name in modules, `Unexpected runtime import: ${name}`);
    return modules[name];
  }, exports);
  return exports;
}
const history = load('../src/lib/assistantHistory.ts');
function components(locale = 'zh-TW', hooks = {}, media = path => ({ url: path ? `blob:${path}` : null, error: '', retry() {} })) {
  return load('../src/components/MobileWebApp.tsx', {
    react: { ...React, ...hooks }, 'react/jsx-runtime': jsx,
    '../lib/i18n': { useI18n: () => ({ locale }) }, '../lib/assistantHistory': history,
    '../lib/useMobileBrowser': { useMobileAssetUrl: (_, path) => media(path), mobileTestHelpOffer: () => null, mobileWiringPhotoFlow: () => null },
    '../lib/mobile': {}, '../lib/mobileBrowserCapture': {}, '../lib/mobileWebView': {}, '../mobileWeb.css': {},
    './AssistantAnalysisTime': { AssistantAnalysisTime: () => null },
    './WiringChatMessage': { WiringCaptureFraming: () => null }, './PhoneCameraAutoTune': { PhoneCameraAutoTune: () => null },
  });
}
function nodes(tree) {
  const result = [];
  function visit(node) {
    if (!React.isValidElement(node)) return;
    result.push(node);
    React.Children.forEach(node.props.children, visit);
  }
  visit(tree);
  return result;
}
function imageHarness(locale = 'zh-TW') {
  const state = [], refs = [];
  let stateIndex = 0, refIndex = 0, effect;
  const { MobileChatImage } = components(locale, {
    useState(initial) {
      const i = stateIndex++;
      if (!(i in state)) state[i] = initial;
      return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }];
    },
    useRef(initial) { return refs[refIndex++] ??= { current: initial }; },
    useEffect(callback) { effect = callback; },
  });
  return {
    render(extra = {}) {
      stateIndex = refIndex = 0;
      return nodes(MobileChatImage({ src: 'blob:saved-image', alt: 'Pi.jpg', title: 'Pi.jpg', openLabel: 'View full image', ...extra }));
    },
    mountDialog(element, trigger = null) { refs[0].current = trigger; refs[1].current = element; return effect(); },
  };
}

test('an image opens only on explicit click, shows the same full image and closes with its button', () => {
  const h = imageHarness();
  let tree = h.render();
  assert.equal(tree.filter(node => node.type === 'dialog').length, 0);
  const trigger = tree.find(node => node.type === 'button');
  assert.equal(trigger.props.type, 'button');
  assert.equal(trigger.props['aria-haspopup'], 'dialog');
  trigger.props.onClick();
  tree = h.render();
  const dialog = tree.find(node => node.type === 'dialog');
  assert.equal(dialog.props['aria-label'], 'Pi.jpg');
  assert.ok(tree.filter(node => node.type === 'img').every(node => node.props.src === 'blob:saved-image'));
  const calls = [], cleanup = h.mountDialog({ showModal: () => calls.push('open'), close: () => calls.push('close') },
    { focus: options => { assert.deepEqual(options, { preventScroll: true }); calls.push('focus'); } });
  assert.deepEqual(calls, ['open']);
  const close = nodes(dialog).find(node => node.type === 'button');
  assert.equal(close.props.children, '關閉');
  assert.equal(close.props.autoFocus, true);
  close.props.onClick();
  assert.equal(h.render().filter(node => node.type === 'dialog').length, 0);
  cleanup();
  assert.deepEqual(calls, ['open', 'close', 'focus']);
});

test('Escape and native close both clear the image viewer, which can be opened again', () => {
  const h = imageHarness('en');
  for (const event of ['onCancel', 'onClose']) {
    h.render().find(node => node.type === 'button').props.onClick();
    const dialog = h.render().find(node => node.type === 'dialog');
    assert.equal(nodes(dialog).find(node => node.type === 'button').props.children, 'Close');
    let prevented = false;
    dialog.props[event]({ preventDefault() { prevented = true; } });
    assert.equal(prevented, event === 'onCancel');
    assert.equal(h.render().filter(node => node.type === 'dialog').length, 0);
  }
});

test('a replaced or revoked image source does not automatically open a different photo', () => {
  const h = imageHarness();
  h.render().find(node => node.type === 'button').props.onClick();
  assert.equal(h.render().filter(node => node.type === 'dialog').length, 1);
  assert.equal(h.render({ src: 'blob:new-image' }).filter(node => node.type === 'dialog').length, 0);
});

const attachment = (id, role = 'user') => ({ id, role, text: id, epoch: 0, round: 1,
  attachments: [{ asset_id: id, type: 'image', filename: `${id}.jpg`, image_url: `/api/mobile/assets/${id}/file` }] });
function workspace(messages) {
  return { api: {}, conversation: { id: 'same-chat', context_epoch: 0, round: 1, before: null, jobs: [], messages },
    draft: '', attachments: [], outbox: [], busy: false };
}
test('desktop, phone, assistant attachments and wiring photos share clickable previews in both languages', () => {
  for (const locale of ['zh-TW', 'en']) {
    const paths = [], { ChatView } = components(locale, {}, path => {
      if (path) paths.push(path);
      return { url: path ? `blob:${path}` : null, error: '', retry() {} };
    });
    const w = workspace([attachment('desktop'), attachment('phone'), attachment('assistant', 'assistant'),
      { id: 'wiring', role: 'user', text: 'Wiring', epoch: 0, round: 1, wiring_flow: { kind: 'photo', image_url: '/api/mobile/wiring-review/evidence/capture' } }]);
    const before = JSON.stringify(w);
    const html = renderToStaticMarkup(React.createElement(ChatView, { w, onPhoto() { throw Error('No workspace navigation'); } }));
    assert.equal((html.match(/aria-haspopup="dialog"/g) ?? []).length, 4);
    assert.equal((html.match(/<img /g) ?? []).length, 4);
    assert.ok(html.includes(locale === 'zh-TW' ? '放大查看圖片' : 'View full image'));
    assert.ok(html.includes(locale === 'zh-TW' ? '放大查看接線照片原圖' : 'View the original wiring photo larger'));
    assert.equal(paths.length, 4);
    assert.equal(JSON.stringify(w), before);
  }
});

test('failed media keeps its reload action and never exposes an empty image viewer', () => {
  const { ChatView } = components('en', {}, path => ({ url: null, error: path ? 'Unavailable' : '', retry() {} }));
  const html = renderToStaticMarkup(React.createElement(ChatView, { w: workspace([attachment('failed')]), onPhoto() {} }));
  assert.ok(html.includes('Reload attachment'));
  assert.equal((html.match(/aria-haspopup="dialog"/g) ?? []).length, 0);
});

test('video thumbnails retain their play action instead of opening as photos', () => {
  const { ChatView } = components('en');
  const message = attachment('video');
  Object.assign(message.attachments[0], { type: 'video', thumbnail_url: '/api/mobile/assets/video/thumbnail' });
  const html = renderToStaticMarkup(React.createElement(ChatView, { w: workspace([message]), onPhoto() {} }));
  assert.ok(html.includes('Play video'));
  assert.ok(html.includes('/api/mobile/assets/video/thumbnail'));
  assert.equal((html.match(/aria-haspopup="dialog"/g) ?? []).length, 0);
});
