import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import postcss from 'postcss';
import ts from 'typescript';
import {systemTextUrl} from './system_text_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const url = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
const catalog = JSON.parse(read('../../profiles/component-catalog.json'));
const maker = url(`export const makerCatalog=${JSON.stringify(catalog)};
export const fillStarterPrompt=state=>state;
export const structuralParts={wheel:{name:'輪子'}};
export const needsDraftConsent=()=>false;
export const discardConcept=state=>state;`);
const replacements = {react:import.meta.resolve('react'), 'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
  '../lib/maker':maker, '../lib/useMaker':url('export const useMakerText=()=>(zh,en)=>zh;'),
  '../lib/i18n':url('export const useI18n=()=>({locale:"zh-TW",tx:v=>v["zh-TW"]});'),
  '../lib/systemText':systemTextUrl};
function compile(name, extra={}) {
  let js = ts.transpileModule(read(`../src/components/${name}.tsx`), {compilerOptions:{target:ts.ScriptTarget.ES2022,
    module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  for (const [key,value] of Object.entries({...replacements,...extra})) js=js.replaceAll(JSON.stringify(key),JSON.stringify(value));
  return url(js);
}
const concept = compile('ProjectConcept');
const viewSwitch = compile('DesignViewSwitch');
const replyPreview = url(ts.transpileModule(read('../src/lib/makerReply.ts'), {compilerOptions:{target:ts.ScriptTarget.ES2022,
  module:ts.ModuleKind.ES2022}}).outputText);
const {makerReplyPreview} = await import(replyPreview);
const {MakerAssistant} = await import(compile('MakerAssistant',{'../lib/makerReply':replyPreview}));
const {DesignStudio} = await import(compile('DesignStudio',{'./ProjectConcept':concept,'./DesignViewSwitch':viewSwitch}));
const {ProjectConcept} = await import(concept);
const design = {id:'layout-test',revision:2,source:'ai',title:'桌上型距離監測器',summary:'完整作品說明保持可讀。',
  component_ids:['hc-sr04','mrd-tf240-8p-cs'],image:{url:'/api/design/images/layout-fixture',width:1200,height:900},
  assembly:{description:'完整結構說明保持可讀。',parts:[{kind:'wheel',quantity:4}]}};

const renderAssistant=(selected,busy=false)=>renderToStaticMarkup(createElement(MakerAssistant,{
  state:{stage:'design',prompt:'保留這段未送出需求',selected,candidate:null,conversation:[{role:'user',text:'保留既有對話'}]},setState(){},
  assistant:{ai:{logged_in:true},aiOptions:{estimate:{},selectionValid:true},busy,error:'',phase:'design',clearConversation(){},loadDemo(){},generate(){},retryImage(){}},onReview(){},onNewProject:async()=>true}));

test('assistant header uses two compact rows and keeps every action and hint accessible',()=>{
  const html=renderAssistant(['hc-sr04']);
  assert.match(html,/<header class="maker-assistant-header"><div class="maker-assistant-heading"><h2 title="設計與藍圖 · 對話與作品跨頁保留">一起把想法做出來<\/h2>/);
  assert.doesNotMatch(html,/CLOUD \/ CO-DESIGNER|<p class="maker-context">|<small class="maker-muted">Demo/);
  for(const label of ['載入 Demo 示範','清除對話','新作品','零件 · 1','已連線']) assert.ok(html.includes(label));
  const contextId=html.match(/<section[^>]*aria-describedby="([^"]+)"/)[1];
  assert.ok(html.includes(`<span id="${contextId}" class="maker-compose-hint">設計與藍圖 · 對話與作品跨頁保留</span>`));
  const demoHintId=html.match(/<button[^>]*title="載入示範對話[^>]*aria-describedby="([^"]+)"/)[1];
  assert.ok(html.includes(`<span id="${demoHintId}" class="maker-compose-hint">載入示範對話與作品預覽，不需 AI；確認後才套用作品。</span>`));
  assert.match(html,/<\/header><div class="maker-conversation"/,'no extra normal-flow explanation rows above the conversation');
  const css=postcss.parse(read('../src/maker.css'));
  const header=css.nodes.find(n=>n.type==='rule'&&n.selector==='.maker-assistant-header');
  assert.match(header.toString(),/flex-direction: column/);
  assert.match(header.toString(),/gap: 8px/);
  assert.match(css.nodes.find(n=>n.type==='rule'&&n.selector==='.maker-assistant-heading h2').toString(),/margin: 0/);
});

test('parts are a closed toolbar disclosure and neither footer row occupies the composer',()=>{
  const html=renderAssistant(catalog.modules.map(module=>module.id));
  assert.match(html,/<div class="maker-chat-tools">[\s\S]*<details class="maker-assistant-parts"><summary[^>]*>零件 · 2/);
  assert.match(html,/<div class="maker-parts-popover"><header><strong>限定零件 · Pi 5 \+ 2/);
  assert.doesNotMatch(html,/<details[^>]*class="maker-assistant-parts"[^>]*\bopen/);
  assert.match(html,/<\/form><\/section>$/,'no normal-flow parts footer after the composer');
  assert.doesNotMatch(html,/<small class="maker-muted">提問或修改都可以/);
  assert.match(html,/class="maker-parts-hint">提問或修改都可以；作品確認後才更新。/);
  assert.match(html,/保留這段未送出需求/);
  assert.match(html,/保留既有對話/);
});

test('the compact input keeps its confirmation hint accessible without a visible hint row',()=>{
  const html=renderAssistant(['hc-sr04']);
  const describedBy=html.match(/<textarea[^>]*aria-describedby="([^"]+)"/)[1];
  assert.ok(html.includes(`<span id="${describedBy}" class="maker-compose-hint">提問或修改都可以；作品確認後才更新。</span>`));
  const css=postcss.parse(read('../src/maker.css'));
  const hint=css.nodes.find(n=>n.type==='rule'&&n.selector==='.maker-compose-hint');
  assert.match(hint.toString(),/position: absolute;/);
  assert.match(hint.toString(),/clip-path: inset\(50%\);/);
  assert.doesNotMatch(hint.toString(),/display: none|visibility: hidden/);
  const popover=css.nodes.find(n=>n.type==='rule'&&n.selector==='.maker-parts-popover');
  assert.match(popover.toString(),/position: absolute;/);
  assert.match(popover.toString(),/width: min\(360px, 100%\);/);
  assert.match(popover.toString(),/overflow: auto;/);
});

test('moving parts preserves catalog-only selection and existing busy/empty send guards',()=>{
  const ready=renderAssistant(['hc-sr04']);
  assert.equal((ready.match(/type="checkbox"/g)||[]).length,catalog.modules.length);
  assert.equal((ready.match(/type="checkbox" checked=""/g)||[]).length,1);
  assert.match(ready,/<button type="submit" class="maker-primary maker-compose-send"[^>]*>/);
  assert.doesNotMatch(ready,/<button type="submit"[^>]*disabled/);
  for(const html of [renderAssistant([],false),renderAssistant(['hc-sr04'],true)]) {
    assert.match(html,/<button type="submit"[^>]*disabled=""/);
  }
  const busy=renderAssistant(['hc-sr04'],true);
  assert.equal((busy.match(/type="checkbox" disabled=""/g)||[]).length,catalog.modules.length);
  assert.match(busy,/限定零件 · Pi 5 \+ 1/);
});

test('ordinary AI replies remain complete short paragraphs, not mandatory bubble lists',()=>{
  const answer='先確認螢幕有沒有亮。再檢查接線與供電。這些步驟還不能證明接線正確。未確認電壓前不要通電。';
  assert.deepEqual(makerReplyPreview(answer),{blocks:[{kind:'paragraph',text:answer}],hasMore:false});
  assert.deepEqual(makerReplyPreview('先看概念。再看藍圖。接著確認。最後開始。'),
    {blocks:[{kind:'paragraph',text:'先看概念。再看藍圖。接著確認。最後開始。'}],hasMore:false});
  assert.deepEqual(makerReplyPreview('- 先看螢幕\n- 再看接線'),{blocks:[{kind:'list',ordered:false,items:[{text:'先看螢幕'},{text:'再看接線'}]}],hasMore:false});
  assert.equal(makerReplyPreview('先看現象。\n```python\nprint(1)\n```').hasMore,true);
  const longIntro=`${'作品概念'.repeat(35)}。未確認電壓前不要通電。`;
  const safetyPreview=makerReplyPreview(longIntro);
  assert.equal(safetyPreview.blocks[0].kind,'paragraph');
  assert.match(safetyPreview.blocks[0].text,/未確認電壓前不要通電/);
  const html=renderToStaticMarkup(createElement(MakerAssistant,{state:{stage:'design',prompt:'',selected:[],candidate:null,
    conversation:[{role:'user',text:'螢幕沒亮'},{role:'assistant',text:answer}]},setState(){},
    assistant:{ai:{logged_in:false},aiOptions:{estimate:null,selectionValid:false},busy:false,error:'',phase:'design',
      clearConversation(){},loadDemo(){},generate(){},retryImage(){}},onReview(){}}));
  assert.match(html,/<p class="maker-reply-text">先確認螢幕有沒有亮。/);
  assert.doesNotMatch(html,/maker-reply-points|maker-reply-full/);
  assert.match(html,/未確認電壓前不要通電。/);
  assert.match(html,/<div class="maker-message user"><small>你<\/small><p>螢幕沒亮<\/p>/);
});

test('only authored multi-item replies render semantic lists, without per-item cards',()=>{
  const render=text=>renderToStaticMarkup(createElement(MakerAssistant,{state:{stage:'design',prompt:'',selected:[],candidate:null,conversation:[{role:'assistant',text}]},setState(){},
    assistant:{ai:{logged_in:false},aiOptions:{estimate:null,selectionValid:false},busy:false,error:'',phase:'design',clearConversation(){},loadDemo(){},generate(){},retryImage(){}},onReview(){}}));
  assert.match(render('可選兩種造型：\n- 圓盤\n- 方盒'),/<p class="maker-reply-text">可選兩種造型：<\/p><ul class="maker-reply-points"><li>圓盤<\/li><li>方盒<\/li>/);
  assert.match(render('2. 斷電\n3. 檢查接線'),/<ol class="maker-reply-points"><li value="2">斷電<\/li><li value="3">檢查接線<\/li>/);
  assert.doesNotMatch(render('- 已修改造型'),/maker-reply-points/);
  const long='需求說明'.repeat(80)+'。未確認電壓前不要通電。';
  const html=render(long);
  assert.match(html,/<details class="maker-reply-full"><summary>查看完整回覆<\/summary><p>/);
  assert.match(html,/未確認電壓前不要通電。/);
  assert.match(html,/需求說明需求說明需求說明/);
  assert.match(render('<script>alert(1)</script>'),/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  const css=postcss.parse(read('../src/maker.css'));
  const items=css.nodes.find(n=>n.type==='rule'&&n.selector==='.maker-reply-points li');
  assert.doesNotMatch(items.toString(),/border:|border-radius:|background:/);
});

test('concept view switch sits beside its label and replaces the redundant blueprint action',()=>{
  const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design,candidate:null},setState(){},onAdopt(){},onViewChange(){}}));
  assert.match(html,/<div class="maker-view-heading"><span class="maker-eyebrow">01 \/ CONCEPT STUDIO<\/span><nav class="maker-design-views"/);
  assert.match(html,/aria-pressed="true" class="active">作品概念/);
  assert.match(html,/<details class="maker-concept-description"><summary>作品說明<\/summary>/);
  assert.match(html,/<details class="project-assembly-details"><summary>造型與結構<\/summary>/);
  assert.match(html,/完整作品說明保持可讀/);
  assert.match(html,/完整結構說明保持可讀/);
  assert.match(html,/輪子 × 4/);
  assert.match(html,/href="\/api\/design\/images\/layout-fixture" target="_blank" rel="noreferrer"/);
  assert.doesNotMatch(html,/查看製作藍圖 →/);
  const css=postcss.parse(read('../src/maker.css'));
  const heading=css.nodes.find(node=>node.type==='rule' && node.selector==='.maker-view-heading');
  assert.match(heading.toString(),/justify-content: flex-start/);
  assert.match(html,/Raspberry Pi 5/);
});

