import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import postcss from 'postcss';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const source=read('../src/components/WorkspaceHeader.tsx');
const jsx=(type,props)=>React.createElement(type,props);
const exports={};
new Function('require','exports',ts.transpileModule(source,{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText)(()=>({jsx,jsxs:jsx}),exports);

test('brand, workflow and controls keep stable wrappers for the single-row layout',()=>{
  const html=renderToStaticMarkup(React.createElement(exports.WorkspaceHeader,{
    brand:React.createElement('h1',null,'Tinkro'),
    navigation:React.createElement('nav',{'aria-label':'Maker workflow'},'Three stages'),
    saveStatus:React.createElement('small',{role:'status'},'Saved'),
  },React.createElement('button',null,'Existing control')));
  assert.match(html,/<header class="header maker-header maker-header-integrated">/);
  assert.match(html,/<div class="maker-header-main"><h1>Tinkro<\/h1><nav aria-label="Maker workflow">Three stages<\/nav><\/div>/);
  assert.match(html,/maker-header-controls"><button>Existing control<\/button><\/div><small role="status">Saved<\/small>/);
  assert.doesNotMatch(source,/useEffect|useState|fetch\(|localStorage|onClick/);
});

test('save failure remains a real visible alert rather than a hidden settings item',()=>{
  const html=renderToStaticMarkup(React.createElement(exports.WorkspaceHeader,{
    brand:'Tinkro',navigation:'Workflow',children:'Controls',
    saveStatus:React.createElement('small',{role:'alert'},'Storage failed; keep this page open'),
  }));
  assert.match(html,/<small role="alert">Storage failed; keep this page open<\/small>/);
  assert.doesNotMatch(html,/hidden|<details/);
});

test('App retains all existing control callbacks and the non-maker header fallback',()=>{
  const app=read('../src/App.tsx');
  assert.match(app,/makerEnabled \? <WorkspaceHeader brand=\{brand\}/);
  assert.match(app,/<MakerModelMenu state=\{maker\} setState=\{setMaker\} assistant=\{makerAI\}/);
  assert.match(app,/<PiConnectionControl \/>/);
  assert.match(app,/onControllerChange=\{\(boardId\) => void handleControllerChange\(boardId\)\}/);
  assert.match(app,/onLocaleChange=\{handleLocaleChange\}/);
  assert.match(app,/<\/WorkspaceHeader> : <header className="header">/);
  assert.match(app,/onClick=\{\(\) => navigateMaker\(stage\)\}/);
  assert.match(app,/saveStatus=\{makerSaved \? null : <small[^>]*role="alert"/);
  assert.doesNotMatch(app,/作品草稿已保存於此瀏覽器|Draft saved in this browser/);
  assert.match(app,/collapsible=\{makerEnabled && !displayModeActive\}/);
});

test('compact header reduces desktop spacing without fixed pane heights or clipped menus',()=>{
  const css=postcss.parse(read('../src/tinkro.css'));
  const scope='.app.tinkro-theme:not(.display-mode-active)';
  const properties=selector=>{
    const result={};
    css.walkRules(selector,rule=>{if(rule.parent.type==='root')rule.walkDecls(d=>result[d.prop]=d.value);});
    return result;
  };
  assert.equal(properties(scope+' .maker-header-integrated').display,'grid');
  assert.equal(properties(scope+' .maker-header-integrated')['grid-template-columns'],'minmax(0, 1fr) auto');
  assert.equal(properties(scope+' .maker-header-main').padding,'0');
  assert.equal(properties(scope+' .maker-header-main')['min-height'],'49px');
  assert.equal(properties(scope+' .maker-header-controls').padding,'0');
  assert.equal(properties(scope+' .maker-header-integrated:has(.runtime-error, .pi-global-error, .glasses-restore-error)')['grid-template-columns'],'minmax(0, 1fr)','errors may add a row but never squeeze stage navigation');
  assert.equal(properties(scope+' .maker-header-controls .runtime-settings .runtime-select')['grid-column'],'auto','reset legacy mobile locale placement');
  assert.equal(properties(scope+' .maker-header-main .maker-nav button')['min-height'],'34px');
  assert.equal(properties(scope+' .maker-header-controls .pi-global-row').height,'30px');
  const logo=properties(scope+' .maker-header-main .brand-logo');
  assert.equal(parseFloat(logo.width)/parseFloat(logo.height),128/40,'preserve wordmark proportions');
  for(const selector of ['.maker-header-integrated','.maker-header-main','.maker-header-controls']) {
    assert.equal(properties(scope+' '+selector).height,undefined);
    assert.notEqual(properties(scope+' '+selector).overflow,'hidden');
  }
});

test('narrow layouts retain 44px header controls and all three navigation targets',()=>{
  const css=postcss.parse(read('../src/tinkro.css'));
  const touchRules=[];
  css.walkAtRules('media',rule=>{
    if(rule.params==='(max-width: 960px)')rule.walkRules(child=>{
      if(child.selector.includes('.maker-header-'))child.walkDecls('min-height',d=>touchRules.push([child.selector,d.value]));
    });
  });
  assert.ok(touchRules.some(([selector,value])=>selector.includes('.runtime-select select')&&value==='44px'));
  assert.ok(touchRules.some(([selector,value])=>selector.includes('.maker-nav button')&&value==='44px'));
  assert.match(read('../src/App.tsx'),/\["design", "guide", "deploy"\]/);
});

function renderSettings({locale='en',collapsible=true,busy=false,disabled=false,error=null,controllers}={}) {
  const strings=JSON.parse(read(`../src/locales/${locale}.json`));
  const module={};
  new Function('require','exports',ts.transpileModule(read('../src/components/RuntimeToolbar.tsx'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText)(id=>{
    if(id==='react')return React;
    if(id==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:React.Fragment};
    if(id==='../lib/i18n')return {useI18n:()=>({locale,t:key=>strings[key],tx:value=>value})};
    if(id==='./ThemeSelect')return {ThemeSelect:()=>React.createElement('select',{'aria-label':'Theme'},React.createElement('option',null,'Dark'))};
    throw Error(`Unexpected import ${id}`);
  },module);
  return renderToStaticMarkup(React.createElement(module.RuntimeToolbar,{
    collapsible,busy,disabled,error,activeBoardId:'pi5',
    controllers:controllers??[{board_id:'pi5',name:'Raspberry Pi 5'}],
    onControllerChange:()=>{},onLocaleChange:()=>{},
  }));
}

test('Settings is localized, closed initially and keeps the original three controls mounted',()=>{
  for(const [locale,label] of [['en','Settings'],['zh-TW','設定']]) {
    const html=renderSettings({locale});
    assert.match(html,/<details class="runtime-settings">/);
    assert.ok(html.includes(`</span>${label}</summary>`));
    assert.equal((html.match(/<select /g)??[]).length,3);
    assert.match(html,/<summary aria-controls="([^"]+)">[\s\S]*<div class="runtime-settings-popover" id="\1">/);
    assert.match(html,/<option value="pi5" selected="">Raspberry Pi 5<\/option>/);
    assert.doesNotMatch(html,/<details[^>]*\bopen=/);
  }
});

test('controller errors remain outside collapsed Settings and non-maker toolbar stays inline',()=>{
  const html=renderSettings({error:'Controller failed'});
  assert.match(html,/<\/details><span class="runtime-error" role="status">Controller failed<\/span>$/);
  const inline=renderSettings({collapsible:false});
  assert.doesNotMatch(inline,/<details|runtime-settings/);
  assert.equal((inline.match(/<select /g)??[]).length,3);
});

test('moving controller into Settings preserves busy, disabled and empty-controller guards',()=>{
  for(const state of [{busy:true},{disabled:true},{controllers:[]}]) {
    const html=renderSettings(state);
    assert.match(html,/<select disabled="" aria-label="Select active controller">/);
    assert.doesNotMatch(html,/<select disabled="" aria-label="(?:Select interface language|Theme)"/);
  }
});

test('Settings disclosure keeps business state untouched and cleans up the outside listener',()=>{
  const runtime=read('../src/components/RuntimeToolbar.tsx');
  assert.doesNotMatch(runtime,/fetch\(|localStorage|sessionStorage|window.location|setMaker|useState/);
  assert.match(runtime,/document.addEventListener\("pointerdown", closeOutside, true\)/);
  assert.match(runtime,/return \(\) => document.removeEventListener\("pointerdown", closeOutside, true\)/);
  assert.match(runtime,/querySelector\("summary"\)\?\.focus\(\)/);
});
