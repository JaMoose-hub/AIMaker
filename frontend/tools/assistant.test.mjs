import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as jsxRuntime from 'react/jsx-runtime';
import {maker, designFor} from './project_guide_fixture.mjs';

const code = ts.transpileModule(readFileSync(new URL('../src/lib/assistant.ts', import.meta.url), 'utf8'), {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS},
}).outputText;
const record = (kind='project') => ({id:kind==='demo'?'demo':'project', kind, project_id:'layout-fixture',
  messages:[],jobs:[],before:null,total:0,context_epoch:0,round:0,demo:null});
const historyCode = ts.transpileModule(readFileSync(new URL('../src/lib/assistantHistory.ts', import.meta.url), 'utf8'), {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS},
}).outputText;
const history = {};
new Function('exports', historyCode)(history);
function harness(request, {demo=null, guard=async()=>true, brokenStorage=false, persisted=new Map()}={}) {
  const values=[], refs=[], calls=[]; let index=0, ref=0;
  let state={...maker.initialMaker(), design:designFor(), prompt:'original draft', code:'manual code'};
  globalThis.localStorage={getItem:key=>persisted.get(key)??null, removeItem:key=>persisted.delete(key),
    setItem(key,value){if(brokenStorage)throw Error('quota');persisted.set(key,value);}};
  persisted.set('boardvision.assistant.v1','project');persisted.set('boardvision.assistant-demo.v1','demo');
  if(demo)persisted.set('boardvision.assistant-demo.v1.open','true');
  const react={...React,useEffect(){},useCallback:fn=>fn,useRef:initial=>refs[ref++]??={current:initial},
    useState(initial){const i=index++;if(!(i in values))values[i]=i===3?record():i===4?demo:typeof initial==='function'?initial():initial;
      return[values[i],next=>values[i]=typeof next==='function'?next(values[i]):next];}};
  const exports={};
  const modules={react,'./maker':{...maker,makerRequest:async(path,body)=>{calls.push({path,body});return request(path,body);}},
    './i18n':{useI18n:()=>({locale:'en'})},'./makerMigration':{MAKER_STORAGE:'boardvision.maker.v1'},
    './wiringEdit':{prepareProjectWiringEdit:guard},'./componentTests':{componentTestKey:()=> 'test-key'}};
  new Function('require','exports',code)(name=>modules[name],exports);
  const update=next=>{state=typeof next==='function'?next(state):next;};
  return {render(debugSession=null){index=0;ref=0;return exports.useAssistant(state,update,null,debugSession);},update,state:()=>state,calls,values,persisted,exports};
}
const deferred=()=>{let resolve,reject;const promise=new Promise((y,n)=>{resolve=y;reject=n;});return{promise,resolve,reject};};

test('accepted send clears only the submitted draft and freezes stage/version/code',async()=>{
  for(const newDraft of ['', 'new typed draft']) {
    const pending=deferred(),h=harness(()=>pending.promise);h.update(s=>({...s,stage:'deploy'}));
    const sent=h.render().send();
    assert.equal(h.calls.length,1);assert.equal(h.calls[0].body.stage,'deploy');
    assert.equal(h.calls[0].body.context.debug_context.code,'manual code');
    if(newDraft)h.render().setDraft(newDraft);
    h.update(s=>({...s,stage:'guide'}));
    pending.resolve(record());assert.equal(await sent,true);
    assert.equal(h.state().prompt,newDraft);assert.equal(h.state().stage,'guide');
    assert.equal(h.state().code,'manual code');
  }
});

