import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import ts from 'typescript';

// Run the real hook with controlled effect lifecycles and API responses.
// No production storage, cloud requests, camera or Pi operations are used.
const code = ts.transpileModule(readFileSync(new URL('../src/lib/debugSessions.ts', import.meta.url), 'utf8'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
}).outputText;
const key = project => `boardvision.ai-debug-session.v1:${encodeURIComponent(project)}`;
const context = project => ({project:{id:project},code:'synthetic draft',test_keys:{},entry:{}});
const session = (id, project, status = 'stopped') => ({id,status,phase:status,
  binding:{project_id:project},conversation_id:`conversation-${project}`,current_target:true,
  capture_task:null,observations:[],evidence:[],jobs:[],updated_at:1});
const history = project => ({id:`conversation-${project}`,project_id:project,messages:[],check_ids:[]});

function harness(request, stored = {}, initialProject = 'current') {
  const slots = [], effects = [], calls = [], storageWrites = [];
  const storage = new Map(Object.entries(stored));
  const timers = new Map(); let nextTimer = 0, cursor = 0, dirty = true, project = initialProject, value;
  const window = {
    localStorage:{getItem:id=>storage.get(id)??null,
      setItem(id,value){storageWrites.push(['save',id,value]);storage.set(id,value);},
      removeItem(id){storageWrites.push(['forget',id]);storage.delete(id);}},
    addEventListener(){},removeEventListener(){},
    setTimeout(callback){timers.set(++nextTimer,callback);return nextTimer;},
    clearTimeout(id){timers.delete(id);},
  };
  const react = {
    useState(initial){
      const index = cursor++;
      if(!slots[index])slots[index]={value:typeof initial==='function'?initial():initial};
      return [slots[index].value,next=>{
        const resolved=typeof next==='function'?next(slots[index].value):next;
        if(!Object.is(slots[index].value,resolved)){slots[index].value=resolved;dirty=true;}
      }];
    },
    useRef(initial){const index=cursor++;return (slots[index]??={current:initial});},
    useEffect(callback,deps){
      const index=cursor++, previous=slots[index];
      if(!previous||deps.some((dep,i)=>!Object.is(dep,previous.deps[i]))) {
        const effect={deps,cleanup:previous?.cleanup};slots[index]=effect;
        effects.push(()=>{effect.cleanup?.();effect.cleanup=callback();});
      }
    },
  };
  const exports = {};
  new Function('require','exports','window','crypto',code)(name=>name==='react'?react:{
    async makerRequest(path,body,signal){calls.push({path,body});return request(path,body,signal);},
  },exports,window,{randomUUID});
  function render(){
    for(let count=0;dirty;count++) {
      assert.ok(count<20,'hook renders must settle');dirty=false;cursor=0;
      value=exports.useDebugSession(project,true);
      for(const effect of effects.splice(0))effect();
    }
  }
  async function settle(){for(let i=0;i<30;i++){await Promise.resolve();render();}}
  render();
  return {get value(){render();return value;},calls,storage,storageWrites,settle,
    async switchProject(next){project=next;dirty=true;render();await settle();},
    async tick(){for(const [id,callback] of [...timers]){timers.delete(id);callback();}await settle();},
    dispose(){for(const slot of slots)slot?.cleanup?.();timers.clear();}};
}

function api({saved={},active=null,conversation=null,create}={}) {
  return (path,body)=>{
    if(path==='debug/sessions')return body?create?.(body)??session('new','current','diagnosing'):{active};
    if(path.startsWith('debug/conversations?'))return {conversation};
    if(path.startsWith('debug/sessions/')&&!body) {
      const result=saved[path.slice('debug/sessions/'.length)];
      if(result)return result;
      throw Object.assign(new Error('session_not_found'),{status:404});
    }
    throw new Error(`Unexpected API operation: ${path}`);
  };
}

