# Genuine landscape phone capture — 2026-10-03

This replaces the earlier forced 90° portrait conversion. Phone orientation and camera pixels are independent gates. A portrait camera stays local while the UI asks the user to turn the phone sideways. Landscape publication preserves upright pixels and full wiring context; it does not rotate CSS, swap metadata or force a portrait scene onto its side.

## Implementation and ownership

- Existing phone-web publisher, hook, preview, photos and pairing are retained. No backend/Pi/AI changes.
- Screen Orientation API is preferred, then legacy orientation and media-query fallbacks. Browsers report screen orientation, not an independently measured physical pose; a rotation lock may require disabling that lock and restarting preview while sideways.
- A pending portrait source has one native camera and decoder, but no outgoing canvas track or stream-start/offer request. Cancellation drains the pending start and removes direction listeners and decoder. No timer arbitrarily ends the user's wait once decoded camera frames exist.
- Actual decoded landscape dimensions plus non-portrait phone orientation enable an unrotated proportional canvas output. Default 1920×1080; selected/constraint-fallback 1280×720. Non-16:9 input is letterboxed, never stretched or cropped; upscaling does not create additional camera detail.
- Local video, local JPEG and RTC use the same output coordinate plane. Turning either phone or source back to portrait stops publication and revokes capture readiness. Saved photos remain independent of the stopped live source.

## Automated verification

Focused files: `mobile_browser.test.mjs` (38), `mobile_capture.test.mjs` (4), `mobile_web.test.mjs` (17), **59 distinct tests**. First run: 58 pass, one SSR assertion failed because it assumed a `disabled` / `class` attribute order. That assertion was corrected and only that case rerun, passing: **60 automated executions total**, not a full-suite run.

[Focused log](unified-assistant/phone-orientation-focused.log), [single-case recheck](unified-assistant/phone-orientation-recheck.log). TypeScript and production build passed. Existing >500 kB bundle warning remains. There were no backend changes requiring new backend tests in this round; this is not a backend/full-suite/hardware regression claim.

Tests cover portrait rejection, phone-vs-pixel direction gating, cancellation/late-result guards, direction invalidation/cleanup, legacy direction fallback, local-only publication state, stale readiness suppression, canonical capture, 720p fallback and existing source ownership.

## Isolated browser checks

Loopback fixture `frontend/tools/mobile-capture-preview.mjs`, 18789, uses the real phone UI/hook/publisher and a synthetic browser-native camera stream. RTC negotiation, FPS, server lock and GPIO geometry are test doubles. Nothing calls a real phone, webcam, Pi, model or cloud service.

Six scenarios passed (Chinese/dark 844×700 and English/light 390×844):

1. Portrait source 1080×1920 plus portrait phone: local-only label/hint, capture disabled, no output track or new stream-start/offer request.
2. Sideways phone while decoded source stays portrait: still no publication; waiting-camera hint remains.
3. Source changes to 1920×1080 while phone stays sideways: one native acquisition, outgoing track and decoded preview 1920×1080. Four colored corners remain in unrotated red/green/blue/yellow order within a 5-level RGB conversion tolerance.
4. Phone capture: JPEG header, saved image natural size, capture metadata and SVG viewBox agree on 1920×1080. JPEG quality 0.95; corner order unchanged. Photo navigation keeps one camera acquisition, zero native stops.
5. Phone turns portrait while the camera pixels remain landscape: server publication becomes inactive, capture disabled, native stop and peer close each exactly once, hidden decoder removed. Direction-change guidance asks for explicit restart.
6. English/light portrait waiting: no horizontal overflow; Stop cancels. Later screen and camera becoming landscape cannot revive publication or leave a decoder behind.

The initial pixel check ran after video metadata changed but before a decoded output frame arrived, and read black pixels. A bounded decoded-pixel wait verified the actual corner colors. The isolated browser daemon later stopped responding; only its verified process tree was restarted, then the landscape/photo/stop flow rechecked. These driver issues are not evidence about phone FPS or Safari compatibility.

[Portrait waiting](unified-assistant/phone-orientation-portrait-wait.png), [landscape preview](unified-assistant/phone-orientation-landscape.png), [saved photo](unified-assistant/phone-orientation-photo.png), [stopped direction](unified-assistant/phone-orientation-stopped.png), [English/light waiting](unified-assistant/phone-orientation-light-wait.png). No page errors remained. Automated plus bounded browser scenario executions stayed below 100; no full frontend/backend suite was run.

## Delivery and remaining device checks

Our production build passed with `index-CHnsgSzS.js` / `MobileWebApp-Cmm9GWY3.js`. At the final read-only check, the shared working directory had a newer build: production 8100 served `index-DojkhJub.js` / `MobileWebApp-BtQENSde.js`. Its phone module still contained the sideways-waiting and direction-stop UI; unrelated concurrent work was not overwritten. No production service, stream, project or Pi was restarted or mutated.

Stop the old phone preview, refresh the phone page, hold it sideways and start preview again. If the camera still reports portrait, disable rotation lock and stop/start while sideways. Refresh desktop assets if needed; no Pi/backend restart is required.

Actual iPhone Safari orientation events, decoded camera rotation, canvas support/CPU cost, encoder dimensions, sustained FPS, battery/heat, network transport and physical GPIO accuracy remain unverified on a device. Workspace aspect ratio may still require letterboxing; no wiring is cropped to simulate full-screen coverage.
