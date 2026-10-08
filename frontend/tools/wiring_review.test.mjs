import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {photoSequence, framingGuide, expectedLocationHelpers, expectedLocationComponent} from './wiring_photo_flow_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const compile = (path, require) => {
  const module = {};
  new Function('React', 'require', 'exports', ts.transpileModule(read(path), {
    compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS, jsx:ts.JsxEmit.React},
  }).outputText)(React, require, module);
  return module;
};
const helpers = compile('../src/lib/wiringReview.ts', () => ({}));
function makeCard(language='zh', hooks=React) {
  return compile('../src/components/WiringReviewCard.tsx', name => name === 'react' ? hooks
    : name.endsWith('wiringExpectedLocation') ? expectedLocationHelpers
    : name.endsWith('WiringExpectedLocation') ? expectedLocationComponent(language)
    : name.endsWith('WiringPhotoSequence') ? {WiringPhotoSequence:photoSequence(hooks,language)}
    : name.endsWith('WiringFramingGuide') ? {WiringFramingGuide:framingGuide(language)}
    : name.endsWith('wiringReview') ? helpers : name.endsWith('useMaker') ? {useMakerText:()=> (zh,en)=>language==='en'?en:zh} : {}).WiringReviewCard;
}
const roleNames = ['pi_side_a','pi_side_b','component_header'];
const slot = role => ({role, capture_id:role, image_url:`/api/debug/sessions/s/evidence/${role}`,size:[3840,2880],sha256:'photo-hash',crop:null,crop_source:'none',available:true});
const endpoint = (id,role,pin,color) => ({id,capture_id:role,role,physical_pin:pin,pin_label:null,color,evidence:'Wire is partially visible',color_visibility:'partial',box:null});
const base = {
  id:'review1',revision:4,round:1,component_id:'hc-sr04',status:'ready',
  slots:Object.fromEntries(roleNames.map(role=>[role,slot(role)])),observations:[endpoint('blue-a','pi_side_a',null,'blue')],
  results:[{wire_id:'echo',expected:{board_pin:'12',physical_pin:12,bcm:18,component_pin:'Echo',connection_kind:'direct'},
    pi_candidates:[endpoint('blue-a','pi_side_a',null,'blue'),endpoint('blue-b','pi_side_b',null,'blue')],
    component_candidates:[{...endpoint('echo','component_header',null,'blue'),pin_label:'Echo'}],comparison:'ambiguous',evidence:'Duplicate blue wires',next_step:'Follow the same wire.'}],
  reviews:{},missing_roles:[],no_progress_count:0,error:null,
};
const props = (review=base) => ({review,components:[{id:'hc-sr04',label:'HC-SR04'}],captureReady:true,
  onAction(){throw Error('Rendering must not submit an action');},onReview(){throw Error('AI/render must not confirm wiring');}});
const render = (review=base, extras={}, language='zh') => renderToStaticMarkup(React.createElement(makeCard(language),{...props(review),...extras}));

test('portrait crop maps through horizontal letterboxing and clamps an off-image drag',()=>{
  const rect={left:100,top:50,width:600,height:400};
  assert.deepEqual(helpers.containedImageRect(rect,[300,600]),{left:300,top:50,width:200,height:400});
  assert.equal(helpers.imagePointFromClient(150,250,rect,[300,600]),null);
  assert.deepEqual(helpers.imagePointFromClient(400,250,rect,[300,600]),[.5,.5]);
  assert.deepEqual(helpers.imagePointFromClient(800,600,rect,[300,600],true),[1,1]);
});
test('landscape and resized viewport coordinates preserve the same original normalized crop',()=>{
  assert.deepEqual(helpers.imagePointFromClient(200,150,{left:0,top:0,width:400,height:400},[400,200]),[.5,.25]);
  assert.deepEqual(helpers.imagePointFromClient(100,75,{left:0,top:0,width:200,height:200},[400,200]),[.5,.25]);
  assert.deepEqual(helpers.cropFromPoints([.9,.8],[.1,.2]),[.1,.2,.9,.8]);
  assert.equal(helpers.cropFromPoints([.1,.1],[.1,.1]),null);
  assert.equal(helpers.validWiringCrop([0,0,NaN,1]),false);
  assert.equal(helpers.containedImageRect({left:0,top:0,width:0,height:2},[10,10]),null);
});
test('review action is bound to the viewed revision and cannot substitute an expected pin',()=>{
  assert.deepEqual(helpers.boundWiringAction(base,{op:'crop',role:'pi_side_a',crop:[0,.2,1,.8]}),
    {op:'crop',role:'pi_side_a',crop:[0,.2,1,.8],review_id:'review1',revision:4});
  assert.equal(base.observations[0].physical_pin,null);
});
test('analysis requires three available views; read-only ready results are not rerun',()=>{
  assert.equal(helpers.canAnalyseWiring({...base,status:'collecting'}),true);
  assert.equal(helpers.canAnalyseWiring(base),false);
  for(const role of roleNames) {
    assert.equal(helpers.canAnalyseWiring({...base,status:'collecting',slots:{...base.slots,[role]:null}}),false);
    assert.equal(helpers.canAnalyseWiring({...base,status:'collecting',slots:{...base.slots,[role]:{...slot(role),available:false}}}),false);
  }
  assert.equal(helpers.canAnalyseWiring({...base,status:'collecting'},true),false);
  assert.equal(helpers.canAnalyseWiring({...base,status:'collecting'},false,true),false);
  assert.equal(helpers.canAnalyseWiring({...base,status:'collecting',no_progress_count:2}),false);
});
test('three photo roles, all repeated-color candidates and nullable Pi identity stay visible',()=>{
  const html=render();
  assert.match(html,/Pi 第一側/); assert.match(html,/Pi 另一側/); assert.match(html,/零件接頭/);
  assert.match(html,/Pi 實體 Pin 12/); assert.match(html,/BCM 18/);
  assert.match(html,/接頭 blue-a/); assert.match(html,/接頭 blue-b/); assert.match(html,/腳號待確認/);
  assert.match(html,/多個候選/); assert.match(html,/尚未確認接對/);
  assert.doesNotMatch(html,/你已親自確認接對|功能通過/);
});

