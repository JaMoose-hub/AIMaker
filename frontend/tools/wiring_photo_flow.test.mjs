import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {photoFlow, photoSequence, reviewHelpers} from './wiring_photo_flow_fixture.mjs';
import {applyFixturePhotoAction} from './wiring_photo_mock.mjs';

const roles=reviewHelpers.wiringPhotoRoles;
const slot=role=>({role,capture_id:role,image_url:'/fixture/'+role,size:[1200,900],sha256:'hash-'+role,crop:null,crop_source:'none',available:true});
const review=(extra={})=>({id:'review',revision:1,round:1,component_id:'hc-sr04',status:'collecting',photo_flow_version:2,
  slots:Object.fromEntries(roles.map(role=>[role,null])),results:[],reviews:{},observations:[],no_progress_count:0,missing_roles:roles,...extra});
const photoAction=(value,role)=>reviewHelpers.boundWiringAction(value,{op:'accept_photo',role,capture_id:value.slots[role].capture_id,sha256:value.slots[role].sha256});
const accept=(value,role)=>applyFixturePhotoAction(value,photoAction(value,role),{now:()=>123});
const withPhotos=()=>review({slots:Object.fromEntries(roles.map(role=>[role,slot(role)]))});
const selectedPhotos=()=>roles.reduce((value,role)=>accept(value,role),withPhotos());
const receipts=value=>({key:photoFlow.wiringPhotoFlowKey(value),accepted:{}});
const baseProps=value=>({review:value,disabled:false,waiting:false,captureReady:true,humanOnly:false,failedCaptures:[],
  onCapture(){throw Error('Rendering cannot capture');},onAnalyse(){throw Error('Rendering cannot analyse');},onAccept(){throw Error('Rendering cannot accept a photo');},
  onPhoto(){throw Error('Rendering cannot open a crop');},onImageError(){},framing:role=>React.createElement('div',{'data-framing':role})});
const text=node=>typeof node==='string'||typeof node==='number'?String(node):Array.isArray(node)?node.map(text).join(''):node&&typeof node==='object'?text(node.props?.children):'';
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};

test('version 2 accepts only the server photo identity and cannot trust a legacy browser receipt',()=>{
  const value=withPhotos(),legacy=roles.reduce((receipt,role)=>photoFlow.acceptWiringPhoto(value,receipt,role),receipts(value));
  assert.deepEqual(photoFlow.acceptedWiringPhotos(value,legacy),[]);
  assert.equal(reviewHelpers.canAnalyseWiring(value),false);
  const selected=selectedPhotos();
  assert.deepEqual(photoFlow.acceptedWiringPhotos(selected),roles);
  assert.equal(reviewHelpers.canAnalyseWiring(selected),true);
  assert.deepEqual(selected.reviews,{},'choosing pictures cannot confirm a physical wire');
});

test('hash, capture, round, availability and stale evidence prevent a selected image from being reused',()=>{
  const value=accept(withPhotos(),'pi_side_a'), original=value.slots.pi_side_a;
  for(const changed of [{...value,round:2},{...value,status:'stale'},
    ...[{capture_id:'replacement'},{sha256:'changed-hash'},{available:false},
      {photo_acceptance:{...original.photo_acceptance,source:'ai'}},
      {photo_acceptance:{...original.photo_acceptance,round:2}},
      {photo_acceptance:{...original.photo_acceptance,capture_id:'old-capture'}},
      {photo_acceptance:{...original.photo_acceptance,sha256:'old-hash'}}]
      .map(extra=>({...value,slots:{...value.slots,pi_side_a:{...original,...extra}}}))]) {
    assert.deepEqual(photoFlow.acceptedWiringPhotos(changed),[]);
    assert.equal(reviewHelpers.canAnalyseWiring(changed),false);
  }
  assert.deepEqual(photoFlow.acceptedWiringPhotos(value,undefined,['pi_side_a']),[]);
});