test('compact preview preserves missing-image and pending-generation confirmation guards',()=>{
  const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design:null,candidate:{...design,image:undefined},aiJobId:null},setState(){},onAdopt(){},onViewChange(){}}));
  assert.match(html,/disabled="" aria-pressed="false" class="">製作藍圖/);
  assert.match(html,/class="maker-primary maker-concept-confirm" disabled=""/);
  assert.match(html,/確認作品並查看藍圖/);
  assert.match(html,/<nav class="maker-design-views"[\s\S]*<button class="maker-primary maker-concept-confirm" disabled="">確認作品並查看藍圖/);
  assert.match(html,/這個版本尚未生成作品圖片/);
  const failed=renderToStaticMarkup(createElement(ProjectConcept,{design:{...design,image:undefined,image_error:'fixture error'}}));
  assert.match(failed,/圖片未生成成功/);
  assert.match(failed,/fixture error/);
});

test('actual job phases replace the idle placeholder, including a first design',()=>{
  for (const phase of ['design','image']) {
    for (const project of [null,{...design,image:undefined,image_error:'previous attempt failed'}]) {
      const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design:project,candidate:null,aiJobId:'active-job'},generationPhase:phase,setState(){},onAdopt(){},onViewChange(){}}));
      assert.match(html,/aria-busy="true"/);
      assert.match(html,new RegExp(`role="status" aria-live="polite" aria-atomic="true" data-phase="${phase}"`));
      assert.match(html,phase==='image'?/正在生成作品圖片/:/AI 正在推論中/);
      assert.match(html,/<div class="project-generation-orbit" aria-hidden="true">/);
      assert.doesNotMatch(html,/這個版本尚未生成作品圖片|圖片未生成成功|先看見你的作品|previous attempt failed/);
      assert.doesNotMatch(html,/\d+%|role="progressbar"/,'no invented progress');
      assert.equal((html.match(/class="project-generation-status/g)||[]).length,1);
    }
  }
});

