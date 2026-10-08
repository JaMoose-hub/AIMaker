import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/wiringEdit.ts', import.meta.url), 'utf8');
const moduleExports = {};
new Function('require', 'exports', ts.transpileModule(source, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS},
}).outputText)(name => {
  if (name === './maker') return {makerRequest() { throw Error('Tests must inject the request port'); }};
  throw Error(`Unexpected runtime import: ${name}`);
}, moduleExports);
const {prepareProjectWiringEdit} = moduleExports;
const snapshotPaths = ['pi/status', 'pi/component-tests', 'debug/trials', 'debug/sessions'];
const idle = () => ({
  'pi/status': {connected: false, busy: false, program: 'unknown', pid: null,
    component_test_id: null, invocation_id: null, version: null, execution: {jobs: []}},
  'pi/component-tests': {connected: false, test_busy: false, active: null, results: [], execution: {jobs: []}},
  'debug/trials': {active: null, results: []},
  'debug/sessions': {active: null},
});
const session = (overrides = {}) => ({id: 'check-old', status: 'paused', phase: 'backend_restarted',
  binding: {project_id: 'project'}, jobs: [], model_busy: false, ...overrides});
function fixture({before = idle(), after, stopResult = {id: 'check-old', status: 'stopped'}, fail} = {}) {
  const calls = [];
  let stopped = false;
  async function request(path, body) {
    calls.push({path, body});
    const failure = fail?.(path, body, stopped);
    if (failure) throw failure;
    if (body !== undefined) {
      assert.equal(path, 'debug/sessions/check-old/actions', 'only this project\'s session may be stopped');
      assert.ok(['stop', 'stop_idle_wiring_review'].includes(body.action), 'only explicit stop or safe idle-photo retirement');
      assert.equal(typeof body.request_id, 'string');
      assert.ok(body.request_id.length > 0);
      assert.equal(body.context, undefined, 'restored sessions may lack an editable context');
      stopped = true;
      return structuredClone(stopResult);
    }
    assert.ok(snapshotPaths.includes(path), `unexpected snapshot ${path}`);
    return structuredClone((stopped && after ? after : before)[path]);
  }
  return {request, calls, mutations: () => calls.filter(call => call.body !== undefined)};
}
const apiError = status => Object.assign(new Error(`HTTP ${status}`), {status});
const rejects = (action, code) => assert.rejects(action, error => error instanceof Error && error.message === code);

test('offline idle Pi can restart wiring without an AI session or any mutation', async () => {
  const f = fixture();
  assert.equal(await prepareProjectWiringEdit('project', f.request), true);
  assert.deepEqual(f.calls.map(call => call.path).sort(), [...snapshotPaths].sort());
  assert.deepEqual(f.mutations(), []);
});

test('whole-workflow Reset never stops an owned AI session or its queued physical work',async()=>{
  for(const queued of [false,true]) {
    const before=idle(),job={id:'owned-test',state:'running'};
    before['debug/sessions'].active=session({status:'running',jobs:queued?[job]:[]});
    if(queued)before['pi/status'].execution.jobs=[job];
    const f=fixture({before});
    await rejects(()=>prepareProjectWiringEdit('project',f.request,false),queued?'hardware_work_active':'other_debug_active');
    assert.deepEqual(f.mutations(),[]);
  }
});

test('whole-workflow Reset permits an idle snapshot without any hardware or AI writes',async()=>{
  const f=fixture();assert.equal(await prepareProjectWiringEdit('unassigned-project',f.request,false),true);
  assert.deepEqual(f.mutations(),[]);assert.equal(f.calls.length,4);
});

test('whole-workflow Reset retires only its idle photo review then verifies all work again',async()=>{
  for(const status of ['awaiting_capture','paused']) {
    const before=idle();before['debug/sessions'].active=session({purpose:'wiring_review',status,phase:'wiring_review'});
    const f=fixture({before,after:idle()});
    assert.equal(await prepareProjectWiringEdit('project',f.request,false),true);
    assert.equal(f.mutations().length,1);assert.equal(f.mutations()[0].body.action,'stop_idle_wiring_review');
    assert.equal(f.calls.length,9);
  }
});

test('Reset cannot retire a busy photo review, a foreign check or a hardware reservation',async()=>{
  for(const [change,code] of [
    [before=>{before['debug/sessions'].active.model_busy=true;},'other_debug_active'],
    [before=>{before['debug/sessions'].active.wiring_review={status:'analysing'};},'other_debug_active'],
    [before=>{before['debug/sessions'].active.binding.project_id='other-project';},'other_debug_active'],
    [before=>{before['pi/component-tests'].results=[{reserved:true}];},'hardware_work_active'],
    [before=>{before['pi/status'].program='running';},'hardware_work_active'],
  ]) {
    const before=idle();before['debug/sessions'].active=session({purpose:'wiring_review',status:'awaiting_capture',phase:'wiring_review'});change(before);
    const f=fixture({before});await rejects(()=>prepareProjectWiringEdit('project',f.request,false),code);
    assert.deepEqual(f.mutations(),[]);
  }
});

