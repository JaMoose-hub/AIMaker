import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers, expectedLocationHelpers as helpers, expectedLocationComponent, framingGuide, photoSequence} from './wiring_photo_flow_fixture.mjs';

// Synthetic source-bound terminal evidence; no model, photographs or hardware work.
const tr=zh=>zh;
const missing=()=>({wire_id:'tft-res',component_id:'mrd-tf240-8p-cs',
  expected:{component_pin:'RES',board_pin:'GPIO25',physical_pin:22,bcm:25,connection_kind:'direct'},
  comparison:'unknown',same_wire:'uncertain',pi_candidates:[],component_candidates:[],
  next_step:'對照接線圖，核對零件上標示 RES 的應接位置；要調整接線請先斷電。',
  diagnosis:{kind:'unconnected_terminal',status:'suspected',observed_board_pin:null,observed_component_pin:null,
    observed_physical_pin:null,board_connector_id:null,component_connector_id:null,retake_roles:[],
    evidence:'RES 標字對應的金屬針露出，未看到杜邦接頭套住。',
    terminal_observation:{pin_id:'RES',state:'uncovered',evidence:'RES 金屬針露出',box:[.2,.3,.3,.6],
      capture_id:'module-photo',source_sha256:'module-sha',source_size:[1200,900],role:'component_header'}}});
const summary=row=>({schema_version:2,headline:'RES 這個腳位疑似漏接。',next_step:row.next_step,
  retake_role:null,observation:'可見金屬針尖',counts:{suspected:1,uncertain:0,no_issue_seen:0},results:[row],evidence:row.diagnosis.evidence});
const shared={react:React,'../lib/useMaker':{useMakerText:()=>tr},'../lib/wiringReview':reviewHelpers,
  '../lib/wiringExpectedLocation':helpers,'./WiringExpectedLocation':expectedLocationComponent('zh')};
const chat=flowModule('../src/components/WiringChatMessage.tsx',{...shared,
  '../lib/wiringChat':flowModule('../src/lib/wiringChat.ts',{'./wiringReview':reviewHelpers}),
  '../lib/wiringPhotoStatus':flowModule('../src/lib/wiringPhotoStatus.ts',{'./wiringReview':reviewHelpers}),
  './AssistantAnalysisTime':{AssistantAnalysisTime:()=>null},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringChat.css':{}});
const card=flowModule('../src/components/WiringReviewCard.tsx',{...shared,
  './WiringPhotoSequence':{WiringPhotoSequence:photoSequence(React,'zh')},'./WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringReview.css':{}});

test('only the server missing-terminal diagnosis gets the missing label; unknown and optional terminals do not',()=>{
  const row=missing(),before=structuredClone(row);
  assert.equal(reviewHelpers.wiringFindingLabel(row,tr),'疑似漏接');
  assert.match(reviewHelpers.wiringSuspectedConnectionText(row,tr),/RES 這個腳位疑似漏接。.*金屬針露出/);
  assert.equal(reviewHelpers.wiringFindingLabel({...row,diagnosis:{status:'uncertain'}},tr),'無法確認');
  assert.equal(reviewHelpers.wiringFindingLabel({...row,expected:{component_pin:'BLK'},diagnosis:{status:'no_issue_seen'}},tr),'未見明顯錯接');
  assert.deepEqual(row,before);
});

test('missing terminal wins over stale colour clues without inventing a wire or mutating saved evidence',()=>{
  const row={...missing(),comparison:'different',wire_colors:{component:{name:'purple',visibility:'clear'},board:{name:'yellow',visibility:'clear'}}};
  const saved=summary(row),before=structuredClone(saved),visual=helpers.wiringVisualSummary(saved,tr,row.wire_id);
  assert.equal(helpers.wiringTargetLabel(row,tr),'RES');assert.equal(visual.headline,'RES 這個腳位疑似漏接。');
  assert.match(visual.next_step,/RES 標字對應的金屬針露出/);assert.match(visual.next_step,/對照接線圖/);
  assert.doesNotMatch(visual.next_step,/紫色線|黃色線|沿同一條線|沿這條線|兩端線色不同/);
  assert.deepEqual(saved,before);
});

test('shared overview shows RES missing evidence and a collapsed intended-position diagram, not generic miswiring',()=>{
  const row=missing();
  const html=renderToStaticMarkup(React.createElement(chat.WiringReviewOverview,{summary:summary(row),focusWireId:row.wire_id}));
  assert.match(html,/<p class="wiring-chat-headline">RES 這個腳位疑似漏接。<\/p>/);
  assert.match(html,/<p class="wiring-chat-instruction">RES 標字對應的金屬針露出/);
  assert.match(html,/<span>疑似漏接<\/span>/);assert.match(html,/<details class="wiring-expected-map"><summary>查看應接位置/);
  assert.doesNotMatch(html,/疑似接錯|沿這條線|<details[^>]*open|null|undefined/);
});

test('legacy card preserves manual decisions while missing terminal advice never asks to trace a nonexistent wire',()=>{
  const row=missing(),review={id:'r',revision:1,round:1,component_id:'mrd-tf240-8p-cs',status:'ready',
    slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:[row],reviews:{},missing_roles:[],no_progress_count:0};
  const before=structuredClone(review);
  const html=renderToStaticMarkup(React.createElement(card.WiringReviewCard,{review,
    components:[{id:'mrd-tf240-8p-cs',label:'MRD-TFT240'}],onAction(){throw Error('No automatic work');},onReview(){throw Error('No automatic confirmation');}}));
  assert.match(html,/疑似漏接/);assert.match(html,/RES 標字對應的金屬針露出/);assert.match(html,/尚未確認接對/);
  assert.doesNotMatch(html,/沿這條線|兩端線色不同|查看照片位置|aria-pressed="true"|疑似接錯|Pin null/);
  assert.deepEqual(review,before);
});
