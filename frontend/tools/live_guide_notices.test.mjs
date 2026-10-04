import assert from 'node:assert/strict';
import test from 'node:test';
import {renderWiringVideo} from './glasses_wiring_fixture.mjs';

for (const cameraSource of ['device', 'phone']) {
  test(`${cameraSource}: routine tracking notices do not cover the live image`, async () => {
    for (const manualOnly of [true, false]) {
      for (const status of [{}, {searching: true}, {visualHeld: true}]) {
        const {html} = await renderWiringVideo({cameraSource, manualOnly, ...status});
        assert.doesNotMatch(html, /wiring-hud-note|Pin 定位暫停|目標定位暫停|辨識暫時不穩/);
        assert.match(html, /class="video-legend"/);
        assert.match(html, /Selected target/);
      }
    }
  });

  test(`${cameraSource}: removing notices preserves held and unavailable pin safeguards`, async () => {
    const held = await renderWiringVideo({cameraSource, manualOnly: true, visualHeld: true});
    assert.equal(held.pin.tracking, 'stale');
    assert.equal(held.pin.guidanceHeld, true);
    assert.match(held.html, /data-guide-connection="GPIO17:TRIG"/);
    const unavailable = await renderWiringVideo({cameraSource, manualOnly: true, searching: true});
    assert.equal(unavailable.pin.guidePinId, null);
    assert.doesNotMatch(unavailable.html, /data-guide-connection=/);
  });

  test(`${cameraSource}: guide endpoints retain centre dots and links without two outer halos`, async () => {
    const {html} = await renderWiringVideo({cameraSource, manualOnly: true});
    assert.doesNotMatch(html, /guidance-halo|component-guidance-halo/);
    assert.match(html, /guidance-target/);
    assert.match(html, /class="pin-dot"/);
    assert.match(html, /component-pin-dot/);
    assert.match(html, /data-guide-connection="GPIO17:TRIG"/);
  });

  test(`${cameraSource}: divider safety warning remains even when tracking is unavailable`, async () => {
    for (const status of [{}, {searching: true}, {visualHeld: true}]) {
      const {html} = await renderWiringVideo({cameraSource, manualOnly: true, connectionKind: 'divider', ...status});
      assert.match(html, /class="wiring-hud-note" role="status"/);
      assert.match(html, /330Ω/);
      assert.match(html, /禁止直連/);
      assert.doesNotMatch(html, /data-guide-connection=/);
    }
  });
}
