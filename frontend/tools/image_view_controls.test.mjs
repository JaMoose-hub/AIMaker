import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const code=ts.transpileModule(readFileSync(new URL('../src/components/ImageViewControls.tsx',import.meta.url),'utf8'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
function load(open=false,portalTargets=[],locale='en'){
  const exports={};
  new Function('require','exports','React',code)(name=>{
    if(name.endsWith('.css'))return {};
    if(name==='react')return {...React,useState:v=>[typeof v==='boolean'?open:v,()=>{}],useId:()=>':source:',useRef:v=>({current:v}),useEffect(){},useLayoutEffect(){}};
    if(name==='react-dom')return {createPortal:(node,target)=>{portalTargets.push(target);return node;}};
    if(name==='../lib/useMaker')return {useMakerText:()=> (zh,en)=>locale==='en'?en:zh};
    throw Error(name);
  },exports,React);
  return exports;
}
const {ImageViewControls}=load();
const sourceProps={source:'webcam',disabled:false,phoneConnected:true,onSelect(){},onConnect(){}};
function sourceNode(props={},open=true){
  const previous=globalThis.document;
  try {globalThis.document={body:{}};return load(open).ImageSourceSelect({...sourceProps,...props});}
  finally {globalThis.document=previous;}
}
const props={view:'live',disabled:false,diagramAvailable:true,onChange(){}};
const viewButtons=node=>node.props.children[0].props.children;
const photoButtons=node=>node.props.children[1]?.props.children??[];

test('two guide entries combine live framing and photographs in both languages',()=>{
  for(const [locale,labels] of [['zh-TW',['照片引導','圖解引導']],['en',['Photo guide','Diagram guide']]]) {
    const {ImageViewControls:Controls}=load(false,[],locale),events=[];
    const node=Controls({...props,onChange:view=>events.push(view)}),buttons=viewButtons(node);
    assert.deepEqual(buttons.map(button=>button.props.children),labels);
    assert.deepEqual(buttons.map(button=>button.key),['photo','diagram']);
    assert.ok(buttons.every(button=>typeof button.props.title==='string'&&button.props.title.length>0));
    buttons.forEach(button=>button.props.onClick());
    assert.deepEqual(events,['live','diagram']);
    const html=renderToStaticMarkup(node);
    assert.ok(labels.every(label=>html.includes(label)),'visible button text also supplies its accessible name');
    assert.doesNotMatch(html,/接線圖|接線照片|Wiring diagram|Wiring photo/);
  }
});

test('live and captured photo remain subviews of one guide without selecting a camera',()=>{
  const events=[];
  for(const view of ['live','diagram','photo']){
    const node=ImageViewControls({...props,view,savedPhotoAvailable:true,onChange:v=>events.push(v)});
    const buttons=viewButtons(node);
    assert.equal(buttons.filter(b=>b.props['aria-pressed']).length,1);
    assert.equal(buttons.find(b=>b.props['aria-pressed']).key,view==='diagram'?'diagram':'photo');
    const subviews=photoButtons(node);
    assert.equal(subviews.length,view==='diagram'?0:2);
    if(subviews.length) {
      assert.equal(subviews.filter(b=>b.props['aria-pressed']).length,1);
      assert.equal(subviews[view==='live'?0:1].props['aria-pressed'],true);
      subviews.forEach(b=>b.props.onClick());
    }
    assert(!renderToStaticMarkup(node).includes('image-source'));
  }
  assert.deepEqual(events,['live','photo','live','photo']);
});

test('calibration, switching and capture guards cover both photo-guide subviews',()=>{
  const buttons=p=>viewButtons(ImageViewControls({...props,...p}));
  assert(buttons({disabled:true}).every(b=>b.props.disabled));
  assert.deepEqual(buttons({photoDisabled:true}).map(b=>!!b.props.disabled),[true,false]);
  assert.deepEqual(buttons({diagramAvailable:false}).map(b=>!!b.props.disabled),[false,true]);
  for(const guard of [{disabled:true},{photoDisabled:true}]) {
    assert(photoButtons(ImageViewControls({...props,savedPhotoAvailable:true,...guard})).every(b=>b.props.disabled));
  }
  assert.deepEqual(photoButtons(ImageViewControls(props)).map(b=>!!b.props.disabled),[false,true]);
});

test('photo-guide entry resumes a saved photograph or framing, never an empty unavailable photo',()=>{
  const events=[];
  for(const [photoView,savedPhotoAvailable,expected] of [['live',true,'live'],['photo',true,'photo'],['photo',false,'live']]) {
    const node=ImageViewControls({...props,view:'diagram',photoView,savedPhotoAvailable,onChange:v=>events.push(v)});
    viewButtons(node)[0].props.onClick();assert.equal(events.at(-1),expected);
  }
});

test('only a different paired source requests a source switch',()=>{
  const events=[];
  const node=sourceNode({source:'phone',onSelect:s=>events.push(s),onConnect:()=>assert.fail()});
  const entries=node.props.children[1].props.children[1];
  entries[1].props.onClick();
  assert.deepEqual(events,[]);
  entries[0].props.onClick();
  assert.deepEqual(events,['webcam']);
  assert.match(renderToStaticMarkup(node),/aria-label="Image source"/);
});

test('an unpaired phone opens pairing without changing the current source',()=>{
  let connects=0;
  const node=sourceNode({phoneConnected:false,onSelect:()=>assert.fail(),onConnect:()=>connects++});
  node.props.children[1].props.children[1][1].props.onClick();
  assert.equal(connects,1);
  assert.equal(node.props.children[1].props.children[1][0].props['aria-checked'],true);
});

test('custom source popup exposes menu selection without a native select',()=>{
  const node=sourceNode({source:'phone'});
  const html=renderToStaticMarkup(node);
  assert(!html.includes('<select'));
  assert.match(html,/aria-haspopup="menu" aria-expanded="true"/);
  assert.equal((html.match(/role="menuitemradio"/g)||[]).length,2);
  assert.equal((html.match(/aria-checked="true"/g)||[]).length,1);
  assert.match(html,/image-source-check/);
});

test('source popup stays inside native fullscreen and cleans up its fullscreen listener',()=>{
  const previous=globalThis.document,targets=[],fullscreen={id:'preview-fullscreen'};
  try {
    globalThis.document={body:{},fullscreenElement:fullscreen};
    load(true,targets).ImageSourceSelect(sourceProps);
    assert.equal(targets[0],fullscreen);
    globalThis.document.fullscreenElement=null;
    load(true,targets).ImageSourceSelect(sourceProps);
    assert.equal(targets[1],globalThis.document.body);
    const source=readFileSync(new URL('../src/components/ImageViewControls.tsx',import.meta.url),'utf8');
    assert.match(source,/removeEventListener\('fullscreenchange', closeMenu\)/);
  } finally {globalThis.document=previous;}
});

test('disabled source picker has no popup or activatable source action',()=>{
  const node=sourceNode({disabled:true,onSelect:()=>assert.fail(),onConnect:()=>assert.fail()});
  assert.equal(node.props.children[0].props.disabled,true);
  assert.equal(node.props.children[0].props['aria-expanded'],false);
  assert.equal(node.props.children[1],null);
});

test('arrows move menu focus without selecting; Escape closes and restores trigger focus',()=>{
  const previous=globalThis.document;
  try {
    const node=sourceNode({onSelect:()=>assert.fail()});
    const trigger=node.props.children[0],menu=node.props.children[1],entries=menu.props.children[1];
    const focused=[];
    const buttons=entries.map((_,i)=>({focus(){focused.push(i);globalThis.document.activeElement=buttons[i];}}));
    entries.forEach((entry,i)=>entry.ref(buttons[i]));
    trigger.ref.current={focus(){focused.push('trigger');}};
    globalThis.document={activeElement:buttons[0]};
    const press=key=>menu.props.onKeyDown({key,preventDefault(){},stopPropagation(){}});
    press('ArrowDown');press('ArrowDown');press('End');press('Home');press('Escape');
    assert.deepEqual(focused,[1,0,1,0,'trigger']);
  } finally {globalThis.document=previous;}
});