test('retaking one photo preserves the other selections; changing wiring starts an unaccepted round',()=>{
  const value=selectedPhotos();
  const retaken=applyFixturePhotoAction(value,reviewHelpers.boundWiringAction(value,{op:'capture',role:'pi_side_b'}),{
    captureSlot:role=>({...slot(role),capture_id:'retake-b',sha256:'retake-hash'}),
  });
  assert.deepEqual(photoFlow.acceptedWiringPhotos(retaken),['pi_side_a','component_header']);
  assert.equal(reviewHelpers.canAnalyseWiring(retaken),false);
  const next=applyFixturePhotoAction(value,reviewHelpers.boundWiringAction(value,{op:'changed'}));
  assert.equal(next.round,value.round+1);assert.deepEqual(photoFlow.acceptedWiringPhotos(next),[]);
  assert.deepEqual(next.reviews,{});assert.equal(reviewHelpers.canAnalyseWiring(next),false);
});

test('the fixture rejects late or changed source acceptance without mutating its displayed round',()=>{
  const value=withPhotos(),before=structuredClone(value);
  const action=photoAction(value,'pi_side_a');
  for(const changed of [{...action,revision:0},{...action,review_id:'other-review'},
    {...action,capture_id:'previous-photo'},{...action,sha256:'previous-hash'},{...action,role:'component_header'}]) {
    assert.throws(()=>applyFixturePhotoAction(value,changed),/stale_wiring_review/);
    assert.deepEqual(value,before);
  }
});

test('legacy sessions can restore a matching receipt without promoting it to a version 2 selection',()=>{
  const value={...withPhotos(),photo_flow_version:undefined};
  const accepted=photoFlow.acceptWiringPhoto(value,receipts(value),'pi_side_a');
  const storage={getItem:()=>JSON.stringify(accepted)};
  assert.deepEqual(photoFlow.acceptedWiringPhotos(value,photoFlow.loadWiringPhotoReceipts(value,storage)),['pi_side_a']);
  assert.deepEqual(photoFlow.acceptedWiringPhotos({...value,photo_flow_version:2},photoFlow.loadWiringPhotoReceipts(value,storage)),[]);
  assert.deepEqual(photoFlow.loadWiringPhotoReceipts({...value,round:2},storage).accepted,{});
  for(const store of [{getItem:()=>'{broken'},{getItem(){throw Error('unavailable');}}])assert.deepEqual(photoFlow.loadWiringPhotoReceipts(value,store).accepted,{});
});

function harness(initial,{acceptResponse}={}) {
  const state=[],refs=[];let cursor=0,refCursor=0,props=baseProps(initial),tree;
  const hooks={...React,useState(value){const i=cursor++;if(!(i in state))state[i]=typeof value==='function'?value():value;
    return[state[i],next=>{state[i]=typeof next==='function'?next(state[i]):next;}];},
    useRef(value){const i=refCursor++;return refs[i]??={current:value};},useEffect(){}};
  const Sequence=photoSequence(hooks),calls=[];
  props={...props,onCapture:role=>calls.push(['capture',role]),onAnalyse:()=>calls.push(['analyse']),onImageError:id=>calls.push(['error',id]),
    onAccept:async(role,photo)=>{calls.push(['accept',role,photo.capture_id,photo.sha256]);
      if(acceptResponse)return acceptResponse(role,photo,props.review);
      const next=accept(props.review,role);props={...props,review:next};return next;}};
  const nodes=()=>{cursor=0;refCursor=0;tree=Sequence(props);const all=[];const visit=n=>{if(!n||typeof n!=='object')return;
    if(Array.isArray(n)){n.forEach(visit);return;}all.push(n);visit(n.props?.children);};visit(tree);return all;};
  return{calls,nodes,get review(){return props.review;},update(next){props={...props,...next};return nodes();},
    button(label){return nodes().find(n=>n.type==='button'&&text(n)===label);},
    load(){const image=nodes().find(n=>n.type==='img'&&n.props.className==='wr-step-photo');assert.ok(image,'current user image exists');image.props.onLoad();},
    use(){const button=nodes().find(n=>n.type==='button'&&/^Use photo/.test(text(n)));assert.ok(button,'explicit photo-use button exists');assert.equal(button.props.disabled,false);return button.props.onClick();}};
}

