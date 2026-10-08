import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import {systemTextUrl} from './system_text_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const url=text=>`data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
const compile=text=>ts.transpileModule(text,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const pricingUrl=url(compile(read('../src/lib/materialPricing.ts')));
const {materialUsdEstimate,MATERIAL_USD_REFERENCE}=await import(pricingUrl);
const resourceUrl=url(compile(read('../src/lib/blueprintResources.ts')));

test('USD reference is pinned, dated and attributed without live fetching',()=>{
  assert.deepEqual(MATERIAL_USD_REFERENCE,{twdPerUsd:31.842,date:'2026-10-01',source:'https://www.cbc.gov.tw/en/lp-700-2.html'});
  assert.doesNotMatch(read('../src/lib/materialPricing.ts'),/fetch\(|localStorage|sessionStorage/);
});

test('USD estimates convert original TWD unit prices, including quantities before rounding',()=>{
  assert.equal(materialUsdEstimate(2500),'US$78.51');
  assert.equal(materialUsdEstimate(65),'US$2.04');
  assert.equal(materialUsdEstimate(220),'US$6.91');
  assert.equal(materialUsdEstimate(2,11),'US$0.69');
  assert.equal(materialUsdEstimate(30,3),'US$2.83');
  assert.equal(materialUsdEstimate(60,2),'US$3.77');
  assert.equal(materialUsdEstimate(0,1),'US$0.00');
  assert.equal(materialUsdEstimate(2500,0),'US$0.00');
  assert.equal(materialUsdEstimate(318420),'US$10,000.00');
});

test('invalid estimates do not leak NaN, Infinity or negative retail prices',()=>{
  for(const [price,quantity] of [[NaN,1],[Infinity,1],[-1,1],[1,-1],[1,Infinity],[1,NaN],[Number.MAX_VALUE,2]]) {
    assert.equal(materialUsdEstimate(price,quantity),null);
  }
});

async function blueprint(locale) {
  let js=compile(read('../src/components/BlueprintPage.tsx'));
  js=js.replace(/import ["']\.\/BlueprintPage\.css["'];?/, '');
  const replacements={
    react:import.meta.resolve('react'),'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
    '../lib/maker':url('export const makerCatalog={modules:[]};export const structuralParts={wheel:{name:"Wheel",price:30}};'),
    '../lib/useMaker':url(`export const useMakerText=()=>(zh,en)=>${locale==='en'?'en':'zh'};`),
    '../lib/i18n':url(`export const useI18n=()=>({locale:${JSON.stringify(locale)},tx:v=>v[${JSON.stringify(locale)}]});`),
    '../lib/systemText':systemTextUrl,'../lib/materialPricing':pricingUrl,'../lib/blueprintResources':resourceUrl,
    '../lib/componentWiringGuides':url('export const guideFor=()=>({name:{en:"Sensor","zh-TW":"感測器"},safety:{en:"Verify ratings","zh-TW":"核對規格"}});'),
    './CircuitDiagram':url('export const CircuitDiagram=()=>null;'),
    './MakerSplitLayout':url(`import {createElement} from ${JSON.stringify(import.meta.resolve('react'))};export const MakerSplitLayout=({left,children})=>createElement('main',{},left,children);`),
    './DesignViewSwitch':url('export const DesignViewSwitch=()=>null;'),
    './HardwarePartsCheck':url('export const HardwarePartsCheck=()=>null;'),
    './MaterialPartArt':url('export const MaterialPartArt=()=>null;'),
    './AssemblyGuide':url(`import {createElement} from ${JSON.stringify(import.meta.resolve('react'))};export const AssemblyGuide=({instructions})=>createElement('div',{},instructions);`),
  };
  for(const [from,to] of Object.entries(replacements)) js=js.replaceAll(JSON.stringify(from),JSON.stringify(to));
  return (await import(url(js))).BlueprintPage;
}
const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
const design=freeze({id:'original-project',revision:7,source:'ai',title:'Existing project',bom:[
  {id:'pi',name:'Raspberry Pi 5',purpose:'Controller',quantity:1,price:2500},
  {id:'wires',name:'Jumper wires',purpose:'Connections',quantity:11,price:2},
  {id:'unknown',name:'Unknown part',purpose:'Unpriced',quantity:1,price:NaN},
],assembly:{description:'Existing assembly',parts:[{kind:'wheel',quantity:3,purpose:'Manual wheels'}]},component_ids:[],wiring:[],instructions:['Keep the existing instruction'],unresolved:[]});

for(const locale of ['zh-TW','en']) test(`Blueprint ${locale} ignores image-only motors entirely`,async()=>{
  const BlueprintPage=await blueprint(locale);
  const props={onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false};
  const base=renderToStaticMarkup(createElement(BlueprintPage,{...props,design}));
  const visual={...design,concept_only_parts:[{kind:'motor',quantity:2,purpose:'Concept motor'}]};
  assert.equal(renderToStaticMarkup(createElement(BlueprintPage,{...props,design:visual})),base);
});

for(const locale of ['zh-TW','en']) test(`Blueprint ${locale} presents purchase links without fictitious retail prices or mutating BOM`,async()=>{
  const before=JSON.stringify(design);
  const BlueprintPage=await blueprint(locale);
  const html=renderToStaticMarkup(createElement(BlueprintPage,{design,onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false}));
  assert.equal(JSON.stringify(design),before);
  assert.equal(design.bom[0].price,2500);
  const cards=html.match(/<article[\s\S]*?<\/article>/g);
  assert.equal(cards.length,4);
  assert.match(cards[1],/× 11/);
  assert.match(cards[3],/× 3/);
  for(const card of cards) {
    assert.doesNotMatch(card,/NT\$|US\$|NaN|Infinity|Demo shop|示範導購/);
    assert.match(card,/href="https:\/\/www.google.com\/search\?tbm=shop&amp;q=/);
    assert.match(card,/target="_blank" rel="noopener noreferrer"/);
  }
  assert.match(html,locale==='en'?/Find parts/:/購買材料/);
  assert.match(html,locale==='en'?/External product links/:/外部商品入口/);
  assert.match(html,locale==='en'?/Partners wanted/:/招商中/);
  assert.match(html,locale==='en'?/Electronic component manufacturers welcome/:/歡迎電子零件廠合作/);
  assert.match(html,/Keep the existing instruction/);
  assert.doesNotMatch(html,/<dialog|合作招商中/);
});
