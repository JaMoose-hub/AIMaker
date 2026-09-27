import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const tree = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let refreshEffect;
function visit(node) {
  if (ts.isCallExpression(node) && node.expression.getText(tree) === 'useEffect'
      && node.arguments[0]?.getText(tree).includes('liveRuntime?.runtime_revision')) {
    refreshEffect = node.arguments[0];
  }
  ts.forEachChild(node, visit);
}
visit(tree);
assert.ok(refreshEffect, 'Runtime synchronization must observe Webcam events');
const js = ts.transpileModule(`const effect = ${refreshEffect.getText(tree)};`, {
  compilerOptions: {target: ts.ScriptTarget.ES2022},
}).outputText;
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness({local = 1, webcam = 2, eye = 1, fetchConfig} = {}) {
  const commits = [], requests = [], prepared = [];
  const bindings = {
    config: {runtime_revision: local}, liveRuntime: {runtime_revision: webcam},
    glasses: {status: {runtime_revision: eye}},
    fetchConfig: async () => { requests.push('config'); return fetchConfig ? fetchConfig() : {board_id: 'raspberry-pi-5', runtime_revision: webcam}; },
    fetchBoardProfile: async board => { requests.push(board); return {id: board}; },
    wsClient: {prepareRuntime: (...args) => prepared.push(args)},
    setConfig: value => commits.push(value), setProfile() {},
    window: {setTimeout, clearTimeout},
  };
  const run = new Function(...Object.keys(bindings), `${js}; return effect;`)(...Object.values(bindings));
  return {run, commits, requests, prepared};
}

test('Webcam runtime refreshes configuration even when Eye status has not changed', async () => {
  const h = harness();
  const cleanup = h.run();
  await flush();
  assert.equal(h.commits[0].runtime_revision, 2);
  assert.deepEqual(h.prepared, [['raspberry-pi-5', 2]]);
  cleanup();
});

test('Current Webcam revision does not repeatedly fetch because Eye is older', async () => {
  const h = harness({local: 2, webcam: 2, eye: 1});
  h.run();
  await flush();
  assert.deepEqual(h.requests, []);
});

test('An obsolete refresh cannot overwrite configuration after its effect is replaced', async () => {
  let resolve;
  const h = harness({fetchConfig: () => new Promise(done => { resolve = done; })});
  const cleanup = h.run();
  cleanup();
  resolve({board_id: 'raspberry-pi-5', runtime_revision: 2});
  await flush();
  assert.deepEqual(h.commits, []);
  assert.deepEqual(h.prepared, []);
});
