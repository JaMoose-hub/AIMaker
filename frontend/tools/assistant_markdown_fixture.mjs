import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const code=ts.transpileModule(readFileSync(new URL('../src/components/AssistantMarkdown.tsx',import.meta.url),'utf8'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText;

/** Real message renderer and GFM parser; only the translation context is stubbed. */
export function markdownFixture(locale='en') {
  const modules={react:React,'react/jsx-runtime':jsx,'react-markdown':{default:Markdown},'remark-gfm':{default:remarkGfm},
    '../lib/useMaker':{useMakerText:()=> (zh,en)=>locale==='en'?en:zh},'./assistantMarkdown.css':{}};
  const exports={};
  new Function('require','exports',code)(name=>{
    if(!(name in modules))throw Error(`Unexpected Markdown import ${name}`);
    return modules[name];
  },exports);
  return exports;
}
