import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers, expectedLocationHelpers as helpers, expectedLocationComponent, framingGuide, photoSequence} from './wiring_photo_flow_fixture.mjs';

const tr=zh=>zh;
// Compact fixtures mirror the live review's ambiguous GND and source-bound ECHO row clue.
// These verify rendering, not model accuracy or physical wiring.
const gnd=()=>({wire_id:'hc-sr04:gnd',component_id:'hc-sr04',
  expected:{board_pin:'GND_P6',physical_pin:6,bcm:null,component_pin:'GND'},
  comparison:'ambiguous',same_wire:'uncertain',pi_candidates:[],component_candidates:[],
  wire_colors:{component:{name:'blue',visibility:'clear'},board:{name:'blue',visibility:'clear'}},
  next_step:'Trace the blue GND wire to its intended position.',
  diagnosis:{status:'uncertain',observed_board_pin:null,observed_physical_pin:null,observed_component_pin:null,
    board_connector_id:null,component_connector_id:null,module_identity_known:true,module_attachment_uncertain:true,
    module_attachment_confirmed:false,evidence:'GND label and housing are identified; strand identity is uncertain.',retake_roles:[]}});
const echo=()=>({...gnd(),wire_id:'hc-sr04:echo',expected:{board_pin:'GPIO18',physical_pin:12,bcm:18,component_pin:'ECHO'},
  wire_colors:{component:{name:'purple',visibility:'clear'},board:{name:'unknown',visibility:'not_visible'}},
  next_step:'對照接線圖，沿紫色 ECHO 線核對應接位置。',
  diagnosis:{...gnd().diagnosis,kind:'row_position_check',expected_row:'outer',candidate_row:'inner',
    row_candidate_ids:['pi_side_a:a3','pi_side_b:b6'],
    evidence:'兩張 Pi 照片中的紫色接頭都像在內排；尚未確認與 ECHO 是同一條線。'}});
const summary=(row,rows=[row])=>({schema_version:2,headline:row.diagnosis.kind==='row_position_check'
  ? '先核對紫色 ECHO 線的位置。' : 'Module labels and housing positions are identified; check both endpoints.',
  next_step:row.next_step,retake_role:null,observation:'',counts:{suspected:0,uncertain:rows.length,no_issue_seen:0},results:rows,evidence:row.diagnosis.evidence});
const review=rows=>({id:'r',revision:1,round:1,component_id:'hc-sr04',status:'ready',
  slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:rows,reviews:{},missing_roles:[],no_progress_count:0});
const shared={react:React,'../lib/useMaker':{useMakerText:()=>tr},'../lib/wiringReview':reviewHelpers,
  '../lib/wiringExpectedLocation':helpers,'./WiringExpectedLocation':expectedLocationComponent('zh')};