test('module labels survive hidden contact in review details without borrowing identity for Pi observations',()=>{
  const labels=['VCC','TRIG','ECHO','GND'];
  const components=labels.map(label=>({...endpoint(`module-${label}`,'component_header',null,'blue'),pin_id:null,
    module_pin_id:label,module_pin_evidence:`Readable ${label} label beside housing.`,contact:'uncertain'}));
  const pi={...endpoint('unknown-pi','pi_side_a',null,'blue'),module_pin_id:'MUST_NOT_IDENTIFY_PI',
    module_pin_evidence:'MUST_NOT_EXPLAIN_PI'};
  const state={...base,observations:[],results:[{...base.results[0],pi_candidates:[pi],component_candidates:components}]};
  const before=structuredClone(state),html=render(state);
  for(const label of labels) assert.match(html,new RegExp(`<strong>${label}</strong>`));
  assert.equal((html.match(/標字位置已辨識；插接待確認/g)||[]).length,4);
  assert.equal((html.match(/腳號待確認/g)||[]).length,1);
  assert.doesNotMatch(html,/MUST_NOT_IDENTIFY_PI|MUST_NOT_EXPLAIN_PI|aria-pressed="true"|功能通過/);
  assert.deepEqual(state,before);
});
test('similar colors never check the human decision or enable retest',()=>{
  const html=render({...base,results:[{...base.results[0],comparison:'similar'}]}, {onRetest(){throw Error('No automatic hardware call');}});
  assert.match(html,/線色相符只提供線索/);
  assert.doesNotMatch(html,/重新測試這個零件/);
  assert.doesNotMatch(html,/aria-pressed="true"/);
});
test('human confirmation enables an explicit retest button and remains separate from functional pass',()=>{
  const html=render({...base,reviews:{echo:{decision:'confirmed',source:'human',at:100,review_revision:4}}},{onRetest(){}});
  assert.match(html,/你已亲自確認接對|你已親自確認接對/);
  assert.match(html,/重新測試這個零件/);
  assert.match(html,/功能測試結果另行記錄/);
  assert.doesNotMatch(html,/功能通過/);
});
test('incomplete or occluded observations never appear as unplugged, and intermediate wiring explains color limits',()=>{
  const row={...base.results[0],pi_candidates:[],comparison:'unknown',expected:{...base.results[0].expected,connection_kind:'divider'}};
  const html=render({...base,results:[row],status:'needs_human',no_progress_count:2});
  assert.match(html,/不能視為未接線/);
  assert.match(html,/此接法含中間連接/);
  assert.match(html,/請沿著同一條線親自核對兩端/);
});
test('retained human decision on replaced evidence is not presented as current confirmation',()=>{
  const html=render({...base,reviews:{echo:{decision:'confirmed',source:'human',at:'2026-10-04T12:00:00Z',review_revision:1,evidence_stale:true}}},{onRetest(){}});
  assert.match(html,/保留先前的人工決定/);
  assert.doesNotMatch(html,/你已親自確認接對|重新測試這個零件|aria-pressed="true"/);
});
test('stale session requires an explicit new review; English is fully localized',()=>{
  const stale=render({...base,status:'stale'});
  assert.match(stale,/本輪已過期/); assert.match(stale,/重新開始本輪核對/);
  assert.doesNotMatch(stale,/我已親自確認接對/);
  const html=render(base,{},'en');
  assert.doesNotMatch(html,/\p{Script=Han}/u);
  assert.match(html,/Physical pin|physical pin/);
});

