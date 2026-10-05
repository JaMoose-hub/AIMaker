import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';
const {outputText}=ts.transpileModule(readFileSync(new URL('../src/lib/componentOverlayScope.ts',import.meta.url),'utf8'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}});
const {componentOverlayScope,componentPosesForOverlay,projectGuideOverlayScope}=await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const hc='hc-sr04',tft='mrd-tf240-8p-cs';

test('project preparation shows all objects; started/reviewed modules stay focused until reset',()=>{
  const ids=[hc,tft], guide={phase:'prepare',componentIndex:0};
  assert.equal(projectGuideOverlayScope(ids,guide),null);
  assert.equal(projectGuideOverlayScope(ids,{...guide,phase:'active'}),hc);
  assert.equal(projectGuideOverlayScope(ids,{...guide,phase:'review'}),hc);
  assert.equal(projectGuideOverlayScope(ids,{...guide,componentIndex:1,phase:'active'}),tft);
  assert.equal(projectGuideOverlayScope(ids,{...guide,componentIndex:1,phase:'review'}),tft);
  assert.equal(projectGuideOverlayScope(ids,guide),null);
  assert.equal(projectGuideOverlayScope(ids,{phase:'active',componentIndex:9}),null);
});

test('selected component wins over a late guide effect; capture context wins while photographing',()=>{
  assert.equal(componentOverlayScope(hc,tft,null),hc);
  assert.equal(componentOverlayScope(null,hc,null),hc);
  assert.equal(componentOverlayScope(null,null,null),null);
  assert.equal(componentOverlayScope(tft,tft,{target:'hc_target'}),hc);
  assert.equal(componentOverlayScope(hc,hc,{target:'tft_screen'}),tft);
  assert.equal(componentOverlayScope(hc,hc,{target:'module_header',wiring_target:{component_id:tft}}),tft);
  assert.equal(componentOverlayScope(hc,null,{target:'overview'}),null);
  assert.equal(componentOverlayScope(hc,hc,null,true),null);
  assert.equal(componentOverlayScope(hc,hc,{target:'tft_screen'},true),tft);
});
test('filter does not mutate packets, coordinates, confidence, tracking or pin order',()=>{
  const poses=[{component_id:hc,tracking:'stale',pins:[{id:'TRIG',x:10,y:20,v:true}]},{component_id:tft,tracking:'locked',pins:[{id:'CS',x:10,y:20,v:true}]}];
  const before=structuredClone(poses);
  const filtered=componentPosesForOverlay(poses,hc);
  assert.deepEqual(filtered,[poses[0]]);assert.equal(filtered[0],poses[0]);assert.deepEqual(poses,before);
  assert.equal(componentPosesForOverlay(poses,null),poses);
});

for(const realtimeEnabled of [true,false]){
  test(`HC active step excludes overlapping TFT outlines and labels (realtime=${realtimeEnabled})`,async()=>{
    const view=await renderWiringVideo({realtimeEnabled,overlayComponentId:hc,extraComponents:[tft]});
    assert.equal((view.html.match(/data-component-id=/g)??[]).length,1);
    assert.match(view.html,/data-component-id="hc-sr04"/);
    assert.doesNotMatch(view.html,/data-component-id="mrd-tf240-8p-cs"|>CS<|>SCL</);
    assert.match(view.html,/class="overlay-svg/);assert.match(view.html,/data-guide-connection="GPIO17:TRIG"/);
  });
  test(`explicit caller focus remains available without a pin target (realtime=${realtimeEnabled})`,async()=>{
    const view=await renderWiringVideo({realtimeEnabled,hasTarget:false,overlayComponentId:hc,extraComponents:[tft]});
    assert.match(view.html,/data-component-id="hc-sr04"/);
    assert.doesNotMatch(view.html,/data-component-id="mrd-tf240-8p-cs"|>CS<|data-guide-connection=/);
    assert.match(view.html,/class="overlay-svg/);
  });
  test(`TFT selection immediately removes the HC guide's held/callout inputs (realtime=${realtimeEnabled})`,async()=>{
    const view=await renderWiringVideo({realtimeEnabled,overlayComponentId:tft,targetComponentId:hc,extraComponents:[tft],manualOnly:true});
    assert.equal(view.target,null);assert.equal(view.pin.guidePinId,null);assert.equal(view.pin.guidePeerPose,null);
    assert.match(view.html,/data-component-id="mrd-tf240-8p-cs"/);
    assert.doesNotMatch(view.html,/data-component-id="hc-sr04"|data-guide-connection=/);
  });
  test(`missing HC pose cannot fall back to another component (realtime=${realtimeEnabled})`,async()=>{
    const view=await renderWiringVideo({realtimeEnabled,overlayComponentId:hc,componentId:tft,hasTarget:false});
    assert.doesNotMatch(view.html,/data-component-id=/);assert.match(view.html,/class="overlay-svg/);
  });
}
test('HC capture scopes review mode and retains its separate framing instruction',async()=>{
  const view=await renderWiringVideo({hasTarget:false,overlayComponentId:tft,extraComponents:[tft],captureTask:{target:'hc_target',instruction:'拍攝超音波與目標'}});
  assert.match(view.html,/data-component-id="hc-sr04"/);assert.doesNotMatch(view.html,/data-component-id="mrd-tf240-8p-cs"/);
  assert.match(view.html,/debug-capture-overlay/);assert.match(view.html,/拍攝超音波與目標/);
});
test('no guide or selected component retains general detection and Eye presentation',async()=>{
  for(const displayMode of ['standard','smart-glasses-demo']){
    const view=await renderWiringVideo({displayMode,hasTarget:false,extraComponents:[tft]});
    assert.match(view.html,/data-component-id="hc-sr04"/);assert.match(view.html,/data-component-id="mrd-tf240-8p-cs"/);
  }
});
test('live and photo share the guide scope; collapsing controls never changes recognition focus',()=>{
  const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
  assert.match(app,/projectGuideOverlayScope\(project\.component_ids, maker\.guide\)/);
  assert.equal((app.match(/overlayComponentId=\{guideOverlayComponentId\}/g)??[]).length,2);
  assert.match(app,/overlayOverview=\{Boolean\(project\) && !displayModeActive && guideOverlayComponentId === null\}/);
  assert.doesNotMatch(app,/overlayOverview=\{[^\n]*guideVisible/);
  const view=readFileSync(new URL('../src/components/VideoView.tsx',import.meta.url),'utf8');
  assert.match(view,/componentPosesForOverlay\(componentPoses, focusedComponentId\)/);
  assert.doesNotMatch(view,/dimmed=\{Boolean\(guideTarget/);
});

for (const cameraSource of ['device','phone']) {
  test(`${cameraSource} overview retains both components and Pi, ignoring a remembered active target`,async()=>{
    const view=await renderWiringVideo({cameraSource,overlayComponentId:hc,overlayOverview:true,extraComponents:[tft]});
    assert.match(view.html,/data-component-id="hc-sr04"/);assert.match(view.html,/data-component-id="mrd-tf240-8p-cs"/);
    assert.match(view.html,/class="overlay-svg/);assert.equal(view.target,null);
    assert.doesNotMatch(view.html,/data-guide-connection=/);
  });
}
