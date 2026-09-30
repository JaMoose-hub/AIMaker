import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const source=read('../src/components/WorkspaceHeader.tsx');
const jsx=(type,props)=>React.createElement(type,props);
const exports={};
new Function('require','exports',ts.transpileModule(source,{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText)(()=>({jsx,jsxs:jsx}),exports);

test('brand and workflow are siblings in one header row, controls are a separate compact strip',()=>{
  const html=renderToStaticMarkup(React.createElement(exports.WorkspaceHeader,{
    brand:React.createElement('h1',null,'Tinkro'),
    navigation:React.createElement('nav',{'aria-label':'Maker workflow'},'Three stages'),
    saveStatus:React.createElement('small',{role:'status'},'Saved'),
  },React.createElement('button',null,'Existing control')));
  assert.match(html,/<header class="header maker-header maker-header-integrated">/);
  assert.match(html,/<div class="maker-header-main"><h1>Tinkro<\/h1><nav aria-label="Maker workflow">Three stages<\/nav><\/div>/);
  assert.match(html,/maker-header-controls"><button>Existing control<\/button><small role="status">Saved<\/small>/);
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
  assert.match(app,/role=\{makerSaved \? "status" : "alert"\}/);
});
