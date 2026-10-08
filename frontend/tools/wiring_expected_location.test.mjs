import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers, expectedLocationHelpers as helpers, expectedLocationComponent, framingGuide, photoSequence} from './wiring_photo_flow_fixture.mjs';

const tr=(zh)=>zh;
const echo=(extra={})=>({wire_id:'wire-echo',component_id:'hc-sr04',
  expected:{component_pin:'ECHO',board_pin:'GPIO18',physical_pin:12,bcm:18,connection_kind:'direct'},
  comparison:'different',pi_candidates:[],component_candidates:[],
  wire_colors:{component:{name:'purple',visibility:'clear'},board:{name:'blue',visibility:'clear'}},
  diagnosis:{status:'uncertain',observed_component_pin:null,observed_board_pin:null,observed_physical_pin:null,
    board_connector_id:null,component_connector_id:null,evidence:'Visible endpoint colours differ.',retake_roles:[]},
  next_step:'沿 ECHO 線核對 Pi Pin 12。',...extra});
const trig=()=>echo({wire_id:'wire-trig',expected:{component_pin:'TRIG',board_pin:'GPIO17',physical_pin:11,bcm:17},
  wire_colors:{component:{name:'green',visibility:'clear'},board:{name:'purple',visibility:'clear'}}});
const summary=(rows=[echo()])=>({schema_version:2,headline:'零件端接頭已辨識，插接狀態尚未確認。',
  next_step:'沿 ECHO 線核對是否接到 Pi Pin 12。',retake_role:null,counts:{suspected:0,uncertain:1,no_issue_seen:0},results:rows,evidence:'Saved observation.'});
const shared={react:React,'../lib/useMaker':{useMakerText:()=>tr},'../lib/wiringReview':reviewHelpers,
  '../lib/wiringExpectedLocation':helpers,'./WiringExpectedLocation':expectedLocationComponent('zh')};
