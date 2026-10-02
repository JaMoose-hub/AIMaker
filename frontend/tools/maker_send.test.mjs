import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {maker,designFor} from './project_guide_fixture.mjs';
import {systemText} from './system_text_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const compile=path=>ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
const hookCode=compile('../src/lib/useMakerAI.ts'),componentCode=compile('../src/components/MakerAssistant.tsx');
const replies={};new Function('exports',compile('../src/lib/makerReply.ts'))(replies);
function nodes(tree,predicate){const found=[];function visit(node){if(!node||typeof node!=='object')return;if(predicate(node))found.push(node);React.Children.forEach(node.props?.children,visit);}visit(tree);return found;}
function harness(request,{loggedIn=true,valid=true,estimated=true,jobId=null,prompt='保留原文\n第二行需求',locale='zh-TW'}={}){
  const values=[],refs=[],requests=[],sends=[];let stateIndex=0,refIndex=0;
  const design=designFor(['hc-sr04']);
  let state={...maker.initialMaker(),design,prompt,aiJobId:jobId,code:'unchanged manual code',conversation:[{role:'assistant',text:'先前回覆'}]};
  const react={...React,useEffect(){},useId:()=> 'isolated-composer',useRef(initial){return refs[refIndex++]??=({current:initial});},
    useState(initial){const i=stateIndex++;if(!(i in values))values[i]=i===0?{logged_in:loggedIn}:typeof initial==='function'?initial():initial;
      return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next;}];}};
  const require=name=>name==='react'?react:name.endsWith('/maker')?{...maker,makerRequest:async(path,body)=>{requests.push({path,body});return request(path,body);}}:
    name.endsWith('/useAIOptions')?{useAIOptions:current=>({selectionValid:valid,estimate:estimated?{}:null,requestKey:JSON.stringify(maker.designRequest(current,'zh-TW',null))})}:
    name.endsWith('/i18n')?{useI18n:()=>({locale,tx:value=>typeof value==='string'?value:value[locale]})}:
    name.endsWith('/systemText')?{systemText}:
    name.endsWith('/useMaker')?{useMakerText:()=>(zh,en)=>locale==='en'?en:zh}:name.endsWith('/makerReply')?replies:{};
  const hook={},component={};new Function('require','exports',hookCode)(require,hook);new Function('React','require','exports',componentCode)(React,require,component);
  const setState=next=>{state=typeof next==='function'?next(state):next;};
  function render(){stateIndex=0;refIndex=0;const assistant=hook.useMakerAI(state,setState);
    const tree=component.MakerAssistant({state,setState,assistant:{...assistant,generate(){const send=assistant.generate();sends.push(send);return send;}},onReview(){}});
    return{assistant,tree};}
  const input=()=>nodes(render().tree,node=>node.type==='textarea')[0];
  const submit=()=>nodes(render().tree,node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  const type=text=>input().props.onChange({target:{value:text}});
  return{render,input,submit,type,requests,sends,state:()=>state};
}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}

test('starter button fills the exact current-language prompt without sending or altering the project',()=>{
  for(const [locale,label,expected] of [['zh-TW','帶入預設',maker.defaultPrompt],['en','Use starter prompt',maker.defaultPromptEn]]){
    const h=harness(()=>assert.fail('starter must not send'),{prompt:'',locale}),before=h.state();
    const button=()=>nodes(h.render().tree,n=>n.type==='button'&&n.props.children===label)[0];
    assert.equal(button().props.type,'button');assert.equal(button().props.disabled,false);
    button().props.onClick();
    assert.equal(h.input().props.value,expected);assert.equal(button(),undefined);
    for(const key of Object.keys(before).filter(key=>key!=='prompt'))assert.equal(h.state()[key],before[key]);
    assert.equal(h.requests.length,0);assert.equal(h.sends.length,0);
  }
});

test('Demo works without AI login, only fetches local Demo data and preserves the active draft',async()=>{
  for(const locale of ['zh-TW','en']) {
    const demo=designFor(['hc-sr04','mrd-tf240-8p-cs']);
    const h=harness(async(path,body)=>{
      assert.equal(path,`design/demo?locale=${locale}`);assert.equal(body,undefined);return demo;
    },{locale,loggedIn:false,valid:false,estimated:false});
    const before=h.state();
    await h.render().assistant.loadDemo();
    assert.equal(h.state().candidate,demo);assert.equal(h.state().candidate.image,undefined);
    for(const key of ['design','guide','code','prompt','selected'])assert.equal(h.state()[key],before[key]);
    assert.deepEqual(h.state().conversation.slice(0,-2),before.conversation);
    const samples=h.state().conversation.slice(-2);
    assert.deepEqual(samples.map(m=>[m.role,m.source]),[['user','demo'],['assistant','demo']]);
    assert.equal(samples[0].text,locale==='en'?maker.defaultPromptEn:maker.defaultPrompt);
    assert.match(samples[1].text,locale==='en'?/built-in demo/:/內建示範/);
    const messages=nodes(h.render().tree,n=>n.props?.className?.startsWith('maker-message '));
    assert.equal(messages.length,3);
    for(const message of messages.slice(-2)){
      const label=nodes(message,n=>n.type==='small')[0].props.children.join('');
      assert.match(label,locale==='en'?/Sample chat/:/示範對話/);
    }
    assert.equal(nodes(messages.at(-1),n=>n.type==='p')[0].props.children,samples[1].text,'sample reply stays complete in both languages');
    assert.equal(nodes(messages.at(-1),n=>n.type==='details').length,0);
    await h.render().assistant.loadDemo();
    assert.deepEqual(h.state().conversation.slice(-2),samples);
    assert.equal(h.state().conversation.length,3,'reloading does not duplicate the sample exchange');
    assert.equal(h.requests.length,2);assert.equal(h.sends.length,0);assert.equal(h.render().assistant.busy,false);
  }
});

