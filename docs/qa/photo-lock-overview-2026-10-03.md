# Photo localization and pre-guide overview

## Report and diagnosis

The user's 17:18 phone capture, `f1484dcc00974dc599f8dc7f412387e7`, contains Pi, HC-SR04 and TFT. The original packet located only Pi: HC reference support failed and the undersized TFT model region missed three mounting holes. This is separate from the UI scope bug: the selected module was filtering other component overlays even before entering the guide.

Frozen evidence is in `backend/runs/diagnostics/photo-lock-20261003/`: `capture.json`, hash-bound `photo.jpg`, `replay.json`, and `fixed-photo-ui.png`.

## Changes

- Photo-only bounded 1x/2x/3x PCB query pyramid uses the existing calibrated reference. Matching requires agreement across reference representations, followed by physical-coordinate deduplication. Repeated descriptors never become extra votes. Existing minimum 16 unique inliers, .45 inlier ratio, .18 board coverage, three quadrants and <=2px median error are unchanged.
- Exact spatial-grid lookups replace quadratic correspondence scans. An equivalence test covers conflict rejection and unique counts, including negative pixel cells.
- TFT gets at most one 1.5x expanded local search before its existing fallback. It still requires four observed holes plus independently supported LCD/header orientation; missing holes are not invented.
- Prepare/review/collapsed-guide views show all component packets. Only a visible active wiring step focuses its selected module. Explicit diagnostic capture targets remain scoped. Display-only/Eye modes retain their previous behavior.
- An uncertain photo component keeps a dashed candidate outline and uncertainty label, but receives no trusted pins or connection line.

## Verification

- 59 completed automated test executions passed (25 before a slow synthetic case was interrupted, 10 reference tests after spatial indexing, 23 frontend scope/style tests, and one final display-mode scope assertion). One synthetic test execution was interrupted, not counted as a pass; its replacement run passed.
- 15 bounded diagnostic localization probes, two replays of the reported image, and three existing frozen-photo regression cases. No new YOLO forwards, Pi commands, cloud checks, retraining or dataset changes. Combined software verification remained below the user's 100-execution ceiling.
- Reported photo: Pi located; HC located with 24 unique inliers, .490 ratio, .181 coverage and four quadrants; TFT located from all four real holes and independently supported sloped LCD edges.
- Three older-photo regressions preserved every previously located object. Older ambiguous Pi/J8 results stayed uncertain.
- Two frontend production builds passed with the existing chunk-size warning.
- Isolated `gpio-photo-preview.mjs` at port 18807 replayed the hash-verified photograph, with mocked APIs and no proxy/hardware access. The fixture's Webcam source label is synthetic; the actual original image is from the phone.
- Browser inspection: prepare mode and collapsed active guide both render HC + TFT + Pi; active visible HC step renders only HC + Pi. Photo renders three reliable outlines and one expected wire. Advancing fixture steps updates GND to VCC/Pin1 endpoints correctly. No browser error logs.
- Screenshot is an offline replay, not a fresh hardware or electrical acceptance result.

## Runtime handoff

The user approved a backend restart. The execution environment rejected the restart command before execution. Confirmed afterward: the original backend PID 18944 still owns port 8100. The new frontend build is served, but the browser needs refresh and the backend localization code still needs a restart. No restart success is claimed. Phone must reconnect and a new photo must be captured afterward; immutable older captures are not silently rewritten.

Skills: React Best Practices for derived presentation state; computer-use and agent-browser/agent-browser-verify checklists for isolated browser verification through the supported CUA API (agent-browser CLI was unavailable).
