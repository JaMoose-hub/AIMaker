import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

function load(path,modules={}) {
  const exports={};
  const source=readFileSync(new URL(path,import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  new Function('require','exports',code)(id=>{assert.ok(id in modules,id);return modules[id];},exports);
  return exports;
}
const resources=load('../src/lib/blueprintResources.ts');
const moduleArt=load('../src/components/CircuitModuleArt.tsx',{'react/jsx-runtime':jsx,'../lib/circuitLayout':{MODULE_WIDTH:352}});
const {MaterialPartArt}=load('../src/components/MaterialPartArt.tsx',{'react/jsx-runtime':jsx,'../lib/blueprintResources':resources,'./CircuitModuleArt':moduleArt});
const kinds={
  'raspberry-pi-5':'pi5','hc-sr04':'ultrasonic','mrd-tf240-8p-cs':'tft','jumper-wires':'jumper',
  breadboard:'breadboard','resistor-330':'resistor','resistor-470':'resistor','power-supply':'power','micro-sd':'storage',
  'structure-wheel':'wheel','structure-axle':'axle','structure-standoff':'standoff',
  'structure-acrylic-panel':'acrylic-panel','structure-bracket':'bracket','structure-screw':'screw',
};

test('existing BOM and structural IDs select their illustration without changing catalogue or quantities',()=>{
  for(const [id,kind] of Object.entries(kinds)){
    const item=Object.freeze({id,name:id,quantity:4,purpose:'original',price:100});
    assert.equal(resources.materialIllustrationKind(item),kind);
    assert.deepEqual(item,{id,name:id,quantity:4,purpose:'original',price:100});
  }
});

test('bilingual descriptive names work and unknown parts get a neutral illustration',()=>{
  for(const [name,kind] of [['Raspberry Pi 5','pi5'],['樹莓派 5','pi5'],['杜邦線 / Jumper wires','jumper'],['TFT 螢幕','tft'],['超音波感測器','ultrasonic'],['麵包板','breadboard'],['電阻','resistor'],['USB-C 電源','power'],['microSD card','storage']]){
    assert.equal(resources.materialIllustrationKind({id:'custom',name}),kind);
  }
  assert.equal(resources.materialIllustrationKind({id:'unknown',name:'Unspecified module'}),'generic');
  for(const id of ['constructor','__proto__','toString']) assert.equal(resources.materialIllustrationKind({id,name:'Unspecified module'}),'generic');
});

test('every illustration is a local accessible SVG, not an interactive or downloaded image',()=>{
  for(const [id,kind] of Object.entries({...kinds,unknown:'generic'})){
    const label=`${id} · Part illustration`;
    const svg=MaterialPartArt({material:{id,name:id},label});
    assert.equal(svg.type,'svg');
    assert.equal(svg.props.role,'img');
    assert.equal(svg.props['aria-label'],label);
    assert.equal(svg.props['data-part-art'],kind);
    assert.equal(svg.props.viewBox,'0 0 420 280');
    assert.equal(svg.props.focusable,'false');
    const markup=renderToStaticMarkup(svg);
    assert.doesNotMatch(markup,/<(?:image|script|foreignObject|button|a)[\s>]|\s(?:href|onClick|onLoad)=/i);
    assert.match(markup,/pointer-events="none"/);
  }
  const unsafe=renderToStaticMarkup(MaterialPartArt({material:{id:'unknown',name:'unknown'},label:'<img src=x onerror=alert(1)>'}));
  assert.match(unsafe,/&lt;img/);
  assert.doesNotMatch(unsafe,/<img/);
});

test('ultrasonic and TFT reuse the existing module artwork and Pi GPIO is decorative',()=>{
  const render=id=>renderToStaticMarkup(MaterialPartArt({material:{id,name:id},label:'Part illustration'}));
  assert.match(render('hc-sr04'),/HC-SR04/);
  assert.match(render('mrd-tf240-8p-cs'),/DISPLAY OFF/);
  assert.match(render('raspberry-pi-5'),/Raspberry Pi/);
  assert.equal((render('raspberry-pi-5').match(/fill="#dbbc71"/g)??[]).length,40);
});

const nodes=node=>!React.isValidElement(node)?[]:[node,...React.Children.toArray(node.props.children).flatMap(nodes)];
test('Find parts adds one bilingual illustration per card and preserves existing links and quantities',()=>{
  for(const locale of ['zh-TW','en']){
    const {BlueprintPage}=load('../src/components/BlueprintPage.tsx',{
      react:{...React,useEffect(){},useId:()=> 'part-fixture',useRef:value=>({current:value}),useState:value=>[value,()=>{}]},
      'react/jsx-runtime':jsx,'../lib/maker':{makerCatalog:{modules:[]},structuralParts:{standoff:{name:'支柱 / Standoff',price:20}}},
      '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='zh-TW'?zh:en},
      '../lib/i18n':{useI18n:()=>({locale,tx:value=>value})},'../lib/systemText':{systemText:text=>text},
      '../lib/blueprintResources':resources,'../lib/componentWiringGuides':{guideFor:()=>({})},
      './CircuitDiagram':{CircuitDiagram:'circuit'},'./DesignViewSwitch':{DesignViewSwitch:'view-switch'},
      './HardwarePartsCheck':{HardwarePartsCheck:'parts-check'},'./AssemblyGuide':{AssemblyGuide:'assembly'},
      './MaterialPartArt':{MaterialPartArt},'./BlueprintPage.css':{},
    });
    const design={id:'fixture',title:'Fixture',revision:1,source:'user',wiring:[],component_ids:[],instructions:[],unresolved:[],
      bom:Object.keys(kinds).filter(id=>!id.startsWith('structure-')).map((id,i)=>({id,name:id,quantity:i+1,purpose:'Original purpose',price:100})),
      assembly:{parts:[{kind:'standoff',quantity:4,purpose:'Original structural purpose'}]}};
    const original=JSON.stringify(design);
    let calls=0;
    const tree=BlueprintPage({design,hasCandidate:false,generating:false,onGuide:()=>calls++,onEdit:()=>calls++,onViewChange:()=>calls++});
    const cards=nodes(tree).filter(n=>n.props.className==='blueprint-shop-card');
    assert.equal(cards.length,design.bom.length+1);
    cards.forEach((card,i)=>{
      const item=i<design.bom.length?design.bom[i]:{id:'structure-standoff',name:locale==='en'?'Standoff':'支柱',quantity:4};
      const children=nodes(card),art=children.filter(n=>n.type===MaterialPartArt);
      assert.equal(art.length,1);
      assert.match(art[0].props.label,locale==='en'?/Part illustration/:/零件示意圖/);
      assert.equal(children.find(n=>n.props.className==='blueprint-shop-art-caption').props.children,locale==='en'?'Illustration':'示意圖');
      assert.equal(children.find(n=>n.props.className==='blueprint-shop-quantity').props.children.join(''),`× ${item.quantity}`);
      const link=children.find(n=>n.type==='a');
      assert.equal(link.props.href,resources.materialPurchaseLink(item).url);
      assert.equal(link.props.rel,'noopener noreferrer');
      assert.equal(link.props.target,'_blank');
    });
    assert.equal(calls,0);
    assert.equal(JSON.stringify(design),original);
  }
});
