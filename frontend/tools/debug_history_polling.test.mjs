import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/lib/debugSessions.ts',import.meta.url),'utf8');
const module={};
new Function('require','exports',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(()=>({}),module);
const {mergeDebugHistory,debugHistoryPath}=module;
const previous={id:'session',conversation_id:'chat',history_version:'revision:session',messages:[{id:'old'}],diagrams:[{id:'diagram'}],error:'old error',phase:'waiting'};

test('compact session keeps history but never retains removed dynamic status',()=>{
  const next=mergeDebugHistory(previous,{id:'session',history_version:previous.history_version,history_unchanged:true,phase:'finished',current_target:false},'session');
  assert.equal(next.messages,previous.messages);assert.equal(next.diagrams,previous.diagrams);
  assert.equal(next.phase,'finished');assert.equal(next.current_target,false);assert.equal(next.error,undefined);
});
test('unchanged conversation keeps evidence and diagram references',()=>{
  const old={...previous,project_id:'project',evidence:[{id:'capture'}],check_ids:['case']};
  const next=mergeDebugHistory(old,{id:old.id,history_version:old.history_version,history_unchanged:true},'conversation');
  assert.equal(next.evidence,old.evidence);assert.equal(next.messages,old.messages);assert.equal(next.check_ids,old.check_ids);
});
test('different owner, version or missing cache never reuses history',()=>{
  for(const old of [null,{...previous,id:'other'},{...previous,history_version:'old'},{...previous,messages:undefined}])
    assert.throws(()=>mergeDebugHistory(old,{id:previous.id,history_version:previous.history_version,history_unchanged:true},'session'),/refresh_required/);
});
test('fresh response replaces history including an empty restarted round',()=>{
  const fresh={id:previous.id,history_version:'new',messages:[],diagrams:[]};
  assert.equal(mergeDebugHistory(previous,fresh,'session'),fresh);
  assert.deepEqual(mergeDebugHistory(previous,fresh,'session').messages,[]);
});
test('legacy server responses without validators still work',()=>{
  const legacy={id:previous.id,messages:[{id:'new'}]};
  assert.equal(mergeDebugHistory(previous,legacy,'session'),legacy);
  assert.equal(debugHistoryPath('debug/sessions',legacy),'debug/sessions');
});
test('validators append safely to existing query and are URL encoded',()=>{
  assert.equal(debugHistoryPath('debug/sessions',previous),'debug/sessions?history_version=revision%3Asession');
  assert.equal(debugHistoryPath('debug/conversations?project_id=a',previous),'debug/conversations?project_id=a&history_version=revision%3Asession');
  assert.match(source,/cachedSessions.clear\(\); activeSessionId = null; cachedConversation = null/);
});
