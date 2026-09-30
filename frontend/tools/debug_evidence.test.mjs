import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
function load(path,require=()=>({})) {
  const exports={};
  new Function('React','require','exports',ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText)(React,require,exports);
  return exports;
}
const helpers=load('../src/lib/debugEvidence.ts');
const wires=[{id:'hc:gnd',componentId:'hc-sr04',componentPin:'GND',boardPin:'GND_P6',boardLabel:'Pin 6 · GND',connectionKind:'direct'},
  {id:'hc:echo',componentId:'hc-sr04',componentPin:'ECHO',boardPin:'GPIO18',boardLabel:'Pin 12 · GPIO18',connectionKind:'direct'}];
const design={id:'project',revision:4,catalog_version:'3',profile_versions:{hc:{sha256:'frozen'}},component_ids:['hc-sr04'],wiring:wires};
const snapshot={id:'diagram',schema_version:'debug-diagram-v1',project_id:'project',project_revision:4,design,render_snapshot:{modules:[{id:'hc-sr04',pins:wires.map(wire=>({id:wire.componentPin})),pin_order:wires.map(wire=>wire.componentPin)}]}};
const reference={snapshot_id:'diagram',wire_ids:['hc:gnd','hc:echo']};

function cardHarness(file,componentName,props) {
  const values=[];let cursor=0;
  const fakeReact={...React,useEffect(){},useRef:()=>({current:null}),useState(initial){const i=cursor++;if(!(i in values))values[i]=initial;return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value;}];}};
  const module=load(file,name=>name==='react'?fakeReact:name.includes('debugEvidence')?helpers:name.includes('useMaker')?{useMakerText:()=>zh=>zh}:{CircuitDiagram:({compactPreview})=>React.createElement('div',{[compactPreview?'data-compact-diagram':'data-full-diagram']:true})});
  return {render(){cursor=0;return module[componentName](props);}};
}
function nodes(element,predicate){const result=[];function visit(node){if(!node||typeof node!=='object')return;if(predicate(node))result.push(node);React.Children.forEach(node.props?.children,visit);}visit(element);return result;}
const buttons=(tree,text)=>nodes(tree,node=>node.type==='button'&&React.Children.toArray(node.props.children).filter(value=>typeof value==='string'||typeof value==='number').join('')===text);

test('historical photo URLs keep the source check and encode the requested original view',()=>{
  assert.equal(helpers.evidenceSessionId({session_id:'old'},{session_id:'new'},'current'),'old');
  assert.equal(helpers.debugEvidenceUrl('old','capture','pi_pins'),'/api/debug/sessions/old/evidence/capture?view=pi_pins');
  assert.equal(helpers.debugEvidenceUrl('old/id','capture id','module/read'),'/api/debug/sessions/old%2Fid/evidence/capture%20id?view=module%2Fread');
});

test('only exact archived wire IDs can be shown and navigation checks version, profiles and wiring',()=>{
  assert.deepEqual(helpers.diagramWires(snapshot,['invented','hc:echo']),[wires[1]]);
  assert.equal(helpers.diagramMatchesCurrent(snapshot,structuredClone(design)),true);
  for(const current of [{...design,revision:5},{...design,id:'different'},{...design,profile_versions:{hc:{sha256:'new'}}},{...design,wiring:[{...wires[0],boardPin:'GND_P9'},wires[1]]}])assert.equal(helpers.diagramMatchesCurrent(snapshot,current),false);
  const localized=structuredClone(snapshot);
  localized.design.wiring[0].instruction={'zh-TW':'接到 GND',en:'Connect GND'};
  const sorted=structuredClone(localized.design);
  sorted.wiring[0].instruction={en:'Connect GND','zh-TW':'接到 GND'};
  assert.equal(helpers.diagramMatchesCurrent(localized,sorted),true,'server JSON key sorting does not age the drawing');
  sorted.wiring[0].instruction.en='A different instruction';
  assert.equal(helpers.diagramMatchesCurrent(localized,sorted),false);
});

