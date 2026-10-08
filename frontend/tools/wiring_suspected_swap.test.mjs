import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {flowModule, reviewHelpers, framingGuide, photoSequence, expectedLocationHelpers, expectedLocationComponent} from './wiring_photo_flow_fixture.mjs';

// Synthetic evidence only: these tests never capture, call a model or operate a Pi.
const tr=(zh)=>zh;
const chatHelpers=flowModule('../src/lib/wiringChat.ts',{'./wiringReview':reviewHelpers});
const statusHelpers=flowModule('../src/lib/wiringPhotoStatus.ts',{'./wiringReview':reviewHelpers});
const shared={react:React,'../lib/useMaker':{useMakerText:()=>tr},'../lib/wiringReview':reviewHelpers,
  '../lib/wiringExpectedLocation':expectedLocationHelpers,'./WiringExpectedLocation':expectedLocationComponent('zh')};
const chat=flowModule('../src/components/WiringChatMessage.tsx',{...shared,
  '../lib/wiringChat':chatHelpers,'../lib/wiringPhotoStatus':statusHelpers,
  './AssistantAnalysisTime':{AssistantAnalysisTime:()=>null},'./AssistantJobProgress':{AssistantJobProgress:()=>null},
  './WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringChat.css':{}});
const card=flowModule('../src/components/WiringReviewCard.tsx',{...shared,
  './WiringPhotoSequence':{WiringPhotoSequence:photoSequence(React,'zh')},
  './WiringFramingGuide':{WiringFramingGuide:framingGuide('zh')},'./wiringReview.css':{}});
const endpoint=(extra={})=>({id:'pi-a',capture_id:'capture-a',role:'pi_side_a',physical_pin:15,pin_id:'15',
  pin_label:null,color:'green',evidence:'Visible plug base.',contact:'covers_pin',box:[.1,.2,.3,.4],...extra});
const row=(extra={})=>({wire_id:'wire-data-a',component_id:'custom-module',
  expected:{component_pin:'DATA_A',board_pin:'13',physical_pin:13,bcm:27,connection_kind:'direct'},
  pi_candidates:[endpoint()],component_candidates:[],comparison:'different',same_wire:'uncertain',
  next_step:'先沿線核對 DATA_A 應接 Pin 13、DATA_B 應接 Pin 15。',
  diagnosis:{status:'suspected',kind:'reciprocal_endpoint_swap',partner_wire_id:'wire-data-b',partner_component_pin:'DATA_B',
    candidate_board_pin:'15',candidate_physical_pin:15,observed_board_pin:null,observed_physical_pin:null,
    observed_component_pin:null,board_connector_id:'pi-a',component_connector_id:'pi-a',retake_roles:[],
    evidence:'兩端線色呈現互換線索，請沿線核對。'},...extra});
const review=(result)=>({id:'review',revision:4,round:1,component_id:'custom-module',status:'ready',
  slots:{pi_side_a:{role:'pi_side_a',capture_id:'capture-a',image_url:'/synthetic-photo.jpg',size:[1000,800],
    sha256:'source-a',crop:null,crop_source:'none',available:true},pi_side_b:null,component_header:null},
  observations:result.pi_candidates,results:[result],reviews:{},missing_roles:[],no_progress_count:0});
const message=(result)=>({id:'reply',role:'assistant',text:'原始分析紀錄',source:'legacy-debug',created_at:1,stage:'guide',
  capability:'debug',epoch:0,round:1,wiring_flow:{flow_id:'flow',review_id:'review',revision:4,round:1,component_id:'custom-module',
    kind:'wire_review',wire_id:result.wire_id,current:true,can_act:true,actions:['review'],result,
    summary:{schema_version:3,headline:'DATA_A 與 DATA_B 疑似接反。',next_step:result.next_step,retake_role:null,
      counts:{suspected:1,uncertain:0,no_issue_seen:0},results:[result],evidence:result.diagnosis?.evidence??''}}});
const renderChat=(result)=>renderToStaticMarkup(React.createElement(chat.WiringChatMessage,{message:message(result),review:review(result),
  onAction(){throw Error('Rendering must never change wiring or operate hardware.');}}));

test('generic reciprocal swap text names the server pair and both candidate and expected Pi positions',()=>{
  const result=row(),before=structuredClone(result);
  assert.equal(reviewHelpers.wiringSuspectedConnectionText(result,tr),
    'DATA_A 與 DATA_B 疑似接反；DATA_A 線色對應 Pi Pin 15（應接 Pi Pin 13），需沿線確認。');
  assert.equal(result.same_wire,'uncertain');assert.deepEqual(result,before);
});

test('colour differences alone never create a swap and old explicit observations remain readable',()=>{
  assert.equal(reviewHelpers.wiringSuspectedConnectionText(row({diagnosis:undefined}),tr),null);
  assert.equal(reviewHelpers.wiringSuspectedConnectionText(row({diagnosis:{status:'uncertain'}}),tr),null);
  const explicit=row({diagnosis:{status:'suspected',observed_component_pin:'DATA_A',observed_physical_pin:11}});
  assert.equal(reviewHelpers.wiringSuspectedConnectionText(explicit,tr),'照片疑似：DATA_A → Pi Pin 11');
});