const chat=flowModule('../src/components/WiringChatMessage.tsx',{...shared,
  '../lib/wiringChat':flowModule('../src/lib/wiringChat.ts',{'./wiringReview':reviewHelpers}),
  '../lib/wiringPhotoStatus':flowModule('../src/lib/wiringPhotoStatus.ts',{'./wiringReview':reviewHelpers}),
  './AssistantAnalysisTime':{AssistantAnalysisTime:()=>null},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringChat.css':{}});
const card=flowModule('../src/components/WiringReviewCard.tsx',{...shared,
  './WiringPhotoSequence':{WiringPhotoSequence:photoSequence(React,'zh')},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringReview.css':{}});
const renderOverview=(saved,focus)=>renderToStaticMarkup(React.createElement(chat.WiringReviewOverview,{summary:saved,focusWireId:focus}));

test('row clue ranks above generic uncertainty without promoting it to suspected or deriving a swap',()=>{
  const row=echo(),ordinary=gnd(),suspected={...gnd(),wire_id:'fault',diagnosis:{...gnd().diagnosis,status:'suspected'}};
  const rows=[ordinary,row,suspected],before=structuredClone(rows);
  assert.deepEqual(reviewHelpers.prioritiseWiringResults(rows).map(r=>r.wire_id),['fault','hc-sr04:echo','hc-sr04:gnd']);
  assert.equal(reviewHelpers.wiringFindingLabel(row,tr),'優先核對');assert.equal(reviewHelpers.wiringFindingStatus(row),'uncertain');
  assert.equal(reviewHelpers.wiringSuspectedConnectionText(row,tr),null);assert.equal(reviewHelpers.wiringHasConnectionClue(ordinary),false);
  assert.deepEqual(rows,before);
});

test('overview preserves the row-check sentence and evidence, with only a collapsed intended-location map',()=>{
  const row=echo(),saved=summary(row,[gnd(),row]),before=structuredClone(saved),html=renderOverview(saved,row.wire_id);
  assert.match(html,/<p class="wiring-chat-headline">先核對紫色 ECHO 線的位置。<\/p>/);
  assert.match(html,/<p class="wiring-chat-observation">兩張 Pi 照片中的紫色接頭都像在內排；尚未確認與 ECHO 是同一條線。<\/p>/);
  assert.match(html,/優先核對/);assert.match(html,/<details class="wiring-expected-map"><summary>查看應接位置/);
  assert.match(html,/data-row="outer" data-row-position="6" data-designed-target="true"/);
  assert.doesNotMatch(html,/疑似接錯|疑似接反|Pin 9|<details[^>]*open|data-wire-id="hc-sr04:gnd"/);
  assert.deepEqual(saved,before);
});

test('a historical all-uncertain GND cursor does not become the main fault or intended-position target',()=>{
  const row=gnd(),saved=summary(row),before=structuredClone(saved),visual=helpers.wiringVisualSummary(saved,tr,row.wire_id);
  assert.equal(visual.headline,'照片尚未找出明確的接線疑點。');assert.deepEqual(visual.targets,[]);
  assert.doesNotMatch(visual.headline+visual.next_step,/GND|接錯|接對|通過|Pin 6/);
  const html=renderOverview(saved,row.wire_id);assert.doesNotMatch(html,/wiring-expected-map/);
  assert.match(html,/查看分析詳情/);assert.deepEqual(saved,before);
});

test('current uncertain review never borrows an earlier handled clue or a different wire for its diagram',()=>{
  const row=gnd(),old=echo(),saved=summary(row,[old,row]),before=structuredClone(saved);
  const current=helpers.wiringVisualSummary(saved,tr,row.wire_id);
  assert.deepEqual(current.targets,[]);assert.doesNotMatch(current.headline+current.next_step,/ECHO|紫色/);
  assert.deepEqual(helpers.wiringVisualSummary(saved,tr).targets,[]);assert.deepEqual(saved,before);
});

test('retake and bare-terminal observations keep their current instruction without a default GND highlight',()=>{
  const row=gnd(),saved={...summary(row),headline:'可見裸露針尖，仍需核對標字。',next_step:'補拍零件接頭標字。',
    observation:'接頭旁可見完整針尖。',retake_role:'component_header'};
  const visual=helpers.wiringVisualSummary(saved,tr,row.wire_id);
  assert.equal(visual.headline,saved.headline);assert.equal(visual.next_step,saved.next_step);assert.deepEqual(visual.targets,[]);
  const missing={...echo(),comparison:'different',expected:{board_pin:'GPIO25',physical_pin:22,bcm:25,component_pin:'RES'},
    diagnosis:{...echo().diagnosis,kind:'unconnected_terminal',status:'suspected',evidence:'RES 針尖裸露。'}};
  const result=helpers.wiringVisualSummary(summary(missing),tr,missing.wire_id);
  assert.equal(result.headline,'RES 這個腳位疑似漏接。');assert.doesNotMatch(result.headline,/優先核對|疑似接錯/);
});

test('legacy card selects the real row clue first while an all-uncertain review remains optional manual checking',()=>{
  const make=rows=>renderToStaticMarkup(React.createElement(card.WiringReviewCard,{review:review(rows),
    components:[{id:'hc-sr04',label:'HC-SR04+'}],onAction(){throw Error('No automatic action');},onReview(){throw Error('No automatic confirmation');}}));
  const row=echo(),before=structuredClone(row),html=make([gnd(),row]);
  assert.match(html,/<header><h4>ECHO<\/h4>/);assert.match(html,/優先核對/);assert.match(html,/兩張 Pi 照片中的紫色接頭/);
  assert.doesNotMatch(html,/疑似接錯|疑似接反|查看照片位置|aria-pressed="true"/);
  const ordinary=make([gnd()]);assert.match(ordinary,/逐線核對（選用）/);assert.match(ordinary,/尚未確認接對/);
  assert.doesNotMatch(ordinary,/wiring-expected-map|先看這條線|先核對這條線/);assert.deepEqual(row,before);
});
