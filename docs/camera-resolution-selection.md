# Webcam resolution selection

Open **切換鏡頭 → 鏡頭解析度**, choose a mode, then **套用解析度**.
The current USB camera advertises MJPEG 2592×1944 at 15 FPS and
1920×1080 at up to 30 FPS. Options come from the current device's
DirectShow capabilities, not a universal list. Other capture backends remain unchanged.

- Selection lasts for the current backend session; browser refresh reads the current mode.
- The actual size is read from decoded frames, not the requested configuration.
- Mode changes share the camera-control lock with tuning, focus and camera switching.
- The frontend follows `runtime_changed` on the existing WebSocket, even after its
  initial hello is cleared. Repeated switches do not require a page reload.
- Capture and vision workers pause before old images, poses and tracking history are cleared.
  Model sessions are retained. The runtime revision changes so clients discard old geometry.
- Three fresh frames at the requested dimensions are required before success.
  Failed changes attempt to restore and verify the previous mode; failed restoration is explicit.
- The client does not retry a write after a lost response; it re-reads the current state.
- No Pi tasks, wiring records, model weights, exposure or focus settings are changed.

Regression coverage: `backend/tests/test_camera_modes.py` and
`frontend/tools/camera_modes.test.mjs`, plus existing camera/tracking/tuning tests.

Live check (2026-09-22): UI switched 1080p → 2592×1944 → 1080p → 2592×1944.
Both `/frame.jpg` and the decoded `/api/tracking/frame` JPEG were 2592×1944.
A short sample contained 43 unique tracking frames at about 13.6 FPS.
This checks video transport, not recognition or wiring accuracy. The 390-pixel viewport
kept the selector and apply button within the dialog without horizontal page overflow.

Software checks: 91 selected backend tests and 191 frontend tests passed; TypeScript
and production build passed. Vite reports a large-bundle advisory.
