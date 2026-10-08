# Component-test / phone stream isolation

## Scope and observations

- Report: both HC-SR04+ and TFT tests sometimes briefly interrupt the desktop phone image.
- Read-only observation during the user's TFT test: 246 synchronized frame responses over 15 seconds; no HTTP errors/empty responses or gaps above 500 ms. Maximum request latency 94 ms; maximum source frame age 172 ms. Runtime revision remained 10, publisher generation 4. This did **not** reproduce the reported physical-test interruption.
- Native publisher snapshots showed roughly 30 fps, RTT 8–10 ms, no NACK/PLI/retransmission deltas, and no encoder quality limitation. These short samples do not establish long-term network stability or rule out intermittent problems.

## Reproduced failure paths and fixes

1. `MobileService.publish_context` wrote workflow JSON while holding the same lock used by native video receipt and asyncio RTC callbacks. An injected slow disk write reproducibly blocked frame receipt. Persistence now uses its own serialized publication lock, writes before committing, and acquires the media lock only for the in-memory commit. Failed saves do not publish partial state. Concurrent publications preserve commit ordering.
2. A missing/expired 2.5-second camera-status lease was treated as confirmed source loss by App, disabling VideoView's healthy tracking request loop. App now distinguishes unknown metadata; the tracked phone view keeps its existing loop alive until explicit failure or a source switch. It still renders only correctly owned/revision-matched frames and retains the original 600 ms pixel/pose freshness limit. Non-tracked fallback video remains blocked when source status is unavailable.

No buffer increase, extra capture pipeline, change to Pi test execution, or relaxation of recognition/pin confidence was introduced. Workflow snapshots and capture tickets keep their existing invalidation behavior.

## Verification

- Backend: 12 passing cases: `test_mobile_media_isolation.py` (4), existing parameterized daily workspace updates (8).
- Frontend: 22 passing cases across `component_stream_isolation`, `phone_live_source`, `live_camera_state`, and `deployment_preview`.
- Three additional passing tracking regressions: runtime/out-of-order rejection, camera identity switch, and persistent-failure pixel/pose expiry.
- 48 total automated case executions including intentional pre-fix failures and reruns, within the user's limit of 50. An initial deployment SSR assertion was corrected to account for the pre-onLoad state; production preview behavior was not changed for that assertion.
- `npm run build`: passed (existing large-chunk advisory only).
- `git diff --check`: passed; line-ending warnings in the shared dirty worktree are not whitespace failures.
- React review: derived primitive state only; no new effects, camera owners, request loops, queues, or model execution.

## Deployment / limits

Source and frontend build are ready. Backend restart and desktop refresh are required. No automatic restart was performed while the user's hardware test was active; permission to restart was requested after Pi reported stopped. No physical test outcome was selected or certified, and no post-restart long-running hardware acceptance has yet been performed.