// Inspect actual React event handlers without a browser; mounting runs no calls.
function eventTree(overrides={}) {
  const hooks={...React,useState:initial=>[typeof initial==='function'?initial():initial,()=>{}],useRef:value=>({current:value}),useEffect(){}};
  const Card=makeCard('en',hooks);
  const tree=Card({...props(),...overrides});
  const all=[];
  const visit=node=>{if(!node||typeof node!=='object')return;if(Array.isArray(node)){node.forEach(visit);return;}all.push(node);visit(node.props?.children);};
  visit(tree);
  return all;
}
test('changing module selection is local and never analyses or confirms',()=>{
  const calls=[];
  const nodes=eventTree({onSelectComponent:id=>calls.push(id)});
  nodes.find(node=>node.type==='select').props.onChange({target:{value:'tft'}});
  assert.deepEqual(calls,['tft']);
});
test('only explicit human button sends a human decision; photograph action is revision bound',async()=>{
  const reviews=[];const actions=[];
  let nodes=eventTree({onReview:(...args)=>reviews.push(args),onAction:action=>actions.push(action)});
  const confirm=nodes.find(node=>node.type==='button'&&node.props.children==='I checked: connected correctly');
  confirm.props.onClick(); await Promise.resolve();
  assert.deepEqual(reviews,[['echo','confirmed']]);assert.deepEqual(actions,[]);
  nodes=eventTree({onAction:action=>actions.push(action)});
  nodes.find(node=>node.type==='button'&&node.props.children==='Retake this view').props.onClick();await Promise.resolve();
  assert.deepEqual(actions,[{op:'capture',role:'pi_side_a',review_id:'review1',revision:4}]);
});
test('human-only state prevents losing review rows to a retake while retaining human buttons and photo viewing',()=>{
  const nodes=eventTree({review:{...base,status:'needs_human',no_progress_count:2}});
  assert(nodes.filter(node=>node.type==='button'&&node.props.children==='Retake this view').every(node=>node.props.disabled));
  assert.equal(nodes.find(node=>node.type==='fieldset').props.disabled,false);
  assert.equal(nodes.find(node=>node.type==='button'&&node.props.children==='View / crop').props.disabled,false);
});
test('assistant tools hide an empty review body while retaining expanded or recommended evidence',()=>{
  const css=read('../src/assistant.css');
  const hideRules=[...css.matchAll(/([^{}]+)\{[^{}]*display\s*:\s*none\s*;?[^{}]*\}/g)]
    .map(match=>match[1]).filter(selector=>selector.includes('.is-actions-only .ai-debug-chat'));
  assert.equal(hideRules.length,1);
  assert.match(hideRules[0],/:not\(:has\(\.ai-debug-current,\s*\.wiring-review-entry\[data-expanded="true"\],\s*\.wiring-review-entry\[data-recommended="true"\]\)\)/);
  const html=render(null);
  assert.match(html,/wiring-review-card/);assert.match(html,/開始接線照片核對/);
  assert.doesNotMatch(html,/ai-debug-current/);
});

const diagnosis = (status, extra={}) => ({status,observed_board_pin:'GPIO18',observed_physical_pin:12,
  observed_component_pin:'TRIG',board_connector_id:'pi_side_a:wrong',component_connector_id:'component_header:trig',
  evidence:'Visible wire route, not colour alone.',retake_roles:[],...extra});

test('legacy matching or different colors cannot become a pin accusation or a pass',()=>{
  for (const comparison of ['similar','different','ambiguous','unknown']) {
    assert.equal(helpers.wiringFindingStatus({...base.results[0],comparison}),'uncertain');
    assert.match(render({...base,results:[{...base.results[0],comparison}]}),/>需確認</);
  }
});

test('suspected pins are shown first without mutating the original order or human decisions',()=>{
  const rows=[{...base.results[0],wire_id:'ok',diagnosis:diagnosis('no_issue_seen')},
    {...base.results[0],wire_id:'unclear'}, {...base.results[0],wire_id:'wrong',diagnosis:diagnosis('suspected')}];
  assert.deepEqual(helpers.prioritiseWiringResults(rows).map(row=>row.wire_id),['wrong','unclear','ok']);
  assert.deepEqual(rows.map(row=>row.wire_id),['ok','unclear','wrong']);
  const html=render({...base,results:rows});
  assert.match(html,/1 條優先核對/);
  assert.match(html,/data-finding="suspected"/);
  assert.doesNotMatch(html,/aria-pressed="true"/);
});

test('result gives expected and possible actual pins with long evidence collapsed by default',()=>{
  const row={...base.results[0],expected:{...base.results[0].expected,physical_pin:11,bcm:17,component_pin:'TRIG'},diagnosis:diagnosis('suspected')};
  const html=render({...base,results:[row]});
  assert.match(html,/TRIG.*Pi Pin 11/);
  assert.match(html,/照片疑似：TRIG.*Pi Pin 12/);
  assert.match(html,/先斷電/);
  assert.match(html,/<details class="wr-finding-details"><summary>查看判斷依據/);
  assert.doesNotMatch(html,/<details class="wr-finding-details" open/);
});

test('unclear endpoint offers only its missing view and never queues a retake on render',()=>{
  const row={...base.results[0],diagnosis:diagnosis('uncertain',{retake_roles:['component_header']})};
  const html=render({...base,results:[row]});
  assert.match(html,/補拍零件接頭/);
  assert.doesNotMatch(html,/補拍Pi 第一側|補拍Pi 另一側/);
});
