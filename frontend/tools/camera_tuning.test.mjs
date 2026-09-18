import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transpileModule, ModuleKind, ScriptTarget} from 'typescript';

const code = readFileSync(new URL('../src/lib/cameraTuning.ts', import.meta.url), 'utf8');
const output = transpileModule(code, {compilerOptions: {module: ModuleKind.ESNext, target: ScriptTarget.ES2022}}).outputText;
const {tuningMessage, requestCameraTuning} = await import('data:text/javascript;base64,' + Buffer.from(output).toString('base64'));
const base = {available: true, busy: false, can_restore: false, state: 'idle', progress: 0, reason: null, saved: false};

test('one-button states distinguish image improvement, no change, and failed restoration', () => {
  assert.equal(tuningMessage(null, null), 'loading');
  assert.equal(tuningMessage(base, null), 'ready');
  for (const state of ['improved','restored','cancelled']) assert.equal(tuningMessage({...base,state}, null), state);
  assert.equal(tuningMessage({...base, reason:'restore_failed'}, null), 'restore_failed');
  assert.equal(tuningMessage({...base, state:'unchanged', reason:'no_improvement'}, null), 'no_improvement');
  assert.equal(tuningMessage({...base, busy:true}, null), 'adjusting');
  assert.equal(tuningMessage({...base, available:false}, null), 'unsupported');
  assert.equal(tuningMessage(base, '<script>untrusted error</script>'), 'control_failed');
});

test('all user-facing states have both languages', () => {
  for(const locale of ['zh-TW','en']) {
    const strings = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`,import.meta.url),'utf8'));
    for(const name of ['ready','loading','improved','restored','cancelled','unsupported','busy','no_restore',
      'needs_light','no_improvement','moving','no_frames','camera_changed','timeout','control_failed','restore_failed','network']) {
      assert.ok(strings[`cameraTune.${name}`],`${locale}: ${name}`);
    }
  }
});

test('request helper uses explicit actions and reports rejection instead of success', async () => {
  const oldWindow=globalThis.window, oldFetch=globalThis.fetch;
  globalThis.window={setTimeout,clearTimeout};
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,...options});return {ok:true,json:async()=>base};};
  try {
    await requestCameraTuning('POST');
    await requestCameraTuning('POST',true);
    await requestCameraTuning('DELETE');
    assert.deepEqual(calls.map(c=>[c.url,c.method]),[
      ['/api/camera/auto-tune','POST'],['/api/camera/auto-tune/restore','POST'],['/api/camera/auto-tune','DELETE']]);
    assert.ok(calls.every(c=>c.signal instanceof AbortSignal));
    globalThis.fetch=async()=>({ok:true,json:async()=>({ok:false,reason:'busy'})});
    await assert.rejects(requestCameraTuning('POST'),/busy/);
  } finally {globalThis.window=oldWindow;globalThis.fetch=oldFetch;}
});