test('all four current snapshots start together before any one completes', async () => {
  const reads = new Map();
  const done = prepareProjectWiringEdit('project', (path, body) => {
    assert.equal(body, undefined);
    return new Promise(resolve => reads.set(path, resolve));
  });
  await Promise.resolve();
  assert.deepEqual([...reads.keys()].sort(), [...snapshotPaths].sort());
  const snapshots = idle();
  for (const [path, resolve] of reads) resolve(snapshots[path]);
  assert.equal(await done, true);
});

test('old terminal AI records and completed job history do not require another stop', async () => {
  for (const status of ['stopped', 'complete', 'error']) {
    const before = idle();
    before['debug/sessions'].active = session({status});
    before['pi/status'].execution.jobs = ['finished', 'failed', 'cancelled'].map((state, index) => ({id: `job-${index}`, state}));
    before['pi/component-tests'].results = [{id: 'old-test', outcome: 'passed', reserved: false}];
    before['debug/trials'].results = [{id: 'old-trial', outcome: 'failed', reserved: false}];
    const f = fixture({before});
    assert.equal(await prepareProjectWiringEdit('project', f.request), true, status);
    assert.deepEqual(f.mutations(), []);
  }
});

test('own recovered AI is stopped using the legacy action then all snapshots are reread', async () => {
  for (const status of ['stopped', 'complete']) {
    const before = idle();
    before['debug/sessions'].active = session();
    const f = fixture({before, after: idle(), stopResult: {id: 'check-old', status}});
    assert.equal(await prepareProjectWiringEdit('project', f.request), true);
    assert.equal(f.mutations().length, 1);
    const stopIndex = f.calls.findIndex(call => call.body !== undefined);
    assert.deepEqual(f.calls.slice(0, stopIndex).map(call => call.path).sort(), [...snapshotPaths].sort());
    assert.deepEqual(f.calls.slice(stopIndex + 1).map(call => call.path).sort(), [...snapshotPaths].sort());
  }
});

test('own live model work must stop before the locally idle Pi may be edited', async () => {
  const before = idle();
  before['debug/sessions'].active = session({status: 'diagnosing', phase: 'environment', model_busy: true});
  const f = fixture({before, after: idle()});
  assert.equal(await prepareProjectWiringEdit('project', f.request), true);
  assert.equal(f.mutations().length, 1);
});

test('only owned queued or running work may be reconciled through the AI stop', async () => {
  for (const state of ['queued', 'running']) {
    const before = idle();
    const job = {id: 'owned-job', state};
    before['debug/sessions'].active = session({status: 'testing', jobs: [job]});
    before['pi/status'].execution.jobs = [job];
    before['pi/component-tests'].active = {id: 'owned-test', reserved: true};
    const f = fixture({before, after: idle()});
    assert.equal(await prepareProjectWiringEdit('project', f.request), true);
    assert.equal(f.mutations().length, 1);
  }
});

test('foreign paused AI with no live work does not block or receive a stop action', async () => {
  const before = idle();
  before['debug/sessions'].active = session({binding: {project_id: 'other-project'}});
  const f = fixture({before});
  assert.equal(await prepareProjectWiringEdit('project', f.request), true);
  assert.deepEqual(f.mutations(), []);
});

test('foreign live AI and a foreign busy model block without stopping somebody else\'s session', async () => {
  for (const overrides of [
    {status: 'diagnosing', phase: 'environment'},
    {status: 'awaiting_capture', phase: 'awaiting_user'},
    {status: 'awaiting_ready', phase: 'prepare_near'},
    {status: 'testing', phase: 'sampling_near'},
    {status: 'paused', model_busy: true},
  ]) {
    const before = idle();
    before['debug/sessions'].active = session({...overrides, binding: {project_id: 'other-project'}});
    const f = fixture({before});
    await rejects(() => prepareProjectWiringEdit('project', f.request), 'other_debug_active');
    assert.deepEqual(f.mutations(), []);
  }
});

