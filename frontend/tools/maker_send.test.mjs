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
function harness(request,{loggedIn=true,valid=true,estimated=true,jobId=null,prompt='保留原文\n第二行需求'}={}){
  const values=[],refs=[],requests=[],sends=[];let stateIndex=0,refIndex=0;
  const design=designFor(['hc-sr04']);
  let state={...maker.initialMaker(),design,prompt,aiJobId:jobId,code:'unchanged manual code',conversation:[{role:'assistant',text:'先前回覆'}]};
  const react={...React,useEffect(){},useId:()=> 'isolated-composer',useRef(initial){return refs[refIndex++]??=({current:initial});},
    useState(initial){const i=stateIndex++;if(!(i in values))values[i]=i===0?{logged_in:loggedIn}:typeof initial==='function'?initial():initial;
      return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next;}];}};
  const require=name=>name==='react'?react:name.endsWith('/maker')?{...maker,makerRequest:async(path,body)=>{requests.push({path,body});return request(path,body);}}:
    name.endsWith('/useAIOptions')?{useAIOptions:current=>({selectionValid:valid,estimate:estimated?{}:null,requestKey:JSON.stringify(maker.designRequest(current,'zh-TW',null))})}:
    name.endsWith('/i18n')?{useI18n:()=>({locale:'zh-TW',tx:value=>typeof value==='string'?value:value['zh-TW']})}:
    name.endsWith('/systemText')?{systemText}:
    name.endsWith('/useMaker')?{useMakerText:()=>zh=>zh}:name.endsWith('/makerReply')?replies:{};
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
