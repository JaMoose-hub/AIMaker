import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { transpileModule, ModuleKind, ScriptTarget } from 'typescript';

const code = readFileSync(new URL('../src/lib/cameraModes.ts', import.meta.url), 'utf8');
const output = transpileModule(code, { compilerOptions: { module: ModuleKind.ESNext, target: ScriptTarget.ES2022 } }).outputText;
const { cameraModeKey, fetchCameraModes, applyCameraMode, modeErrorKey } = await import('data:text/javascript;base64,' + Buffer.from(output).toString('base64'));
const high = { width: 2592, height: 1944, fps: 15 };

test('high resolution is paired with its real frame rate, not a global 30 FPS', () => {
  assert.equal(cameraModeKey(high), '2592x1944@15');
  assert.notEqual(cameraModeKey(high), cameraModeKey({ ...high, fps: 30 }));
});

test('GET is cancellable; POST binds to camera identity and is never retried', async () => {
  const oldFetch = globalThis.fetch, oldWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, ...options }); return { ok: true, json: async () => ({ ok: true }) }; };
  try {
    const controller = new AbortController();
    await fetchCameraModes(controller.signal);
    assert.equal(calls[0].signal, controller.signal);
    await applyCameraMode('usb-device', high);
    assert.deepEqual(JSON.parse(calls[1].body), { device_id: 'usb-device', ...high });
    assert.equal(calls[1].method, 'POST');
    let count = 0;
    globalThis.fetch = async () => { count++; throw new Error('disconnected'); };
    await assert.rejects(applyCameraMode('usb-device', high), /disconnected/);
    assert.equal(count, 1);
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: 'camera_adjustment_busy' }) });
    await assert.rejects(applyCameraMode('usb-device', high), /camera_adjustment_busy/);
  } finally { globalThis.fetch = oldFetch; globalThis.window = oldWindow; }
});

test('unknown errors do not expose raw device output; every message is translated', () => {
  assert.equal(modeErrorKey(new Error('raw log')), 'camera.modeError.camera_mode_unknown');
  for (const locale of ['zh-TW', 'en']) {
    const strings = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`, import.meta.url), 'utf8'));
    for (const reason of ['camera_mode_unknown', 'camera_modes_unavailable', 'camera_adjustment_busy',
      'camera_modes_unsupported', 'camera_changed', 'camera_mode_unsupported', 'camera_worker_busy',
      'camera_mode_failed', 'camera_restore_failed']) assert.ok(strings[modeErrorKey(new Error(reason))]);
    for (const key of ['resolution', 'modeApply', 'modeApplying', 'modeActual', 'modeNoFrame', 'modeHint', 'modeSuccess', 'modeRefresh'])
      assert.ok(strings[`camera.${key}`]);
  }
});

test('same-socket resolution changes expose the new runtime even after hello is cleared', async () => {
  const source = readFileSync(new URL('../src/lib/wsClient.ts', import.meta.url), 'utf8')
    .replace('import { useSyncExternalStore } from "react";', 'const useSyncExternalStore = () => {};');
  const js = transpileModule(source, { compilerOptions: { module: ModuleKind.ESNext, target: ScriptTarget.ES2022 } }).outputText;
  const { wsClient } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
  const oldWindow = globalThis.window;
  globalThis.window = { requestAnimationFrame: () => 1, setTimeout: () => 1 };
  try {
    const send = message => wsClient.handleMessage({ data: JSON.stringify(message) });
    send({ type: 'hello', board_id: 'raspberry-pi-5', runtime_revision: 1 });
    for (const revision of [2, 3, 4]) {
      send({ type: 'runtime_changed', board_id: 'raspberry-pi-5', runtime_revision: revision });
      assert.equal(wsClient.getSnapshot().runtime.runtime_revision, revision);
      assert.equal(wsClient.getSnapshot().hello, null);
      assert.equal(wsClient.getSnapshot().detection, null);
    }
    send({ type: 'runtime_changed', board_id: 'raspberry-pi-5', runtime_revision: 3 });
    assert.equal(wsClient.getSnapshot().runtime.runtime_revision, 4);
    // A newer detection can also recover a missed runtime_changed event.
    send({ type: 'detection', board_id: 'raspberry-pi-5', runtime_revision: 5 });
    assert.equal(wsClient.getSnapshot().runtime.runtime_revision, 5);
    send({ type: 'hello', board_id: 'raspberry-pi-5', runtime_revision: 1 });
    assert.equal(wsClient.getSnapshot().runtime.runtime_revision, 1);
    const view = readFileSync(new URL('../src/components/VideoView.tsx', import.meta.url), 'utf8');
    assert.ok(view.includes('original.runtime?.runtime_revision ?? original.hello?.runtime_revision'));
  } finally { globalThis.window = oldWindow; }
});

test('camera inventory is cancellable and uncached; switch sends device identity exactly once', async () => {
  const source = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  const js = transpileModule(source, { compilerOptions: { module: ModuleKind.ESNext, target: ScriptTarget.ES2022 } }).outputText;
  const api = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
  const previous = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => { calls.push({url, ...options}); return {ok:true,json:async()=>({ok:true,cameras:[]})}; };
  try {
    const controller = new AbortController();
    await api.fetchCameras(controller.signal);
    assert.equal(calls[0].signal, controller.signal);
    assert.equal(calls[0].cache, 'no-store');
    await api.postSelectCamera(1, 'stable-device-id');
    assert.deepEqual(JSON.parse(calls[1].body), {index:1,device_id:'stable-device-id'});
    let attempts = 0;
    globalThis.fetch = async () => { attempts++; throw new Error('lost response'); };
    await assert.rejects(api.postSelectCamera(1, 'stable-device-id'));
    assert.equal(attempts, 1);
    globalThis.fetch = async () => ({ok:false,status:409});
    assert.equal((await api.postSelectCamera(1, 'stable-device-id')).error_code, 'camera_adjustment_busy');
  } finally { globalThis.fetch = previous; }
});

test('camera picker refreshes only safe metadata lists and permits reconnect without preview', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /cameraPickerVisible=\{config\?\.camera_source === "device"\}/);
  assert.doesNotMatch(app, /setCamerasAvailable|fetchCameras/);
  const source = readFileSync(new URL('../src/components/CameraPicker.tsx', import.meta.url), 'utf8');
  assert.match(source, /canPoll = !!resp.refreshable/);
  assert.match(source, /controller.abort\(\)/);
  assert.match(source, /switchingRef.current \|\| modeBusyRef.current/);
  assert.match(source, /cam.selectable \?\? cam.available/);
  assert.match(source, /!cam.is_current \|\| !cam.available/);
  assert.match(source, /postSelectCamera\(index, cam.device_id\)/);
  for (const locale of ['zh-TW','en']) {
    const strings = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`,import.meta.url),'utf8'));
    for (const key of ['refresh','refreshHint','readyToTry','deviceName','reconnect','selectionUnknown'])
      assert.ok(strings[`camera.${key}`]);
    for (const reason of ['camera_changed','camera_inventory_unavailable','camera_modes_unavailable',
      'camera_worker_busy','camera_restore_failed','camera_adjustment_busy']) assert.ok(strings[`camera.selectError.${reason}`]);
  }
});
