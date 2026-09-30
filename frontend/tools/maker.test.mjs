import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import {systemTextUrl} from './system_text_fixture.mjs';

const catalog = JSON.parse(readFileSync(new URL("../../profiles/component-catalog.json", import.meta.url), "utf8"));
const source = readFileSync(new URL("../src/lib/maker.ts", import.meta.url), "utf8").replace(/import catalog from [^;]+;/, `const catalog = ${JSON.stringify(catalog)};`);
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const m = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
// Exercise real component event handlers with deterministic hooks and no cloud or storage.
const moduleUrl = js => `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`;
const hooksUrl = moduleUrl(`export let value=null; export const reset=()=>{value=null};
  export const useState=()=>[value,v=>{value=v}]; export const useEffect=()=>{};
  export const useRef=()=>({current:null}); export const useId=()=>"fixture-prompt";`);
const hooks = await import(hooksUrl);
const replyPreviewJS=ts.transpileModule(readFileSync(new URL('../src/lib/makerReply.ts',import.meta.url),'utf8'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022},
}).outputText;
let assistantJS = ts.transpileModule(readFileSync(new URL('../src/components/MakerAssistant.tsx',import.meta.url),'utf8'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX},
}).outputText;
for(const [name,url] of Object.entries({react:hooksUrl,'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
  '../lib/maker':moduleUrl(`export const makerCatalog=${JSON.stringify(catalog)}`),
  '../lib/makerReply':moduleUrl(replyPreviewJS),
  '../lib/useMaker':moduleUrl('export const useMakerText=()=>(zh,en)=>zh'),
  '../lib/i18n':moduleUrl('export const useI18n=()=>({locale:"zh-TW",tx:v=>typeof v=== "string"?v:v["zh-TW"]})'),
  '../lib/systemText':systemTextUrl,
})) assistantJS=assistantJS.replaceAll(JSON.stringify(name),JSON.stringify(url));
const {MakerAssistant}=await import(moduleUrl(assistantJS));
const resetGateURL=moduleUrl(`export let gate=async()=>true; export const setGate=value=>{gate=value}; export const prepareProjectWiringEdit=id=>gate(id);`);
const resetGate=await import(resetGateURL);
let makerAIJS=ts.transpileModule(readFileSync(new URL('../src/lib/useMakerAI.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
for(const [name,value] of Object.entries({react:hooksUrl,'./maker':moduleUrl(outputText),'./makerMigration':moduleUrl('export const MAKER_STORAGE="boardvision.maker.v1"'),
  './wiringEdit':resetGateURL,'./useAIOptions':moduleUrl('export const useAIOptions=()=>({})'),
  './i18n':moduleUrl('export const useI18n=()=>({locale:"zh-TW"})')}))makerAIJS=makerAIJS.replaceAll(JSON.stringify(name),JSON.stringify(value));
const {useMakerAI}=await import(moduleUrl(makerAIJS));

test('actual newProject hook backs up before reset and does not make generation requests',async()=>{
  const original=globalThis.localStorage;
  const writes=[];
  globalThis.localStorage={setItem:(key,value)=>writes.push([key,JSON.parse(value)])};
  try{
    hooks.reset();
    const before={...m.initialMaker(),design,candidate:{...design,revision:2},code:'manual draft'};
    let state=before;const checked=[];
    resetGate.setGate(async id=>{checked.push(id);return true});
    const ai=useMakerAI(state,update=>{state=update(state)});
    assert.equal(await ai.newProject(),true);
    assert.deepEqual(checked,[design.id]);
    assert.equal(writes[0][0],'boardvision.maker.v1.before-new-project');
    assert.deepEqual(writes[0][1],before);
    assert.equal(writes[1][0],'boardvision.maker.v1');
    assert.equal(writes[1][1].design,null);
    assert.equal(state.design,null);assert.equal(state.candidate,null);
  }finally{globalThis.localStorage=original;}
});

test('actual newProject hook preserves the project when active work or backup fails',async()=>{
  const original=globalThis.localStorage;
  try{
    for(const failure of ['hardware_work_active','wiring_state_unavailable','backup']){
      hooks.reset();let writes=0;
      const before={...m.initialMaker(),design,code:'keep me'};let state=before;
      globalThis.localStorage={setItem(){writes++;if(failure==='backup')throw Error('quota')}};
      resetGate.setGate(async()=>{if(failure!=='backup')throw Error(failure);return true});
      const ai=useMakerAI(state,update=>{state=update(state)});
      assert.equal(await ai.newProject(),false,failure);
      assert.equal(state,before);
      assert.equal(writes,failure==='backup'?1:0);
    }
    hooks.reset();const busy={...m.initialMaker(),design,aiJobId:'live-job'};let checks=0;
    resetGate.setGate(async()=>{checks++;return true});
    assert.equal(await useMakerAI(busy,()=>assert.fail('busy reset')).newProject(),false);
    assert.equal(checks,0);
  }finally{globalThis.localStorage=original;}
});
function nodes(tree){return Array.isArray(tree)?tree.flatMap(nodes):tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
function textOf(tree){return Array.isArray(tree)?tree.map(textOf).join(''):tree&&typeof tree==='object'?textOf(tree.props?.children):typeof tree==='string'?tree:'';}
function assistantFixture(state, busy=false, onNewProject){
  hooks.reset();
  const calls=[];
  const props={state,setState(){throw Error('Unexpected state mutation');},onReview(){},onNewProject,assistant:{busy,ai:{logged_in:true},
    aiOptions:{estimate:{},selectionValid:true},generate(){calls.push('generate');},loadDemo(){calls.push('demo');},clearConversation(){calls.push('clear');}}};
  const render=()=>MakerAssistant(props);
  const button=name=>nodes(render()).find(n=>n.type==='button'&&textOf(n)===name);
  return {render,button,calls};
}

test('new project is separate from clearing chat and requires explicit confirmation',async()=>{
  let resets=0;
  const f=assistantFixture({...m.initialMaker(),design,conversation:[{role:'user',text:'old'}]},false,async()=>{resets++;return true});
  f.button('新作品').props.onClick();
  assert.match(textOf(f.render()),/作品、圖片、預覽、對話、程式與接線進度將清空/);
  assert.equal(resets,0);
  f.button('取消').props.onClick();
  assert.equal(resets,0);
  f.button('新作品').props.onClick();
  await f.button('確認從頭開始').props.onClick();
  assert.equal(resets,1);
  assert.equal(f.button('確認從頭開始'),undefined);
  assert.deepEqual(f.calls,[]);
});

test('new project stays guarded when busy and keeps its confirmation after failure',async()=>{
  let resets=0;
  const busy=assistantFixture(m.initialMaker(),true,async()=>{resets++;return true});
  assert.equal(busy.button('新作品').props.disabled,true);
  busy.button('新作品').props.onClick();
  assert.equal(busy.button('確認從頭開始'),undefined);
  const failed=assistantFixture(m.initialMaker(),false,async()=>{resets++;return false});
  failed.button('新作品').props.onClick();
  await failed.button('確認從頭開始').props.onClick();
  assert.equal(resets,1);
  assert(failed.button('確認從頭開始'));
});

test('new project removes approved and preview image context while preserving AI preferences',()=>{
  const before={...m.initialMaker(),design,candidate:{...design,revision:2},code:'manual code',stage:'deploy',designView:'blueprint',
    aiModel:'chosen-model',aiEffort:'high',aiExpectedOutputTokens:4000,selected:['hc-sr04'],conversation:[{role:'user',text:'old'}],
    guide:{...m.emptyGuide(),confirmed:{wire:{signature:'old'}}},hardware:{saved:'test'},debug:{caseId:'old-case'}};
  const next=m.newMakerProject(before);
  assert.equal(next.design,null);assert.equal(next.candidate,null);assert.equal(next.code,'');
  assert.deepEqual(next.conversation,[]);assert.deepEqual(next.guide,m.emptyGuide());assert.deepEqual(next.hardware,{});assert.equal(next.debug,undefined);
  assert.equal(next.aiModel,before.aiModel);assert.equal(next.aiEffort,before.aiEffort);assert.deepEqual(next.selected,before.selected);
  const request=m.designRequest(next,'zh-TW',null);
  assert.equal(request.current,null);assert.deepEqual(request.conversation,[]);assert.equal(request.design_mode,'free');
  assert.equal(m.restoreMaker(JSON.stringify(next)).design,null);
  const busy={...before,aiJobId:'live-job'};assert.equal(m.newMakerProject(busy),busy);
});

test('one composer replaces intent and appearance switches, clearing requires confirmation',()=>{
  const f=assistantFixture({...m.initialMaker(),conversation:[{role:'user',text:'keep me'}]});
  assert.equal(nodes(f.render()).filter(n=>n.type==='textarea').length,1);
  assert.equal(nodes(f.render()).filter(n=>n.type==='select').length,0);
  assert.doesNotMatch(textOf(f.render()),/設計／修改作品|詢問 AI|生成方式/);
  f.button('清除對話').props.onClick();
  assert.match(textOf(f.render()),/作品、接線進度、程式與未送出的文字都會保留/);
  assert.deepEqual(f.calls,[]);
  f.button('取消').props.onClick();
  assert.equal(f.button('確認清除'),undefined);
  f.button('清除對話').props.onClick();
  f.button('確認清除').props.onClick();
  assert.deepEqual(f.calls,['clear']);
});

test('integrated composer keeps a labelled two-line draft and an accessible icon submit',()=>{
  const draft = '保留我的輸入\n第二行';
  const f = assistantFixture({...m.initialMaker(),prompt:draft});
  const tree = f.render();
  const row = nodes(tree).find(n=>n.props?.className==='maker-compose-row');
  const field = nodes(tree).find(n=>n.type==='label' && n.props.className==='maker-compose-label');
  const input = nodes(row).find(n=>n.type==='textarea');
  assert.equal(field.props.htmlFor,input.props.id);
  assert.equal(input.props.rows,2);
  assert.equal(input.props.value,draft);
  assert.equal(input.props.maxLength,8000);
  assert.match(textOf(field),/想做什麼，或想問什麼/);
  assert.equal(nodes(row).filter(n=>n.type==='button'&&n.props.type==='submit').length,1);
  const send = nodes(row).find(n=>n.type==='button');
  assert.equal(send.props['aria-label'],'送出訊息');
  assert.equal(send.props.title,'送出訊息');
  assert.equal(nodes(send).find(n=>n.type==='svg').props['aria-hidden'],'true');
  assert.equal(nodes(tree).find(n=>n.type==='button'&&n.props.type==='submit').props.disabled,false);
  let prevented=false;
  nodes(tree).find(n=>n.type==='form').props.onSubmit({preventDefault(){prevented=true}});
  assert.equal(prevented,true);
  assert.deepEqual(f.calls,['generate']);
  assert.equal(nodes(assistantFixture({...m.initialMaker(),prompt:''}).render()).find(n=>n.type==='button'&&n.props.type==='submit').props.disabled,true);
});

test('icon submit preserves busy, whitespace and missing-component guards even on form submission',()=>{
  for(const [state,busy] of [[m.initialMaker(),true],[{...m.initialMaker(),prompt:' \n'},false],[{...m.initialMaker(),selected:[]},false]]) {
    const f=assistantFixture(state,busy), tree=f.render();
    const send=nodes(tree).find(n=>n.type==='button'&&n.props.type==='submit');
    assert.equal(send.props.disabled,true);
    if(busy) assert.equal(send.props['aria-label'],'處理中…');
    nodes(tree).find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
    assert.deepEqual(f.calls,[]);
  }
});

test('Demo asks before replacing a preview and never submits a cloud request',()=>{
  const f=assistantFixture({...m.initialMaker(),candidate:design});
  f.button('載入 Demo 示範').props.onClick();
  assert.match(textOf(f.render()),/已確認作品與程式不會改變/);
  assert.deepEqual(f.calls,[]);
  f.button('取消').props.onClick();
  assert.deepEqual(f.calls,[]);
  f.button('載入 Demo 示範').props.onClick();
  f.button('載入示範預覽').props.onClick();
  assert.deepEqual(f.calls,['demo']);
  const empty=assistantFixture(m.initialMaker());
  empty.button('載入 Demo 示範').props.onClick();
  assert.deepEqual(empty.calls,['demo']);
});

test('busy conversations cannot be cleared or replaced and empty history cannot be cleared',()=>{
  const f=assistantFixture({...m.initialMaker(),conversation:[{role:'user',text:'pending'}]},true);
  assert.equal(f.button('清除對話').props.disabled,true);
  assert.equal(f.button('載入 Demo 示範').props.disabled,true);
  assert.equal(assistantFixture(m.initialMaker()).button('清除對話').props.disabled,true);
});
const design = {
  id: "test", revision: 1, source: "demo", catalog_version: catalog.version, title: "test", summary: "test",
  component_ids: ["hc-sr04"], wiring: catalog.modules[0].steps.map(s => ({ ...s, id: `hc-sr04:${s.id}`, componentId: "hc-sr04" })),
  code: "old", tests: [], features: [], instructions: [], unresolved: [], bom: [],
};

test('starter prompt matches the requested multi-line brief without submitting an AI job',()=>{
  const expected = [
    '我想做一個桌上型距離監測器。', '', '需求：',
    '- 可以偵測前方物體的距離',
    '- 螢幕即時顯示目前距離與狀態',
    '- 當距離小於 20 cm 時，顯示警告，並在螢幕上顯示一台靠近障礙物的小車圖示',
    '- 裝置使用上下兩層圓形壓克力圓盤組成，並使用支柱固定',
    '- 底部加裝三個輪胎，形成可手動推動的三輪底座',
    '- 整體大小適合放在桌面上', '',
    '請直接依照以上需求生成完整作品設計與組裝圖片，並規劃所需零件、組裝方式與接線。已提供的需求不要重複詢問，其餘造型與結構細節請自行採用合理配置。',
  ].join('\n');
  assert.equal(m.defaultPrompt,expected);
  assert.equal(m.initialMaker().prompt,expected);
  assert.equal(m.restoreMaker(null).prompt,expected);
  const f=assistantFixture(m.initialMaker());
  assert.equal(nodes(f.render()).find(n=>n.type==='textarea').props.value,expected);
  assert.deepEqual(f.calls,[]);
  assert.equal(m.initialMaker().aiJobId,null);
});

test('known starter drafts upgrade without changing projects or overwriting custom and in-flight drafts',()=>{
  const state={...m.initialMaker(),design,candidate:{...design,revision:2},code:'manual draft',
    conversation:[{role:'user',text:'keep previous conversation'}]};
  for(const prompt of [
    '幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與警告狀態，距離小於 20 公分時顯示警告。',
    '幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與顯示狀態，距離小於 20 公分時顯示警告的小車車',
  ].flatMap(prompt=>[prompt, `${prompt}\n`, ` \t${prompt}\r\n`])) {
    const restored=m.restoreMaker(JSON.stringify({...state,prompt}));
    assert.equal(restored.prompt,m.defaultPrompt);
    assert.deepEqual(restored.design,state.design);
    assert.deepEqual(restored.candidate,state.candidate);
    assert.equal(restored.code,state.code);
    assert.deepEqual(restored.conversation,state.conversation);
    assert.equal(restored.aiJobId,null);
    assert.equal(m.restoreMaker(JSON.stringify(restored)).prompt,m.defaultPrompt);
    assert.equal(m.restoreMaker(JSON.stringify({...state,prompt,aiJobId:'pending-job'})).prompt,prompt);
  }
  for(const prompt of ['', ' \n', '我還沒送出的自訂需求\n請保留', m.defaultPrompt,
    '幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與顯示狀態，距離小於 21 公分時顯示警告的小車車\n'])
    assert.equal(m.restoreMaker(JSON.stringify({...state,prompt})).prompt,prompt);
  const olderZh = `我想做一個桌上型距離監測器。

需求：
- 可以偵測前方物體的距離
- 螢幕即時顯示目前距離與狀態
- 當距離小於 20 cm 時，顯示警告，並在螢幕上顯示一台靠近障礙物的小車圖示
- 裝置使用上下兩層圓形壓克力圓盤組成，並使用支柱固定
- 整體大小適合放在桌面上

請根據以上需求，幫我決定需要哪些電子零件、感測器、控制板、螢幕與其他必要元件，並規劃如何組裝與接線。`;
  const olderEn = `I want to build a desktop distance monitor.

Requirements:
- Detect the distance to objects in front of it
- Display the current distance and status on a screen
- Warn below 20 cm and show a small car approaching an obstacle on the screen
- Use two stacked circular acrylic plates held together by standoffs
- Keep the overall size suitable for a desktop

Based on these requirements, help me choose the electronic components, sensors, controller, display and other necessary parts, and plan the assembly and wiring.`;
  for(const [prompt,next] of [[olderZh,m.defaultPrompt],[olderEn,m.defaultPromptEn]]) {
    const restored=m.restoreMaker(JSON.stringify({...state,prompt}));
    assert.equal(restored.prompt,next);
    for(const key of ['design','candidate','conversation','code'])assert.deepEqual(restored[key],state[key]);
    assert.equal(m.restoreMaker(JSON.stringify({...state,prompt,aiJobId:'pending-job'})).prompt,prompt);
    const customized=prompt+'\nKeep my custom addition';
    assert.equal(m.restoreMaker(JSON.stringify({...state,prompt:customized})).prompt,customized);
  }
});
test("image requests are explicit, safe image URLs survive restoration, failed images cannot confirm", () => {
  const state = m.initialMaker();
  assert.equal(m.designRequest(state, 'zh-TW', null).generate_image, true);
  assert.equal(m.designRequest({...state, aiIntent: 'ask'}, 'zh-TW', null).generate_image, false);
  const pending = {...design, image_required: true, image_error: 'quota'};
  const withCandidate = {...state, candidate: pending};
  assert.equal(m.confirmConcept(withCandidate), withCandidate);
  const id = 'a'.repeat(32);
  const image = {id, url: `/api/design/images/${id}`, width: 1024, height: 1024};
  const complete = {...pending, image};
  assert.equal(m.validDesign(complete), true);
  assert.equal(m.validDesign({...complete, image: {...image, url: 'https://external.invalid/image'}}), false);
  assert.equal(m.restoreMaker(JSON.stringify({...state, candidate: complete})).candidate.image.url, image.url);
  assert.equal(m.confirmConcept({...state, candidate: complete}).stage, 'design');
  assert.equal(m.confirmConcept({...state, candidate: complete}).designView, 'blueprint');
  assert.equal(m.validDesign({...complete, assembly: {description:'cart', parts:[{kind:'motor', quantity:1, purpose:'drive'}]}}), false);
});
test("saved project is validated and restoration never revives camera evidence", () => {
  let state = m.applyDesign(m.initialMaker(), design, "guide");
  state.guide.phase = "active"; state.guide.checks = ["power-off"];
  state.code = "manual draft";
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.code, "manual draft");
  assert.equal(restored.guide.phase, "prepare");
  assert.equal(restored.guide.restored, true);
  assert.deepEqual(restored.guide.checks, []);
  assert.equal(m.restoreMaker("broken").design, null);
  assert.equal(m.restoreMaker(JSON.stringify({ ...state, design: { ...design, catalog_version: "bad" } })).design, null);
});
test("candidate does not overwrite manual code; applying revision preserves only matching wires", () => {
  let state = m.applyDesign(m.initialMaker(), design, "guide");
  state.code = "manual";
  for (const w of design.wiring) state.guide.confirmed[w.id] = { signature: m.wireSignature(w), mode: "camera", at: "test" };
  const revision = { ...design, revision: 2, code: "new" };
  state.guide.phase = "active"; state.guide.index = 2;
  state.candidate = revision;
  assert.equal(state.code, "manual");
  const applied = m.applyDesign(state, revision, "design");
  assert.equal(applied.code, "new");
  assert.equal(Object.keys(applied.guide.confirmed).length, 4);
  assert.equal(applied.guide.index, 2);
  assert.equal(applied.guide.phase, "active");
  const rewired = { ...revision, wiring: revision.wiring.map((w, i) => i ? w : { ...w, boardPin: "GND_P9" }) };
  assert.equal(Object.keys(m.applyDesign(state, rewired, "guide").guide.confirmed).length, 3);
  assert.equal(Object.keys(m.applyDesign(state, { ...revision, id: "different" }, "guide").guide.confirmed).length, 0);
});
test("unknown wires cannot be restored as authoritative project pins", () => {
  assert(m.validDesign(design));
  assert(!m.validDesign({ ...design, wiring: [{ ...design.wiring[0], boardPin: "GPIO99" }] }));
  assert(!m.validDesign({ ...design, component_ids: ["fake-module"] }));
  assert(!m.validDesign({ ...design, component_ids: ["hc-sr04", "hc-sr04"] }));
  const restored = m.restoreMaker(JSON.stringify({ ...m.initialMaker(), design, guide: { confirmed: null, componentIndex: "invalid", mode: "fake" }, conversation: [null] }));
  assert.equal(restored.guide.componentIndex, 0);
  assert.equal(restored.guide.mode, "camera");
  assert.deepEqual(restored.conversation, []);
});

test("AI choices persist without touching projects and older saved state migrates safely", () => {
  const state = { ...m.initialMaker(), design, code: "manual code", aiModel: "gpt-5.6-luna", aiEffort: "high", aiExpectedOutputTokens: 8000 };
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.aiModel, "gpt-5.6-luna");
  assert.equal(restored.aiEffort, "high");
  assert.equal(restored.aiExpectedOutputTokens, 8000);
  assert.equal(restored.code, "manual code");
  const legacy = { ...state }; delete legacy.aiModel; delete legacy.aiEffort; delete legacy.aiExpectedOutputTokens;
  assert.equal(m.restoreMaker(JSON.stringify(legacy)).aiEffort, "low");
  const invalid = m.restoreMaker(JSON.stringify({ ...state, aiModel: {}, aiEffort: "invented", aiExpectedOutputTokens: -20 }));
  assert.equal(invalid.aiModel, ""); assert.equal(invalid.aiEffort, "low"); assert.equal(invalid.aiExpectedOutputTokens, null);
  assert.equal(m.applyDesign(state, { ...design, revision: 2 }, "design").aiModel, state.aiModel);
});

test("blueprint is a saved view within design; legacy blueprint stage restores without losing the project", () => {
  const state = m.confirmConcept({ ...m.initialMaker(), candidate: design });
  assert.equal(state.stage, 'design');
  assert.equal(state.designView, 'blueprint');
  for (const wire of design.wiring) state.guide.confirmed[wire.id] = {
    signature: m.wireSignature(wire), mode: 'camera', at: '2026-09-29T00:00:00Z',
  };
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.stage, "design");
  assert.equal(restored.designView, "blueprint");
  assert.deepEqual(restored.design.wiring, design.wiring);
  assert.deepEqual(restored.guide.confirmed, state.guide.confirmed);
  const legacy = m.restoreMaker(JSON.stringify({ ...state, stage: 'blueprint', designView: undefined }));
  assert.equal(legacy.stage, 'design');
  assert.equal(legacy.designView, 'blueprint');
  assert.deepEqual(legacy.design.wiring, design.wiring);
  assert.deepEqual(legacy.guide.confirmed, state.guide.confirmed);
  assert.equal(m.restoreMaker(JSON.stringify({ ...m.initialMaker(), stage: "blueprint" })).stage, "design");
  assert.equal(m.restoreMaker(JSON.stringify({ ...m.initialMaker(), stage: "blueprint" })).designView, "concept");
  assert.equal(m.restoreMaker(JSON.stringify({ ...state, aiJobId: "job-123", aiIntent: "ask" })).aiJobId, "job-123");
});

test("all stages send cloud context, while unapproved revisions never replace wiring or code", () => {
  let state = m.confirmConcept({ ...m.initialMaker(), candidate: design });
  state.candidate = { ...design, title: "new concept", revision: 2, code: "new" };
  state.code = "manual draft";
  state.conversation = [{ role: "user", text: "keep same modules" }];
  state.designMode = "fixed";
  const before = JSON.stringify(state);
  for (const stage of ["design", "guide", "deploy"]) {
    const request = m.designRequest({ ...state, stage, designView: stage === 'design' ? 'concept' : 'blueprint' }, "zh-TW", "model");
    assert.equal(request.workflow.stage, stage);
    assert.equal(request.current.title, stage === "design" ? "new concept" : "test");
    assert.equal(request.conversation[0].text, "keep same modules");
    assert.equal(request.workflow.code_draft, stage === "deploy" || stage === "guide" ? "manual draft" : "");
  }
  const blueprint = m.designRequest(state, 'zh-TW', 'model');
  assert.equal(blueprint.workflow.stage, 'blueprint');
  assert.equal(blueprint.current.title, 'test');
  assert.equal(m.designRequest({ ...state, stage: "guide", aiIntent: "ask" }, "en", "model").current.title, "test");
  assert.equal(JSON.stringify(state), before);
});

test("malformed saved concept metadata cannot crash the preview renderer", () => {
  assert(!m.validDesign({ ...design, preview: { screen_lines: [123] } }));
  assert(m.validDesign({ ...design, preview: null }));
});

test("exhibition guide starts and records manual steps without power checks or detector state", () => {
  const before = m.emptyGuide();
  assert.deepEqual(before.checks, []);
  let session = m.startProjectGuide(before);
  assert.equal(session.phase, 'active');
  for (let i=0; i<design.wiring.length; i++) session = m.confirmProjectWire(design, session);
  assert.equal(session.phase, 'review');
  assert.equal(Object.keys(session.confirmed).length, design.wiring.length);
  assert.equal(Object.keys(before.confirmed).length, 0);
  assert.deepEqual(session.checks, []);
  assert.equal(m.confirmProjectWire(design, session), session);
});

test("restart works in every phase and invalidates a same-step cloud result without replacing design or code", () => {
  const state = {...m.initialMaker(), design, code:'hand-edited', conversation:[{role:'user',text:'keep'}]};
  for (const phase of ['prepare', 'active', 'review']) {
    const old = {...m.emptyGuide(), phase, run:3, componentIndex:2, index:3, checks:['power-off'], restored:true,
      confirmed:{old:{signature:'old', mode:'camera',at:'old'}}};
    const next = {...state,guide:m.restartProjectGuide(old)};
    assert.equal(next.guide.componentIndex, 0);
    assert.equal(next.guide.index, 0);
    assert.equal(next.guide.phase, 'prepare');
    assert.equal(next.guide.run, 4);
    assert.equal(next.guide.restored, false);
    assert.deepEqual(next.guide.confirmed, {});
    assert.deepEqual(next.guide.checks, []);
    assert.equal(next.design, state.design);
    assert.equal(next.code, 'hand-edited');
    assert.equal(next.conversation, state.conversation);
    assert.equal(m.restartProjectGuide(next.guide).run, 5);
  }
});

test("manual code requires separate consent before confirming a concept", () => {
  const state = { ...m.applyDesign(m.initialMaker(), design, "design"), code: "manual", candidate: { ...design, revision: 2, code: "new" } };
  assert(m.needsDraftConsent(state));
  assert.equal(m.confirmConcept(state), state);
  assert.equal(m.confirmConcept(state, true).stage, "design");
  assert.equal(m.confirmConcept(state, true).designView, "blueprint");
  assert.equal(m.confirmConcept(state, true).code, "new");
  assert.equal(m.confirmConcept(m.initialMaker()).stage, "design");
});

test("fixed and free modes persist without replacing approved or working versions", () => {
  const candidate = { ...design, revision: 2, title: 'working preview' };
  const state = { ...m.initialMaker(), design, candidate, code: 'manual draft',
    conversation: [{role: 'user', text: 'old car'}] };
  for (const mode of ['fixed', 'free']) {
    const restored = m.restoreMaker(JSON.stringify({ ...state, designMode: mode }));
    assert.equal(restored.designMode, mode);
    assert.deepEqual(restored.design, design);
    assert.deepEqual(restored.candidate, candidate);
    assert.equal(restored.code, 'manual draft');
    assert.deepEqual(restored.conversation, state.conversation);
    const request = m.designRequest(restored, 'zh-TW', null);
    assert.equal(request.design_mode, mode);
    assert.deepEqual(request.component_ids, state.selected);
    assert.equal(request.current.revision, 2);
    assert.equal(request.intent, 'auto');
    assert.deepEqual(request.conversation, state.conversation);
    const ask = m.designRequest({ ...restored, aiIntent: 'ask' }, 'zh-TW', null);
    assert.deepEqual(ask.conversation, state.conversation);
    assert.equal(ask.generate_image, false);
  }
  const legacy = { ...state }; delete legacy.designMode;
  assert.equal(m.restoreMaker(JSON.stringify(legacy)).designMode, 'free');
  assert.equal(m.restoreMaker(JSON.stringify({...state, designMode: 'invalid'})).designMode, 'free');
});

test("one conversation ignores legacy UI intent and keeps context for questions and revisions", () => {
  for (const aiIntent of ['ask','design','auto']) {
    const state=m.restoreMaker(JSON.stringify({...m.initialMaker(),aiIntent,design,conversation:[{role:'user',text:'keep this'}]}));
    assert.equal(state.aiIntent,'auto');
    const req=m.designRequest(state,'zh-TW',null);
    assert.equal(req.intent,'auto');assert.equal(req.generate_image,true);
    assert.equal(req.conversation[0].text,'keep this');
  }
});

test("clear conversation only clears messages and never abandons a pending AI job",()=>{
  const state={...m.initialMaker(),design,candidate:{...design,revision:2},code:'manual',prompt:'unsent text',
    debug:{caseId:'case'},conversation:[{role:'user',text:'old'}]};
  const result=m.clearMakerConversation(state);
  assert.deepEqual(result,{...state,conversation:[]});
  assert.equal(result.design,state.design);assert.equal(result.guide,state.guide);
  assert.deepEqual(m.restoreMaker(JSON.stringify(result)).conversation,[]);
  const busy={...state,aiJobId:'pending'};
  assert.equal(m.clearMakerConversation(busy),busy);
});

test("demo is a preview; approved code and wire progress change only after confirmation",()=>{
  const state={...m.initialMaker(),design,code:'manual',stage:'guide',conversation:[{role:'user',text:'keep'}]};
  const demo={...design,id:'demo',code:'fixed-demo'};
  const next=m.previewDemo(state,demo);
  assert.equal(next.candidate,demo);assert.equal(next.stage,'design');
  assert.equal(next.design,state.design);assert.equal(next.guide,state.guide);
  assert.equal(next.code,'manual');assert.equal(next.conversation,state.conversation);
  assert.equal(m.confirmConcept(next),next,'manual code still needs separate consent');
  assert.equal(m.previewDemo(state,{...demo,source:'ai'}),state);
  const busy={...state,aiJobId:'pending'};assert.equal(m.previewDemo(busy,demo),busy);
});
