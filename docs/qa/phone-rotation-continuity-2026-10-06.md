# Phone rotation and live geometry continuity — 2026-10-06

## Scope and evidence

The preceding live investigation reproduced portrait/landscape switching without
pressing component test or AI help. Rotation closed the publisher, changed the
generation, and was followed by 1080p -> 720p -> 540p changes. Each size change
invoked full camera handover, including stopping/restarting inference workers.
The observed receiver buffer overflow count was zero. This does not establish
every independent cause of low bandwidth or test/AI-related stalls.

## Changes

- Native orientation/resize events update metadata and briefly withhold capture
  hints; they do not close the camera track, peer, or server publication. Delayed
  native playback can restore readiness without reopening the camera. Explicit
  Stop still releases ownership and cancels pending callbacks.
- Sender preference is `maintain-framerate`, with the existing optional-control
  fallback. The original local camera/photo path is not resized or resampled.
  See [RTCRtpSender.setParameters](https://developer.mozilla.org/en-US/docs/Web/API/RTCRtpSender/setParameters).
- The selected PhoneFrameSource accepts same-owner native size transitions.
  Source/session/generation, age, and monotonic sequence checks remain intact.
- The existing single-slot FrameBus assigns a geometry epoch on size changes
  and source clear. A -> B -> A is detectable even when a slow worker skips B.
- Board/component workers clear their own temporal geometry on their own
  inference thread; loaded models, capture, and runtime source identity remain.
  Motion tracking rejects old-epoch seeds and late results. Phone calibration
  remains disabled; no webcam calibration is silently adopted.
- Native size receipt immediately revokes phone capture readiness. Analysis
  started on pre-change pixels cannot restore the old lock after completion.
- Rotation/resizing no longer requires the source-selection API, so AI/capture
  business-state locks do not block this same-source size update. Genuine source
  replacement still uses the existing guarded transaction.

## Validation

46 test executions, all passing (44 distinct cases; two final frontend reruns).
No hardware tests or paid AI calls were triggered.

- 15 selected `frontend/tools/mobile_browser.test.mjs` cases: ownership,
  orientation, native pixels, sender fallback, rotation continuity, Stop.
- 17 cases: `test_phone_live_source.py` plus the initial five cases in
  `test_phone_geometry_continuity.py`.
- 9 cases: native-size capture invalidation, three existing parallel-motion
  cases, two existing VisionWorker cases, and three slow test-help cases.
- 2 cases: component worker geometry reset on its owner thread and existing
  recognition-stall/native-receipt isolation.
- 3 final frontend cases: rotation continuity, Stop during rotation, and delayed
  native playback recovery.
- TypeScript no-emit check and Python compile check passed.
- Vite production build verified in an isolated output directory:
  `backend/runs/qa/rotation-continuity-build-20261006`. The existing large-chunk
  warning remains. Running frontend assets were not replaced.

## Application and remaining acceptance

No restart, Git commit/push, or live phone interruption was performed in this
turn. Apply a matching frontend production build and backend restart together;
then refresh the phone page. Do not deploy only this frontend against the old
dimension-rejecting backend.

Real-device acceptance is still required: rotate in both directions, use Next,
test each of HC-SR04+ / TFT, then invoke AI help. Confirm publisher generation and
capture stay continuous while dimensions adapt, actual receipt/FPS recover,
old pins disappear during reacquisition, and Stop does not auto-revive. These
software tests are not a real-phone stability or electrical-wiring guarantee.

## Authorized restart — 2026-10-06 11:18 (Asia/Taipei)

User requested restart. Verified Pi program stopped, no active Pi job, and no AI
inference/capture in flight. Stopped the verified old supervisor/backend tree,
built `frontend/dist` successfully, and started the backend with the existing
supervisor script (supervisor 47996, backend listener 2152). HTTPS proxy 37556
was retained. Desktop and certificate-verified phone HTTPS returned 200 with
the new `index-CqSKt4LV.js` assets. Reloaded the desktop: UI rendered and browser
warn/error log was empty; new backend stderr was empty. The existing debug case
was preserved as paused / backend_restarted. Phone refresh/re-pair and real
rotation/test/AI-stream acceptance remain user-device follow-up work.