test('real polling loop reuses exact history while status and new messages update',async()=>{
  let version='v1',phase='waiting';
  const request=path=>{
    const url=new URL(path,'http://test/');
    if(url.pathname==='/debug/sessions')return {active:null};
    const isHistory=url.pathname==='debug/conversations' || url.pathname==='/debug/conversations';
    const full=isHistory?{...history('current'),messages:[{id:version}],diagrams:[{id:'drawing'}],history_version:version}
      :{...session('saved','current'),phase,messages:[{id:version}],diagrams:[{id:'drawing'}],history_version:version};
    let value=full;
    if(url.searchParams.get('history_version')===version){
      value=isHistory?{id:full.id,project_id:'current',history_version:version,history_unchanged:true}
        :{...full,messages:undefined,diagrams:undefined,history_unchanged:true};
    }
    return isHistory?{conversation:value}:value;
  };
  const h=harness(request,{'boardvision.ai-debug-session.v1:current':'saved'});
  try {
    await h.settle();const first=h.value.record.messages;
    phase='finished';await h.tick();
    assert.equal(h.value.record.phase,'finished');assert.equal(h.value.record.messages,first);
    assert(h.calls.some(call=>call.path.includes('history_version=v1')));
    version='v2';await h.tick();
    assert.equal(h.value.record.messages[0].id,'v2');assert.equal(h.value.conversation.messages[0].id,'v2');
  } finally {h.dispose();}
});

test('invalid compact response discards validators and recovers with a full read',async()=>{
  let malformed=false;
  const request=path=>{
    if(path.startsWith('debug/conversations?'))return {conversation:{...history('current'),history_version:'v1'}};
    if(path.split('?')[0]==='debug/sessions')return {active:null};
    if(malformed && path.includes('history_version='))return {id:'foreign',history_version:'v1',history_unchanged:true};
    return {...session('saved','current'),messages:[],history_version:'v1'};
  };
  const h=harness(request,{'boardvision.ai-debug-session.v1:current':'saved'});
  try {
    await h.settle();malformed=true;await h.tick();
    assert.match(h.value.error,/refresh_required/);
    await h.tick();assert.equal(h.value.record.id,'saved');assert.equal(h.value.error,'');
    assert.equal(h.calls.filter(call=>call.path.startsWith('debug/sessions/')).at(-1).path,'debug/sessions/saved');
  } finally {h.dispose();}
});

test('wiring restart clears own pointer and history, survives reload, and sends only an explicit reset',async()=>{
  const old=session('old','current'), foreign=session('foreign','other');
  let conversation={...history('current'),messages:[{id:'old-message',text:'old'}]};
  const request=(path,body)=>{
    if(path==='debug/conversations/restart') {
      assert.equal(body.project_id,'current');assert.equal(body.expected_conversation_id,'conversation-current');
      conversation={id:'fresh-round',project_id:'current',messages:[],check_ids:[],diagrams:[],evidence:[]};
      old.conversation_current=false;
      return {conversation};
    }
    return api({saved:{old},conversation})(path,body);
  };
  const h=harness(request,{[key('current')]:old.id,[key('other')]:foreign.id});
  try {
    await h.settle();assert.equal(h.value.conversation.messages.length,1);
    assert.equal(await h.value.restartConversation(),true);await h.settle();await h.tick();
    assert.equal(h.value.record,null);assert.equal(h.value.conversation.id,'fresh-round');
    assert.equal(h.value.resetVersion,1);assert.equal(h.storage.has(key('current')),false);
    assert.equal(h.storage.get(key('other')),foreign.id);
    assert.deepEqual(h.calls.filter(c=>c.body).map(c=>c.path),['debug/conversations/restart']);
    const reload=harness(request,Object.fromEntries(h.storage));
    try {await reload.settle();assert.deepEqual(reload.value.conversation.messages,[]);assert.equal(reload.value.record,null);}
    finally {reload.dispose();}
  } finally {h.dispose();}
});

