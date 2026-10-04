import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import {maker,componentTests,designFor} from './project_guide_fixture.mjs';

// Exercise the actual restart/edit event handler without camera, Pi, cloud or
// production storage. Rendering JSX does not invoke child components.
const require=createRequire(import.meta.url);
const compiled=ts.transpileModule(readFileSync(new URL('../src/components/ProjectGuidePanel.tsx',import.meta.url),'utf8'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText;
function fixture(failure='',inspection=false,options={}){
  const calls=[],errors=[],design=designFor(['hc-sr04','mrd-tf240-8p-cs']);
  const guide={...maker.emptyGuide(),phase:'review',run:2,inspection,
    confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),at:'original'}])),...options.session};
  const hooks={useMemo:fn=>fn(),useRef:value=>({current:value}),useEffect(){},useState:value=>[value,next=>errors.push(next)]};
  const tests={pending:false,status:{active:null,results:[]},invalidate:async cid=>{calls.push(['invalidate',cid]);return failure!=='invalidate';}};
  const exports={};
  new Function('require','exports',compiled)(name=>{
    if(name==='react')return hooks;
    if(name==='react/jsx-runtime')return require(name);
    if(name.endsWith('/maker'))return maker;
    if(name.endsWith('/componentTests'))return componentTests;
    if(name.endsWith('/useComponentTests'))return {useComponentTests:()=>tests};
    if(name.endsWith('/useMaker'))return {useMakerText:()=>zh=>zh};
    if(name.endsWith('/i18n'))return {useI18n:()=>({t:key=>key,tx:x=>x})};
    if(name.endsWith('/componentWiringGuides'))return {guideFor:()=>({name:'module',safety:'synthetic',unresolved:[]})};
    if(name.endsWith('/componentHeaderGuide'))return {componentHeaderGuideText:()=>null,componentModelName:id=>id};
    if(name.endsWith('/piHeaderGuide'))return {piHeaderGuideText:()=>null};
    return new Proxy({}, {get:()=>()=>null});
  },exports);
  const panel=exports.ProjectGuidePanel({design,session:guide,visible:true,pinsById:new Map(),disabled:false,floating:true,
    onTargetChange(){},onVisibleChange(){},onDeploy(){},onChange:next=>calls.push(['commit-edit',next]),
    onBeforeEdit:async cid=>{calls.push(['stop',cid]);if(failure==='stop')throw Error('hardware_work_active');return true;},
    onRestart:async next=>{calls.push(['reset-chat']);if(failure==='reset')throw Error('connection_lost');calls.push(['commit-round',next]);return true;},
    onInspectComponent:id=>calls.push(['inspect',id]),
  });
  function find(node,text){
    if(!node||typeof node!=='object')return null;
    if(node.type==='button'&&(node.props['aria-label']===text||JSON.stringify(node.props.children)?.includes(text)))return node;
    for(const child of Object.values(node.props??{}).flat()){const result=find(child,text);if(result)return result;}
    return null;
  }
  return {guide,design,calls,errors,restart:find(panel.props.headerActions,'重新開始接線引導'),
    edit:find(panel.props.actions,'我要修改此零件接線'),
    start:find(panel.props.actions,'開始接線'),
    moduleTabs:design.component_ids.map(id=>find(panel.props.progress,id)),
    async settle(){for(let i=0;i<25;i++)await Promise.resolve();}};
}
test('restart confirms stop and invalidation before clearing chat and committing a fresh guide',async()=>{
  const f=fixture();f.restart.props.onClick();f.restart.props.onClick();await f.settle();
  assert.deepEqual(f.calls.map(c=>c[0]),['stop','invalidate','reset-chat','commit-round']);
  assert.equal(f.calls[0][1],undefined);assert.equal(f.calls[1][1],undefined);
  const next=f.calls.at(-1)[1];assert.deepEqual(next.confirmed,{});assert.equal(next.run,3);
  assert.equal(next.phase,'prepare');assert.equal(next.componentIndex,0);assert.equal(next.index,0);
  assert.equal(Object.keys(f.guide.confirmed).length,f.design.wiring.length,'original input is not mutated');
});
for(const failure of ['stop','invalidate','reset'])test(`${failure} failure never commits a new wiring round`,async()=>{
  const f=fixture(failure);f.restart.props.onClick();await f.settle();
  assert.equal(f.calls.some(c=>c[0].startsWith('commit')),false);
  if(failure!=='reset')assert.equal(f.calls.some(c=>c[0]==='reset-chat'),false);
  assert.equal(Object.keys(f.guide.confirmed).length,f.design.wiring.length);
});
test('editing one component preserves the AI conversation and the other module confirmations',async()=>{
  const f=fixture('',true);assert.ok(f.edit);f.edit.props.onClick();await f.settle();
  assert.deepEqual(f.calls.map(c=>c[0]),['stop','invalidate','commit-edit']);
  assert.equal(f.calls[0][1],'hc-sr04');assert.equal(f.calls[1][1],'hc-sr04');
  const next=f.calls.at(-1)[1];
  assert(f.design.wiring.filter(w=>w.componentId==='mrd-tf240-8p-cs').every(w=>next.confirmed[w.id]===f.guide.confirmed[w.id]));
});
test('photo module tabs in prepare only select the module and cannot begin inspecting a wire',()=>{
  for(const index of [0,1]) {
    const f=fixture('',false,{session:{phase:'prepare',index:0,confirmed:{}}});
    const before=structuredClone(f.guide);
    assert.ok(f.moduleTabs[index]);f.moduleTabs[index].props.onClick();
    assert.deepEqual(f.calls.map(call=>call[0]),['commit-edit']);
    const next=f.calls[0][1];
    assert.equal(next.phase,'prepare');assert.equal(next.componentIndex,index);assert.equal(next.index,0);
    assert.equal(next.inspection,false);assert.equal(next.run,f.guide.run);assert.deepEqual(next.confirmed,{});
    assert.deepEqual(f.guide,before);
    const selected=fixture('',false,{session:next});
    assert.ok(selected.start);selected.start.props.onClick();
    const started=selected.calls[0][1];
    assert.equal(started.phase,'active');assert.equal(started.componentIndex,index);assert.equal(started.index,0);
  }
});
test('active photo module tabs keep explicit read-only wire inspection available',()=>{
  const f=fixture('',false,{session:{phase:'active'}});
  f.moduleTabs[1].props.onClick();
  assert.deepEqual(f.calls,[['inspect','mrd-tf240-8p-cs']]);
  assert.equal(Object.keys(f.guide.confirmed).length,f.design.wiring.length);
});