test('a revision keeps the actual image visible and never enables candidate adoption while working',()=>{
  const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design,candidate:design,aiJobId:'active-job'},generationPhase:'image',setState(){},onAdopt(){},onViewChange(){}}));
  assert.match(html,/class="project-generation-status is-compact"/);
  assert.match(html,/目前圖片會保留/);
  assert.match(html,/src="\/api\/design\/images\/layout-fixture"/);
  assert.match(html,/class="maker-primary maker-concept-confirm" disabled=""/);
  assert.doesNotMatch(html,/這個版本尚未生成作品圖片/);
});

test('completion, failure, login or demo loading cannot leave a generation animation running',()=>{
  for (const project of [null,design,{...design,image:undefined},{...design,image:undefined,image_error:'generation failed'}]) {
    for (const phase of ['design','image','demo']) {
      const html=renderToStaticMarkup(createElement(DesignStudio,{state:{design:project,candidate:null,aiJobId:null},generationPhase:phase,setState(){},onAdopt(){},onViewChange(){}}));
      assert.match(html,/aria-busy="false"/);
      assert.doesNotMatch(html,/project-generation-status|project-generation-orbit/);
      if (project?.image_error)assert.match(html,/圖片未生成成功[\s\S]*generation failed/);
    }
  }
  const app=read('../src/App.tsx');
  assert.match(app,/<DesignStudio[^>]*generationPhase=\{makerAI\.phase\}/);
  const source=read('../src/components/ProjectConcept.tsx');
  assert.doesNotMatch(source,/fetch\(|setInterval\(|setTimeout\(|useEffect\(/,'presentation does not start cloud work or polling');
});

test('loading motion is decorative, theme-colored and disabled for reduced motion',()=>{
  const css=postcss.parse(read('../src/maker.css'));
  const orbit=css.nodes.find(n=>n.type==='rule'&&n.selector==='.project-generation-orbit::before');
  assert.match(orbit.toString(),/var\(--brand-blue, #417abe\)/);
  assert.match(orbit.toString(),/var\(--brand-teal, #16b9a6\)/);
  assert.match(orbit.toString(),/animation: project-generation-spin/);
  const reduced=css.nodes.find(n=>n.type==='atrule'&&n.params==='(prefers-reduced-motion: reduce)');
  assert.match(reduced.toString(),/\.project-generation-orbit::before, \.project-generation-dots i \{ animation: none;/);
});

test('cloud design replies reach chat without appending the complete design summary',()=>{
  const hook=read('../src/lib/useMakerAI.ts');
  assert.match(hook,/const text = job\.answer \|\| job\.explanation \|\| job\.design!\.title/);
  assert.doesNotMatch(hook,/job\.design!\.summary/);
});

test('preview grows without cropping and compact composer contains its send button',()=>{
  const css=postcss.parse(read('../src/maker.css'));
  function declaration(selector,property) {
    let value;
    css.walkRules(r=>{if(r.parent.type==='root' && r.selector===selector)r.walkDecls(property,d=>{value=d.value})});
    return value;
  }
  assert.equal(declaration('.maker-compose-row','grid-template-columns'),'minmax(0, 1fr) 56px');
  assert.equal(declaration('.maker-compose-row','border-radius'),'18px');
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
