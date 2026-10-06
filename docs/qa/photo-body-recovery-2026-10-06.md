# Static Pi localization recovery — 2026-10-06

## Reproduction and cause

The user reported a locked live view followed by an oversized Pi box and missing GPIO in the frozen photo. One fresh 1920 x 1080 Webcam snapshot reproduced the failure: `yolo_clipped`, confidence 0.4976 in a box `[2, 103.11, 1081.41, 1077]`, no semantic outline, and photo reason `model_body_only`. HC-SR04 and TFT geometry were located.

`PhotoGeometry.board` returned before reference matching whenever the model did not supply a usable quad. Thus even strong independent texture evidence inside a body ROI could never recover the board. Separately, a minimally accepted board reference stopped the native-detail fallback even if its subsequent J8 row alignment was ambiguous.

The live backend exited unexpectedly at 17:52:30 and its existing supervisor automatically restarted it; this turn did not initiate that exit. Earlier in-memory photo URLs consequently became unavailable. The fresh reproduction was downloaded and frozen for offline replay before any further restart. The exit cause was not established by this geometry investigation.

## Fix boundary

- A valid current-photo body box may now bound reference search even when its model quad is missing or rejected. Its rectangle is never a semantic outline or a pin source.
- Body-only search cannot use the contour-orientation fallback. It must meet the existing distributed unique-reference support and final in-frame board geometry gates, then pass independent current-image J8 alignment.
- If an accepted reference leaves J8 ambiguous, the existing native-reference bank gets at most one attempt. Its board hypothesis must have more unique inliers, no less reference coverage, and a maximum corner shift within 5% of the prior diagonal; all original reference/J8 gates remain in effect.
- No old live pose is copied into the photo. The original frozen frame, frame identity, timestamp, and confidence provenance are preserved. Contact visibility and electrical verification remain false.
- No live worker, model, camera setting, buffer, AI route, or Pi command was changed.

## Evidence

Frozen local diagnostic assets (not committed):
`C:/Users/james/AppData/Local/Temp/tinkro-photo-replay-75b9f446ee5b40d79683f635ca3fc330/`

- `capture.json` and `photo.jpg`: original API result and its hash-matched JPEG, frame 842.
- `fixed.json`: replay after the fix, using the same image and saved model DTOs, zero model forwards in replay.
- Pi: `located`, 57 unique inliers, coverage 0.206, reprojection median 1.216 px, current J8 row support `[20, 20]`, accepted row alignment.
- Pin hint counts: Pi 40, HC-SR04 4, TFT 8. All three geometry states `located` on this reproduction.
- One full geometry replay measured about 0.54 seconds, excluding capture/network/model latency. This is not an end-to-end latency guarantee or an independent real-scene accuracy benchmark.

39 regression tests passed: 34 photo geometry cases (including body ROI failure/success, blank pixels, weak reference, distant alternative hypotheses, ambiguous J8, and original TFT/identity cases) and 5 snapshot isolation cases. No test failures. Existing Starlette/httpx deprecation warning only. Whitespace check passed.

## Deployment

After explicit user permission, the backend was restarted at 17:58 (Asia/Taipei): supervisor PID 4372, backend PID 33332. HTTPS gateway PID 27532 remained running. Pi was disconnected with an empty job queue; no Pi action was performed. Startup stderr remained empty during verification.

The existing desktop tab was refreshed. Two actual UI captures at 17:59 and 18:00 both returned `located` for Pi, HC-SR04, and TFT, with 40/4/8 pin hints, `same_frame: true`, `continuous_inference: true`, and a displayed 1920 x 1080 JPEG. IDs: `de86d8ef8d4b461da0a6290992f5ef70` and `746a3e049d264f7bbf4db1d16cbdc82b`. The second screenshot shows all three "Reliable geometry" overlays and no oversized yellow Pi box. Local-only evidence: `photo-body-recovery-2026-10-06.png` beside this report (Git-ignored, not committed); raw API results were saved as `live-verified.json` and `live-verified-2.json` in the diagnostic directory above.

The turn stayed within 50 test/experiment executions: 39 regression cases, 7 offline geometry attempts, and 3 live snapshots including the original reproduction. Two successful fresh captures are not a broad scene accuracy benchmark or long-duration stream stability test. Existing saved results were not silently rewritten. No claims of electrical correctness, verified physical wire insertion, 95% accuracy, or universal capture success are made.

The investigation and verification skills guided evidence collection from the photo response through same-image replay, geometry gates, and snapshot/live-worker isolation.