test('compact diagram messages keep separate selections and route only their referenced wire to the left',()=>{
  const requests=[];
  const a=cardHarness('../src/components/DiagramEvidenceCard.tsx','DiagramEvidenceCard',{snapshot,reference,currentDesign:design,onDiagram:request=>requests.push(request)});
  const b=cardHarness('../src/components/DiagramEvidenceCard.tsx','DiagramEvidenceCard',{snapshot,reference,currentDesign:design,onDiagram:request=>requests.push(request)});
  assert.doesNotMatch(renderToStaticMarkup(a.render()),/data-full-diagram|data-compact-diagram|<svg|<dialog/);
  buttons(a.render(),'HC · ECHO')[0].props.onClick();
  assert.match(renderToStaticMarkup(a.render()),/HC-SR04\+ · ECHO/);
  assert.match(renderToStaticMarkup(b.render()),/HC-SR04\+ · GND/);
  const links=nodes(a.render(),node=>node.type==='button'&&node.props.className==='ai-diagram-open');
  assert.equal(links.length,1);assert.equal(links[0].props['aria-controls'],'current-step-diagram');
  assert.equal(links[0].props.disabled,false);links[0].props.onClick();
  assert.deepEqual(requests,[{snapshot,wireId:'hc:echo'}]);
  assert.equal(buttons(a.render(),'查看完整電路').length,0);
  assert.equal(buttons(a.render(),'前往此接線步驟').length,0);
});

test('old diagrams open their original read-only snapshot, not the new wiring',()=>{
  const requests=[];
  const card=cardHarness('../src/components/DiagramEvidenceCard.tsx','DiagramEvidenceCard',{snapshot,reference,currentDesign:{...design,revision:5,wiring:[{...wires[0],boardLabel:'Pin 9 · GND'},wires[1]]},onDiagram:request=>requests.push(request)});
  const html=renderToStaticMarkup(card.render());
  assert.match(html,/歷史版本・僅供檢視/);
  assert.match(html,/示意接法，非實物驗證/);
  assert.doesNotMatch(html,/前往此接線步驟/);
  nodes(card.render(),node=>node.type==='button'&&node.props.className==='ai-diagram-open')[0].props.onClick();
  assert.equal(requests[0].snapshot,snapshot);
  assert.equal(requests[0].snapshot.design.wiring[0].boardLabel,'Pin 6 · GND');
});

test('inspection accepts archived versions but rejects missing wires, foreign projects and unavailable frozen profiles',()=>{
  const before=structuredClone(snapshot);
  assert.deepEqual(helpers.createDiagramInspection(snapshot,'hc:echo',{...design,revision:99}),{snapshot,wireId:'hc:echo'});
  assert.equal(helpers.createDiagramInspection(snapshot,'invented',design),null);
  assert.equal(helpers.createDiagramInspection(snapshot,'hc:gnd',{...design,id:'other'}),null);
  assert.equal(helpers.createDiagramInspection({...snapshot,project_revision:1},'hc:gnd',design),null);
  assert.equal(helpers.createDiagramInspection({...snapshot,render_snapshot:{modules:[]}},'hc:gnd',design),null);
  assert.equal(helpers.createDiagramInspection({...snapshot,render_snapshot:{modules:[{id:'hc-sr04',pins:[],pin_order:[]}]}},'hc:gnd',design),null);
  assert.equal(helpers.createDiagramInspection(snapshot,'hc:gnd',null),null);
  assert.deepEqual(snapshot,before);
});

test('left-diagram viewing preserves confirmations, test binding, AI intent, code, candidate and conversations',()=>{
  const state={design,stage:'guide',code:'unchanged',prompt:'unsent',candidate:{id:'candidate'},conversation:[{role:'user',text:'unchanged'}],
    guide:{phase:'review',componentIndex:0,index:1,mode:'camera',confirmed:{'hc:gnd':{at:'original'}},checks:['ready'],inspectionReturn:{index:2,mode:'camera'}},
    debug:{panelOpen:true,intent:'debug',runId:'original-run',wireId:'original-wire',symptom:'original-symptom'}};
  const before=structuredClone(state), request={snapshot,wireId:'hc:gnd'};
  const viewed=helpers.inspectDiagramInMaker(state,request);
  assert.deepEqual(viewed,{...state,guide:{...state.guide,mode:'2d'}});
  for(const key of ['design','candidate','conversation'])assert.equal(viewed[key],state[key]);
  assert.equal(viewed.guide.confirmed,state.guide.confirmed);
  assert.equal(viewed.guide.inspectionReturn,state.guide.inspectionReturn);
  assert.deepEqual(viewed.debug,state.debug);
  assert.deepEqual(state,before);
  assert.equal(helpers.inspectDiagramInMaker(state,{snapshot,wireId:'invented'}),state);
  assert.equal(helpers.inspectDiagramInMaker({...state,design:{...design,id:'foreign'}},request).guide,state.guide);
});

test('a missing workspace handler disables the link and frozen divider precautions remain visible',()=>{
  const copy=structuredClone(snapshot);copy.design.wiring[1].connectionKind='divider';
  const card=cardHarness('../src/components/DiagramEvidenceCard.tsx','DiagramEvidenceCard',{snapshot:copy,reference:{...reference,initial_focus_wire_id:'hc:echo',caption:'保留原始引用說明'},currentDesign:design});
  assert.match(renderToStaticMarkup(card.render()),/ECHO 需分壓，不可直連 GPIO/);
  assert.match(renderToStaticMarkup(card.render()),/保留原始引用說明/);
  assert.equal(nodes(card.render(),node=>node.type==='button'&&node.props.className==='ai-diagram-open')[0].props.disabled,true);
});