test('failed reset retains chat and pointer; unknown-outcome retry uses the same request ID',async()=>{
  const old=session('old','current');let attempts=0;
  const conversation=history('current'), fresh={...conversation,id:'fresh'};
  const request=(path,body)=>{
    if(path==='debug/conversations/restart') {
      if(++attempts===1)throw new Error('connection_lost');
      old.conversation_current=false;return {conversation:fresh};
    }
    return api({saved:{old},conversation:attempts>1?fresh:conversation})(path,body);
  };
  const h=harness(request,{[key('current')]:old.id});
  try {
    await h.settle();await assert.rejects(h.value.restartConversation(),/connection_lost/);await h.settle();
    assert.equal(h.value.record.id,old.id);assert.equal(h.storage.get(key('current')),old.id);
    assert.equal(h.value.conversation.id,conversation.id);assert.equal(h.value.resetVersion,0);
    assert.equal(await h.value.restartConversation(),true);
    const resets=h.calls.filter(c=>c.body);assert.equal(resets[0].body.request_id,resets[1].body.request_id);
  } finally {h.dispose();}
});

test('late poll cannot restore the old conversation after a wiring restart',async()=>{
  const old=session('old','current');let resolvePoll, delayed=false;
  let conversation=history('current');
  const request=(path,body)=>{
    if(path==='debug/conversations/restart') {old.conversation_current=false;conversation={...conversation,id:'fresh'};return {conversation};}
    if(path.startsWith('debug/conversations?') && delayed)return new Promise(resolve=>{resolvePoll=resolve;});
    return api({saved:{old},conversation})(path,body);
  };
  const h=harness(request,{[key('current')]:old.id});
  try {
    await h.settle();delayed=true;await h.tick();assert.equal(typeof resolvePoll,'function');
    await h.value.restartConversation();delayed=false;
    resolvePoll({conversation:history('current')});await h.settle();
    assert.equal(h.value.conversation.id,'fresh');assert.equal(h.value.record,null);
    assert.equal(h.storage.has(key('current')),false);
  } finally {h.dispose();}
});

test('project switch rejects a late reset and does not clear the new project pointer',async()=>{
  let finish;
  const h=harness((path,body)=>{
    if(body)return new Promise(resolve=>{finish=resolve;});
    if(path==='debug/sessions')return {active:null};
    if(path.startsWith('debug/conversations?'))return {conversation:history(decodeURIComponent(path.split('=')[1]))};
    throw Error(path);
  },{[key('next')]:'next-old'});
  try {
    await h.settle();const pending=h.value.restartConversation();await h.switchProject('next');
    finish({conversation:{...history('current'),id:'fresh'}});assert.equal(await pending,false);
    await h.settle();assert.equal(h.storage.get(key('next')),'next-old');assert.equal(h.value.resetVersion,0);
    assert.equal(h.storageWrites.length,0);
  } finally {h.dispose();}
});

test('a wrongly saved foreign stopped check is detached, not reused or deleted',async()=>{
  const old=session('old-foreign','other');
  const h=harness(api({saved:{'old-foreign':old}}),{[key('current')]:old.id,[key('other')]:old.id});
  try {
    await h.settle();
    assert.equal(h.value.record,null,'foreign stopped history is not the current check');
    assert.equal(h.storage.has(key('current')),false,'only the wrong local pointer is removed');
    assert.equal(h.storage.get(key('other')),old.id,'the owning project keeps its pointer');
    await h.value.create(context('current'),'現在這接法要怎麼接？','synthetic-model','low','fast',{purpose:'wiring_review'});
    const posts=h.calls.filter(call=>call.body);
    assert.equal(posts.length,1,'no automatic retry, stop, capture or deletion');
    assert.equal(posts[0].body.context.project.id,'current');
    assert.equal('conversation_id' in posts[0].body,false);
    assert.equal(posts[0].body.purpose,'wiring_review');
    assert.equal(old.conversation_id,'conversation-other');
  } finally {h.dispose();}
});

