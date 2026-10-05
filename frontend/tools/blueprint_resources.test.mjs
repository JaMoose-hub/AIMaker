import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
function load(path,modules={}) {
  const exports={};const code=ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  new Function('require','exports',code)(id=>{assert.ok(id in modules,id);return modules[id];},exports);return exports;
}
const resources=load('../src/lib/blueprintResources.ts');
const nodes=node=>!React.isValidElement(node)?[]:[node,...React.Children.toArray(node.props.children).flatMap(nodes)];
test('purchase links use official Pi entry and exact sensor/display searches without inventing stores',()=>{
  assert.equal(resources.materialPurchaseLink({id:'raspberry-pi-5',name:'Pi'}).url,'https://www.raspberrypi.com/products/raspberry-pi-5/');
  for(const [id,terms] of [['hc-sr04',['HC-SR04+','3.3V','ECHO']],['mrd-tf240-8p-cs',['MRD_TFT240_8P_CS','ILI9341','8 pin']]]) {
    const link=resources.materialPurchaseLink({id,name:'ignored'}),url=new URL(link.url);
    assert.equal(link.official,false);assert.equal(url.origin,'https://www.google.com');
    assert.equal(url.searchParams.get('tbm'),'shop');for(const term of terms)assert.ok(url.searchParams.get('q').includes(term));
  }
});
test('untrusted material names are encoded as search text, never an executable URL',()=>{
  const name='javascript:alert(1)&next=https://bad.invalid';const url=new URL(resources.materialPurchaseLink({id:'custom',name}).url);
  assert.equal(url.origin,'https://www.google.com');assert.equal(url.searchParams.get('q'),name);assert.equal(url.searchParams.get('next'),null);
});
test('bilingual labels are compact and assembly splitting preserves every character of the source',()=>{
  assert.equal(resources.conciseMaterialName('輪子 / 輪子 / Wheel','zh-TW'),'輪子');assert.equal(resources.conciseMaterialName('輪子 / Wheel','en'),'Wheel');
  const line='先斷電；確認 ECHO 3.3V。不要直連 5V。';assert.equal(resources.assemblyActions(line).join(''),line);
});
test('assembly only advances reading progress and calls wiring entry on the final explicit action',()=>{
  let slot=0,cursor=0,calls=0;const react={...React,useState:init=>{if(cursor++===0&&slot===undefined)slot=init;return[slot,value=>{slot=value;}];}};
  const {AssemblyGuide}=load('../src/components/AssemblyGuide.tsx',{react,'react/jsx-runtime':jsx,'../lib/useMaker':{useMakerText:()=>(zh)=>zh},'../lib/blueprintResources':resources});
  const instructions=['先斷電；保留散熱。','核對供電；保留 BLK 未接。'],props={instructions,onGuide:()=>calls++};const render=()=>{cursor=0;return AssemblyGuide(props);};
  let tree=render();assert.equal(calls,0);assert.equal(nodes(tree).find(n=>n.type==='output').props.children.join(''),'1 / 2');
  nodes(tree).find(n=>n.type==='button'&&n.props.className==='maker-primary').props.onClick();tree=render();assert.equal(calls,0);
  assert.equal(nodes(tree).filter(n=>n.props.className==='blueprint-assembly-card').length,1);
  assert.equal(nodes(tree).find(n=>n.type==='output').props.children.join(''),'2 / 2');
  nodes(tree).find(n=>n.type==='button'&&n.props.className==='maker-primary').props.onClick();assert.equal(calls,1);assert.deepEqual(instructions,props.instructions);
});
test('blueprint expands diagram space without removing electrical precautions from existing guide views',()=>{
  const page=read('../src/components/BlueprintPage.tsx'),diagram=read('../src/components/CircuitDiagram.tsx');
  assert.match(page,/workspace readableDefault hideWorkspaceNotes/);assert.match(diagram,/hideWorkspaceNotes = false/);
  assert.match(page,/規格與接線注意事項/);assert.match(page,/guideFor\(componentId\).safety/);
});

function compactHeader({hasCandidate=false,generating=false,locale='zh-TW'}={}) {
  const calls=[];
  const {BlueprintPage}=load('../src/components/BlueprintPage.tsx',{
    react:{...React,useEffect(){},useId:()=> 'header-fixture',useRef:value=>({current:value}),useState:value=>[value,()=>{}]},
    'react/jsx-runtime':jsx,'../lib/maker':{makerCatalog:{modules:[]},structuralParts:{}},
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='zh-TW'?zh:en},
    '../lib/i18n':{useI18n:()=>({locale,tx:value=>value})},'../lib/systemText':{systemText:text=>text},
    '../lib/blueprintResources':resources,'../lib/componentWiringGuides':{guideFor:()=>({})},
    './CircuitDiagram':{CircuitDiagram:'circuit'},'./DesignViewSwitch':{DesignViewSwitch:'view-switch'},
    './HardwarePartsCheck':{HardwarePartsCheck:'parts-check'},'./AssemblyGuide':{AssemblyGuide:'assembly'},'./BlueprintPage.css':{},
  });
  const design={title:'桌上型三輪測距恐龍',revision:6,source:'user',bom:[],wiring:[],component_ids:[],instructions:[],unresolved:[]};
  const tree=BlueprintPage({design,hasCandidate,generating,onGuide:()=>calls.push('guide'),onEdit:()=>calls.push('edit'),onViewChange(){}});
  return {tree,calls};
}

test('candidate and background status stay in the compact title metadata, never separate page rows',()=>{
  for(const locale of ['zh-TW','en']) {
    const f=compactHeader({hasCandidate:true,generating:true,locale});
    const page=nodes(f.tree).find(n=>n.props.className==='maker-preview maker-blueprint-page');
    const meta=nodes(f.tree).find(n=>n.props.className==='blueprint-title-meta');
    const notice=nodes(meta).find(n=>n.type==='button');
    assert.ok(notice.props['aria-label'].includes(locale==='zh-TW'?'返回設計':'Design'));
    assert.equal(nodes(meta).filter(n=>n.props.role==='status').length,1);
    assert.equal(React.Children.toArray(page.props.children).filter(n=>n.props?.className?.includes('maker-candidate-notice')||n.props?.role==='status').length,0);
    assert.deepEqual(f.calls,[]);
    notice.props.onClick();assert.deepEqual(f.calls,['edit']);
    nodes(f.tree).find(n=>n.type==='button'&&n.props.className==='maker-primary').props.onClick();
    assert.deepEqual(f.calls,['edit','guide']);
  }
});

test('compact header without updates retains the title, tabs and explicit hardware check entry',()=>{
  const f=compactHeader();
  assert.equal(nodes(f.tree).filter(n=>n.props.className==='maker-candidate-notice blueprint-revision-link'||n.props.role==='status').length,0);
  assert.equal(nodes(f.tree).find(n=>n.type==='h2').props.children,'桌上型三輪測距恐龍');
  assert.equal(nodes(f.tree).filter(n=>n.props.role==='tab').length,4);
  assert.equal(nodes(f.tree).filter(n=>n.props.className==='blueprint-check-shortcut').length,1);
  assert.deepEqual(f.calls,[]);
});
