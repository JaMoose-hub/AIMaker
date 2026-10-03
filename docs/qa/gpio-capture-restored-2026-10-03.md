# Shared wiring-photo capture restored

## Scope

- Added one capture action inside the live image, next to the existing source control. The reference-photo view exposes the same action as Retake; an empty photo view can also capture.
- Webcam and phone use the existing `/api/photo-wiring/sessions` flow against the selected FrameBus source. No second camera handle, phone viewer, AI request, Pi test, or backend restart was introduced.
- The operation owner stays above the live/photo views. Source controls, calibration, competing AI capture and view switching are disabled while this operation owns the camera lease.
- Accepted photographs retain source, project revision and wiring round. Exact runtime/source binding rejects late source changes. Late results never move the user out of the design stage.
- Capture errors preserve the old photo and release inference. Resume errors retain the new photo and expose a recovery-only action. A combined capture/resume failure still reports capture failure after successful recovery.
- Existing GPIO geometry validation and electrical-verification boundaries are unchanged.

## Validation

- TypeScript and production build passed. The existing large-chunk warning remains.
- 18 distinct targeted Node checks passed (`gpio_photo_workspace.test.mjs` and `live_camera_overlay.test.mjs`). 44 Node test executions including reruns; one initial malformed-fixture expectation was corrected before the passing runs.
- Isolated browser fixture on port 18819, with fake media/API and no external network: Webcam capture, phone capture through the same endpoint, automatic photo selection, GPIO overlays, retake, capture failure, resume failure/recovery, combined failure/recovery, double-click coalescing, disconnected phone, late stage change, passive empty-photo view and capture from that view.
- Dark desktop 1413×871, dark narrow 900×740, and light English 900×740 were inspected. One visible capture control; no horizontal page overflow or captured browser errors. Button remains legible against the live image in either theme.
- Local port 8100 served the updated production entry. The user's live browser was not refreshed or operated; reload it to receive the new frontend.

## Evidence and limits

- `gpio-capture-restored-live.png`
- `gpio-capture-restored-photo.png`
- `gpio-capture-restored-narrow.png`
- `gpio-capture-restored-light.png`

The fixture uses synthetic imagery and GPIO geometry. This verifies UI integration and request/recovery behavior, not real-device capture latency, real-scene YOLO/GPIO accuracy, or electrical wiring. No hardware test was performed. The private fixture and browser session were closed afterward.