test('same-project conversation and legacy check conversation are reused',async()=>{
  for(const conversation of [history('current'),null]) {
    const own=session('own','current');
    const h=harness(api({saved:{own},conversation}),{[key('current')]:own.id});
    try {
      await h.settle();await h.value.create(context('current'),'接哪一腳？','synthetic-model','low');
      assert.equal(h.calls.find(call=>call.body).body.conversation_id,'conversation-current');
    } finally {h.dispose();}
  }
});

test('global live work from another project remains stoppable but is never saved as local history',async()=>{
  const foreign=session('foreign-live','other','awaiting_ready');
  const request=api({active:foreign});
  const h=harness((path,body,signal)=>body?.action==='stop'?{...foreign,status:'stopped'}:request(path,body,signal));
  try {
    await h.settle();
    assert.equal(h.value.record.id,foreign.id);
    assert.equal(h.storage.has(key('current')),false);
    assert.equal(h.calls.some(call=>call.body),false,'surfacing another project cannot operate hardware');
    await h.value.action('stop');
    assert.equal(h.calls.filter(call=>call.body).length,1);
    assert.equal(h.calls.at(-1).body.action,'stop','explicit stop is still allowed');
    assert.equal(h.storage.has(key('current')),false);
    await h.value.create(context('current'),'回到目前作品問接法','synthetic-model','low');
    assert.equal('conversation_id' in h.calls.at(-1).body,false,
      'the stopped foreign record cannot become the fallback for a new check');
    assert.equal(h.calls.filter(call=>call.body).length,2,'only explicit stop and explicit send are posted');
  } finally {h.dispose();}
});

test('own saved history is retained while foreign live work is surfaced',async()=>{
  const own=session('own','current'), foreign=session('foreign-live','other','awaiting_ready');
  const conversation=history('current');
  const h=harness(api({saved:{own},active:foreign,conversation}),{[key('current')]:own.id});
  try {
    await h.settle();await h.tick();
    assert.equal(h.value.record.id,foreign.id);
    assert.equal(h.value.conversation.id,conversation.id);
    assert.equal(h.storage.get(key('current')),own.id);
    assert.deepEqual(h.storageWrites,[],'foreign work cannot replace the saved own check');
  } finally {h.dispose();}
});

test('foreign conversation responses and unbound legacy checks never become a conversation fallback',async()=>{
  for(const saved of [{...session('unbound','current'),binding:undefined},session('own','current')]) {
    const h=harness(api({saved:{[saved.id]:saved},conversation:history('other')}),{[key('current')]:saved.id});
    try {
      await h.settle();
      assert.equal(h.value.conversation,null);
      await h.value.create(context('current'),'接法問題','synthetic-model','low');
      assert.equal(h.calls.find(call=>call.body).body.conversation_id,saved.binding?'conversation-current':undefined);
    } finally {h.dispose();}
  }
});

test('a mismatched draft context cannot start a check for another project',async()=>{
  const h=harness(api());
  try {
    await h.settle();
    assert.equal(await h.value.create(context('other'),'錯誤作品','synthetic-model','low'),undefined);
    assert.equal(h.calls.some(call=>call.body),false);
  } finally {h.dispose();}
});

test('a project switch rejects a late create result and keeps the new project conversation',async()=>{
  let finish;
  const created=new Promise(resolve=>{finish=resolve;});
  const h=harness((path,body)=>{
    if(body)return created;
    if(path==='debug/sessions')return {active:null};
    if(path.startsWith('debug/conversations?'))return {conversation:history(decodeURIComponent(path.split('=')[1]))};
    throw new Error(`Unexpected request ${path}`);
  });
  try {
    await h.settle();
    const pending=h.value.create(context('current'),'第一個作品','synthetic-model','low');
    await h.switchProject('next');
    finish(session('late','current','diagnosing'));await pending;await h.settle();await h.tick();
    assert.equal(h.value.record,null);
    assert.equal(h.value.conversation.project_id,'next');
    assert.deepEqual(h.storageWrites,[],'late responses cannot persist a foreign check');
    assert.equal(h.calls.filter(call=>call.body).length,1,'switching projects does not resubmit');
  } finally {h.dispose();}
});
