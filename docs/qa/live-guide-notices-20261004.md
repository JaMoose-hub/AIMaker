# Live guide tracking notices

- Removed routine paused/held tracking banners from the shared Webcam/phone `VideoView`; retained the target pill and divider electrical warning.
- No changes to pose selection, held coordinates, pin visibility safeguards, recognition, capture, or guide progress.
- `node --test tools/live_guide_notices.test.mjs tools/phone_live_source.test.mjs tools/component_overlay_scope.test.mjs`: 26 passed.
- `npm run build`: passed (existing bundle-size advisory only).
- Isolated production-bundle preview with synthetic frames: active guide target remained visible, `.wiring-hud-note` count was zero for a direct connection, console errors were empty. Screenshot: `live-guide-without-pause-hint.png`.
- This is software/UI verification, not a real-camera, GPIO, electrical, or hardware acceptance test. The user's current tab was not refreshed.