test('mobile workspace publication follows stage, code, guide round, context and chosen model without conversation recursion',()=>{
  const h=harness(()=>record());
  const first=h.render().mobileContext;
  h.update(s=>({...s,stage:'guide',code:'changed code',aiModel:'chosen-model',aiEffort:'high',guide:{...s.guide,run:2}}));
  const second=h.render().mobileContext;
  assert.equal(second.conversation_id,'project');assert.equal(second.stage,'guide');assert.equal(second.round,2);
  assert.equal(second.context.debug_context.code,'changed code');assert.equal(second.design.model,'chosen-model');
  assert.notDeepEqual(second,first);
  assert.deepEqual(h.render().mobileContext,second,'An unrelated render must not invent a new workspace');
  h.render().setDraft('unfinished chat input');
  assert.deepEqual(h.render().mobileContext,second,'Editing the chat draft does not change the published workspace');
  h.render().acceptExternal({...record(),context_epoch:2});
  const cleared=h.render().mobileContext;
  assert.equal(cleared.context.assistant_context_epoch,2);
  assert.notDeepEqual(cleared,second,'Clearing conversation context republishes the workspace');
});

test('phone workspace excludes only the desktop debug session binding while desktop sends retain it',async()=>{
  const h=harness(()=>record());
  h.update(s=>({...s,stage:'guide',debug:{...s.debug,caseId:'case',image:{id:'evidence-image',frame_id:77},debug_session_id:'nested-evidence-reference'}}));
  const {assistantWorkspacePayload,assistantMobileWorkspacePayload}=h.exports;
  const first={id:'debug-A',status:'awaiting_capture'},second={id:'debug-B',status:'diagnosing'};
  const desktop=assistantWorkspacePayload(h.state(),'en',undefined,first);
  const phone=assistantMobileWorkspacePayload(h.state(),'en',undefined,first);
  const expected=structuredClone(desktop);delete expected.context.debug_session_id;
  assert.deepEqual(phone,expected,'Every field except the top-level desktop session binding is preserved');
  assert.equal(desktop.context.debug_session_id,'debug-A');
  assert.equal(phone.context.debug_context.entry.debug_session_id,'nested-evidence-reference');
  assert.deepEqual(phone.context.debug_context.entry.image,{id:'evidence-image',frame_id:77});
  assert.ok(phone.context.debug_context.wiring_target.wire_id);
  const published=h.render(first).mobileContext;
  for(const session of [second,{...first,status:'stopped'},{...first,status:'complete'},null]) {
    assert.deepEqual(h.render(session).mobileContext,published,'Starting, replacing or stopping debug does not republish the phone project');
    assert.deepEqual(assistantMobileWorkspacePayload(h.state(),'en',undefined,session),phone);
  }
  assert.equal(assistantWorkspacePayload(h.state(),'en',undefined,second).context.debug_session_id,'debug-B');
  assert.equal(assistantWorkspacePayload(h.state(),'en',undefined,{...first,status:'stopped'}).context.debug_session_id,null);
  await h.render(second).send('debug');
  assert.equal(h.calls[0].body.context.debug_session_id,'debug-B');
  assert.deepEqual(h.calls[0].body.context.debug_context,desktop.context.debug_context);
});

test('phone workspace still changes for actual guide round, revision, wiring target and cleared context',()=>{
  const h=harness(()=>record());const original=h.state(),first=h.render({id:'debug-A',status:'diagnosing'}).mobileContext;
  for(const change of [
    value=>({...value,guide:{...value.guide,run:1}}),
    value=>({...value,design:{...value.design,revision:value.design.revision+1}}),
    value=>({...value,guide:{...value.guide,index:value.guide.index+1}}),
  ]) {
    h.update(change(original));const next=h.render({id:'debug-B',status:'stopped'}).mobileContext;
    assert.notDeepEqual(next,first);
    assert.equal('debug_session_id' in next.context,false);
  }
  h.update(original);h.render().acceptExternal({...record(),context_epoch:1});
  const cleared=h.render().mobileContext;assert.equal(cleared.context.assistant_context_epoch,1);assert.notDeepEqual(cleared,first);
  const mobile=h.exports.assistantMobileWorkspacePayload;
  assert.notDeepEqual(mobile(original,'en',undefined,null,'wiring'),mobile(original,'en',undefined,null,'debug'));
});