test('three explicit photo choices form one question at a time and never analyse or confirm a wire automatically',async()=>{
  const h=harness(withPhotos());
  for(const [index,role] of roles.entries()) {
    assert.equal(h.nodes().filter(n=>n.type==='img'&&n.props.className==='wr-step-photo').length,1);
    const button=h.nodes().find(n=>n.type==='button'&&/^Use photo/.test(text(n)));assert.equal(button.props.disabled,true,'image must load first');
    h.load();await h.use();h.nodes();
    assert.equal(h.calls.length,index+1);assert.equal(h.calls.at(-1)[0],'accept');assert.equal(h.calls.at(-1)[1],role);
    assert.equal(h.calls.some(call=>call[0]==='analyse'||call[0]==='capture'),false);
    assert.deepEqual(h.review.reviews,{});
  }
  const analyse=h.button('Analyse these three photos');assert.ok(analyse);assert.equal(analyse.props.disabled,false);analyse.props.onClick();
  assert.equal(h.calls.filter(call=>call[0]==='analyse').length,1);assert.deepEqual(h.review.reviews,{});
});

test('false, null and failed acceptance leave the current question unanswered and block analysis',async()=>{
  for(const result of [false,null,Error('accept failed')]) {
    const h=harness(withPhotos(),{acceptResponse:()=>result instanceof Error?Promise.reject(result):Promise.resolve(result)});
    h.load();await h.use();
    assert.deepEqual(photoFlow.acceptedWiringPhotos(h.review),[]);
    assert.ok(h.nodes().some(n=>n.type==='img'&&n.props.alt==='Pi first side'));
    assert.equal(h.button('Analyse these three photos'),undefined);
    assert.deepEqual(h.review.reviews,{});assert.equal(h.calls.length,1);
  }
});

test('a pending or late acceptance cannot choose a replacement image or the next wiring round',async()=>{
  const response=deferred(),initial=withPhotos(),h=harness(initial,{acceptResponse:()=>response.promise});
  h.load();const pending=h.use();assert.deepEqual(photoFlow.acceptedWiringPhotos(h.review),[]);
  const next={...initial,round:2,revision:2,slots:{...initial.slots,pi_side_a:{...slot('pi_side_a'),capture_id:'new-round-photo'}}};
  h.update({review:next});response.resolve(accept(initial,'pi_side_a'));await pending;
  assert.deepEqual(photoFlow.acceptedWiringPhotos(h.review),[]);assert.equal(h.button('Analyse these three photos'),undefined);
  assert.deepEqual(h.review.reviews,{});
});

test('remounting after navigation restores server-selected photos without model or hardware actions',()=>{
  const selected=accept(accept(withPhotos(),'pi_side_a'),'pi_side_b'),h=harness(selected);
  assert.ok(h.nodes().some(n=>n.type==='img'&&n.props.alt==='Module header'));
  assert.deepEqual(h.calls,[]);assert.deepEqual(selected.reviews,{});
});

test('a broken current image cannot be accepted or reach analysis; capture remains a separate explicit action',()=>{
  const h=harness(withPhotos());h.update({failedCaptures:['pi_side_a']});
  assert.equal(h.nodes().some(n=>n.type==='button'&&/^Use photo/.test(text(n))),false);
  assert.equal(h.button('Analyse these three photos'),undefined);assert.deepEqual(h.calls,[]);assert.deepEqual(h.review.reviews,{});
});

test('no camera, busy and human-only states retain instructions and disable capture',()=>{
  for(const extra of [{captureReady:false},{humanOnly:true},{disabled:true}]) {
    const html=renderToStaticMarkup(React.createElement(photoSequence(),{...baseProps(review()),...extra}));
    assert.match(html,/Pi first side/);assert.match(html,/disabled=""/);assert.doesNotMatch(html,/Use photo, next step/);
  }
});
