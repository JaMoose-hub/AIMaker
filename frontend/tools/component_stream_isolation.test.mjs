import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';

const app = ts.createSourceFile('App.tsx', readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let availability, statusUnknown;
function visit(node) {
  if (ts.isJsxAttribute(node) && node.name.getText(app) === 'sourceUnavailable') availability = node.initializer.expression;
  if (ts.isJsxAttribute(node) && node.name.getText(app) === 'sourceStatusUnknown') statusUnknown = node.initializer.expression;
  ts.forEachChild(node, visit);
}
visit(app);
assert.ok(availability);
assert.ok(statusUnknown);
const unavailable = new Function('config', 'liveCamera', 'phoneReady', `return ${availability.getText(app)}`);
const unknown = new Function('config', 'liveCamera', `return ${statusUnknown.getText(app)}`);
const missingStatus = () => ({sourceUnavailable:unavailable({camera_source:'phone'}, {status:null}, undefined),
  sourceStatusUnknown:unknown({camera_source:'phone'}, {status:null})});

test('a delayed status poll must not tear down healthy same-frame phone polling during a component test', async () => {
  for (const livePreviewHost of [null, {}]) {
    const view = await renderWiringVideo({cameraSource:'phone', cameraIdentity:'phone:paired:2',
      ...missingStatus(), livePreviewHost});
    assert.equal(view.tracking[0], true);
    assert.match(view.html, /data:image\/jpeg;base64,fixture/);
    // SSR cannot fire the deployment image's onLoad; its initial paint notice
    // is expected. It must receive the same, visible frame, not lose the source.
    if (livePreviewHost) assert.match(view.html, /<img src="data:image\/jpeg;base64,fixture"[^>]*draggable="false"\/>/);
    else assert.doesNotMatch(view.html, /等待手機串流/);
  }
});

test('missing metadata is not permission to show expired pixels or reuse another video path', async () => {
  const view = await renderWiringVideo({cameraSource:'phone', ...missingStatus(), frameAvailable:false});
  assert.equal(view.tracking[0], true, 'keep probing for the next correctly owned frame');
  assert.equal(view.pin, undefined);
  assert.doesNotMatch(view.html, /data:image\/jpeg|src="\/video"|src="\/frame.jpg/);
});

test('unknown metadata cannot enable fallback MJPEG when same-frame tracking is disabled', async () => {
  const view = await renderWiringVideo({cameraSource:'phone', ...missingStatus(), realtimeEnabled:false});
  assert.equal(view.tracking[0], false);
  assert.equal(view.pin, undefined);
  assert.doesNotMatch(view.html, /data:image\/jpeg|src="\/video"|src="\/frame.jpg/);
});

test('explicit source failure and user source changes still hide frames and pins', async () => {
  const blocked = unavailable({camera_source:'phone'}, {status:{ready:false,error:'phone_dimensions_changed'}}, false);
  assert.equal(blocked, true);
  for (const reason of [{sourceUnavailable:blocked}, {sourceChanging:true}]) {
    const view = await renderWiringVideo({cameraSource:'phone', ...reason});
    assert.equal(view.tracking[0], false);
    assert.equal(view.pin, undefined);
    assert.doesNotMatch(view.html, /data:image\/jpeg/);
  }
});