test('failed delivery preserves text and the idempotency key survives a reload',async()=>{
  const h=harness(async()=>{throw Error('offline');});
  assert.equal(await h.render().send(),false);assert.equal(h.state().prompt,'original draft');
  const id=h.calls[0].body.request_id;
  const reloaded=harness(async()=>record(),{persisted:h.persisted});
  await reloaded.render().send();assert.equal(reloaded.calls[0].body.request_id,id);
  assert.equal(reloaded.state().prompt,'');
});

test('an unacknowledged text retry freezes its displayed photo and payload across new captures and reload',async()=>{
  const media=name=>({asset_ids:[name],capture_id:`capture-${name}`,epoch:0,round:0,
    attachments:[{asset_id:name,filename:`${name}.jpg`,image_url:`/${name}`} ]});
  const h=harness(async()=>{throw Error('offline');});
  h.render().acceptExternal({...record(),active_media:media('first')});
  assert.equal(await h.render().send(),false);
  const original=structuredClone(h.calls[0].body);
  assert.deepEqual(original.asset_ids,['first']);assert.equal(original.capture_id,'capture-first');assert.equal(original.inherit_media,false);
  h.render().acceptExternal({...record(),active_media:media('second')});
  assert.equal(h.render().mediaReference.attachments[0].filename,'first.jpg');
  assert.equal(await h.render().send(),false);assert.deepEqual(h.calls[1].body,original);
  const reloaded=harness(async()=>{throw Error('offline');},{persisted:h.persisted});
  reloaded.render().acceptExternal({...record(),active_media:media('second')});
  assert.equal(reloaded.render().mediaReference.capture_id,'capture-first');
  await reloaded.render().send();assert.deepEqual(reloaded.calls[0].body,original);
  reloaded.render().setDraft('A different follow-up');
  assert.equal(reloaded.render().mediaReference.capture_id,'capture-second');
  await reloaded.render().send();assert.notEqual(reloaded.calls[1].body.request_id,original.request_id);
  assert.deepEqual(reloaded.calls[1].body.asset_ids,['second']);
});

test('a text-only retry also freezes the absence of media when a photo arrives later',async()=>{
  const h=harness(async()=>{throw Error('offline');});
  await h.render().send();const first=structuredClone(h.calls[0].body);
  assert.equal(first.inherit_media,false);assert.equal(first.asset_ids,undefined);
  h.render().acceptExternal({...record(),active_media:{asset_ids:['later'],capture_id:'later-photo',epoch:0,round:0,attachments:[]}});
  assert.equal(h.render().mediaReference,null);
  await h.render().send();assert.deepEqual(h.calls[1].body,first);
});

test('legacy outboxes preserve their original no-media request fingerprint on retry',async()=>{
  const h=harness(async()=>{throw Error('offline');});await h.render().send();
  const saved=JSON.parse(h.persisted.get('boardvision.assistant.v1.outbox'));
  h.persisted.set('boardvision.assistant.v1.outbox',JSON.stringify({key:saved.key,id:saved.id}));
  const original={...h.calls[0].body};delete original.inherit_media;
  const reloaded=harness(async()=>record(),{persisted:h.persisted});
  await reloaded.render().send();assert.deepEqual(reloaded.calls[0].body,original);
});

test('double submit has one request, new project rejects a late result',async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);
  const first=h.render().send(),second=h.render().send();
  assert.equal(await second,false);assert.equal(h.calls.length,1);
  h.render().activateConversation({...record(),id:'new-project'});
  h.update(s=>({...s,design:null,prompt:'new project draft'}));
  pending.resolve({...record(),jobs:[{id:'job',status:'completed',version:{project_id:'layout-fixture',revision:1},result:designFor()}]});
  await first;assert.equal(h.state().design,null);assert.equal(h.state().candidate,null);
  assert.equal(h.state().prompt,'new project draft');
});

