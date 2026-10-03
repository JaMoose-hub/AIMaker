import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {readFileSync} from 'node:fs';
import postcss from 'postcss';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';

const sourceControl=React.createElement('div',{className:'image-source-host'},'Phone stream');
test('source control is inside the live shell, not the toolbar or a new stream viewer',async()=>{
  const {html}=await renderWiringVideo({sourceControl});
  const dock=html.indexOf('live-camera-dock');
  assert(dock>html.indexOf('class="video-shell'));
  assert(dock<html.indexOf('image-source-host'));
  assert.equal((html.match(/image-source-host/g)||[]).length,1);
  assert(!html.includes('live-camera-message-card'));
  assert(!html.includes('<video'));
});
test('references hide the existing shell without unmounting its source portal',async()=>{
  const {html}=await renderWiringVideo({sourceControl,alternateView:React.createElement('section',null,'Photo')});
  assert.match(html,/<div hidden="" class="video-shell/);
  assert.equal((html.match(/image-source-host/g)||[]).length,1);
});
test('phone disconnect groups one explanation and reconnect button while suppressing old frames',async()=>{
  const {html,pin}=await renderWiringVideo({sourceControl,cameraSource:'phone',sourceUnavailable:true,connected:false,onRetrySource(){}});
  assert.equal(pin,undefined);
  assert.equal((html.match(/live-camera-message-card/g)||[]).length,1);
  assert(html.includes('等待手機串流')&&html.includes('重新連接'));
  assert(!html.includes('hint-pill')&&!html.includes('data:image/jpeg'));
});
test('pending and service-offline states do not offer an unusable reconnect action',async()=>{
  for(const args of [{sourceChanging:true},{backendDown:true}]){
    const {html}=await renderWiringVideo({sourceControl,onRetrySource(){},...args});
    assert(html.includes('live-camera-message-card'));
    assert(!html.includes('重新連接</button>'));
  }
});
test('a rolled-back switch leaves the original frame visible with a compact in-video error',async()=>{
  const {html}=await renderWiringVideo({sourceControl,sourceError:'mobile_publisher_not_ready'});
  assert(html.includes('未能切換，保留原來源'));
  assert(html.includes('data:image/jpeg'));
  assert(!html.includes('live-camera-message-card'));
});

test('live controls share one row and height; status notices stay below both controls',()=>{
  const css=postcss.parse(readFileSync(new URL('../src/components/LiveCameraOverlay.css',import.meta.url),'utf8'));
  const rule=selector=>css.nodes.find(node=>node.type==='rule' && node.selector===selector);
  const value=(selector,property)=>rule(selector)?.nodes.find(node=>node.prop===property)?.value;
  assert.equal(value('.live-camera-dock','display'),'grid');
  assert.equal(value('.live-camera-dock','column-gap'),'0');
  assert.equal(value('.live-camera-dock .gpio-capture-action','display'),'contents');
  for(const selector of ['.live-camera-dock .gpio-capture-action small','.live-camera-switch-error']) {
    assert.equal(value(selector,'grid-column'),'1 / -1');
  }
  const shared='.app.tinkro-theme:not(.display-mode-active) .live-camera-dock :is(.image-source-trigger, .gpio-capture-action .gpio-capture-button)';
  assert.equal(value(shared,'height'),'var(--live-control-height)');
  assert.equal(value(shared,'box-shadow'),'none');
  const mobile=css.nodes.find(node=>node.type==='atrule' && node.params==='(max-width:700px)').toString();
  assert.match(mobile,/--live-control-height:44px/);
  assert.match(mobile,/clip-path:inset\(50%\)/,'compact capture label remains accessible');
  assert.doesNotMatch(mobile,/gpio-capture-button[^}]*display:none/);
});
