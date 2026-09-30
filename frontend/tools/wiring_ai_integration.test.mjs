import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {maker, componentTests, designFor, renderTestCard} from './project_guide_fixture.mjs';

const confirmed = design => ({...maker.emptyGuide(),phase:'review',componentIndex:1,index:2,
  confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),mode:'camera',at:'2026-09-29T00:00:00Z'}]))});

test('reviewing pins and returning preserves confirmations, test bindings and resume position',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);const guide=confirmed(design);
  const key=componentTests.componentTestKey(design,guide,'hc-sr04');
  const review=maker.reviewProjectWire(design,guide,'hc-sr04','ECHO','debug');
  assert.equal(review.confirmed,guide.confirmed);
  assert.equal(review.inspectionSource,'debug');
  assert.equal(maker.currentWire(design,review).componentPin,'ECHO');
  assert.equal(componentTests.componentTestKey(design,review,'hc-sr04'),key);
  assert.deepEqual(maker.confirmProjectWire(design,review),review);
  const next=maker.reviewProjectWire(design,review,'mrd-tf240-8p-cs','GND','guide');
  const resumed=maker.resumeProjectGuide(next);
  assert.equal(resumed.componentIndex,guide.componentIndex);assert.equal(resumed.index,guide.index);
  assert.equal(resumed.phase,guide.phase);assert.equal(resumed.confirmed,guide.confirmed);
  assert.deepEqual(maker.reviewProjectWire(design,guide,'hc-sr04','missing'),guide);
});

test('explicit edit invalidates only the selected module; repeated confirmation keeps its timestamp',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);const guide=confirmed(design);
  const edited=maker.editProjectComponent(design,maker.reviewProjectWire(design,guide,'hc-sr04','ECHO'));
  assert.equal(edited.index,0,'Restart the selected module so every cleared pin can be confirmed in order');
  assert.ok(design.wiring.filter(w=>w.componentId==='hc-sr04').every(w=>!edited.confirmed[w.id]));
  assert.ok(design.wiring.filter(w=>w.componentId==='mrd-tf240-8p-cs').every(w=>edited.confirmed[w.id]===guide.confirmed[w.id]));
  const active={...guide,phase:'active',componentIndex:0,index:0};
  const again=maker.confirmProjectWire(design,active);
  assert.equal(componentTests.componentTestKey(design,active,'hc-sr04'),componentTests.componentTestKey(design,again,'hc-sr04'));
});

test('return to debug preserves original problem and exact run instead of overwriting with undefined',()=>{
  const design=designFor();const initial={...maker.initialMaker(),design,debug:{componentId:'hc-sr04',runId:'run-old',symptom:'no_echo',source:'guide'}};
  const next=maker.enterDebug(initial,'mrd-tf240-8p-cs');
  assert.equal(next.stage,'guide');assert.equal(next.debug.panelOpen,true);assert.equal(next.debug.intent,'debug');
  assert.equal(next.debug.runId,'run-old');assert.equal(next.debug.symptom,'no_echo');
  assert.equal(next.debug.componentId,'hc-sr04');assert.equal(next.debug.selectedComponentId,'mrd-tf240-8p-cs');
  assert.equal(maker.enterDebug(next,'hc-sr04','run-new','no_progress').debug.runId,'run-new');
});

test('return from a read-only pin review opens the same assistant and restores the guide cursor',()=>{
  const design=designFor(['hc-sr04','mrd-tf240-8p-cs']);const guide=confirmed(design);
  const debug={caseId:'case-old',runId:'run-old',trialId:'trial-old',symptom:'screen blank',panelOpen:false,intent:'debug'};
  const reviewed={...maker.initialMaker(),stage:'guide',design,guide:maker.reviewProjectWire(design,guide,'hc-sr04','ECHO','debug'),debug};
  const resumed=maker.enterDebug(reviewed);
  assert.equal(resumed.stage,'guide');assert.deepEqual(resumed.debug,{...debug,panelOpen:true,selectedComponentId:undefined});
  assert.equal(resumed.guide.index,guide.index);assert.equal(resumed.guide.componentIndex,guide.componentIndex);
  assert.equal(resumed.guide.phase,guide.phase);assert.equal(resumed.guide.confirmed,guide.confirmed);
  const restored=maker.restoreMaker(JSON.stringify({...resumed,stage:'deploy'}));
  assert.equal(restored.debug.caseId,'case-old');assert.equal(restored.debug.intent,'debug');assert.equal(restored.debug.panelOpen,true);
});

test('returning from a wiring conversation diagram preserves its focus until an explicit new debug issue',()=>{
  const design=designFor();const debug={panelOpen:false,intent:'wiring',caseId:'case-old',symptom:'check this connector'};
  const state={...maker.initialMaker(),stage:'guide',design,debug,guide:maker.reviewProjectWire(design,maker.emptyGuide(),'hc-sr04','ECHO','debug')};
  const resumed=maker.enterDebug(state);
  assert.equal(resumed.debug.intent,'wiring');assert.equal(resumed.debug.panelOpen,true);assert.equal(resumed.debug.caseId,'case-old');
  assert.equal(maker.enterDebug(resumed,'hc-sr04','new-run','no_echo').debug.intent,'debug');
  assert.equal(maker.enterDebug({...resumed,stage:'deploy'}).debug.intent,'debug');
});

test('exact TFT confirmation never substitutes another active run or offers a new test',async()=>{
  const design=designFor(['mrd-tf240-8p-cs']);const session={...confirmed(design),componentIndex:0};
  const run={id:'new-run',project_id:design.id,component_id:'mrd-tf240-8p-cs',guide_key:componentTests.componentTestKey(design,session,'mrd-tf240-8p-cs'),
    reserved:true,outcome:'awaiting_confirmation',phase:'awaiting_visual',created_at:1,options:['1111','2222'],samples:{},logs:[]};
  const tests={status:{connected:true,active:run,results:[run]},pending:false,error:null};
  const wrong=await renderTestCard({design,session,tests,runId:'old-run'});
  assert.match(wrong,/不會改用其他測試/);assert.doesNotMatch(wrong,/1111|確認顯示結果/);
  const right=await renderTestCard({design,session,tests,runId:'new-run'});
  assert.match(right,/1111/);assert.match(right,/確認顯示結果/);assert.doesNotMatch(right,/重新測試 MRD/);
});

const storeSource=readFileSync(new URL('../src/lib/componentTestStore.ts',import.meta.url),'utf8')
  .replace('import { makerRequest } from "./maker";','const makerRequest = () => { throw new Error("Unexpected default request"); };');
const storeJS=ts.transpileModule(storeSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {createComponentTestStore}=await import(`data:text/javascript;base64,${Buffer.from(storeJS).toString('base64')}`);
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('guide and chat share one poll; a late GET cannot overwrite the action result',async()=>{
  const get=deferred(),post=deferred(),calls=[];
  const store=createComponentTestStore('p',async(path,body,signal)=>{calls.push({path,body,signal});return body?post.promise:get.promise;});
  const stopGuide=store.subscribe(()=>{}),stopChat=store.subscribe(()=>{});
  assert.equal(calls.length,1);
  const sending=store.send('test/action',{action:'visual'});
  assert.equal(await store.send('test/action',{action:'visual'}),false);
  const fresh={connected:true,active:null,results:[{id:'fresh'}]};
  post.resolve(fresh);assert.equal(await sending,true);
  get.resolve({connected:true,active:null,results:[{id:'old'}]});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(store.getSnapshot().status,fresh);
  stopGuide();assert.equal(calls[0].signal.aborted,false);
  stopChat();assert.equal(calls[0].signal.aborted,true);
});