test('the left workspace uses the frozen snapshot, and full circuit/return controls stay on the left',()=>{
  let returns=0;
  const inspection={snapshot,wireId:'hc:echo'};
  const view=cardHarness('../src/components/DiagramInspectionView.tsx','DiagramInspectionView',{inspection,currentDesign:{...design,revision:5},capturePending:true,onReturn(){returns++;}});
  const diagram=()=>nodes(view.render(),node=>typeof node.type==='function'&&node.props.workspace)[0];
  assert.equal(diagram().props.design,snapshot.design);
  assert.equal(diagram().props.frozenProfile,snapshot.render_snapshot);
  assert.equal(diagram().props.activeId,'hc:echo');
  assert.equal(diagram().props.focusLabel,'查看接法');
  assert.match(renderToStaticMarkup(view.render()),/歷史版本 · 僅供檢視/);
  assert.match(renderToStaticMarkup(view.render()),/AI 正在等待實物照片/);
  buttons(view.render(),'查看完整電路')[0].props.onClick();
  assert.equal(diagram().props.activeId,undefined);
  assert.equal(diagram().props.design,snapshot.design);
  buttons(view.render(),'返回 AI 指出的接線')[0].props.onClick();
  assert.equal(diagram().props.activeId,'hc:echo');
  buttons(view.render(),'返回目前步驟')[0].props.onClick();assert.equal(returns,1);
});

test('actual App linkage changes only display state and retains the AI panel and capture safeguards',()=>{
  const source=read('../src/App.tsx'), tree=ts.createSourceFile('App.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let handler;
  function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='inspectDiagram')handler=node.initializer;ts.forEachChild(node,visit);}visit(tree);
  const code=ts.transpileModule(`const inspect=${handler.getText(tree)};`,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const original={design,stage:'guide',code:'original-code',guide:{mode:'camera',index:1,phase:'review',confirmed:{saved:'confirmation'}},debug:{panelOpen:true,intent:'wiring',runId:'exact-run'},conversation:['original']};
  const request={snapshot,wireId:'hc:gnd'};
  for(const blocked of ['none','calibration','display','foreign']) {
    let state=original, evidence=null, override=null;const visibility=[];
    const inspect=new Function('calibrateOpen','displayModeActive','project','createDiagramInspection','setGuideVisible','setEvidenceDiagram','setDiagramCaptureOverride','diagramCaptureKey','setMaker','inspectDiagramInMaker',`${code};return inspect;`)(
      blocked==='calibration',blocked==='display',blocked==='foreign'?{...design,id:'foreign'}:design,helpers.createDiagramInspection,
      value=>visibility.push(value),update=>{evidence=update(evidence);},value=>{override=value;},'capture-one',update=>{state=update(state);},helpers.inspectDiagramInMaker);
    inspect(request);
    if(blocked==='none') {
      assert.deepEqual(state,{...original,guide:{...original.guide,mode:'2d'}});
      assert.deepEqual(evidence,{...request,requestId:1});
      assert.equal(override,'capture-one');assert.deepEqual(visibility,[true]);
      inspect(request);assert.equal(evidence.requestId,2,'opening the same reference must reset its local view');
    } else {assert.equal(state,original);assert.equal(evidence,null);assert.equal(override,null);assert.deepEqual(visibility,[]);}
  }
  assert.match(source,/onDiagram=\{inspectDiagram\}/);
  assert.match(source,/evidenceDiagram\.snapshot\.project_id === project\.id/,'project changes cannot display a foreign snapshot');
});

test('photo views switch within the same capture and expired views do not replace another image',()=>{
  const evidence={id:'capture',frame_id:10,available:true,captured_at:1,mode:'pin_crops',views:[{name:'pi_overview'},{name:'pi_pins'},{name:'component_pins',available:false}]};
  const card=cardHarness('../src/components/PhotoEvidenceCard.tsx','PhotoEvidenceCard',{evidence,sessionId:'old'});
  assert.match(renderToStaticMarkup(card.render()),/view=pi_overview/);
  buttons(card.render(),'Pi Pin 特寫')[0].props.onClick();
  assert.match(renderToStaticMarkup(card.render()),/view=pi_pins/);
  buttons(card.render(),'零件 Pin 特寫')[0].props.onClick();
  const html=renderToStaticMarkup(card.render());
  assert.match(html,/此張照片已無法取得/);
  assert.doesNotMatch(html,/<img/);
});
