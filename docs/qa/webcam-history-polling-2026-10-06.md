# Webcam contention from history polling — 2026-10-06

## Finding

Live read-only profiling of the existing backend found repeated debug/assistant/mobile history projection in AnyIO workers (deepcopy and sensitive-data redaction), plus JSON serialization in the main thread. A debug session GET returned about 1.85 MB; its separate conversation GET returned about 1.92 MB. The debug hook fetched both and scheduled the next round 1.5 seconds after completion, even without AI or Pi jobs in that session. This is a concrete competing workload, not proof that every tracking stall has the same cause.

The profiler was extracted to a unique temporary directory, not installed in the application's Python environment. Nonblocking sampling had 733 GIL-held samples and 64 sampling errors; it is supporting attribution, not an exact CPU-time accounting or a browser-render FPS benchmark.

## Changes

- Debug reads accept an optional `history_version`. Matching versions omit historical messages and diagrams, but still compute current camera/target, test/job, blocker and actionable-state projections.
- The history version is scoped to its owner and invalidated on every persisted debug mutation, redaction-password change and process restart. The full legacy response remains available without a validator. Sensitive-data sanitization is retained. Polling responses use `Cache-Control: no-store`.
- The client keeps at most two session histories (saved/local and globally active) plus the current conversation, scoped to the hook's project/effect. It merges only an exact owner/version match; errors clear validators. No active session does not evict a stopped session's saved history.
- Debug public projection excludes private drafts/internal fields before copying, rather than copying them and then discarding them.
- Assistant reads avoid a second complete copy before pagination; append-only wiring-history sync compares message counts instead of copying every old message.
- Mobile wiring-review ownership uses a small session-link projection rather than copying the entire assistant history twice. Epoch, archive and cleared-session guards remain.

## Verification

35 distinct regression cases passed: 16 backend and 19 frontend. Total executions were 41, including two initially failing hook checks and their successful repair/recheck. The hook checks caught the stopped-case cache being evicted by an empty active-session response; it now retains separate bounded caches. Six isolated timing iterations keep the total test/timing executions below 50.

Coverage includes API full/compact/legacy reads, no-store headers, a sentinel that fails if unchanged polling traverses history, fresh hardware gates, message/diagram invalidation, redaction and password changes, restart/foreign-owner isolation, pagination/output isolation, phone session links, existing mobile collection and chat-restart flows, actual polling-hook updates, malformed compact recovery, late-response and cross-project behavior.

TypeScript and the production Vite build passed. The existing large-bundle advisory and Starlette TestClient deprecation warning remain. `git diff --check` reported no whitespace errors (existing line-ending warnings remain).

### Isolated API replay

The current 160 messages and 12 diagrams were copied from a read-only public API response into a temporary fake-service fixture. Fake session/test metadata was used; no camera, model, Pi, or production history mutations were performed. Three full-history and three unchanged-status rounds each requested both session and conversation through FastAPI TestClient:

| Mode | Combined response bytes | Round times (ms) |
| --- | ---: | --- |
| Full history | 3,773,104 | 470.43, 471.18, 597.44 |
| Unchanged status | 3,520 | 2.27, 1.82, 1.81 |

The small response size depends on current status/test metadata; these are isolated API measurements, not a promise of production latency or Webcam FPS.

## Deployment boundary

Frontend assets were built. Following explicit user authorization, the verified backend supervisor tree was restarted at 17:45 (Asia/Taipei). New supervisor PID: 52072; backend listener PID: 51472. The existing HTTPS gateway on port 8443 remained PID 27532. Startup stderr was empty and the root page returned HTTP 200. No Pi actions were sent; after restart its connection is disconnected and the execution queue is empty, requiring explicit reconnection for hardware tests.

The user's existing desktop tab was refreshed and verified to load `index-43qyDm7R.js`; the Webcam image was visibly restored with natural dimensions 1920 x 1080. Live API checks preserved 161 messages and 12 diagrams in the saved session. Its unchanged response shrank from 1,894,233 to 9,307 bytes; the project conversation shrank from 1,969,493 to 221 bytes. Both compact responses reported `history_unchanged` and `Cache-Control: no-store`. The session was stopped with `model_busy: false`; no analysis was replayed.

A single 12.02-second read-only tracking sample after refreshing the client received 269 frames (22.37 FPS); per-second counts were 23, 23, 22, 24, 22, 21, 22, 20, 23, 22, 23, 24. Request errors: 0. Frame-delivery gap p95: 76.31 ms; maximum: 132.16 ms. Processing p50/p95/max: 32.53/56.73/130.91 ms. This is backend tracking delivery, not browser render FPS, a controlled same-scene A/B experiment, or long-duration stability acceptance. No 30 FPS guarantee is implied.

No model, resolution, pin geometry, FrameBus buffering, or hardware settings were changed. Existing user/worktree modifications were preserved.

The verification skill guided checks across the polling hook, API response, history ownership and rendering-state merge, keeping isolated performance evidence separate from live video acceptance.
