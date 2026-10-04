import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {maker,designFor} from './project_guide_fixture.mjs';
import {systemText} from './system_text_fixture.mjs';
import {passiveCountdown,passiveChat} from './capture_ui_fixture.mjs';
import {wiringEntryHelpers,WiringReviewEntry} from './wiring_review_entry_fixture.mjs';

const source=readFileSync(new URL('../src/components/AiDebugPanel.tsx',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
function nodes(tree,predicate){const found=[];function visit(node){if(!node||typeof node!=='object')return;if(predicate(node))found.push(node);React.Children.forEach(node.props?.children,visit);}visit(tree);return found;}
function harness({wireIndex=0,english=false,variant='wiring',pending=false,record=null,actionsOnly=false,webcamReady=true,error='',countdown=passiveCountdown}={}){
  const values=[],refs=[];let stateIndex=0,refIndex=0,focuses=0;
  const actions=[];
  const react={...React,useEffect(){},useLayoutEffect(){},useRef(initial){const i=refIndex++;return refs[i]??=( {current:initial} );},
    useState(initial){const i=stateIndex++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return[values[i],next=>{values[i]=typeof next==='function'?next(values[i]):next;}];}};
  const module={};
  new Function('React','require','exports',code)(React,name=>name==='react'?react:name.endsWith('/maker')?maker:
    name.endsWith('/useMaker')?{useMakerText:()=>((zh,en)=>english?en:zh)}:
    name.endsWith('/systemText')?{systemText}:
    name.endsWith('/useCaptureCountdown')?{useCaptureCountdown:countdown}:
    name.endsWith('/useChatScroll')?{useChatScroll:passiveChat}:
    name.endsWith('/CaptureCountdown')?{CaptureCountdown:()=>null}:
    name.endsWith('/wiringReviewEntry')?wiringEntryHelpers:
    name.endsWith('/WiringReviewEntry')?{WiringReviewEntry}:
    name.endsWith('/componentTests')?{componentComplete:()=>true}:
    name.endsWith('/debugSessions')?{sameDebugTestKeys:()=>true}: {},module);
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const wire=design.wiring[wireIndex];
  const unexpected=(...args)=>{actions.push(args);throw Error('A preset triggered an external action');};
  const props={state:{...maker.initialMaker(),design},context:{test_keys:{}},currentCodeHash:'',
    session:{record,pending,error,create:unexpected,action:unexpected},variant,actionsOnly,
    wiringTarget:{component_id:wire.componentId,wire_id:wire.id},webcamReady,eyeActive:false,cameraSource:'device',cameraRuntimeRevision:1,
    repairCaseId:null,repairAppliedHash:null,repairCandidateReady:false,
    ...Object.fromEntries(['onReturnWebcam','onCase','onRetest','onTrial','onReviewRepair','onManual','onWiring','onDiagram','onOpenDebug'].map(key=>[key,unexpected]))};
  function render(){stateIndex=0;refIndex=0;const tree=module.AiDebugPanel(props);const input=nodes(tree,node=>node.type==='textarea')[0];if(input)input.ref.current={focus(){focuses++;}};return tree;}
  function presets(){return nodes(render(),node=>node.props?.className==='ai-debug-quick ai-debug-wiring-presets').flatMap(group=>nodes(group,node=>node.type==='button'));}
  function entry(){return nodes(render(),node=>node.type==='textarea')[0];}
  return{props,design,wire,render,presets,entry,actions,focuses:()=>focuses};
}

test('shared chat shows one capture/tool row and keeps secondary tools collapsed in both languages',()=>{
  for(const english of [false,true]) {
    const h=harness({actionsOnly:true,english});
    const setting=()=>nodes(h.render(),n=>n.props?.id==='assistant-debug-settings')[0];
    assert.equal(setting().props.hidden,true);
    assert.equal(nodes(h.render(),n=>n.type==='textarea').length,0);
    const toggle=nodes(h.render(),n=>n.props?.className==='assistant-debug-tools-toggle')[0];
    assert.equal(toggle.props['aria-expanded'],false);
    toggle.props.onClick();
    assert.equal(setting().props.hidden,false);
    const select=nodes(setting(),n=>n.type==='select')[0];
    select.props.onChange({target:{value:'thorough'}});
    assert.equal(nodes(setting(),n=>n.type==='select')[0].props.value,'thorough');
    assert.equal(nodes(setting(),n=>n.type==='button').length,2);
    let focused=false;
    toggle.ref.current={focus(){focused=true;}};
    h.render().props.onKeyDown({key:'Escape',preventDefault(){},stopPropagation(){}});
    assert.equal(setting().props.hidden,true);
    assert.equal(focused,true);
    assert.equal(nodes(setting(),n=>n.type==='select')[0].props.value,'thorough');
    assert.deepEqual(h.actions,[]);
  }
});

test('compact photo action still enters the countdown and preserves capture guards',async()=>{
  const waiting=[];
  const h=harness({actionsOnly:true,countdown:()=>({remaining:null,run:async action=>{waiting.push(action);},cancel(){}})});
  const capture=nodes(h.render(),n=>n.props?.className==='assistant-capture')[0];
  assert.match(capture.props['aria-label'],/10 秒倒數/);
  await capture.props.onClick();
  assert.equal(waiting.length,1);
  assert.deepEqual(h.actions,[],'No capture or model call before countdown completes');
  for(const options of [{pending:true},{webcamReady:false},{countdown:()=>({remaining:8,run(){throw Error('disabled');},cancel(){}})}]) {
    const blocked=harness({actionsOnly:true,...options});
    assert.equal(nodes(blocked.render(),n=>n.props?.className==='assistant-capture')[0].props.disabled,true);
  }
});

test('active stop and errors stay outside collapsed settings',()=>{
  const h=harness({actionsOnly:true,error:'camera_frame_unavailable',record:{id:'active',status:'paused',phase:'awaiting_user',messages:[],observations:[],instruction:'Check wiring',test_results:[]}});
  const tree=h.render(),settings=nodes(tree,n=>n.props?.id==='assistant-debug-settings')[0];
  assert.equal(settings.props.hidden,true);
  assert.equal(nodes(settings,n=>n.props?.className==='assistant-debug-stop').length,0);
  assert.equal(nodes(tree,n=>n.props?.className==='assistant-debug-stop').length,1);
  assert.equal(nodes(tree,n=>n.props?.role==='alert').length,1);
});

test('wiring mode offers exactly three contextual editable questions',()=>{
  const h=harness();
  assert.deepEqual(h.presets().map(button=>button.props.children),['這一步怎麼接？','Pi 腳位在哪？','怎麼檢查接線？']);
  for(const button of h.presets()){
    assert.equal(button.props.type,'button');
    assert(button.props.title.includes(h.wire.boardLabel));
    h.entry().props.onChange({target:{value:''}});
    button.props.onClick();
    assert.equal(h.entry().props.value,button.props.title);
  }
  assert.equal(h.focuses(),3);
  assert.deepEqual(h.actions,[]);
});

test('presets preserve an existing draft and do not duplicate a question',()=>{
  const h=harness();
  h.entry().props.onChange({target:{value:'我看不清楚接腳標籤。'}});
  const button=h.presets()[0];
  button.props.onClick();button.props.onClick();
  assert.equal(h.entry().props.value,`我看不清楚接腳標籤。\n${button.props.title}`);
  h.entry().props.onChange({target:{value:'  \n'}});
  button.props.onClick();
  assert.equal(h.entry().props.value,button.props.title);
  assert.deepEqual(h.actions,[]);
});

test('every HC and TFT step uses its own current module and physical pin',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  for(let wireIndex=0;wireIndex<design.wiring.length;wireIndex++){
    const h=harness({wireIndex,english:true});
    const module=maker.makerCatalog.modules.find(item=>item.id===h.wire.componentId);
    assert.equal(h.presets().length,3);
    assert(h.presets()[0].props.title.includes(`${module.name.en} ${h.wire.componentPin}`));
    for(const button of h.presets())assert(button.props.title.includes(h.wire.boardLabel));
  }
});

test('changing the current wire updates questions without discarding the draft',()=>{
  const h=harness();
  h.entry().props.onChange({target:{value:'尚未送出的草稿'}});
  const wire=h.design.wiring.find(item=>item.componentPin==='VCC');
  h.props.wiringTarget={component_id:wire.componentId,wire_id:wire.id};
  assert(h.presets()[0].props.title.includes(`VCC → Pi ${wire.boardLabel}`));
  assert.equal(h.entry().props.value,'尚未送出的草稿');
});

test('debug mode and missing or mismatched targets do not show wiring questions',()=>{
  assert.equal(harness({variant:'debug'}).presets().length,0);
  const h=harness();
  h.props.wiringTarget.wire_id='missing';assert.equal(h.presets().length,0);
  h.props.wiringTarget={component_id:'other-module',wire_id:h.wire.id};assert.equal(h.presets().length,0);
  h.props.state.design=null;assert.equal(h.presets().length,0);
});

test('pending sends disable and guard presets, while AI-busy drafts remain local',()=>{
  const pending=harness({pending:true});
  for(const button of pending.presets()){assert.equal(button.props.disabled,true);button.props.onClick();}
  assert.equal(pending.entry().props.value,'');assert.deepEqual(pending.actions,[]);
  const busy=harness({record:{id:'busy',status:'awaiting_capture',phase:'awaiting_user',model_busy:true,observations:[],messages:[],symptom:'',updated_at:0}});
  assert.equal(busy.presets().length,3);
  busy.presets()[2].props.onClick();
  assert.match(busy.entry().props.value,/不要自動執行測試/);
  assert.deepEqual(busy.actions,[]);
});

test('wiring question chips are not hidden by the legacy debug-only CSS rule',()=>{
  const css=readFileSync(new URL('../src/debug.css',import.meta.url),'utf8');
  assert.match(css,/\.is-wiring-review \.ai-debug-quick:not\(\.ai-debug-wiring-presets\)\s*\{\s*display:none/);
});
