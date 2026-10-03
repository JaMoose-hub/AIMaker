import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {maker,designFor,componentTests} from './project_guide_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const jsx=(type,props,key)=>React.createElement(type,{...props,...(key===undefined?{}:{key})});
const jsxRuntime={jsx,jsxs:jsx,Fragment:React.Fragment};
const module={};
new Function('require','exports',ts.transpileModule(read('../src/components/StepDiagramView.tsx'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText)(name=>name==='react/jsx-runtime'?jsxRuntime:
  name.includes('CircuitDiagram')?{CircuitDiagram:props=>{const wire=props.design.wiring.find(w=>w.id===props.activeId);return React.createElement('output',{'data-active':props.activeId,'data-readable':props.readableDefault,'data-workspace':props.workspace},`${wire.componentPin} ${wire.boardLabel}`);}}:
  {useMakerText:()=>zh=>zh},module);
const appTree=ts.createSourceFile('App.tsx',read('../src/App.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function find(predicate){let result;function visit(node){if(predicate(node))result=node;ts.forEachChild(node,visit);}visit(appTree);assert.ok(result);return result;}
const show=find(node=>ts.isVariableDeclaration(node)&&node.name.getText(appTree)==='showWiringDiagram').initializer;
const shouldShow=new Function('projectWire','makerStage','maker','displayModeActive','debugCaptureSession','diagramCaptureOverride','diagramCaptureKey','calibrateOpen = false','diagramInspection = null',`return ${show.getText(appTree)};`);

test('camera and 2D toggle are reversible and accessible without any hardware operation',()=>{
  const modes=[];
  for(const diagramVisible of [false,true]) {
    const button=module.WiringViewToggle({diagramVisible,onChange:mode=>modes.push(mode)});
    assert.equal(button.props.type,'button');
    assert.equal(button.props['aria-pressed'],diagramVisible);
    assert.equal(button.props['aria-controls'],'current-step-diagram');
    assert.match(renderToStaticMarkup(button),diagramVisible?/返回鏡頭/:/本步驟 2D 接線圖/);
    button.props.onClick();
  }
  assert.deepEqual(modes,['2d','camera']);
});

test('users can inspect 2D while a photo is requested, but calibration blocks switching',()=>{
  const modes=[];
  const button=module.WiringViewToggle({diagramVisible:false,captureRequired:true,onChange:mode=>modes.push(mode)});
  assert.equal(button.props.disabled,false);assert.match(button.props.title,/拍攝實物時請返回鏡頭/);
  button.props.onClick();assert.deepEqual(modes,['2d']);
  assert.equal(module.WiringViewToggle({diagramVisible:false,disabled:true,onChange(){}}).props.disabled,true);
});

test('every current HC and TFT step passes its exact wire to the readable diagram',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  for(const wire of design.wiring){
    const html=renderToStaticMarkup(React.createElement(module.StepDiagramView,{design,wire}));
    assert.match(html,/id="current-step-diagram"/);
    assert.ok(html.includes(`data-active="${wire.id}"`));
    assert.ok(html.includes(wire.componentPin));assert.ok(html.includes(wire.boardLabel));
    assert.match(html,/data-readable="true"/);
    assert.match(html,/data-workspace="true"/);
    assert.doesNotMatch(html,/step-diagram-heading/,'the current wire heading is not repeated outside the diagram');
  }
});

// Render the actual schematic and its exact profile routes. Only the viewport
// measurement and decorative module art are replaced in this server fixture.
const layoutPath=new URL('../src/lib/circuitLayout.ts',import.meta.url);
const layoutSource=readFileSync(layoutPath,'utf8').replace(/import (\w+) from "([^"]+\.json)";/g,
  (_,name,path)=>`const ${name} = ${readFileSync(new URL(path,layoutPath),'utf8')};`);
const layoutExports={};
new Function('exports',ts.transpileModule(layoutSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(layoutExports);
const guideExports={};
const guidePath=new URL('../src/lib/componentWiringGuides.ts',import.meta.url);
const guideSource=readFileSync(guidePath,'utf8').replace(/import (\w+) from "([^"]+\.json)";/g,
  (_,name,path)=>`const ${name} = ${readFileSync(new URL(path,guidePath),'utf8')};`);
new Function('exports',ts.transpileModule(guideSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(guideExports);
const diagramExports={};
new Function('require','exports',ts.transpileModule(read('../src/components/CircuitDiagram.tsx'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText)(name=>name==='react'?React:name==='react/jsx-runtime'?jsxRuntime:
  name.endsWith('circuitLayout')?layoutExports:name.endsWith('componentWiringGuides')?guideExports:
  name.endsWith('useMaker')?{useMakerText:()=>zh=>zh}:name.endsWith('i18n')?{useI18n:()=>({tx:value=>typeof value==='string'?value:value['zh-TW']})}:
  name.endsWith('CircuitModuleArt')?{CircuitModuleArt:()=>null}:
  {CircuitViewport:props=>React.createElement('div',{'data-fill':props.fitToViewport,'data-preferred':props.preferredScale},
    props.toolbarStart,props.toolbarEnd,props.children)},diagramExports);

test('full-frame step diagrams show one heading, one current-module chip and the exact active endpoints',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const before=structuredClone(design);
  for(const wire of design.wiring){
    const html=renderToStaticMarkup(React.createElement(diagramExports.CircuitDiagram,{design,activeId:wire.id,readableDefault:true,workspace:true}));
    assert.match(html,/class="maker-circuit circuit-workspace"/);
    assert.match(html,/data-fill="true"/);
    assert.equal((html.match(/<h2>/g)??[]).length,1);
    assert.ok(html.includes(wire.boardLabel));
    assert.equal((html.match(/class="circuit-step-module"/g)??[]).length,1);
    assert.equal((html.match(/data-circuit-module=/g)??[]).length,1);
    assert.ok(html.includes(`data-circuit-module="${wire.componentId}"`));
    assert.match(html,new RegExp(`class="circuit-connection active" data-circuit-wire="${wire.id}"`));
    assert.doesNotMatch(html,/circuit-module-tabs/,'inactive filter buttons are not stacked in the step view');
    assert.match(html,/<details class="circuit-workspace-notes"><summary>/,'detailed notes are collapsed initially');
    assert.match(html,/示意圖不代表導通驗證/);
  }
  assert.deepEqual(design,before);
});

test('Blueprint and compact AI previews retain their original controls and no full-frame mode',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const html=renderToStaticMarkup(React.createElement(diagramExports.CircuitDiagram,{design}));
  assert.match(html,/circuit-module-tabs/);assert.match(html,/全部零件/);
  assert.match(html,/data-fill="false"/);assert.doesNotMatch(html,/circuit-workspace/);
  assert.equal((html.match(/data-circuit-module=/g)??[]).length,2);
  const preview=renderToStaticMarkup(React.createElement(diagramExports.CircuitDiagram,{design,compactPreview:true}));
  assert.match(preview,/ai-diagram-preview-image/);
  assert.doesNotMatch(preview,/<button|<dialog|circuit-inspector|circuit-workspace/);
});

test('a divider warning stays visible above the full-frame canvas instead of only inside notes',()=>{
  const design=designFor(), wire=design.wiring.find(w=>w.componentPin==='ECHO');
  wire.connectionKind='divider';
  const html=renderToStaticMarkup(React.createElement(diagramExports.CircuitDiagram,{design,activeId:wire.id,workspace:true}));
  const heading=html.split('data-fill=')[0];
  assert.match(heading,/ECHO 需分壓，不可直連 GPIO/);
  assert.match(html,/330Ω/);assert.match(html,/470Ω/);
});

test('2D is available with the AI tab open and only requested captures temporarily reveal the camera',()=>{
  const state={...maker.initialMaker(),guide:{...maker.emptyGuide(),mode:'2d'},debug:{panelOpen:true}};
  assert.equal(shouldShow({},'guide',state,false,null),true);
  const capture={capture_task:{id:'photo-one',target:'pi_header'}};
  assert.equal(shouldShow({},'guide',state,false,capture,null,'photo-one'),false);
  assert.equal(shouldShow({},'guide',state,false,capture,'photo-one','photo-one'),true,'an explicit view choice can inspect the diagram while waiting');
  assert.equal(shouldShow({},'guide',state,false,capture,'photo-one','photo-two'),false,'the next capture reveals the camera again');
  assert.equal(shouldShow({},'guide',state,false,null),true);
  assert.equal(state.guide.mode,'2d');
  assert.equal(shouldShow(undefined,'guide',state,false,null),false);
  assert.equal(shouldShow(undefined,'guide',state,false,null,null,null,false,{}),true,'an explicitly selected archived diagram can display independently of the guide cursor');
  assert.equal(shouldShow({},'design',state,false,null),false);
  assert.equal(shouldShow({},'guide',state,true,null),false);
  assert.equal(shouldShow({},'guide',state,false,null,null,null,true),false,'opening board calibration reveals the camera');
});

test('the actual unified App switch retains the source, cursor, chat and test bindings',()=>{
  const control=find(node=>ts.isJsxSelfClosingElement(node)&&node.tagName.getText(appTree)==='ImageViewControls');
  const handler=control.attributes.properties.find(prop=>prop.name?.getText(appTree)==='onChange').initializer.expression;
  const code=ts.transpileModule(`const change=${handler.getText(appTree)};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const liveHandler=find(node=>ts.isVariableDeclaration(node)&&node.name.getText(appTree)==='changeImageView').initializer.arguments[0];
  const liveCode=ts.transpileModule(`const change=${liveHandler.getText(appTree)};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const original={...maker.initialMaker(),design,guide:{...maker.emptyGuide(),phase:'active',index:2,checks:['position']},
    debug:{panelOpen:true,intent:'wiring',runId:'synthetic-run'},conversation:[{role:'user',text:'GND 要接哪裡？'}]};
  let current=original;
  let override;
  let inspection='previous inspection';
  let imageView='phone';
  const lastLiveView={current:'phone'};
  const setMaker=update=>{current=update(current);};
  const setOverride=next=>{override=next;};
  const setInspection=next=>{inspection=next;};
  const setImageView=next=>{imageView=next;};
  const changeImageView=new Function('setMaker','setDiagramCaptureOverride','setEvidenceDiagram','setImageView','lastLiveView',`${liveCode};return change;`)(setMaker,setOverride,setInspection,setImageView,lastLiveView);
  const change=new Function('setMaker','setDiagramCaptureOverride','diagramCaptureKey','setEvidenceDiagram','setImageView','lastLiveView','projectWire','changeImageView',`${code};return change;`)(setMaker,setOverride,'capture-one',setInspection,setImageView,lastLiveView,design.wiring[2],changeImageView);
  const signature=componentTests.componentTestKey(design,original.guide,'hc-sr04');
  for(const view of ['diagram','live','photo','live']) {
    const mode=view==='diagram'?'2d':'camera';
    change(view);
    assert.deepEqual(current,{...original,guide:{...original.guide,mode}});
    assert.equal(current.debug,original.debug);assert.equal(current.conversation,original.conversation);
    assert.equal(current.guide.confirmed,original.guide.confirmed);
    assert.equal(override,mode==='2d'?'capture-one':null);
    assert.equal(inspection,null,'the toolbar returns to the actual current step, not an old AI reference');
    assert.equal(imageView,view==='photo'?'photo':'phone','view changes keep the last live source');
    assert.equal(lastLiveView.current,'phone');
    assert.equal(componentTests.componentTestKey(design,current.guide,'hc-sr04'),signature);
  }
});

test('the 2D capture-wait notice does not imply a diagram is an actual hardware photo',()=>{
  const design=designFor();
  const html=renderToStaticMarkup(React.createElement(module.StepDiagramView,{design,wire:design.wiring[0],capturePending:true}));
  assert.match(html,/AI 正在等待實物照片/);assert.match(html,/返回鏡頭拍攝/);
});

test('the camera remains mounted and the alternate diagram replaces only its visible body',()=>{
  const app=read('../src/App.tsx'),video=read('../src/components/VideoView.tsx');
  assert.equal((app.match(/<VideoView\b/g)??[]).length,1);
  assert.match(video,/ref=\{containerRef\}\s+hidden=\{Boolean\(alternateView\) && !displayOnlyMode\}/);
  assert.match(video,/\{!displayOnlyMode \? alternateView : null\}/);
  assert.match(app,/const projectWire = project \? currentWire\(project, maker.guide\)/,'prepare, active and review all have the current step');
  assert.match(app,/wire=\{projectWire\}/);
  assert.doesNotMatch(app,/resizable=\{[^}]*!showWiringDiagram/,'2D retains the same adjustable pane widths');
});
