import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import {maker, designFor} from './project_guide_fixture.mjs';
import {systemText} from './system_text_fixture.mjs';

const sampleURL='/demo/distance-monitor-three-wheel-motors-v2.png';
const source=readFileSync(new URL('../src/components/ProjectConcept.tsx',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
const demo=()=>({...designFor(['hc-sr04','mrd-tf240-8p-cs']),title:'Demo distance monitor'});
const generatedImage={id:'a'.repeat(32),url:`/api/design/images/${'a'.repeat(32)}`,width:1000,height:700};
function concept(locale='zh-TW') {
  let failed='';
  const react={...React,useState:()=>[failed,value=>{failed=value;}]};
  const require=name=>name==='react'?react:name.endsWith('/maker')?maker:
    name.endsWith('/useMaker')?{useMakerText:()=>(zh,en)=>locale==='en'?en:zh}:
    name.endsWith('/i18n')?{useI18n:()=>({locale,tx:v=>v[locale]})}:
    name.endsWith('/systemText')?{systemText}:assert.fail(`Unexpected import ${name}`);
  const exports={};new Function('React','require','exports',js)(React,require,exports);
  return {html:(design,extra={})=>renderToStaticMarkup(React.createElement(exports.ProjectConcept,{design,...extra})),
    tree:design=>exports.ProjectConcept({design})};
}
function nodes(tree) { return Array.isArray(tree)?tree.flatMap(nodes):tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[]; }

test('bundled sample is a real versioned PNG with matching dimensions and provenance',()=>{
  const bytes=readFileSync(new URL(`../public${sampleURL}`,import.meta.url));
  assert.equal(bytes.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  assert.equal(bytes.readUInt32BE(16),1536);assert.equal(bytes.readUInt32BE(20),1024);
  assert.equal(createHash('sha256').update(bytes).digest('hex'),'4ced7d7fc35ed955d942f531e0d3286640e0f306c07b546c66724848e3cdb0fd');
});

for(const locale of ['zh-TW','en']) {
  test(`full-kit Demo shows a clearly labelled bundled image in ${locale} without mutating data`,()=>{
    const design=demo(),before=JSON.stringify(design),html=concept(locale).html(design);
    assert.ok(html.includes(`src="${sampleURL}"`));assert.ok(html.includes(`href="${sampleURL}"`));
    assert.match(html,/width="1536" height="1024"/);
    assert.match(html,locale==='en'?/BUILT-IN SAMPLE \(NOT GENERATED NOW\)/:/內建示範圖（非本次生成）/);
    assert.match(html,locale==='en'?/not wiring verification/:/非接線驗證/);
    assert.match(html,locale==='en'?/three wheels, two motors/:/三個輪胎、兩顆馬達/);
    assert.match(html,locale==='en'?/Concept image only · Motor × 2/:/僅概念圖 · 馬達 × 2/);
    assert.match(html,locale==='en'?/excluded from the blueprint, wiring, tests and deployment/:/不納入藍圖、接線、測試或部署/);
    assert.doesNotMatch(html,/AI GENERATED|project-image-empty/);
    assert.equal(JSON.stringify(design),before);assert.equal(design.image,undefined);
  });
}

test('AI images, errors and missing-image confirmation guards never use the Demo sample',()=>{
  for(const properties of [{},{image_required:true},{image_error:'generation failed'}]) {
    const design={...demo(),source:'ai',...properties};
    const html=concept('en').html(design);
    assert.doesNotMatch(html,/\/demo\/|BUILT-IN SAMPLE/);assert.match(html,/project-image-empty/);
    const state={...maker.initialMaker(),candidate:design};
    assert.equal(maker.confirmConcept(state),state);
  }
  for(const source of ['ai','demo']) {
    const html=concept().html({...demo(),source,image:generatedImage});
    assert.ok(html.includes(`src="${generatedImage.url}"`));assert.match(html,/AI GENERATED/);
    assert.doesNotMatch(html,/\/demo\//);
  }
});

test('sample never misrepresents a different Demo kit, motors or an image job failure',()=>{
  for(const overrides of [
    {component_ids:['hc-sr04']},{component_ids:['mrd-tf240-8p-cs']},{component_ids:['hc-sr04','hc-sr04']},
    {concept_only_parts:[{kind:'motor',quantity:2,purpose:'Requested motors'}]},
    {image_required:true},{image_error:'image failed'},{image_job_id:'pending-image'},
  ]) assert.doesNotMatch(concept().html({...demo(),...overrides}),/\/demo\//);
});

test('Demo image load failure exposes a local retry, not automatic AI generation or another fallback',()=>{
  const c=concept('en'),design=demo();
  const image=nodes(c.tree(design)).find(n=>n.type==='img');
  image.props.onError();
  const failed=c.html(design);
  assert.match(failed,/Image unavailable/);assert.match(failed,/no AI generation will start automatically/);
  assert.doesNotMatch(failed,/<img/);
  nodes(c.tree(design)).find(n=>n.type==='button').props.onClick();
  assert.ok(c.html(design).includes(`src="${sampleURL}"`));
  assert.doesNotMatch(source,/fetch\(|setInterval\(|setTimeout\(|useEffect\(/);
});

test('Demo preview, confirmation and restore keep the sample presentation-only and preserve drafts',()=>{
  const prior={...demo(),id:'approved',source:'ai',image:generatedImage};
  const state={...maker.applyDesign(maker.initialMaker(),prior,'design'),prompt:'Unsent draft',code:'Manual code',
    conversation:[{role:'user',text:'Keep this conversation'}],hardware:{result:'not touched'}};
  const preview=maker.previewDemo(state,demo());
  for(const key of ['design','code','guide','hardware','prompt'])assert.equal(preview[key],state[key]);
  assert.deepEqual(preview.conversation.slice(0,-2),state.conversation);
  assert.equal(preview.candidate.image,undefined);
  assert.ok(concept().html(preview.candidate).includes(sampleURL));
  const restored=maker.restoreMaker(JSON.stringify(preview));
  assert.ok(concept().html(restored.candidate).includes(sampleURL));
  const discarded=maker.discardConcept(preview);
  assert.equal(discarded.design,prior);assert.equal(discarded.code,state.code);
  assert.doesNotMatch(concept().html(discarded.design),/\/demo\//);
  const fresh=maker.previewDemo(maker.initialMaker(),demo());
  const confirmed=maker.confirmConcept(fresh);
  assert.equal(confirmed.candidate,null);assert.equal(confirmed.design.source,'demo');
  assert.equal(confirmed.design.image,undefined);
  assert.ok(concept().html(maker.restoreMaker(JSON.stringify(confirmed)).design).includes(sampleURL));
});

test('resetting, discarding or clearing saved project data cannot remove the bundled Demo image',()=>{
  const asset=new URL(`../public${sampleURL}`,import.meta.url);
  const original=readFileSync(asset);
  const confirmed=maker.confirmConcept(maker.previewDemo(maker.initialMaker(),demo()));
  const withPreview=maker.previewDemo({...confirmed,conversation:[{role:'user',text:'Old conversation'}]},demo());
  for(const cleared of [
    maker.newMakerProject(withPreview),
    maker.clearMakerConversation(withPreview),
    maker.discardConcept(withPreview),
    maker.restoreMaker(null), // equivalent to clearing the browser's saved project
  ]) {
    const restored=maker.restoreMaker(JSON.stringify(cleared));
    const reloaded=maker.previewDemo(restored,demo());
    assert.ok(concept().html(reloaded.candidate).includes(`src="${sampleURL}"`));
    assert.deepEqual(readFileSync(asset),original);
    assert.doesNotMatch(JSON.stringify(reloaded),/\/demo\/|data:image/,'sample is not owned by saved project state');
  }
  const fresh=maker.newMakerProject(withPreview);
  assert.equal(fresh.design,null);assert.equal(fresh.candidate,null);
  assert.equal(maker.designRequest(fresh,'zh-TW',null).current,null,'new projects do not silently inherit Demo');
});

test('Demo sample cannot become a generated artifact or an AI edit reference',()=>{
  const confirmed=maker.confirmConcept(maker.previewDemo(maker.initialMaker(),demo()));
  for(const intent of ['auto','design','ask']) {
    const request=maker.designRequest({...confirmed,aiIntent:intent,designMode:'fixed'},'en',null);
    assert.equal(request.current.image,undefined);
    assert.doesNotMatch(JSON.stringify(request),/\/demo\/|distance-monitor-three-wheel-motors-v2/);
  }
  // An actual image ID cannot be used to smuggle a static Demo URL into image state.
  assert.equal(maker.validDesign({...demo(),source:'ai',image:{...generatedImage,url:sampleURL}}),false);
  assert.equal(maker.restoreMaker(JSON.stringify({...maker.initialMaker(),candidate:{...demo(),source:'ai',image:{...generatedImage,url:sampleURL}}})).candidate,null);
});