test('merge keeps loaded older history after polling, updates archive and context',()=>{
  const {mergeConversation}=harness(()=>record()).exports;
  const messages=Array.from({length:80},(_,i)=>({id:String(i),round:0,epoch:0,capability:'debug',text:String(i)}));
  const merged=mergeConversation({...record(),messages,before:null,total:80},{...record(),round:1,context_epoch:1,messages:messages.slice(30),before:30,total:80});
  assert.equal(merged.messages.length,80);assert.equal(merged.before,null);
  assert.equal(merged.context_epoch,1);assert.ok(merged.messages.every(m=>m.archived));
  const growing=mergeConversation({...record(),messages:messages.slice(0,49),total:49},
    {...record(),messages:messages.slice(10,60),total:60,before:10});
  assert.equal(growing.messages.length,60);assert.equal(growing.before,null);
});

test('Demo builtin confirmation is isolated and deduplicated; leaving does not cancel',async()=>{
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:null,checklist:{},state:'checklist_pending'}};
  const h=harness(async()=>({...demo,demo:{...demo.demo,confirmed_revision:1,result:designFor()}}),{demo});
  const before=h.state();await h.render().confirmDemo('builtin');
  assert.equal(h.calls[0].path,'assistant/conversations/demo/confirm');
  assert.equal(h.calls[0].body.generation,null);assert.equal(h.calls[0].body.mode,'builtin');
  const id=h.calls[0].body.request_id;await h.render().confirmDemo('builtin');assert.equal(h.calls[1].body.request_id,id);
  h.render().setDemoOpen(false);assert.equal(h.state(),before);assert.equal(h.calls.length,2);
});

test('adoption is guarded by active work, backup, confirmed revision and stale project',async()=>{
  const result=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:1,result,state:'result_pending'}};
  for(const reason of ['hardware','storage','revision','stale']) {
    let h;
    h=harness(async()=>({...record(),id:'adopted'}),{demo:reason==='revision'?{...demo,demo:{...demo.demo,revision:2}}:demo,
      brokenStorage:reason==='storage',guard:async()=>{if(reason==='hardware')throw Error('hardware_work_active');
        if(reason==='stale'){h.update(s=>({...s,prompt:'changed'}));h.render();}return true;}});
    const before=h.state();assert.equal(await h.render().adoptDemo(),false,reason);
    assert.equal(h.state().design,before.design,reason);assert.equal(h.state().code,before.code,reason);
  }
});

test('adoption saves a backup and new conversation; never mutates the Demo result',async()=>{
  const result=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const demo={...record('demo'),demo:{revision:1,confirmed_revision:1,result,state:'result_pending'}};
  const h=harness(async(path,body)=>({...record(),id:body.id,project_id:body.project_id}),{demo});
  const before=h.state();assert.equal(await h.render().adoptDemo(),true);
  assert.deepEqual(JSON.parse(h.persisted.get('boardvision.maker.v1.before-demo-adoption')),before);
  assert.equal(h.state().stage,'design');assert.equal(h.state().designView,'blueprint');
  assert.notEqual(h.state().design.id,result.id);assert.equal(result.id,'layout-fixture');
  assert.equal(h.render().demo.demo.result,result);
});

test('storage unavailable does not erase the active draft on a failed request',async()=>{
  const h=harness(async()=>{throw Error('offline');},{brokenStorage:true});
  await h.render().send();assert.equal(h.state().prompt,'original draft');assert.equal(h.render().storageError,true);
});

function chatComponents(locale) {
  const modules = {react:React, 'react/jsx-runtime':jsxRuntime,
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='en'?en:zh},
    '../lib/i18n':{useI18n:()=>({locale,tx:value=>typeof value==='string'?value:value[locale]})},
    '../lib/maker':maker, './ProjectConcept':{ProjectConcept:()=>null},
    '../lib/assistant':harness(()=>record()).exports,
    '../lib/assistantHistory':history,
    './MobileCompanion':{MobileCompanion:()=>null,MobileAttachmentCards:()=>null},
    '../lib/useChatScroll':{useChatScroll:()=>({chatRef:null,contentRef:null,unread:false})}};
  for (const name of ['AIModelControls','MakerModelMenu','UnifiedAssistant','AssistantWorkspace']) {
    const exports={};
    const compiled=ts.transpileModule(readFileSync(new URL(`../src/components/${name}.tsx`,import.meta.url),'utf8'),{
      compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
    }).outputText;
    new Function('require','exports',compiled)(key=>modules[key],exports);
    modules[`./${name}`]=exports;
  }
  return modules;
}