const chatHelpers=flowModule('../src/lib/wiringChat.ts',{'./wiringReview':reviewHelpers});
const chat=flowModule('../src/components/WiringChatMessage.tsx',{...shared,'../lib/wiringChat':chatHelpers,
  '../lib/wiringPhotoStatus':flowModule('../src/lib/wiringPhotoStatus.ts',{'./wiringReview':reviewHelpers}),
  './AssistantAnalysisTime':{AssistantAnalysisTime:()=>null},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringChat.css':{}});
const card=flowModule('../src/components/WiringReviewCard.tsx',{...shared,
  './WiringPhotoSequence':{WiringPhotoSequence:photoSequence(React,'zh')},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringReview.css':{}});
function elements(tree,type){const found=[];const visit=node=>{if(!node||typeof node!=='object')return;if(Array.isArray(node)){node.forEach(visit);return;}if(node.type===type)found.push(node);visit(node.props?.children);};visit(tree);return found;}

test('saved physical pin and shared Pi guide place GPIO18 in outer row position six, not GPIO ordinal eighteen',()=>{
  const result=helpers.expectedWiringLocation(echo());
  assert.equal(result.physical,12);assert.equal(result.row,'outer');assert.equal(result.number,6);
  const inner=helpers.expectedWiringLocation(trig());assert.equal(inner.row,'inner');assert.equal(inner.number,6);
});

test('historical or invalid profile mapping never substitutes a new expected location',()=>{
  for(const expected of [{board_pin:'GPIO17',physical_pin:12},{board_pin:'GPIO18',physical_pin:18},
    {board_pin:'old-profile-name',physical_pin:12},{board_pin:'GPIO18',physical_pin:41},{board_pin:'GPIO18',physical_pin:null}]) {
    assert.equal(helpers.expectedWiringLocation(echo({expected})),null);
  }
  const saved=summary([echo({expected:{component_pin:'ECHO',board_pin:'old-profile-name',physical_pin:12}})]);
  assert.deepEqual(helpers.wiringVisualSummary(saved,tr,'wire-echo'),{headline:saved.headline,next_step:saved.next_step,targets:[]});
});

test('wire labels use only observed component colour, never planned or Pi-end colour',()=>{
  assert.equal(helpers.wiringTargetLabel(echo(),tr),'ECHO（紫色線）');
  assert.equal(helpers.wiringTargetLabel(trig(),tr),'TRIG（綠色線）');
  for(const component of [undefined,{name:'unknown',visibility:'clear'},{name:'red',visibility:'not_visible'}]) {
    assert.equal(helpers.wiringTargetLabel(echo({wire_colors:{component,board:{name:'red',visibility:'clear'}}}),tr),'ECHO');
  }
});

test('old colour-mismatch summary becomes a brief suspected problem but insufficient views stay uncertain',()=>{
  const saved=summary(),before=structuredClone(saved),visual=helpers.wiringVisualSummary(saved,tr,'wire-echo');
  assert.equal(visual.headline,'ECHO（紫色線）疑似接錯，請先核對。');
  assert.match(visual.next_step,/零件端是紫色線，Pi 應接位置看起來是藍色線/);assert.match(visual.next_step,/查看應接位置/);
  assert.doesNotMatch(visual.next_step,/Pin 12|GPIO18/);assert.deepEqual(saved,before);
  const unknown={...summary([echo({comparison:'unknown'})]),headline:'目前無法確認。',next_step:'補拍插頭底部。'};
  const untouched=helpers.wiringVisualSummary(unknown,tr,'wire-echo');assert.equal(untouched.headline,unknown.headline);assert.equal(untouched.next_step,unknown.next_step);
  const handled=echo({wire_id:'handled',diagnosis:{status:'suspected',kind:'reciprocal_endpoint_swap',partner_component_pin:'GND'}});
  const current={...unknown,results:[handled,unknown.results[0]],observation:'可見裸露針尖',retake_role:'component_header'};
  const protectedView=helpers.wiringVisualSummary(current,tr,'wire-echo');
  assert.equal(protectedView.headline,current.headline);assert.equal(protectedView.next_step,current.next_step);
  assert.deepEqual(protectedView.targets,[]);
  assert.deepEqual(helpers.wiringVisualSummary(current,tr).targets,[]);
  const hidden={...unknown,results:[echo({comparison:'unknown',diagnosis:{status:'uncertain',module_identity_known:true,module_attachment_uncertain:true}})]};
  const friendly=helpers.wiringVisualSummary(hidden,tr,'wire-echo');
  assert.match(friendly.headline,/尚未找出明確的接線疑點/);assert.match(friendly.next_step,/逐線核對/);assert.doesNotMatch(friendly.headline,/疑似接錯/);
  assert.deepEqual(friendly.targets,[]);
  const bothRows=structuredClone(hidden);
  bothRows.results[0].diagnosis.retake_roles=['pi_side_a','pi_side_b'];
  bothRows.next_step='請補拍 Pi 內排與外排。';
  assert.equal(helpers.wiringVisualSummary(bothRows,tr,'wire-echo').next_step,bothRows.next_step);
});

test('compact diagram identifies orientation and target while physical and GPIO references stay inside details',()=>{
  const html=renderToStaticMarkup(React.createElement(expectedLocationComponent('zh').WiringExpectedLocation,{rows:[echo()]}));
  const primary=html.replace(/<details><summary>腳號與 GPIO[\s\S]*?<\/details>/g,'');
  assert.match(html,/<details class="wiring-expected-map"><summary>查看應接位置<\/summary>/);
  assert.doesNotMatch(html,/<details[^>]*open/);
  assert.match(primary,/設計應接位置/);assert.match(primary,/ECHO（紫色線）/);assert.match(primary,/外排・靠板邊緣/);assert.match(primary,/第 6 個位置/);
  assert.match(primary,/從這端開始/);assert.match(primary,/USB/);assert.match(primary,/網路孔/);
  assert.equal((html.match(/data-row-position=/g)||[]).length,40);
  assert.equal((html.match(/data-designed-target="true"/g)||[]).length,1);
  assert.match(primary,/data-row="outer" data-row-position="6" data-designed-target="true"/);
  assert.doesNotMatch(primary,/Pin 12|GPIO18|紅色線|<img|已確認|通過/);assert.match(html,/<details>.*Pi Pin 12.*GPIO18/);
});

test('switching a design target changes only the local illustration and matches the reciprocal partner',()=>{
  let state=null;
  const hooks={...React,useState:initial=>[state??initial,next=>{state=next;} ]};
  const Component=expectedLocationComponent('zh',hooks).WiringExpectedLocation;
  const rows=[echo(),trig()],before=structuredClone(rows);
  let tree=Component({rows});assert.equal(tree.props['data-wire-id'],'wire-echo');
  elements(tree,'button')[1].props.onClick();tree=Component({rows});assert.equal(tree.props['data-wire-id'],'wire-trig');
  assert.deepEqual(rows,before);
  const pair=echo({diagnosis:{status:'suspected',kind:'reciprocal_endpoint_swap',partner_wire_id:'wire-trig',partner_component_pin:'TRIG'}});
  const unrelated=echo({wire_id:'unrelated',diagnosis:{status:'suspected'}});
  assert.deepEqual(helpers.wiringLocationTargets([pair,unrelated,trig()],'wire-echo').map(row=>row.wire_id),['wire-echo','wire-trig']);
});

test('shared chat summary renders the saved expected map without changing the historical reply',()=>{
  const saved=summary(),before=structuredClone(saved);
  const html=renderToStaticMarkup(React.createElement(chat.WiringReviewOverview,{summary:saved,focusWireId:'wire-echo'}));
  assert.match(html,/<p class="wiring-chat-headline">ECHO（紫色線）疑似接錯，請先核對。<\/p>/);
  assert.match(html,/wiring-expected-location/);assert.match(html,/data-row="outer" data-row-position="6" data-designed-target="true"/);
  assert.match(html,/線色不同・待核對/);assert.deepEqual(saved,before);
});

test('legacy review keeps human confirmation and existing diagram navigation while using the compact target',()=>{
  const result=echo(),review={id:'review',revision:1,round:1,component_id:'hc-sr04',status:'ready',
    slots:{pi_side_a:null,pi_side_b:null,component_header:null},results:[result],observations:[],reviews:{},missing_roles:[],no_progress_count:0};
  const before=structuredClone(review),calls=[];
  const props={review,components:[{id:'hc-sr04',label:'HC-SR04+'}],onInspectWire:wire=>calls.push(wire),
    onAction(){throw Error('No hardware action');},onReview(){throw Error('No automatic confirmation');}};
  const html=renderToStaticMarkup(React.createElement(card.WiringReviewCard,props));
  assert.match(html,/wiring-expected-location/);assert.match(html,/看應接腳位/);assert.match(html,/尚未確認接對/);
  assert.doesNotMatch(html,/aria-pressed="true"|你已親自確認接對|功能通過/);
  assert.deepEqual(review,before);assert.deepEqual(calls,[]);
});
