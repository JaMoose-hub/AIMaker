import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {maker,designFor} from './project_guide_fixture.mjs';
const helper={};new Function('exports',ts.transpileModule(readFileSync(new URL('../src/lib/wiringReceipt.ts',import.meta.url),'utf8'),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(helper);
function fixture(){
  const state={...maker.initialMaker(),design:designFor(),code:'unchanged-code'};
  const before={project_id:state.design.id,code_hash:'code-hash',guide_hash:'before',test_keys:{'hc-sr04':'before'}};
  const after={...before,guide_hash:'after',test_keys:{'hc-sr04':'after'}};
  const confirmed={'wire-1':{signature:'valid-wire',mode:'camera',at:'2026-10-04T07:00:00.000Z'}};
  const outbox={request_id:'explicit-human',conversation_id:'chat',context_epoch:0,message_id:'question',flow_id:'flow',
    action:{op:'review',wire_id:'wire-1',decision:'confirmed'},context:{guide_confirmations:confirmed},before_binding:before,
    before_signature:helper.wiringReceiptSignature(state)};
  const receipt={request_id:'explicit-human',flow_id:'flow',context_epoch:0,project_id:state.design.id,project_revision:state.design.revision,
    op:'review',wire_id:'wire-1',decision:'confirmed',before_binding:structuredClone(before),after_binding:structuredClone(after),
    guide_confirmations:confirmed,guide_run:0,test_keys:after.test_keys,review_id:'review',round:1,context_fingerprint:'context-hash'};
  const session={binding:structuredClone(after),wiring_review:{id:'review',round:1,status:'ready'}};
  return{state,outbox,receipt,session};
}
test('wiring receipt restores only an exact explicit human decision and preserves navigation and draft',()=>{
  const f=fixture(),state={...f.state,prompt:'new draft',guide:{...f.state.guide,componentIndex:2}};
  const result=helper.guideFromWiringReceipt(state,f.outbox,f.receipt,f.session,'chat',0);
  assert.ok(result);assert.deepEqual(result.confirmed,f.receipt.guide_confirmations);assert.equal(result.componentIndex,2);
  assert.equal(state.prompt,'new draft');assert.deepEqual(f.state.guide.confirmed,{});
});
test('wiring receipt cannot restore after another human decision or a new wiring round',()=>{
  const f=fixture(),changed={...f.state,guide:{...f.state.guide,confirmed:{other:{at:'later'}}}};
  assert.equal(helper.guideFromWiringReceipt(changed,f.outbox,f.receipt,f.session,'chat',0),null);
  assert.equal(helper.guideFromWiringReceipt(f.state,f.outbox,f.receipt,{...f.session,wiring_review:{id:'review',round:2,status:'collecting'}},'chat',0),null);
});
test('wiring receipt cannot upgrade an observation or a foreign receipt into confirmation',()=>{
  const f=fixture();assert.equal(helper.guideFromWiringReceipt(f.state,f.outbox,null,f.session,'chat',0),null);
  assert.equal(helper.guideFromWiringReceipt(f.state,f.outbox,{...f.receipt,request_id:'other-human'},f.session,'chat',0),null);
  assert.equal(helper.guideFromWiringReceipt(f.state,f.outbox,f.receipt,f.session,'chat',1),null);
});
