import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import {systemTextUrl} from './system_text_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const url=text=>`data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
async function concept(locale) {
  let js=ts.transpileModule(read('../src/components/ProjectConcept.tsx'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX},
  }).outputText;
  const replacements={
    react:import.meta.resolve('react'),'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
    '../lib/maker':url('export const makerCatalog={modules:[]};export const structuralParts={};'),
    '../lib/useMaker':url(`export const useMakerText=()=>(zh,en)=>${locale==='en'?'en':'zh'};`),
    '../lib/i18n':url(`export const useI18n=()=>({locale:${JSON.stringify(locale)},tx:v=>v[${JSON.stringify(locale)}]});`),
    '../lib/systemText':systemTextUrl,
  };
  for(const [from,to] of Object.entries(replacements))js=js.replaceAll(JSON.stringify(from),JSON.stringify(to));
  return (await import(url(js))).ProjectConcept;
}

const design={id:'concept-fixture',revision:1,title:'Distance monitor',component_ids:[],
  assembly:{description:'Two round plates',parts:[]}};
for(const locale of ['zh-TW','en']) {
  test(`Concept ${locale} labels motor appearance separately even before an image exists`,async()=>{
    const ProjectConcept=await concept(locale);
    const visual={...design,concept_only_parts:[{kind:'motor',quantity:2,purpose:'Under the chassis'}]};
    const before=JSON.stringify(visual);
    const html=renderToStaticMarkup(createElement(ProjectConcept,{design:visual}));
    assert.match(html,locale==='en'?/Concept image only · Motor × 2/:/僅概念圖 · 馬達 × 2/);
    assert.match(html,locale==='en'?/excluded from the blueprint, wiring, tests and deployment/:/不納入藍圖、接線、測試或部署/);
    assert.doesNotMatch(html.match(/<div class="project-scope">.*?<\/div>/)?.[0]??'',/Motor|馬達/);
    assert.equal(JSON.stringify(visual),before);
    assert.doesNotMatch(renderToStaticMarkup(createElement(ProjectConcept,{design})),/project-concept-only/);
  });
}

test('guide, debugging and deploy components do not render concept-only parts',()=>{
  for(const name of ['BlueprintPage','ProjectGuidePanel','AiDebugPanel','DebugPage','PiDeployPanel']) {
    assert.doesNotMatch(read(`../src/components/${name}.tsx`),/concept_only_parts/);
  }
});
