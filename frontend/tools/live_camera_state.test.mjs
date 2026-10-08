import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
function load(path, modules = {}) {
  const exports = {};
  new Function('exports', 'require', ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'),
    { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText)(exports, name => {
      if (!(name in modules)) throw Error(`Unexpected import ${name}`); return modules[name];
    }); return exports;
}
const domain = load('../src/lib/liveCameraState.ts');
const config = (revision = 1) => ({ camera_source: 'phone', camera_identity: 'phone:paired:2', runtime_revision: revision });
const status = (revision = 1) => ({ kind: 'phone', session_id: 'paired', generation: 2, runtime_revision: revision, ready: true, error: null });
const response = body => ({ ok: true, json: async () => body });
const turn = () => new Promise(resolve => setImmediate(resolve));

test('one failed status poll retains a bounded metadata lease, not a renewed frame lease', () => {
  const value = status();
  assert.equal(domain.currentLiveCameraStatus(value, 1000, config(), 2000), value);
  assert.equal(domain.currentLiveCameraStatus(value, 1000, config(), 3501), null);
  assert.equal(domain.currentLiveCameraStatus(value, 1000, config(), 999), null);
  assert.equal(domain.currentLiveCameraStatus(value, 1000, null, 1100), null);
});

test('session, generation, source and runtime changes immediately retire old status', () => {
  for (const changed of [config(2), { ...config(), camera_identity: 'phone:other:2' }, { ...config(), camera_identity: 'phone:paired:3' },
    { ...config(), camera_source: 'device' }, { ...config(), camera_identity: undefined }])
    assert.equal(domain.currentLiveCameraStatus(status(), 1000, changed, 1100), null);
});

test('camera deadlines include hung response bodies and non-cooperating fetch', async () => {
  const before = globalThis.fetch;
  try {
    globalThis.fetch = () => new Promise(() => {});
    await assert.rejects(domain.liveCameraRequest('/status', {}, 10), /live_camera_timeout/);
    globalThis.fetch = async () => ({ ok: true, json: () => new Promise(() => {}) });
    await assert.rejects(domain.liveCameraRequest('/status', {}, 10), /live_camera_timeout/);
  } finally { globalThis.fetch = before; }
});

test('cancelled and HTTP errors remain errors; successful bodies are read once', async () => {
  const before = globalThis.fetch;
  try {
    const abort = new AbortController(); abort.abort(); let calls = 0;
    globalThis.fetch = async () => { calls++; return response({ ready: true }); };
    await assert.rejects(domain.liveCameraRequest('/status', {}, 10, abort.signal), { name: 'AbortError' });
    assert.equal(calls, 0);
    assert.deepEqual(await domain.liveCameraRequest('/status'), { ready: true });
    globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: 'mobile_context_changed' }) });
    await assert.rejects(domain.liveCameraRequest('/status'), /mobile_context_changed/);
  } finally { globalThis.fetch = before; }
});

async function fixture(run) {
  const before = globalThis.fetch, states = [], refs = [], effects = [], memos = [];
  let si, ri, ei, mi, currentConfig = config(), configCalls = 0;
  const same = (a, b) => a?.length === b?.length && a.every((value, i) => Object.is(value, b[i]));
  const hooks = {
    useState(initial) { const i = si++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
      return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
    useRef(initial) { return refs[ri++] ??= { current: initial }; },
    useCallback(callback, deps) { const i = mi++; if (!memos[i] || !same(memos[i].deps, deps)) memos[i] = { deps, callback }; return memos[i].callback; },
    useEffect(callback, deps) { const i = ei++; if (!effects[i] || !same(effects[i].deps, deps)) effects[i] = { deps, callback, pending: true, cleanup: effects[i]?.cleanup }; },
  };
  const { useLiveCamera } = load('../src/lib/useLiveCamera.ts', { react: hooks, './liveCameraState': domain });
  const onConfig = next => { currentConfig = next; configCalls++; };
  const render = () => {
    si = ri = ei = mi = 0; const result = useLiveCamera(currentConfig, onConfig);
    for (const effect of effects) if (effect.pending) { effect.pending = false; effect.cleanup?.(); effect.cleanup = effect.callback(); }
    return result;
  };
  const flush = async () => { for (let i = 0; i < 4; i++) { await turn(); render(); } };
  const remount = () => { for (const effect of [...effects].reverse()) effect.cleanup?.();
    for (const effect of effects) effect.cleanup = effect.callback(); };
  try { await run({ render, flush, remount, configCalls: () => configCalls, setConfig: value => { currentConfig = value; } }); }
  finally { for (const effect of [...effects].reverse()) effect.cleanup?.(); globalThis.fetch = before; await turn(); }
}

test('late pre-selection poll cannot overwrite a completed camera transaction', async () => {
  await fixture(async f => {
    let release, polls = 0;
    globalThis.fetch = async (url, init) => {
      if (url === '/api/config') return response(config(2));
      if (init.method === 'POST') return response(status(2));
      if (++polls === 1) return new Promise(resolve => { release = resolve; });
      return response(status(2));
    };
    f.render(); await turn();
    assert.equal(await f.render().select('phone', { session_id: 'paired', stream: { generation: 2 } }), true);
    await f.flush(); release(response(status(1))); await f.flush();
    assert.equal(f.render().status.runtime_revision, 2); assert.equal(f.configCalls(), 1);
  });
});

test('size changes reselect only the owned generation and new geometry revision', async () => {
  await fixture(async f => {
    let revision = 1, switches = 0;
    globalThis.fetch = async (url, init) => {
      if (url === '/api/config') return response(config(revision));
      if (url.startsWith('/api/mobile/session')) return response({ session_id: 'paired', stream: { generation: 2 } });
      if (init.method === 'POST') { switches++; revision = 2; assert.equal(JSON.parse(init.body).generation, 2); return response(status(2)); }
      return response(revision === 1 ? { ...status(), ready: false, error: 'phone_dimensions_changed', pending_size: [1280, 720] } : status(2));
    };
    f.render(); await f.flush();
    assert.equal(switches, 1); assert.equal(f.render().status.runtime_revision, 2); assert.equal(f.render().pending, false);
  });
});

test('an expired status can reconnect via current identity but never a new generation', async () => {
  await fixture(async f => {
    let switches = 0;
    globalThis.fetch = async (url, init) => {
      if (url.startsWith('/api/mobile/session')) return response({ session_id: 'paired', stream: { generation: 3 } });
      if (init.method === 'POST') { switches++; return response(status()); }
      return response(status());
    };
    f.render(); await f.flush(); await f.render().reconnect();
    assert.equal(switches, 0, 'old desktop ownership cannot auto-join a replacement publisher');
  });
});

test('effect remount clears cancelled selection and its late reply cannot lock the new owner', async () => {
  await fixture(async f => {
    let release, posts = 0;
    globalThis.fetch = async (url, init) => {
      if (url === '/api/config') return response(config(2));
      if (init.method === 'POST' && ++posts === 1) return new Promise(resolve => { release = resolve; });
      if (init.method === 'POST') return response(status(2));
      return response(status(2));
    };
    f.render();
    const old = f.render().select('phone', { session_id: 'paired', stream: { generation: 2 } });
    assert.equal(f.render().pending, true);
    f.remount(); assert.equal(f.render().pending, false);
    assert.equal(await f.render().select('phone', { session_id: 'paired', stream: { generation: 2 } }), true);
    release(response(status(1))); await old; await f.flush();
    assert.equal(f.render().pending, false); assert.equal(f.render().status.runtime_revision, 2);
  });
});
