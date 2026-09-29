import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import postcss from 'postcss';
import ts from 'typescript';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const url = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
const catalog = JSON.parse(read('../../profiles/component-catalog.json'));
const maker = url(`export const makerCatalog=${JSON.stringify(catalog)};
export const structuralParts={wheel:{name:'輪子'}};
export const needsDraftConsent=()=>false;`);
const replacements = {react:import.meta.resolve('react'), 'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
  '../lib/maker':maker, '../lib/useMaker':url('export const useMakerText=()=>(zh,en)=>zh;'),
  '../lib/i18n':url('export const useI18n=()=>({tx:v=>v["zh-TW"]});')};
function compile(name, extra={}) {
  let js = ts.transpileModule(read(`../src/components/${name}.tsx`), {compilerOptions:{target:ts.ScriptTarget.ES2022,
    module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  for (const [key,value] of Object.entries({...replacements,...extra})) js=js.replaceAll(JSON.stringify(key),JSON.stringify(value));
  return url(js);
}
const concept = compile('ProjectConcept');
const {DesignStudio} = await import(compile('DesignStudio',{'./ProjectConcept':concept}));
const {ProjectConcept} = await import(concept);
const design = {id:'layout-test',revision:2,source:'ai',title:'桌上型距離監測器',summary:'完整作品說明保持可讀。',
  component_ids:['hc-sr04','mrd-tf240-8p-cs'],image:{url:'/api/design/images/layout-fixture',width:1200,height:900},
  assembly:{description:'完整結構說明保持可讀。',parts:[{kind:'wheel',quantity:4}]}};

test('concept details start collapsed without removing text, components or the full-size image link',()=>{
  const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design,candidate:null},setState(){},onAdopt(){}}));
  assert.match(html,/<details class="maker-concept-description"><summary>作品說明<\/summary>/);
  assert.match(html,/<details class="project-assembly-details"><summary>造型與結構<\/summary>/);
  assert.match(html,/完整作品說明保持可讀/);
  assert.match(html,/完整結構說明保持可讀/);
  assert.match(html,/輪子 × 4/);
  assert.match(html,/href="\/api\/design\/images\/layout-fixture" target="_blank" rel="noreferrer"/);
  assert.match(html,/查看 Blueprint/);
  assert.match(html,/Raspberry Pi 5/);
});

test('compact preview preserves missing-image and pending-generation confirmation guards',()=>{
  const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design:null,candidate:{...design,image:undefined},aiJobId:null},setState(){},onAdopt(){}}));
  assert.match(html,/class="maker-primary" disabled=""/);
  assert.match(html,/這個版本尚未生成作品圖片/);
  const failed=renderToStaticMarkup(createElement(ProjectConcept,{design:{...design,image:undefined,image_error:'fixture error'}}));
  assert.match(failed,/圖片未生成成功/);
  assert.match(failed,/fixture error/);
});

test('preview grows without cropping and compact composer contains its send button',()=>{
  const css=postcss.parse(read('../src/maker.css'));
  function declaration(selector,property) {
    let value;
    css.walkRules(r=>{if(r.parent.type==='root' && r.selector===selector)r.walkDecls(property,d=>{value=d.value})});
    return value;
  }
  assert.equal(declaration('.maker-compose-row','grid-template-columns'),'minmax(0, 1fr) 56px');
  assert.equal(declaration('.maker-compose-row','border-radius'),'12px');
  assert.equal(declaration('.maker-assistant .maker-compose-row textarea','border'),'0');
  assert.equal(declaration('.maker-assistant .maker-compose-row textarea','resize'),'vertical');
  assert.equal(declaration('.maker-assistant .maker-compose-send','width'),'44px');
  assert.equal(declaration('.maker-assistant .maker-compose-send','height'),'44px');
  assert.equal(declaration('.maker-assistant textarea','height'),'64px');
  assert.equal(declaration('.maker-assistant textarea','max-height'),'160px');
  assert.equal(declaration('.maker-field textarea','resize'),'vertical');
  assert.equal(declaration('.project-image-concept figure img','height'),'auto');
  assert.equal(declaration('.project-image-concept figure img','max-height'),'65dvh');
  assert.equal(declaration('.project-image-concept figure img','object-fit'),'contain');
  const desktop=css.nodes.find(n=>n.type==='atrule' && n.params==='(min-width: 961px) and (min-height: 601px)');
  assert.ok(desktop);
  assert.match(desktop.toString(),/\.maker-concept-page > \.project-image-concept \{ flex: 1 0 auto;/);
  assert.match(desktop.toString(),/figure > a \{ flex: 1 0 auto; height: auto; min-height: 260px;/);
  assert.match(desktop.toString(),/figure img \{ position: absolute; inset: 0; height: 100%; max-height: none;/);
  assert.doesNotMatch(css.toString(),/height: clamp\(180px, 30dvh, 300px\)/);
  assert.equal(declaration('.maker-stage-design .maker-assistant .maker-conversation','flex'),'1 1 180px');
  assert.doesNotMatch(css.toString(),/height: clamp\(110px, 14dvh, 160px\)/);
});
