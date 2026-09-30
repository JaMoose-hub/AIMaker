import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import {systemTextUrl} from './system_text_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const url=source=>`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const compile=source=>ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const catalog=JSON.parse(read('../../profiles/component-catalog.json'));
const makerURL=url(compile(read('../src/lib/maker.ts').replace(/import catalog from [^;]+;/,`const catalog=${JSON.stringify(catalog)};`)));
const m=await import(makerURL);
const hooksURL=url(`let values=[],cursor=0; export const reset=()=>{values=[];cursor=0};
  export const begin=()=>{cursor=0}; export const useState=initial=>{const i=cursor++; if(!(i in values))values[i]=initial;
    return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value}];};`);
const hooks=await import(hooksURL);
const textURL=url(`export let locale='zh-TW'; export const setLocale=v=>{locale=v}; export const useMakerText=()=>(zh,en)=>locale==='en'?en:zh; export const useI18n=()=>({locale});`);
const translations=await import(textURL);
let studioJS=compile(read('../src/components/DesignStudio.tsx'));
for(const [key,value] of Object.entries({react:hooksURL,'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'),
  '../lib/maker':makerURL,'../lib/useMaker':textURL,
  '../lib/i18n':textURL,'../lib/systemText':systemTextUrl,
  './ProjectConcept':url('export function ProjectConcept(){}; export function ProjectGenerationStatus(){}'),
  './DesignViewSwitch':url('export function DesignViewSwitch(){}'),
}))studioJS=studioJS.replaceAll(JSON.stringify(key),JSON.stringify(value));
const {DesignStudio}=await import(url(studioJS));
const image=id=>({id:id.repeat(32),url:`/api/design/images/${id.repeat(32)}`,width:1024,height:1024});
const approved={id:'discard-fixture',revision:2,source:'ai',title:'Confirmed v2',summary:'Saved project',
  catalog_version:catalog.version,component_ids:['hc-sr04'],code:'approved code',tests:[],features:[],instructions:[],unresolved:[],bom:[],image:image('a'),
  wiring:catalog.modules[0].steps.map(w=>({...w,id:`hc-sr04:${w.id}`,componentId:'hc-sr04'}))};
