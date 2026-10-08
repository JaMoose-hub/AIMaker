import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import { maker, designFor } from './project_guide_fixture.mjs';

const read = name => readFileSync(new URL(name, import.meta.url), 'utf8');
function load(name, modules) {
  const exports = {};
  const code = ts.transpileModule(read(name), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  new Function('require', 'exports', code)(key => { assert.ok(key in modules, 'Unmocked import: '+key); return modules[key]; }, exports);
  return exports;
}
const helpers = load('../src/lib/hardwarePartsCheck.ts', { './maker': maker });
const resources = load('../src/lib/blueprintResources.ts', {});
const children = node => React.Children.toArray(node?.props?.children);
const find = (node, predicate) => !node || typeof node !== 'object' ? [] : [...(predicate(node) ? [node] : []), ...children(node).flatMap(child => find(child, predicate))];
function uiHarness(name, locale = 'zh-TW') {
  const values = []; let index = 0;
  const react = { ...React, useId: () => 'test', useEffect() {}, useRef: () => ({ current: null }),
    useState(initial) { const slot = index++; if (!(slot in values)) values[slot] = typeof initial === 'function' ? initial() : initial;
      return [values[slot], value => { values[slot] = typeof value === 'function' ? value(values[slot]) : value; }]; } };
  const modules = { react, 'react/jsx-runtime': jsx, '../lib/useMaker': { useMakerText: () => (zh,en) => locale==='en'?en:zh },
    '../lib/i18n': { useI18n: () => ({ locale, tx: value => value[locale] }) }, '../lib/hardwarePartsCheck': helpers,
    '../lib/headerPanels': {usePhoneUploadEntry:()=>({request:0,open:()=>{}})}, '../lib/blueprintResources':resources,
    '../lib/maker': maker, '../lib/systemText': { systemText: text => text }, '../lib/materialPricing': { materialUsdEstimate:()=>'$0', MATERIAL_USD_REFERENCE:{} },
    '../lib/componentWiringGuides': { guideFor:id=>({...maker.makerCatalog.modules.find(m=>m.id===id),safety:{en:'Check specifications','zh-TW':'核對規格'}}) },
    './CircuitDiagram':{CircuitDiagram:'MockDiagram'}, './DesignViewSwitch':{DesignViewSwitch:'MockViewSwitch'},
    './HardwarePartsCheck':{HardwarePartsCheck:'MockCheck'}, './BlueprintPage.css':{} };
  modules['./MaterialPartArt']={MaterialPartArt:'MockPartArt'};
  modules['./AssemblyGuide']={AssemblyGuide:'MockAssembly'};
  const exports = load(name,modules);
  const component = exports.HardwarePartsCheck ?? exports.BlueprintPage;
  return { render(props) { index=0; return component(props); } };
}

test('English ECHO requirements remain visible and accessible outside a short input placeholder',()=>{
  const tree=uiHarness('../src/components/HardwarePartsCheck.tsx','en').render({});
  const input=find(tree,node=>node.type==='input'&&node.props.placeholder==='Model and voltage')[0];
  assert.ok(input);const hint=find(tree,node=>node.props?.id===input.props['aria-describedby'])[0];
  assert.ok(hint);assert.match(children(hint).join(''),/supply voltage and ECHO rating/);
  assert.match(children(hint).join(''),/does not mean the same variant/);
});

for (const locale of ['zh-TW','en']) test(`hardware comparison ${locale} scopes exactly three canonical electronics and keeps missing evidence uncertain`,()=>{
  const input=helpers.emptyPurchasedHardware();input['hc-sr04']='HC-SR04 generic';
  const prompt=helpers.hardwarePartsCheckPrompt(input,locale,false);
  assert.deepEqual(helpers.demoHardware,['raspberry-pi-5','hc-sr04','mrd-tf240-8p-cs']);
  assert.equal(prompt.split('\n').filter(line=>/^[123]\. /.test(line)).length,3);
  assert.match(prompt,/HC-SR04 generic/);
  assert.match(prompt,/HC-SR04\+ \/ 3.3V/);assert.match(prompt,/ILI9341/);
  assert.doesNotMatch(prompt,/motor|wheel|wires/);
  assert.match(prompt,locale==='en'?/No photo is supplied/:/這次沒有附照片/);
  assert.match(prompt,locale==='en'?/Not provided; cannot confirm/:/未提供，無法確認/);
  assert.match(prompt,locale==='en'?/exactly three short bullets/:/只回覆三個短條列/);
  assert.match(prompt,locale==='en'?/Right part \/ Wrong part \/ Cannot confirm/:/買對／買錯／還不能確認/);
  assert.match(prompt,locale==='en'?/No table, introduction, conclusion/:/不用表格、開場、總結/);
  assert.match(prompt,locale==='en'?/Similar appearance and purpose count as Right part/:/外觀與用途接近就說買對/);
  assert.match(prompt,locale==='en'?/For Right part, add no explanation/:/買對不用解釋/);
  assert.match(prompt,locale==='en'?/only for a clearly different hardware type/:/明顯是不同零件類型才說買錯/);
  assert.equal(input['raspberry-pi-5'],'');
});

test('hardware check opens without an AI request; empty evidence cannot submit',()=>{
  let calls=0;const h=uiHarness('../src/components/HardwarePartsCheck.tsx');
  const tree=h.render({onAsk:()=>{calls++;return Promise.resolve(true);}});
  assert.equal(find(tree,n=>n.type==='li').length,3);
  assert.equal(find(tree,n=>n.type==='input').length,3);
  assert.equal(find(tree,n=>n.props.className==='maker-primary')[0].props.disabled,true);
  assert.equal(calls,0);
});

test('explicit hardware check sends only entered evidence and reports sent, not verified',async()=>{
  const calls=[],h=uiHarness('../src/components/HardwarePartsCheck.tsx');
  const props={onAsk:async(...args)=>{calls.push(args);return true;}};
  find(h.render(props),n=>n.type==='input')[0].props.onChange({target:{value:'Raspberry Pi 5 16GB'}});
  const send=find(h.render(props),n=>n.props.className==='maker-primary')[0];assert.equal(send.props.disabled,false);
  await send.props.onClick();
  // onClick delegates without blocking the UI; settle the accepted callback.
  await Promise.resolve();await Promise.resolve();
  assert.equal(calls.length,1);assert.equal(calls[0][1],false);assert.match(calls[0][0],/Raspberry Pi 5 16GB/);
  assert.match(find(h.render(props),n=>n.props.role==='status')[0].props.children,/已送出/);
});

test('photo reference is opt-in and consent does not carry over to a replacement with the same filename',()=>{
  const h=uiHarness('../src/components/HardwarePartsCheck.tsx');
  const props={photoLabel:'parts.jpg',photoKey:'capture-1',onAsk:async()=>true};
  let tree=h.render(props);const photo=find(tree,n=>n.type==='input'&&n.props.type==='checkbox')[0];
  assert.equal(photo.props.checked,false);assert.equal(find(tree,n=>n.props.className==='maker-primary')[0].props.disabled,true);
  photo.props.onChange({target:{checked:true}});tree=h.render(props);
  assert.equal(find(tree,n=>n.props.className==='maker-primary')[0].props.disabled,false);
  tree=h.render({...props,photoKey:'capture-2'});
  assert.equal(find(tree,n=>n.type==='input'&&n.props.type==='checkbox')[0].props.checked,false);
  assert.equal(find(tree,n=>n.props.className==='maker-primary')[0].props.disabled,true);
});

test('failed hardware submission keeps entered evidence and does not assert a match',async()=>{
  const h=uiHarness('../src/components/HardwarePartsCheck.tsx'),props={onAsk:async()=>false};
  find(h.render(props),n=>n.type==='input')[1].props.onChange({target:{value:'Unknown sensor'}});
  find(h.render(props),n=>n.props.className==='maker-primary')[0].props.onClick();await Promise.resolve();await Promise.resolve();
  const tree=h.render(props);assert.equal(find(tree,n=>n.type==='input')[1].props.value,'Unknown sensor');
  assert.match(find(tree,n=>n.props.role==='status')[0].props.children,/尚未送出/);
});

test('busy / unavailable AI disables hardware comparison without removing the inputs',()=>{
  const h=uiHarness('../src/components/HardwarePartsCheck.tsx');
  const props={onAsk:async()=>true,disabledReason:'AI unavailable'};
  find(h.render(props),n=>n.type==='input')[0].props.onChange({target:{value:'Pi5'}});
  const tree=h.render(props);assert.equal(find(tree,n=>n.props.className==='maker-primary')[0].props.disabled,true);
  assert.equal(find(tree,n=>n.type==='input').length,3);
});

test('01 resource tabs precede one mounted diagram, default to overview and keep materials / instructions intact',()=>{
  const design=designFor(),before=JSON.stringify(design),h=uiHarness('../src/components/BlueprintPage.tsx');
  const props={design,onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false};
  let tree=h.render(props);
  const tabs=find(tree,n=>n.props.role==='tab');assert.equal(tabs.length,3);
  assert.equal(tabs.find(n=>n.props['aria-selected']).props['data-tab'],'overview');
  assert.equal(find(tree,n=>n.type==='MockDiagram').length,1);
  assert.equal(find(tree,n=>n.type==='details'&&n.props.className==='assistant-build-details').length,0);
  tabs.find(n=>n.props['data-tab']==='materials').props.onClick();tree=h.render(props);
  assert.equal(find(tree,n=>n.props.role==='tabpanel'&&!n.props.hidden).length,1);
  assert.equal(find(tree,n=>n.props.role==='tabpanel'&&!n.props.hidden)[0].props.id,'test-materials-panel');
  assert.equal(JSON.stringify(design),before);assert.equal(find(tree,n=>n.type==='MockDiagram').length,1);
});

test('demo hides both hardware-check entries and skips the hidden feature with keyboard navigation',()=>{
  for(const locale of ['zh-TW','en']){
    const h=uiHarness('../src/components/BlueprintPage.tsx',locale);
    const props={design:designFor(),onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false};
    let tree=h.render(props);
    assert.deepEqual(find(tree,n=>n.props.role==='tab').map(n=>n.props['data-tab']),['overview','materials','steps']);
    assert.equal(find(tree,n=>n.props.className==='blueprint-check-shortcut'||n.type==='MockCheck').length,0);
    find(tree,n=>n.props.role==='tab'&&n.props['data-tab']==='overview')[0].props.onKeyDown({key:'ArrowRight',preventDefault(){}});
    tree=h.render(props);
    assert.equal(find(tree,n=>n.props.role==='tab'&&n.props['aria-selected'])[0].props['data-tab'],'materials');
  }
});

test('hardware check remains explicitly re-enableable and hiding an active check returns to overview',()=>{
  const h=uiHarness('../src/components/BlueprintPage.tsx');
  const props={design:designFor(),onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false,partsCheckEnabled:true};
  let tree=h.render(props);
  assert.equal(find(tree,n=>n.props.role==='tab').length,4);
  find(tree,n=>n.props.className==='blueprint-check-shortcut')[0].props.onClick();tree=h.render(props);
  assert.equal(find(tree,n=>n.props.role==='tabpanel'&&!n.props.hidden)[0].props.id,'test-parts-check-panel');
  tree=h.render({...props,partsCheckEnabled:false});
  assert.equal(find(tree,n=>n.type==='MockCheck').length,0);
  assert.equal(find(tree,n=>n.props.role==='tabpanel'&&!n.props.hidden)[0].props.id,'test-overview-panel');
});

test('resource tabs support keyboard wrap and clicking an instruction returns to its highlighted diagram',()=>{
  const h=uiHarness('../src/components/BlueprintPage.tsx'),design=designFor();
  const props={design,onGuide(){},onEdit(){},onViewChange(){},hasCandidate:false,generating:false};
  let tree=h.render(props);
  find(tree,n=>n.props.role==='tab'&&n.props['data-tab']==='overview')[0].props.onKeyDown({key:'ArrowLeft',preventDefault(){}});
  tree=h.render(props);assert.equal(find(tree,n=>n.props.role==='tab'&&n.props['aria-selected'])[0].props['data-tab'],'steps');
  find(tree,n=>n.props['data-blueprint-wire'])[0].props.onClick();tree=h.render(props);
  assert.equal(find(tree,n=>n.props.role==='tab'&&n.props['aria-selected'])[0].props['data-tab'],'overview');
  assert.equal(find(tree,n=>n.type==='MockDiagram')[0].props.selectedId,design.wiring[0].id);
});

test('hardware photo entry opens the existing phone panel without triggering comparison',()=>{
  const h=uiHarness('../src/components/HardwarePartsCheck.tsx');
  let requests=0;const tree=h.render({onAsk:async()=>{requests++;return true;}});
  const upload=find(tree,n=>n.props.className==='blueprint-upload-entry')[0];
  find(upload,n=>n.type==='button')[0].props.onClick();
  assert.equal(requests,0);assert.equal(find(tree,n=>n.type==='input').length,3);
});