test('AI design demo in the chat menu is offered only in stage 01',()=>{
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    for(const stage of ['design','guide','deploy']) {
      const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
        state:{...maker.initialMaker(),stage},setState(){},onNewProject(){},
        controller:{record:record(),draft:'',demoOpen:false,busy:false},
        legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
      }));
      assert.equal(html.includes(locale==='en'?'Try AI design demo':'體驗 AI 設計 Demo'),stage==='design');
    }
  }
});

test('desktop shows the paired phone message and reply across wiring rounds without exposing cleared context',()=>{
  const {mergeConversation}=harness(()=>record()).exports;
  const older={id:'phone-greeting',role:'user',text:'安安',source:'mobile',created_at:1,stage:'guide',capability:'answer',round:2,epoch:0};
  const reply={...older,id:'greeting-reply',role:'assistant',text:'安安！',created_at:2};
  const cleared={...older,id:'cleared',text:'CLEARED-CONTEXT',epoch:-1};
  const next=mergeConversation(null,{...record(),round:3,messages:[older,reply,cleared],total:3});
  const merged=mergeConversation(next,{...next});
  assert.equal(merged.messages[0].archived,true,'Existing round provenance remains intact');
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{
      state:{...maker.initialMaker(),stage:'guide',guide:{run:3}},setState(){},onNewProject(){},
      controller:{record:merged,draft:'',demoOpen:false,mobileContext:{round:3},busy:false},
      legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
    }));
    assert.match(html,/安安/);assert.match(html,/安安！/);
    assert.doesNotMatch(html,/CLEARED-CONTEXT/);
    assert.match(html,locale==='en'?/Previous round; not evidence for this round/:/上一輪紀錄，不作為本輪證據/);
  }
});

test('shared history keeps server message identities while cleared history requires an explicit view',()=>{
  const value={context_epoch:1,round:3,messages:[
    {id:'old-round',epoch:1,round:2,stage:'guide',capability:'answer'},
    {id:'archived',epoch:1,round:3,archived:true},
    {id:'cleared',epoch:0,round:2,stage:'guide',capability:'answer'},
  ]};
  const before=structuredClone(value);
  assert.deepEqual(history.conversationMessages(value).map(m=>m.id),['old-round','archived']);
  assert.deepEqual(history.conversationMessages(value,true).map(m=>m.id),['old-round','archived','cleared']);
  assert.equal(history.conversationMessageNote(value.messages[0],value),'previous_round');
  assert.equal(history.conversationMessageNote(value.messages[2],value),'previous_context');
  assert.deepEqual(value,before,'Displaying history cannot rewrite its source context');
});

test('model and reasoning controls live inside the single composer across stages, locales and Demo',()=>{
  const model={id:'fake-model',name:'Fixture model',efforts:['low','high'],default_effort:'low',excluded_efforts:[]};
  for(const locale of ['en','zh-TW']) for(const stage of ['design','guide','deploy']) for(const demoOpen of [false,true]) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const state={...maker.initialMaker(),stage,aiModel:model.id};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{state,setState(){},onNewProject(){},
      controller:{record:record(),draft:'keep my draft',demoOpen,busy:false},
      legacy:{ai:{logged_in:true},busy:false,aiOptions:{options:{models:[model]},selectedModel:model,selectionValid:true}}}));
    assert.equal((html.match(/class="maker-model-menu is-compact"/g)||[]).length,1);
    assert.match(html,/class="assistant-input"[\s\S]*<\/textarea><div class="assistant-input-actions"><details class="maker-model-menu is-compact"[\s\S]*<\/details><button type="submit"/);
    assert.match(html,/<summary title="[^"]*Fixture model" aria-label="[^"]*Fixture model"><svg[^>]*aria-hidden="true"/);
    assert.doesNotMatch(html,/unified-composer-footer|class="maker-model-value"/);
    assert.match(html,/Fixture model/);
    assert.match(html,locale==='en'?/Reasoning effort/:/推理強度/);
    assert.match(html,/keep my draft/);
  }
});

