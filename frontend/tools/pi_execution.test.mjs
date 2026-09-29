import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const url = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
function compile(path, replacements={}) {
  let js = ts.transpileModule(readFileSync(new URL(`../src/${path}`,import.meta.url),'utf8'),
    {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  for(const [key,value] of Object.entries({react:import.meta.resolve('react'),'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),...replacements}))
    js=js.replaceAll(JSON.stringify(key),JSON.stringify(value));
  return url(js);
}
const apiUrl=compile('lib/piApi.ts'), api=await import(apiUrl);
const textUrl=url('export const useMakerText=()=> (zh,en)=>zh;');
const localeUrl=url('export const useI18n=()=>({t:key=>key});');
async function render(name, status, props={}, connection={}) {
  const context=url(`export const usePiConnection=()=>({...${JSON.stringify({status,pending:false,networkError:false,error:null,...connection})},connect(){},action(){},perform(){}});`);
  const module=await import(compile(`components/${name}.tsx`,{'../lib/piApi':apiUrl,'../lib/PiConnection':context,
    '../lib/useMaker':textUrl,'../lib/i18n':localeUrl,'../lib/wiringGuideProfiles':url('export const piPhotoresistorExample=()=>"print(1)";')}));
  return renderToStaticMarkup(createElement(module[name],props));
}
const status={connected:true,busy:false,component_test_id:null,program:'running',logs:[],execution:{jobs:[],policy:'confirm_then_fifo'}};
const job={id:'job',kind:'deploy',label:'作品部署',state:'queued',owner:null,error:null};

test('Pi connection lives next to the model selector, not in deployment panel',async()=>{
  const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.match(app,/<MakerModelMenu[\s\S]{0,250}<PiConnectionControl/);
  const top=await render('PiConnectionControl',status), panel=await render('PiDeployPanel',status);
  assert.equal((top.match(/pi-global-connect/g)||[]).length,1);
  assert.ok(!panel.includes('pi-connect-button'));
  assert.ok(panel.includes('deploy-code-card') && panel.includes('deploy-output'));
  const offline=await render('PiDeployPanel',{...status,connected:false});
  assert.ok(offline.includes('先連線 Pi，才能部署程式'));
});

test('deployment keeps the editor on the left and output on the right',async()=>{
  const html=await render('PiDeployPanel',status,{draft:'print("preserve this draft")',onDebug(){}});
  assert.ok(html.indexOf('class="pi-deploy-button deploy-code-deploy"') < html.indexOf('id="pi-python-code"'));
  assert.match(html,/class="deploy-primary-column"/);
  assert.match(html,/class="deploy-results-column"/);
  assert.ok(html.indexOf('id="pi-python-code"') < html.indexOf('class="deploy-results-column"'));
  assert.match(html,/<textarea[^>]+id="pi-python-code"[\s\S]*preserve this draft/);
  assert.match(html,/沒有反應？幫我檢查/);
  assert.doesNotMatch(html,/功能通過|整合驗證通過/);
});

test('empty deployment view has no duplicate Pi connection card or badge',async()=>{
  for(const candidate of [null,
    {...status,connected:false,program:'unknown',deployment:'idle'},
    {...status,program:'not_deployed',deployment:'idle'},
    {...status,connected:false,program:'unknown',deployment:'idle',connection_error:'Connection refused'}]) {
    const html=await render('PiDeployPanel',candidate,{onDebug(){}});
    assert.doesNotMatch(html,/class="deploy-live|class="pi-connection|Pi 目前的狀態|還沒連上 Pi/);
    assert.match(html,/class="deploy-code-card workflow-surface"/);
    assert.match(html,/class="deploy-output workflow-surface"/);
  }
  const css=readFileSync(new URL('../src/debug.css',import.meta.url),'utf8');
  assert.match(css,/\.deploy-workspace\s*\{[^}]*grid-template-columns:minmax\(0,1\.05fr\) minmax\(0,\.95fr\)/);
});

test('program activity and diagnostic access survive connection loss without claiming it stopped',async()=>{
  for(const [candidate,connection] of [
    [{...status,connected:false},{}],
    [status,{networkError:true}],
    [{...status,connected:false,program:'unknown',version:{run_id:'run-one',code_hash:'abc123'},logs:['last output']},{}],
  ]) {
    const html=await render('PiDeployPanel',candidate,{onDebug(){}},connection);
    assert.match(html,/輸出結果/);
    assert.match(html,/Pi 狀態待確認/);
    assert.match(html,/暫時無法更新狀態；恢復連線後會重新核對/);
    assert.match(html,/沒有反應？幫我檢查/);
    assert.doesNotMatch(html,/程式執行中|pi\.program\.stopped/);
    assert.match(html,/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  }
  for(const candidate of [
    {...status,program:'unknown',deployment:'uploading'},
    {...status,program:'unknown',deployment:'idle',execution:{jobs:[job]}},
    {...status,program:'stopped',deployment:'succeeded'},
  ]) assert.match(await render('PiDeployPanel',candidate,{onDebug(){}}),/class="deploy-output workflow-surface"/);
});

test('deployment blockers remain enforced in the friendly launch view',async()=>{
  for(const candidate of [{...status,connected:false},{...status,execution:undefined}]) {
    assert.match(await render('PiDeployPanel',candidate),/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  }
  assert.match(await render('PiDeployPanel',status,{draft:'   '}),/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  const blocked={title:'Check power',component_ids:[],unresolved:['Confirm voltage'],requirements:{imports:[],devices:[]},code:'print(1)'};
  const html=await render('PiDeployPanel',status,{project:blocked});
  assert.match(html,/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  assert.match(html,/Confirm voltage/);
});

test('runtime failure keeps error, version and logs together in output without inventing hardware success',async()=>{
  const html=await render('PiDeployPanel',{...status,program:'failed',deployment:'failed',exit_code:1,error:'RuntimeError: test failure',version:{code_hash:'abc123',run_id:'run-one'},logs:['test log']});
  assert.match(html,/需要檢查/);
  const details=html.slice(html.indexOf('<section class="deploy-output workflow-surface"'));
  assert.match(details,/RuntimeError: test failure/);
  assert.match(details,/abc123/);
  assert.match(details,/test log/);
  assert.doesNotMatch(html.slice(0,html.indexOf('<section class="deploy-output workflow-surface"')),/RuntimeError: test failure/);
  assert.doesNotMatch(html,/功能通過|整合驗證通過/);
});

test('handoff names next task and requires explicit confirmation; blocked is not running',async()=>{
  const html=await render('PiConnectionControl',{...status,component_test_id:'run',execution:{jobs:[{...job,state:'awaiting_confirmation',owner:'test:run'}]}});
  for(const text of ['作品部署','等待交接確認','確認停止目前程式，接著執行','取消排隊','一次執行一個']) assert.ok(html.includes(text));
  assert.ok(html.includes('open=""'));
  const blocked=await render('PiConnectionControl',{...status,execution:{jobs:[{...job,state:'blocked',error:'offline'}]}});
  assert.ok(blocked.includes('等待連線／核對') && blocked.includes('offline'));
  assert.ok(!blocked.includes('確認停止目前程式，接著執行'));
});

test('active test permits queueing deployment; duplicate queued deployment is disabled',async()=>{
  const available=await render('PiDeployPanel',{...status,component_test_id:'run'});
  assert.match(available,/class="pi-deploy-button deploy-code-deploy">/);
  const queued=await render('PiDeployPanel',{...status,execution:{jobs:[job]}});
  assert.match(queued,/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  assert.ok(queued.includes('已加入佇列'));
});

test('old backend cannot bypass FIFO, connection status polling is centralized',async()=>{
  const old=await render('PiDeployPanel',{...status,execution:undefined});
  assert.match(old,/class="pi-deploy-button deploy-code-deploy" disabled=""/);
  assert.ok(old.includes('重新啟動 Tinkro'));
  const panel=readFileSync(new URL('../src/components/PiDeployPanel.tsx',import.meta.url),'utf8');
  assert.ok(!panel.includes('fetchPiStatus') && !panel.includes('connectPi'));
  const connection=readFileSync(new URL('../src/lib/PiConnection.tsx',import.meta.url),'utf8');
  assert.ok(connection.includes('controller.abort()') && connection.includes('version === epoch.current'));
  const css=readFileSync(new URL('../src/maker.css',import.meta.url),'utf8');
  assert.match(css,/\.pi-global-control[^}]+flex: 0 0 220px/);
  assert.match(css,/\.pi-execution-popover[^}]+position: absolute/);
});

test('deploy preserves request id and code; conflicts expose actionable reason without retry',async()=>{
  const original=globalThis.fetch, calls=[];
  globalThis.fetch=async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({ok:true,status})};};
  try {
    await api.deployPi('print(10)',undefined,'fixed-id');
    assert.deepEqual(JSON.parse(calls[0].options.body),{code:'print(10)',request_id:'fixed-id'});
    globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({detail:'handoff_changed'})});
    await assert.rejects(api.executionAction('job','confirm','test:old'),/handoff_changed/);
    assert.equal(calls.length,1);
  } finally {globalThis.fetch=original;}
});