test('real pending jobs, test or trial reservations, and remote program evidence block an idle-looking session', async () => {
  const variants = [
    ...['queued', 'preflight', 'awaiting_confirmation', 'stopping', 'blocked', 'running'].map(state => snapshots => {
      snapshots['pi/status'].execution.jobs = [{id: 'pending-job', state}];
    }),
    snapshots => {snapshots['pi/component-tests'].active = {id: 'test', reserved: true};},
    snapshots => {snapshots['pi/component-tests'].results = [{id: 'reserved-test', reserved: true}];},
    snapshots => {snapshots['pi/component-tests'].test_busy = true;},
    snapshots => {snapshots['pi/component-tests'].execution.jobs = [{id: 'queued-test', state: 'queued'}];},
    snapshots => {snapshots['debug/trials'].active = {id: 'trial', reserved: true};},
    snapshots => {snapshots['debug/trials'].results = [{id: 'reserved-trial', reserved: true}];},
    snapshots => {snapshots['pi/status'].busy = true;},
    snapshots => {snapshots['pi/status'].component_test_id = 'reserved-test';},
    snapshots => {snapshots['pi/status'].pid = 1234;},
    ...['running', 'starting', 'stopping', 'reconnecting'].map(program => snapshots => {snapshots['pi/status'].program = program;}),
    snapshots => {snapshots['pi/status'].invocation_id = 'unknown-prior-invocation';},
    snapshots => {snapshots['pi/status'].version = {run_id: 'old-run', code_hash: 'old-hash'};},
  ];
  for (const [index, change] of variants.entries()) {
    const before = idle(); change(before);
    const f = fixture({before});
    await rejects(() => prepareProjectWiringEdit('project', f.request), 'hardware_work_active');
    assert.deepEqual(f.mutations(), [], `case ${index} must not stop unrelated hardware`);
  }
});

test('a stopped AI response never substitutes for checking remaining reservations and newly queued work', async () => {
  for (const change of [
    snapshots => {snapshots['pi/component-tests'].results = [{id: 'leftover', reserved: true}];},
    snapshots => {snapshots['debug/trials'].active = {id: 'leftover-trial', reserved: true};},
    snapshots => {snapshots['pi/status'].execution.jobs = [{id: 'new-other-work', state: 'queued'}];},
  ]) {
    const before = idle(); before['debug/sessions'].active = session();
    const after = idle(); change(after);
    const f = fixture({before, after});
    await rejects(() => prepareProjectWiringEdit('project', f.request), 'hardware_work_active');
    assert.equal(f.mutations().length, 1);
  }
});

test('unconfirmed AI stop cannot reset wiring even when the first hardware snapshot is idle', async () => {
  for (const stopResult of [{id: 'check-old', status: 'paused'}, {id: 'check-old', status: 'error'},
    {id: 'check-old', status: 'awaiting_capture'}, {id: 'other-check', status: 'stopped'}, {}]) {
    const before = idle(); before['debug/sessions'].active = session();
    const f = fixture({before, after: idle(), stopResult});
    await rejects(() => prepareProjectWiringEdit('project', f.request), 'ai_stop_unconfirmed');
    assert.equal(f.mutations().length, 1);
  }
});

test('incomplete snapshot responses cannot be mistaken for an idle device', async () => {
  for (const change of [
    snapshots => {delete snapshots['pi/status'].execution;},
    snapshots => {delete snapshots['pi/component-tests'].results;},
    snapshots => {delete snapshots['debug/trials'].results;},
  ]) {
    const before = idle(); change(before);
    const f = fixture({before});
    await rejects(() => prepareProjectWiringEdit('project', f.request), 'wiring_state_unavailable');
    assert.deepEqual(f.mutations(), []);
  }
});

test('incompatible snapshot or stop APIs report a backend update instead of pretending hardware is active', async () => {
  for (const status of [404, 405, 422]) {
    for (const failedPath of [...snapshotPaths, 'debug/sessions/check-old/actions']) {
      const before = idle(); before['debug/sessions'].active = session();
      const f = fixture({before, fail: path => path === failedPath ? apiError(status) : undefined});
      await rejects(() => prepareProjectWiringEdit('project', f.request), 'wiring_backend_restart_required');
      if (failedPath !== 'debug/sessions/check-old/actions') assert.deepEqual(f.mutations(), []);
    }
  }
});

test('snapshot network failures and post-stop verification failures keep wiring unchanged', async () => {
  for (const postStop of [false, true]) {
    for (const failure of [new Error('Failed to fetch'), apiError(500)]) {
      const before = idle(); before['debug/sessions'].active = session();
      const f = fixture({before, after: idle(), fail: (path, _body, stopped) =>
        path === 'debug/trials' && stopped === postStop ? failure : undefined});
      await rejects(() => prepareProjectWiringEdit('project', f.request), 'wiring_state_unavailable');
      assert.equal(f.mutations().length, postStop ? 1 : 0);
    }
  }
});