const candidate={...approved,revision:3,title:'Unconfirmed v3',code:'preview code',image:image('b')};
function stateWithPreview(){
  const state=m.applyDesign(m.initialMaker(),approved,'design');
  return {...state,candidate,code:'manual draft',prompt:'Keep my input',guide:{...state.guide,phase:'active',index:2,
    confirmed:{[approved.wiring[0].id]:{signature:m.wireSignature(approved.wiring[0]),mode:'2d',at:'2026-09-30T09:00:00Z'}}},
    conversation:[{role:'user',text:'Keep this history'}],hardware:{test:'saved result'},debug:{panelOpen:true,caseId:'saved-case'}};
}
function nodes(tree){return Array.isArray(tree)?tree.flatMap(nodes):tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
function textOf(tree){return Array.isArray(tree)?tree.map(textOf).join(''):tree&&typeof tree==='object'?textOf(tree.props?.children):typeof tree==='string'||typeof tree==='number'?String(tree):'';}
function fixture(state=stateWithPreview(),busy=false,locale='zh-TW'){
  hooks.reset();translations.setLocale(locale);
  const adopted=[];
  const props={state,busy,onAdopt:value=>adopted.push(value),onViewChange(){},setState:update=>{props.state=typeof update==='function'?update(props.state):update}};
  const render=()=>{hooks.begin();return DesignStudio(props)};
  const button=name=>nodes(render()).find(n=>n.type==='button'&&textOf(n)===name);
  return {render,button,adopted,state:()=>props.state,update:values=>{props.state={...props.state,...values}},busy:value=>{props.busy=value},
    concept:()=>nodes(render()).find(n=>n.type?.name==='ProjectConcept'),feedback:()=>nodes(render()).find(n=>n.props?.className==='maker-concept-feedback')};
}

test('discard preserves every approved project, code, wiring, chat and hardware field',()=>{
  const state=stateWithPreview(),next=m.discardConcept(state,candidate);
  assert.equal(next.candidate,null);
  for(const key of Object.keys(state).filter(key=>key!=='candidate'))assert.equal(next[key],state[key],key);
  assert.equal(m.designRequest(next,'zh-TW',null).current,approved);
  assert.equal(m.discardConcept(next),next);
});

test('saved discard restores confirmed v2 image and manual wiring, never rejected v3',()=>{
  const state=stateWithPreview(),next=m.discardConcept(state);
  const restored=m.restoreMaker(JSON.stringify(next));
  assert.equal(restored.candidate,null);
  assert.equal(restored.design.revision,2);
  assert.deepEqual(restored.design.image,approved.image);
  assert.equal(restored.code,state.code);
  assert.deepEqual(restored.guide.confirmed,state.guide.confirmed);
  assert.deepEqual(restored.conversation,state.conversation);
  assert.equal(restored.aiJobId,null);
});

test('discard refuses in-flight jobs and stale handlers targeting a different preview',()=>{
  const state=stateWithPreview();
  const busy={...state,aiJobId:'live-job'};
  assert.equal(m.discardConcept(busy,candidate),busy);
  const newer={...state,candidate:{...candidate,revision:4}};
  assert.equal(m.discardConcept(newer,candidate),newer);
  assert.equal(m.discardConcept(m.initialMaker()).design,null);
});

test('real discard handler restores the approved image and clearly labels confirmed v2',()=>{
  const f=fixture(),before=f.state();
  assert.equal(f.render().props['data-concept-state'],'preview');
  assert.match(textOf(f.render()),/未確認預覽 · v3/);
  assert.equal(f.concept().props.design.image,candidate.image);
  f.button('捨棄此預覽').props.onClick();
  assert.equal(f.render().props['data-concept-state'],'approved');
  assert.match(textOf(f.render()),/已確認作品 · v2/);
  assert.equal(f.concept().props.design,approved);
  assert.equal(f.feedback().props.role,'status');
  assert.equal(textOf(f.feedback()),'已捨棄預覽，目前顯示已確認作品 v2。');
  assert.equal(f.button('捨棄此預覽'),undefined);
  for(const key of ['design','code','guide','conversation','hardware','debug'])assert.equal(f.state()[key],before[key]);
  assert.deepEqual(f.adopted,[]);
});

test('first preview discard returns empty, without inventing a confirmed version or image',()=>{
  const f=fixture({...m.initialMaker(),candidate});
  f.button('捨棄此預覽').props.onClick();
  assert.equal(f.render().props['data-concept-state'],'empty');
  assert.equal(f.concept(),undefined);
  assert.match(textOf(f.render()),/先看見你的作品/);
  assert.equal(textOf(f.feedback()),'已捨棄預覽，尚未有已確認作品。');
  assert.equal(m.restoreMaker(JSON.stringify(f.state())).design,null);
});

test('enqueue and polling disable both discard and adoption without abandoning work',()=>{
  for(const polling of [false,true]){
    const state={...stateWithPreview(),aiJobId:polling?'live-job':null};
    const f=fixture(state,!polling);
    assert.equal(f.render().props['aria-busy'],true);
    const discard=f.button('捨棄此預覽');
    assert.equal(discard.props.disabled,true);
    assert.match(discard.props.title,/AI 處理完成後/);
    assert.equal(f.button('確認作品並查看藍圖 →').props.disabled,true);
    discard.props.onClick();
    assert.equal(f.state(),state);
    assert.equal(f.feedback(),undefined);
  }
});

test('late discard clicks cannot erase a newer candidate or a newly started AI job',()=>{
  for(const change of [{candidate:{...candidate,revision:4}},{aiJobId:'new-job'}]){
    const f=fixture(),old=f.button('捨棄此預覽');
    f.update(change);
    const before=f.state();
    old.props.onClick();
    assert.equal(f.state(),before);
    assert.equal(f.feedback(),undefined);
  }
});

test('discard clears manual-code consent and feedback does not leak to another revision',()=>{
  const f=fixture();
  f.button('確認作品並查看藍圖 →').props.onClick();
  assert(f.button('確認取代並進入 Blueprint'));
  f.button('捨棄此預覽').props.onClick();
  assert.equal(f.button('確認取代並進入 Blueprint'),undefined);
  f.update({candidate});
  assert.equal(f.feedback(),undefined);
  assert.equal(f.button('確認取代並進入 Blueprint'),undefined);
  f.update({candidate:null,design:candidate});
  assert.equal(f.feedback(),undefined);
  assert.match(textOf(f.render()),/已確認作品 · v3/);
});

test('English version and discard feedback remain concise and explicit',()=>{
  const f=fixture(stateWithPreview(),false,'en');
  assert.match(textOf(f.render()),/Unconfirmed preview · v3/);
  f.button('Discard preview').props.onClick();
  assert.match(textOf(f.render()),/Confirmed project · v2/);
  assert.equal(textOf(f.feedback()),'Preview discarded. Showing confirmed project v2.');
  const fresh=fixture({...f.state()},false,'en');
  assert.match(textOf(fresh.render()),/Confirmed project · v2/);
  assert.equal(fresh.feedback(),undefined,'action notice is transient, version label survives remount');
});
