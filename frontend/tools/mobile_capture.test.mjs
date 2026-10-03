import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {File} from 'node:buffer';
import ts from 'typescript';
const exports={};
const code=ts.transpileModule(readFileSync(new URL('../src/lib/mobileBrowserCapture.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
new Function('exports','File',code)(exports,File);
const {captureBrowserVideoFrame}=exports;

function scene(width=1920,height=1080){
  const calls=[], track={readyState:'live',stop(){throw Error('Capture must not stop camera');}};
  const stream={getVideoTracks:()=>[track]},canvas={width:0,height:0,getContext:()=>({drawImage(...args){calls.push(['draw',...args]);}}),
    toBlob(done,mime,quality){calls.push(['blob',canvas.width,canvas.height,mime,quality]);done(new Blob(['encoded frame'],{type:mime}));}};
  const video={srcObject:stream,videoWidth:width,videoHeight:height,readyState:4,paused:false,ownerDocument:{createElement(name){assert.equal(name,'canvas');return canvas;}}};
  return {calls,track,stream,canvas,video};
}

test('phone capture preserves full landscape and portrait dimensions without stopping camera',async()=>{
  for(const [width,height] of [[1920,1080],[1080,1920]]){
    const s=scene(width,height),file=await captureBrowserVideoFrame(s.video,s.stream);
    assert.deepEqual(s.calls,[['draw',s.video,0,0,width,height],['blob',width,height,'image/jpeg',.95]]);
    assert.equal(file.type,'image/jpeg');assert.ok(file.size>0);assert.equal(s.track.readyState,'live');
    assert.equal(s.canvas.width,0);assert.equal(s.canvas.height,0);
  }
});

test('not-ready, paused, detached and ended camera frames cannot become saved photos',async()=>{
  for(const mutate of [s=>s.video.videoWidth=0,s=>s.video.readyState=1,s=>s.video.paused=true,s=>s.video.srcObject={},s=>s.track.readyState='ended']){
    const s=scene();mutate(s);await assert.rejects(captureBrowserVideoFrame(s.video,s.stream));assert.equal(s.calls.length,0);
  }
});

test('failed blob encoding releases memory and keeps the stream available for retry',async()=>{
  const s=scene();s.canvas.toBlob=done=>done(null);
  await assert.rejects(captureBrowserVideoFrame(s.video,s.stream),/保存失敗/);
  assert.equal(s.track.readyState,'live');assert.equal(s.canvas.width,0);assert.equal(s.canvas.height,0);
});

test('a camera or orientation change during async encoding rejects the old capture',async()=>{
  for(const mutate of [s=>s.video.srcObject={},s=>s.track.readyState='ended',s=>s.video.videoWidth=1080]){
    const s=scene();let finish;s.canvas.toBlob=done=>{finish=done;};
    const pending=captureBrowserVideoFrame(s.video,s.stream);mutate(s);finish(new Blob(['frame'],{type:'image/jpeg'}));
    await assert.rejects(pending,error=>/來源或方向已改變/.test(error.message)&&/請重試拍照/.test(error.message)&&!error.message.includes('鎖定'));assert.equal(s.canvas.width,0);
  }
});
