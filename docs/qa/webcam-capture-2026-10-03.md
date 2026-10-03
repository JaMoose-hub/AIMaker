# Webcam capture check — 2026-10-03

## Scope and runtime

The user authorized Webcam testing. One new Webcam photograph and one offline geometry replay were performed; no Pi test, deployment, AI photo submission, training, or application-code edit was performed. Verification remained below 100 runs.

Port 8100 is still owned by backend PID 18944, started at 17:05:24 +08:00. This predates the photo-geometry fixes. The earlier rejected restart was not retried or bypassed. The browser was refreshed to load the latest built frontend. Webcam/device source, runtime revision 5, 1920 × 1080, and real-time tracking were confirmed. Pi was disconnected with no active component test.

## Actual Webcam observations

- Before capture, frame 10809 had Pi, HC-SR04 and TFT all locked, with 40/4/8 projected pins. All three outlines were visible in the collapsed-guide overview.
- The main `擷取接線照片` action created capture `402e9a4ffa1041668b10c8c32fe33d94` at 17:51, frame 10976, camera `webcam-33a794e3ffe739903078c1cc`.
- All three photo objects were `located`: Pi `board_and_j8_supported`, HC `distributed_reference_supported`, TFT `four_rings_lcd_and_header`.
- The actual photo UI showed three outlines and a dashed expected GND → Pi Pin 6 link. `same_frame=true`, capture skew 0 ms, `stale=false`, and `electrical_verified=false`.
- Returning to live view resumed fresh frames. Frame 13350 again reported all three locked, with 40/4/8 projected pins. The display packet is explicitly `display_only=true`.
- Opening the guide exposed the existing component-test review phase. All three outlines remained visible as intended in review. The guide was collapsed again without advancing a step or changing manual wiring confirmations. Active wiring-step filtering was not exercised in this live check.
- No browser error logs were returned. The page was left on Webcam live view with the guide collapsed.

## Fixed-code regression on the same photograph

Downloaded the original capture packet and JPEG without modification. JPEG SHA-256 is `2ab1da61f73f19b94f66228e2b06816a6310fe461906244cbb358ae297d30a9e`.

The current `app.photo_geometry` saved-packet replay passed its image hash, frame, size and runtime checks and located all three objects. Replay performed zero new model forwards; it reused the captured model output and ran the fixed geometry code offline. This is not evidence that the running backend has loaded the fixes, and does not validate the previous failing phone capture in a restarted runtime.

## Evidence and limits

Artifacts: `backend/runs/diagnostics/webcam-capture-20261003/{capture.json,photo.jpg,replay.json,webcam-photo-ui.png,webcam-live-ui.png}`.

This demonstrates one successful real Webcam scene and capture workflow, plus one fixed-code regression replay. It does not establish robustness across lighting, angles or motion, electrical continuity, correct physical attachment, or component function. Backend restart and a fresh phone capture remain pending for live confirmation of the previous phone-specific failure.

Browser verification followed the computer-use and agent-browser / agent-browser-verify skill checklists through the supported CUA browser API.
