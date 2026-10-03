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