test('chat keeps one short swap summary and next step without fake observed pins or wrong-pin markers',()=>{
  const result=row(),before=structuredClone(result),html=renderChat(result);
  assert.match(html,/<p class="wiring-chat-headline">DATA_A 與 DATA_B 疑似接反。<\/p>/);
  assert.match(html,/<p class="wiring-chat-instruction">先沿線核對 DATA_A 應接 Pin 13、DATA_B 應接 Pin 15。<\/p>/);
  assert.match(html,/線色對應 Pi Pin 15（應接 Pi Pin 13）/);
  assert.doesNotMatch(html,/null|undefined|查看照片位置|照片疑似：.*→ Pi Pin|功能通過/);
  assert.deepEqual(result,before);
});

test('legacy review renders the same suspected pair without confirming wiring or enabling a retest',()=>{
  const result=row(),state=review(result),before=structuredClone(state);
  const html=renderToStaticMarkup(React.createElement(card.WiringReviewCard,{review:state,
    components:[{id:'custom-module',label:'Custom module'}],onAction(){throw Error('No action');},
    onReview(){throw Error('No confirmation');},onRetest(){throw Error('No hardware');}}));
  assert.match(html,/DATA_A 與 DATA_B 疑似接反/);assert.match(html,/尚未確認接對/);
  assert.doesNotMatch(html,/null|undefined|查看照片位置|aria-pressed="true"|重新測試這個零件/);
  assert.deepEqual(state,before);
});

test('Pi row-count evidence stays in details and readable module labels survive uncertain contact',()=>{
  const pi=endpoint({pin_seat:{image_id:'pi_side_a',row:'inner',column:8,base_box:[.1,.2,.3,.4],
    orientation_anchor:'照片中看見 Pin 1 端板角',count_evidence:'由端點逐位數到第八位',capture_id:'capture-a',source_sha256:'source-a',source_size:[1000,800]}});
  const module=endpoint({id:'module-a',role:'component_header',capture_id:'module-capture',physical_pin:null,pin_id:null,
    module_pin_id:'DATA_A',module_pin_evidence:'標字 DATA_A 可讀',contact:'uncertain'});
  const html=renderChat(row({pi_candidates:[pi],component_candidates:[module]}));
  assert.match(html,/照片定位：內排第 8 位（從 Pin 1／2 端數）/);assert.match(html,/由端點逐位數到第八位/);
  assert.match(html,/DATA_A.*綠色/);assert.match(html,/標字位置已辨識；插接待確認/);
  assert.ok(html.indexOf('照片定位：')>html.indexOf('查看腳位與線色依據'));
});

test('requested row, wrong source or invalid position cannot create a photo-seat description',()=>{
  const base=endpoint({pin_seat:{image_id:'pi_side_a',row:'outer',column:7,capture_id:'capture-a'}});
  assert.match(reviewHelpers.wiringPinSeatText(base,tr),/外排第 7 位/);
  assert.equal(reviewHelpers.wiringPinSeatText(endpoint({requested_row:'inner'}),tr),null);
  for (const patch of [{image_id:'pi_side_b'},{capture_id:'old-photo'},{column:0},{column:21},{column:1.5},{row:'uncertain'}]) {
    assert.equal(reviewHelpers.wiringPinSeatText({...base,pin_seat:{...base.pin_seat,...patch}},tr),null);
  }
  assert.equal(reviewHelpers.wiringPinSeatText({...base,role:'component_header'},tr),null);
});

test('a source-bound row-only seat stays useful without inventing a numbered position',()=>{
  const base=endpoint({pin_id:null,physical_pin:null,pin_seat:{image_id:'pi_side_a',row:'inner',column:null,
    base_box:[.1,.2,.3,.4],orientation_anchor:'板中心在下方，可辨內排',count_evidence:'接頭遮住位置邊界',
    capture_id:'capture-a',source_sha256:'source-a',source_size:[1000,800]}});
  const before=structuredClone(base);
  assert.equal(reviewHelpers.wiringPinSeatText(base,tr),'照片定位：內排，第幾個位置尚未確認');
  assert.equal(reviewHelpers.wiringPinSeatText({...base,pin_seat:{...base.pin_seat,row:'outer'}},tr),'照片定位：外排，第幾個位置尚未確認');
  for(const patch of [{capture_id:'old-photo'},{image_id:'pi_side_b'},{column:undefined},{column:0}]) {
    assert.equal(reviewHelpers.wiringPinSeatText({...base,pin_seat:{...base.pin_seat,...patch}},tr),null);
  }
  const html=renderChat(row({pi_candidates:[base]}));
  assert.match(html,/照片定位：內排，第幾個位置尚未確認/);
  assert.doesNotMatch(html,/內排第 (?:0|1|null|undefined) 位/);
  const designed={...row(),expected:{board_pin:'GPIO18',physical_pin:12,bcm:18,component_pin:'ECHO'},pi_candidates:[base]};
  const expected=expectedLocationHelpers.expectedWiringLocation(designed);
  assert.equal(expected.row,'outer');assert.equal(expected.number,6);
  assert.deepEqual(base,before);assert.equal(base.pin_id,null);assert.equal(base.physical_pin,null);
});