test('compact model trigger keeps a descriptive sign-in name and leaves standalone menus unchanged',()=>{
  const {MakerModelMenu}=chatComponents('en')['./MakerModelMenu'];
  const props={state:maker.initialMaker(),setState(){},assistant:{ai:{logged_in:false},aiOptions:{},busy:false}};
  const compact=renderToStaticMarkup(React.createElement(MakerModelMenu,{...props,compact:true}));
  assert.match(compact,/aria-label="Choose AI model and reasoning effort · Select model \/ sign in"/);
  const regular=renderToStaticMarkup(React.createElement(MakerModelMenu,props));
  assert.match(regular,/class="maker-model-value"/);
  assert.doesNotMatch(regular,/maker-model-brain/);
});

test('wiring quick questions use one disclosure; other stages retain inline suggestions',()=>{
  for(const locale of ['en','zh-TW']) for(const stage of ['design','guide','deploy']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const state={...maker.initialMaker(),design:designFor(),stage};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,{state,setState(){},onNewProject(){},
      controller:{record:record(),draft:'keep my draft',demoOpen:false,busy:false},
      legacy:{ai:{logged_in:true},busy:false,aiOptions:{selectionValid:true}}}));
    if(stage==='guide') {
      assert.match(html,/<details class="assistant-suggestions"><summary>/);
      assert.doesNotMatch(html,/class="assistant-quick"/);
      assert.match(html,/class="assistant-wire-context"/);
    } else {
      assert.match(html,/class="assistant-quick"/);
      assert.doesNotMatch(html,/class="assistant-suggestions"/);
    }
    assert.match(html,/keep my draft/);
  }
});

test('orb toggle exposes its action and unread state without conditionally unmounting either pane',()=>{
  const previousWindow=globalThis.window;
  globalThis.window={matchMedia:()=>({matches:false})};
  try {
    for(const locale of ['en','zh-TW']) for(const aiOpen of [true,false]) {
      const {AssistantWorkspace}=chatComponents(locale)['./AssistantWorkspace'];
      const html=renderToStaticMarkup(React.createElement(AssistantWorkspace,{aiOpen,onAiOpen(){},latestReply:'new-reply',
        children:React.createElement('div',{id:'camera-kept'}),assistant:React.createElement('textarea',{defaultValue:'draft kept'})}));
      assert.match(html,new RegExp(`aria-expanded="${aiOpen}"`));
      assert.match(html,/aria-controls="assistant-chat-content"/);
      assert.match(html,/id="assistant-chat-content"/);
      assert.match(html,/class="assistant-orb" aria-hidden="true"/);
      assert.match(html,/class="assistant-orb-core"/);
      assert.match(html,/class="assistant-orb-chevron"/);
      assert.match(html,/id="camera-kept"/);
      assert.match(html,/>draft kept<\/textarea>/);
      const label=aiOpen ? (locale==='en'?'Collapse AI conversation':'收合 AI 對話')
        : (locale==='en'?'Open AI conversation, new reply':'展開 AI 對話，有新回覆');
      assert.ok(html.includes(`aria-label="${label}"`));
      assert.equal(html.includes('assistant-orb-unread'),!aiOpen);
    }
  } finally { globalThis.window=previousWindow; }
});

