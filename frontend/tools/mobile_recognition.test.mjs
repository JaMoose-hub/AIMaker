import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
const read=file=>readFileSync(new URL(file,import.meta.url),'utf8');
function load(file,modules={}) {
  const exports={};const js=ts.transpileModule(read(file),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('require','exports',js)(name=>modules[name],exports);return exports;
}
const r=load('../src/lib/mobileRecognition.ts');
const geometry=load('../src/lib/geometry.ts',{react:React});
function session() {
  const pose={frame_id:10,runtime_revision:2,video_size:[1920,1080],tracking:'locked',pins:[{id:'P1',x:200,y:180,c:.9,v:true}],outline:[[100,100],[600,100],[600,800],[100,800]]};
  return {session_id:'phone',context_id:'ctx',conversation_id:'project',stream:{active:true,publisher_connected:true,generation:2,preview_seq:10,can_capture:false,
    recognition:{source:'phone',session_id:'phone',generation:2,context_id:'ctx',frame_seq:10,video_size:[1920,1080],valid_for_ms:1500,coordinates_are_hints_only:true,
      detection:{...pose,board_id:'raspberry-pi-5'},components:[{...pose,component_id:'hc-sr04'}]}}};
}
const lease=s=>r.mobileRecognitionLease(s,100,{key:'',deadline:0});
test('phone live results render even while capture is finding, with the shared unmirrored letterbox',()=>{
  const s=session();assert.equal(r.phoneRecognitionForDisplay(s,[1920,1080],101,lease(s)),s.stream.recognition);
  const box=geometry.computeLetterbox([1920,1080],1000,400);
  assert.equal(box.mirrorX,false);assert.equal(box.mirrorY,false);
  assert.deepEqual(geometry.toDisplay(box,960,540),{x:500,y:200});
});
test('decoded portrait, lower resolution and zero metadata cannot receive landscape coordinates',()=>{
  const s=session();for(const size of [[1080,1920],[1280,720],[0,0],[NaN,1080]])assert.equal(r.phoneRecognitionForDisplay(s,size,101,lease(s)),null);
});
test('foreign source, phone, generation, workspace and sample do not earn a display lease',()=>{
  for(const changes of [{source:'webcam'},{session_id:'other'},{generation:3},{context_id:'old'},{frame_seq:9},{valid_for_ms:NaN}]){
    const s=session();Object.assign(s.stream.recognition,changes);assert.equal(lease(s).deadline,0);
  }
});
test('live results follow current desktop steps without adopting the phone photo/chat context',()=>{
  const s=session();s.available_context={context_id:'new-step',conversation_id:'project'};
  assert.equal(lease(s).deadline,0);
  s.stream.recognition.context_id='new-step';assert.ok(r.phoneRecognitionForDisplay(s,[1920,1080],101,lease(s)));
  assert.equal(s.context_id,'ctx');s.available_context.conversation_id='other-project';assert.equal(lease(s).deadline,0);
});
test('repeated telemetry cannot renew an old sample, including after leaving and reopening phone preview',()=>{
  const first=r.receivePhoneRecognition(null,session(),100);
  const repeated=r.receivePhoneRecognition(first,session(),1000);
  assert.equal(repeated.stream.recognition.display_deadline,1600);
  const reopened=r.mobileRecognitionLease(repeated,1700,{key:'',deadline:0});
  assert.equal(r.phoneRecognitionForDisplay(repeated,[1920,1080],1700,reopened),null);
});
test('a newer sample renews its lease while out-of-order results never render',()=>{
  const s=session(),first=lease(s);s.stream.recognition.frame_seq=s.stream.preview_seq=11;
  const newer=r.mobileRecognitionLease(s,1300,first);assert.equal(newer.deadline,2800);
  s.stream.recognition.frame_seq=s.stream.preview_seq=10;
  const replay=r.mobileRecognitionLease(s,1400,newer);assert.equal(replay,newer);
  assert.equal(r.phoneRecognitionForDisplay(s,[1920,1080],1400,replay),null);
});
test('disconnect, publisher loss and local sample timeout remove the overlays',()=>{
  for(const changes of [{active:false},{publisher_connected:false}]) {const s=session();Object.assign(s.stream,changes);assert.equal(lease(s).deadline,0);}
  const s=session();assert.equal(r.phoneRecognitionForDisplay(s,[1920,1080],1600,lease(s)),null);
});
test('board and every component must have the same phone sample, generation and image dimensions',()=>{
  for(const change of [p=>p.components[0].frame_id--,p=>p.components[0].runtime_revision++,p=>p.components[0].video_size=[1080,1920],
    p=>p.detection.frame_id--,p=>p.detection.pins[0].x=NaN,p=>p.detection.outline[0][0]=Infinity,
    p=>p.detection.pins[0]=null,p=>p.detection.outline[0]=null]) {
    const s=session();change(s.stream.recognition);assert.equal(r.phoneRecognitionForDisplay(s,[1920,1080],101,lease(s)),null);
  }
});
test('phone overlays reuse existing pin and wiring renderers, not webcam detection hooks or display offsets',()=>{
  const source=read('../src/components/MobileRecognitionOverlay.tsx');
  for(const component of ['PinOverlay','ComponentPinOverlay','GuideConnectionOverlay','ObjectRecognitionOverlay'])assert.ok(source.includes(`<${component}`));
  assert.match(source,/localGuidanceOnly/);assert.match(source,/interactive=\{false\}/);
  assert.doesNotMatch(source,/useDetection|useComponentPoses|useTrackingFrame|mirrorX|manualPinOffset|openMobileViewer/);
  assert.match(read('../src/App.tsx'),/preview: null, showing: phoneMainActive,[\s\S]*?pinsById, guideTarget/);
  const companion=read('../src/components/MobileCompanion.tsx');
  assert.match(companion,/\[session\.session_id, session\.stream\.generation, active, attempt\]/,'new detections do not renegotiate RTC');
});
