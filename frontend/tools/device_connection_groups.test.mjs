import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import postcss from 'postcss';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const source=read('../src/components/DeviceConnectionGroups.tsx');
const jsx=(type,props)=>React.createElement(type,props);
const module={};
new Function('require','exports',ts.transpileModule(source,{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText)(id=>{
  if(id==='react/jsx-runtime')return {jsx,jsxs:jsx};
  if(id==='../deviceConnections.css')return {};
  throw Error(`Unexpected import ${id}`);
},module);

test('phone camera and Pi runtime have separate localized groups with decorative identity icons',()=>{
  for(const [phoneLabel,piLabel] of [['手機取景','Pi 執行'],['Phone camera','Pi runtime']]) {
    const html=renderToStaticMarkup(React.createElement(module.DeviceConnectionGroups,{
      phoneLabel,piLabel,
      phoneName:'Phone',piName:'Pi',
      phone:React.createElement('div',{className:'mobile-toolbar-slot'},'Phone control'),
      pi:React.createElement('div',{className:'pi-global-control'},'Pi controls'),
    }));
    assert.ok(html.includes(`is-phone" role="group" aria-label="${phoneLabel}"`));
    assert.ok(html.includes(`is-pi" role="group" aria-label="${piLabel}"`));
    assert.match(html,/is-phone[\s\S]*Phone control<\/div><\/div><div class="maker-device-group is-pi"[\s\S]*Pi controls/);
    assert.equal((html.match(/aria-hidden="true" focusable="false"/g)??[]).length,2);
    assert.match(html,/<span>Phone<\/span>/);
    assert.match(html,/<span>Pi<\/span>/);
    assert.doesNotMatch(html,/role="button"|tabindex|<button|<details/,'wrappers are not duplicate interactive controls');
  }
});

test('device grouping retains the existing phone portal, Pi component, and separate Settings',()=>{
  const app=read('../src/App.tsx');
  assert.match(app,/phone=\{<div className="mobile-toolbar-slot mobile-header-slot" ref=\{setMobileTriggerHost\} \/>\}/);
  assert.match(app,/pi=\{<PiConnectionControl \/>\}/);
  assert.match(app,/<\/div>\}\s*\{runtimeControls\}/);
  assert.match(app,/trigger: !displayModeActive \? mobileTriggerHost : null/);
  assert.doesNotMatch(source,/useEffect|useState|fetch\(|localStorage|onClick|createPortal/);
});

test('device styles separate purpose, preserve popovers, and stack on narrow screens',()=>{
  const css=postcss.parse(read('../src/deviceConnections.css'));
  const phone=[];let narrow=false;
  css.walkRules(rule=>{
    if(rule.selector.endsWith('.maker-device-group.is-phone')&&rule.parent.type==='root')rule.walkDecls(d=>phone.push([d.prop,d.value]));
    if(rule.parent.type==='atrule'&&rule.parent.params==='(max-width:700px)'&&rule.selector.endsWith('.maker-connection-controls.maker-device-connections')) {
      const values={};rule.walkDecls(d=>values[d.prop]=d.value);
      narrow=values.display==='contents';
    }
    if(rule.selector.endsWith('.maker-device-group'))rule.walkDecls('overflow',d=>assert.notEqual(d.value,'hidden'));
  });
  assert.ok(phone.some(([key,value])=>key==='border-color'&&value==='var(--line-blue)'));
  assert.ok(narrow);
  assert.match(read('../src/deviceConnections.css'),/\.pi-execution-popover \{\s*left:auto; right:0;/);
  assert.match(read('../src/deviceConnections.css'),/mobile-connect-button \{ min-height:44px; \}/);
});

test('header shortcuts hide only top-row text and preserve status dots and touch sizes',()=>{
  const css=read('../src/deviceConnections.css');
  assert.match(css,/\.maker-header-integrated :is\(\.mobile-connection-label,\.pi-device-state,\.pi-device-count,\.pi-header-stop-label,\.runtime-settings-label\)\s*\{[^}]*clip-path:inset\(50%\)/);
  assert.match(css,/\.maker-header-integrated :is\(\.mobile-device-icon,\.pi-device-icon,\.runtime-settings-icon\)\s*\{[^}]*display:block; width:17px; height:17px/);
  assert.match(css,/\.maker-header-integrated :is\(\.mobile-connection-dot,\.pi-device-dot\)\s*\{[^}]*position:absolute/);
  assert.match(css,/@media\(max-width:960px\)\s*\{[^}]*\.maker-header-integrated[^}]*width:44px; height:44px; min-width:44px; min-height:44px/);
});

test('real phone trigger keeps localized tooltip, accessible state and original click callback',()=>{
  const file=ts.createSourceFile('MobileCompanion.tsx',read('../src/components/MobileCompanion.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let trigger;
  function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(file)==='trigger')trigger=node.initializer.getText(file);ts.forEachChild(node,visit);}
  visit(file);assert.ok(trigger);
  const factory=new Function('React','phoneConnected','connectionError','connectionLabel','open','view','controller','showConnection','workspace','tr',
    ts.transpileModule(`const trigger=${trigger};`,{compilerOptions:{jsx:ts.JsxEmit.React}}).outputText+';return trigger;');
  for(const [connected,label] of [[false,'連接手機'],[true,'手機已連接'],[true,'Phone connected']]) {
    let clicks=0;
    const button=factory(React,connected,false,label,false,'connection',{project:{}},()=>clicks++,{trigger:{}},zh=>zh);
    assert.equal(button.props.title,label);assert.equal(button.props['aria-label'],label);
    assert.equal(button.props['data-connected'],connected);assert.equal(button.props['aria-controls'],'mobile-companion-panel');
    const html=renderToStaticMarkup(button);assert.match(html,/class="mobile-device-icon"[^>]*aria-hidden="true"/);
    assert.match(html,/class="mobile-connection-dot"/);button.props.onClick();assert.equal(clicks,1);
  }
});