test('redesigned send icon preserves its accessible name, busy indicator and every disable guard',()=>{
  const {UnifiedAssistant}=chatComponents('en')['./UnifiedAssistant'];
  const base={state:maker.initialMaker(),setState(){},onNewProject(){},
    controller:{record:record(),draft:'keep my draft',demoOpen:false,busy:false},
    legacy:{ai:{logged_in:true},busy:false,aiOptions:{selectionValid:true}}};
  for(const scenario of ['ready','busy','legacyBusy','noRecord','empty','noParts','signedOut','invalidModel']) {
    const props={...base,state:{...base.state},controller:{...base.controller},legacy:{...base.legacy}};
    if(scenario==='busy')props.controller.busy=true;
    if(scenario==='legacyBusy')props.legacy.busy=true;
    if(scenario==='noRecord')props.controller.record=null;
    if(scenario==='empty')props.controller.draft='  ';
    if(scenario==='noParts')props.state.selected=[];
    if(scenario==='signedOut')props.legacy.ai={logged_in:false};
    if(scenario==='invalidModel')props.legacy.aiOptions={selectionValid:false};
    const html=renderToStaticMarkup(React.createElement(UnifiedAssistant,props));
    const button=html.match(/<button type="submit" class="assistant-send"[\s\S]*?<\/button>/)[0];
    assert.equal(button.includes('disabled=""'),scenario!=='ready');
    assert.match(button,/<span class="sr-only">Send<\/span>/);
    assert.equal(button.includes('assistant-send-pending'),scenario==='busy');
    if(scenario==='ready')assert.match(button,/<svg[^>]*aria-hidden="true"/);
  }
});

test('text follow-up visibly references only inherited media from the current context and wiring round',()=>{
  const active={asset_ids:['new-asset'],capture_id:'new-capture',epoch:2,round:3,
    attachments:[{asset_id:'old-asset',filename:'old-photo.jpg',image_url:'/old'},
      {asset_id:'new-asset',filename:'latest-photo.jpg',image_url:'/new'}]};
  const base={...record(),context_epoch:2,round:3,active_media:active};
  for(const locale of ['en','zh-TW']) {
    const {UnifiedAssistant}=chatComponents(locale)['./UnifiedAssistant'];
    const render=(next=base,round=3,demoOpen=false)=>renderToStaticMarkup(React.createElement(UnifiedAssistant,{
      state:{...maker.initialMaker(),guide:{run:round}},setState(){},onNewProject(){},
      controller:{record:next,draft:'What about this wire?',demoOpen,mobileContext:{round},busy:false},
      legacy:{ai:{logged_in:true},aiOptions:{selectionValid:true},busy:false},
    }));
    const html=render();assert.match(html,/latest-photo.jpg/);assert.doesNotMatch(html,/old-photo.jpg/);
    assert.match(html,locale==='en'?/This message references: /:/此訊息引用：/);
    assert.ok(html.indexOf('assistant-media-reference')<html.indexOf('id="unified-prompt"'));
    assert.match(render({...base,round:1}),/latest-photo.jpg/,'Fresh photo can replace media before record round reconciles');
    for(const hidden of [render({...base,context_epoch:4}),render(base,4),render(base,3,true),render({...base,active_media:null}),render({...base,active_media:{...active,asset_ids:[]}})])
      assert.doesNotMatch(hidden,/assistant-media-reference/);
    const fresh=render({...base,active_media:{...active,asset_ids:['fresh'],capture_id:'fresh-capture',attachments:[{asset_id:'fresh',filename:'newly-captured.jpg',image_url:'/fresh'}]}});
    assert.match(fresh,/newly-captured.jpg/);assert.doesNotMatch(fresh,/latest-photo.jpg/);
  }
});

test('moving model controls keeps original model selection and compatible effort without changing project or draft',()=>{
  const {AIModelControls}=chatComponents('en')['./AIModelControls'];
  const model={id:'different-model',efforts:['medium','high'],default_effort:'medium',excluded_efforts:[]};
  let state={...maker.initialMaker(),aiModel:'old',aiEffort:'low',prompt:'keep draft',design:designFor()};
  const before=state;
  const tree=AIModelControls({state,setState:next=>{state=next(state);},busy:false,
    ai:{options:{models:[model]},selectedModel:model,selectionValid:true}});
  const selects=[];
  function visit(node){if(!React.isValidElement(node))return;if(node.type==='select')selects.push(node);React.Children.forEach(node.props.children,visit);}
  visit(tree);
  selects[0].props.onChange({target:{value:model.id}});
  assert.equal(state.aiModel,model.id);assert.equal(state.aiEffort,'medium');
  assert.equal(state.prompt,before.prompt);assert.equal(state.design,before.design);
});
