import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as jsx from 'react/jsx-runtime';

function load(file, modules = {}) {
  const exports = {};
  const js = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  new Function('require', 'exports', js)(name => { assert.ok(name in modules, name); return modules[name]; }, exports);
  return exports;
}
const domain = load('../src/lib/wiringReview.ts');
const roles = domain.wiringPhotoRoles;
function fixture() {
  const states = [], refs = [], effects = []; let stateCursor = 0, refCursor = 0;
  const hooks = {
    useState(initial) { const i = stateCursor++; if (!(i in states)) states[i] = initial; return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
    useRef(initial) { const i = refCursor++; return refs[i] ??= { current: initial }; },
    useEffect(callback) { effects.push(callback); },
  };
  const module = load('../src/lib/useMobileWiringAlbum.ts', { react: hooks, './wiringReview': domain });
  let context = { contextId: 'context', conversationId: 'chat', epoch: 1, review: { id: 'review', round: 2, revision: 1, component_id: 'hc-sr04' } };
  const files = roles.map(role => ({ name: role + '.jpg', type: 'image/jpeg' }));
  const render = () => { stateCursor = refCursor = 0; effects.length = 0; return module.useMobileWiringAlbum(context); };
  const request = (role = roles[0], extra = {}) => ({ ...context, role, message_id: role, request_id: 'request-' + context.review.revision, ...extra });
  return { files, render, request, update(value) { context = { ...context, ...value }; }, context: () => context, flush() { effects.forEach(effect => effect()); } };
}

test('three album photos stage locally and require explicit view and unchanged-wiring confirmation', () => {
  const f = fixture(); assert.equal(f.render().stage(f.files, f.request()), true);
  let album = f.render(); assert.equal(album.selection.photos.length, 3);
  assert.deepEqual(album.selection.photos.map(photo => photo.role), roles);
  assert.equal(album.fileFor(f.request()), null);
  album.confirm(true); album = f.render(); assert.equal(album.fileFor(f.request()), f.files[0]);
});

test('three queued photos follow three fresh sequential questions, not one batch submission', () => {
  const f = fixture(); f.render().stage(f.files, f.request()); f.render().confirm(true);
  for (let i = 0; i < 3; i++) {
    f.update({ review: { ...f.context().review, revision: i + 1 } });
    const request = f.request(roles[i]), album = f.render();
    assert.equal(album.fileFor(request), f.files[i]); album.submitted(request, f.files[i]);
    assert.equal(f.render().fileFor(request), null, 'a successful view cannot send twice');
    assert.equal(f.render().selection.photos.filter(photo => photo.sent).length, i + 1);
  }
});

test('a failed upload retains its photo and all other views for retry', () => {
  const f = fixture(); f.render().stage(f.files, f.request()); f.render().confirm(true);
  assert.equal(f.render().fileFor(f.request()), f.files[0]);
  assert.equal(f.render().selection.photos.some(photo => photo.sent), false);
  assert.equal(f.render().fileFor(f.request()), f.files[0]);
});

test('role reassignment swaps views without losing files and resets confirmation', () => {
  const f = fixture(); f.render().stage(f.files, f.request()); f.render().confirm(true);
  f.render().assign(0, 'component_header'); const album = f.render();
  assert.deepEqual(album.selection.photos.map(photo => photo.role), ['component_header', 'pi_side_b', 'pi_side_a']);
  assert.deepEqual(album.selection.photos.map(photo => photo.file), f.files);
  assert.equal(album.selection.confirmed, false);
});

test('already submitted views cannot be reassigned or selected again', () => {
  const f = fixture(); f.render().stage(f.files, f.request()); f.render().confirm(true); f.render().submitted(f.request(), f.files[0]);
  f.render().assign(1, 'pi_side_a'); f.render().assign(0, 'component_header');
  assert.deepEqual(f.render().selection.photos.map(photo => photo.role), roles);
  assert.equal(f.render().fileFor(f.request()), null);
});

test('project, chat, epoch, component and photo-round changes invalidate all old album files', () => {
  for (const change of [{ contextId: 'other' }, { conversationId: 'other' }, { epoch: 2 },
    { review: { id: 'other', round: 2, component_id: 'hc-sr04' } },
    { review: { id: 'review', round: 3, component_id: 'hc-sr04' } },
    { review: { id: 'review', round: 2, component_id: 'mrd-tft240-8p-cs' } }]) {
    const f = fixture(); f.render().stage(f.files, f.request()); f.render().confirm(true); const old = f.request();
    f.update(change); const album = f.render();
    assert.equal(album.selection, null); assert.equal(album.fileFor(old), null);
    assert.equal(album.stage(f.files, old), false); f.flush(); assert.equal(f.render().selection, null);
  }
});

test('selection caps at three, keeps existing files on error, and can stage two remaining views', () => {
  const f = fixture(); f.render().stage(f.files, f.request());
  assert.equal(f.render().stage([...f.files, f.files[0]], f.request()), false);
  assert.equal(f.render().selection.photos.length, 3);
  assert.equal(f.render().stage(f.files.slice(0, 2), f.request('pi_side_b')), true);
  assert.deepEqual(f.render().selection.photos.map(photo => photo.role), ['pi_side_b', 'pi_side_a']);
  assert.equal(f.render().stage([], f.request()), false);
});

test('clear removes local photographs without creating an upload or changing the review', () => {
  const f = fixture(), before = structuredClone(f.context());
  f.render().stage(f.files, f.request()); f.render().clear();
  assert.equal(f.render().selection, null); assert.deepEqual(f.context(), before);
});

test('late delivery receipts only mark the exact selected file, never a replacement or another camera photo',()=>{
  const f=fixture(),request=f.request();f.render().stage(f.files,request);const old=f.render();
  old.submitted(request,{name:'other-camera-photo.jpg',type:'image/jpeg'});
  assert.equal(f.render().selection.photos[0].sent,false);
  f.render().clear();const replacements=f.files.map(file=>({...file}));f.render().stage(replacements,request);f.render();
  old.submitted(request,f.files[0]);assert.equal(f.render().selection.photos.some(photo=>photo.sent),false);
  f.render().submitted(request,replacements[0]);assert.equal(f.render().selection.photos[0].sent,true);
});

test('album panel labels all three views, requires confirmation and disables sent or busy controls', () => {
  const { MobileWiringAlbumPanel } = load('../src/components/MobileWiringAlbumPanel.tsx', {
    react: { ...React, useState: value => [value, () => {}], useEffect() {} }, 'react/jsx-runtime': jsx, '../lib/wiringReview': domain,
  });
  const nodes = element => !React.isValidElement(element) ? [] : [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
  const f = fixture(); f.render().stage(f.files, f.request());
  const tr = (_, en) => en; let used = 0;
  const render = disabled => nodes(MobileWiringAlbumPanel({ album: f.render(), role: 'pi_side_a', disabled, onUse: () => used++, tr }));
  let tree = render(false); assert.equal(tree.filter(node => node.type === 'select').length, 3);
  assert.equal(tree.find(node => node.props.className === 'mw-button mw-primary').props.disabled, true);
  tree.find(node => node.type === 'input').props.onChange({ target: { checked: true } });
  tree = render(false); const send = tree.find(node => node.props.className === 'mw-button mw-primary');
  assert.equal(send.props.disabled, false); send.props.onClick(); assert.equal(used, 1);
  f.render().submitted(f.request(), f.files[0]); tree = render(false);
  assert.equal(tree.find(node => node.type === 'select').props.disabled, true);
  assert.equal(tree.find(node => node.props.className === 'mw-button mw-primary').props.disabled, true);
  assert.ok(render(true).filter(node => ['select', 'button', 'input'].includes(node.type)).every(node => node.props.disabled));
});
