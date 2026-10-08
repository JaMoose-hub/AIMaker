import test from 'node:test';
import assert from 'node:assert/strict';
import {createElement} from 'react';
import {readFileSync} from 'node:fs';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';

const preview = html => html.match(/<section[^>]*class="deployment-live-preview workflow-surface"[\s\S]*?<\/section>/)?.[0] ?? '';

test('deployment is a presentation of the existing tracking frame, not a second camera/tracker', async () => {
  const result = await renderWiringVideo({livePreviewHost:{},livePreviewControls:createElement('span',null,'One source selector')});
  const view = preview(result.html);
  assert.equal(result.trackingCalls,1);
  assert.match(view,/src="data:image\/jpeg;base64,fixture"/);
  assert.match(view,/One source selector/);
  assert.match(view,/全螢幕實際畫面/);
  assert.doesNotMatch(view,/overlay-svg|GPIO17|TRIG|guide-connection|功能通過/);
  const source=readFileSync(new URL('../src/components/DeploymentLivePreview.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(source,/fetch\(|getUserMedia|useRealtimeTracking|setInterval|connectPi/);
  assert.match(source,/removeEventListener\('fullscreenchange'/);
});

test('phone transitions and missing tracking frames cannot reuse stale or bypass media', async () => {
  for(const condition of [{sourceChanging:true},{sourceUnavailable:true},{frameAvailable:false}]) {
    const result=await renderWiringVideo({livePreviewHost:{},cameraSource:'phone',...condition});
    const view=preview(result.html);
    if (condition.frameAvailable === false) assert.doesNotMatch(view,/等待手機串流/,'brief frame gaps do not immediately raise a reconnect notice');
    else assert.match(view,/等待手機串流/);
    assert.doesNotMatch(view,/<img|\/video|\/frame\.jpg|is-live/);
    assert.equal(result.trackingCalls,1);
  }
});

test('backend loss hides camera data, display-only modes have no deployment preview', async () => {
  const disconnected=preview((await renderWiringVideo({livePreviewHost:{},backendDown:true})).html);
  assert.match(disconnected,/<img[^>]*hidden=""/);
  assert.doesNotMatch(disconnected,/is-live/);
  for(const displayMode of ['optical-hud-demo','smart-glasses-demo'])
    assert.equal(preview((await renderWiringVideo({livePreviewHost:{},displayMode})).html),'');
});

test('preview contains the full picture and reserves output space; fullscreen preserves source', () => {
  const css=readFileSync(new URL('../src/components/deploymentLivePreview.css',import.meta.url),'utf8');
  assert.match(css,/object-fit:contain/);
  assert.match(css,/max-height:26dvh/);
  assert.match(css,/:fullscreen \.deployment-preview-viewport[^}]*max-height:none/);
  const source=readFileSync(new URL('../src/components/DeploymentLivePreview.tsx',import.meta.url),'utf8');
  assert.match(source,/root\.current\.requestFullscreen\(\)/);
  assert.match(source,/catch \{ setFullscreenError\(true\); \}/);
});
