import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {transpileModule, ModuleKind, ScriptTarget} from 'typescript';
import {createElement} from 'react';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';
const source = readFileSync(new URL('../src/lib/cameraTools.ts', import.meta.url), 'utf8');
const exports = {};
new Function('exports', transpileModule(source, {compilerOptions:{module:ModuleKind.CommonJS,target:ScriptTarget.ES2022}}).outputText)(exports);
const place = exports.cameraToolsPlacement;
for (const [label,viewport,anchor] of [
  ['desktop',{width:1651,height:871},{top:156,bottom:186,right:1080}],
  ['phone',{width:390,height:844},{top:180,bottom:224,right:378}],
  ['near viewport bottom',{width:1365,height:500},{top:410,bottom:450,right:1340}],
  ['scrolled above viewport',{width:390,height:844},{top:-100,bottom:-60,right:378}],
  ['scrolled below viewport',{width:390,height:844},{top:1000,bottom:1044,right:378}],
]) test(`camera tools stay within the ${label}`,()=>{
  const result=place(anchor,viewport);
  assert(result.left>=12);
  assert(result.left+result.width<=viewport.width-12);
  assert(result.top>=12);
  assert(result.top+result.maxHeight<=viewport.height-12);
  assert(result.maxHeight>0);
  if(label==='near viewport bottom') assert(result.top+result.maxHeight<anchor.top);
});

test('real video controls can be grouped into camera tools without duplicating the toolbar actions',async()=>{
  let received;
  const {html}=await renderWiringVideo({viewControl:controls=>{
    received=controls;
    return createElement('section',{'data-camera-tools-slot':true},controls);
  }});
  assert(received);
  const slot=html.match(/<section data-camera-tools-slot="true">([\s\S]*?)<\/section>/)?.[1];
  assert(slot);
  for(const label of ['即時追蹤','左右鏡像','上下鏡像','校正方向']) assert(slot.includes(label));
  assert.equal((html.match(/class="mirror-controls"/g)??[]).length,1);
  assert.equal((html.match(/class="pin-calibration-controls"/g)??[]).length,1);
});

test('alternate 2D view supplies no video actions, leaving the camera mounted and hidden',async()=>{
  let received='unset';
  const {html}=await renderWiringVideo({
    alternateView:createElement('section',null,'2D'),
    viewControl:controls=>{received=controls;return createElement('button',null,'Camera tools');},
  });
  assert.equal(received,null);
  assert(!html.includes('mirror-controls'));
  assert.match(html,/<div hidden="" class="video-shell/);
  assert.match(html,/class="video-img/);
});

test('calibrating the board keeps mirror and direction actions disabled after regrouping',async()=>{
  const {html}=await renderWiringVideo({calibrateOpen:true,viewControl:controls=>controls});
  for(const label of ['左右鏡像','上下鏡像','校正方向']){
    const button=html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g).find(markup=>markup.includes(label));
    assert(button);
    assert.match(button,/<button[^>]*disabled=""/);
  }
});

test('non-Pi controllers retain mirror and direction controls without showing unsupported realtime tracking',async()=>{
  const {html}=await renderWiringVideo({boardId:'arduino-uno',viewControl:controls=>controls});
  assert(!html.includes('realtime-toggle'));
  for(const label of ['左右鏡像','上下鏡像','校正方向']) assert(html.includes(label));
});