test('failed or busy Demo loads never add sample chat or erase a draft',async()=>{
  for(const response of [async()=>{throw Error('offline');},async()=>({source:'demo'})]){
    const h=harness(response),before=h.state();
    await h.render().assistant.loadDemo();
    assert.equal(h.state(),before);assert.ok(h.render().assistant.error);
  }
  const busy=harness(()=>assert.fail('must not load'),{jobId:'active'}),before=busy.state();
  await busy.render().assistant.loadDemo();assert.equal(busy.state(),before);
});

test('a real follow-up after Demo keeps sample bubbles local and sends only real chat',async()=>{
  const h=harness(async(path)=>path.startsWith('design/demo')?designFor(['hc-sr04','mrd-tf240-8p-cs']):{job_id:'follow-up'});
  const history=h.state().conversation;
  await h.render().assistant.loadDemo();
  h.type('Move the screen to the front');h.submit();await h.sends[0];
  assert.deepEqual(h.requests[1].body.conversation,history);
  assert.equal(h.requests[1].body.prompt,'Move the screen to the front');
  assert.equal(h.state().conversation.at(-1).source,undefined);
  assert.equal(h.state().conversation.at(-1).text,'Move the screen to the front');
  assert.equal(h.state().conversation.filter(m=>m.source==='demo').length,2);
});

test('starter button protects in-flight requests and newly typed drafts',()=>{
  const blocked=harness(()=>assert.fail('must not send'),{prompt:'',jobId:'busy-job'}),before=blocked.state();
  const busyButton=nodes(blocked.render().tree,n=>n.type==='button'&&n.props.children==='帶入預設')[0];
  assert.equal(busyButton.props.disabled,true);busyButton.props.onClick();assert.equal(blocked.state(),before);
  const h=harness(()=>assert.fail('must not send'),{prompt:''});
  const staleButton=nodes(h.render().tree,n=>n.type==='button'&&n.props.children==='帶入預設')[0];
  h.type('keep new draft');staleButton.props.onClick();assert.equal(h.input().props.value,'keep new draft');
});

test('accepted form submission clears the bound composer, preserves history and survives restore',async()=>{
  const response=deferred(),h=harness(()=>response.promise);
  const before=h.state();h.submit();
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].path,'design/generate');
  assert.equal(h.requests[0].body.prompt,before.prompt);
  assert.equal(h.input().props.value,before.prompt,'keep input until the server accepts it');
  response.resolve({job_id:'accepted-job'});await h.sends[0];
  assert.equal(h.input().props.value,'');assert.equal(h.state().aiJobId,'accepted-job');
  assert.deepEqual(h.state().conversation,[...before.conversation,{role:'user',text:before.prompt}]);
  for(const key of ['design','candidate','guide','code','selected'])assert.equal(h.state()[key],before[key]);
  const restored=maker.restoreMaker(JSON.stringify(h.state()));
  assert.equal(restored.prompt,'');assert.equal(restored.conversation.at(-1).text,before.prompt);
});

test('a rejected send retains the input and existing conversation for retry',async()=>{
  const h=harness(async()=>{throw Error('offline');});const before=h.state();
  h.submit();await h.sends[0];
  assert.equal(h.state(),before);assert.equal(h.input().props.value,before.prompt);
  assert.match(h.render().assistant.error,/offline/);assert.equal(h.render().assistant.busy,false);
});

test('new text entered while enqueueing is not erased or added as the sent message',async()=>{
  const response=deferred(),h=harness(()=>response.promise),sent=h.state().prompt;
  h.submit();h.type('下一則尚未送出的問題');
  response.resolve({job_id:'accepted-job'});await h.sends[0];
  assert.equal(h.input().props.value,'下一則尚未送出的問題');
  assert.equal(h.state().conversation.at(-1).text,sent);
  assert.equal(h.requests.length,1);
});

test('double submits and busy, blank, offline or invalid model guards do not clear text',async()=>{
  const response=deferred(),h=harness(()=>response.promise);
  h.submit();h.submit();assert.equal(h.requests.length,1);assert.equal(h.sends.length,1);
  response.resolve({job_id:'accepted-job'});await h.sends[0];
  for(const options of [{jobId:'busy-job'},{prompt:' \n'},{loggedIn:false},{valid:false},{estimated:false}]){
    const blocked=harness(()=>assert.fail('blocked send requested an AI job'),options),before=blocked.state();
    blocked.submit();assert.equal(blocked.requests.length,0);assert.equal(blocked.state(),before);
  }
});
