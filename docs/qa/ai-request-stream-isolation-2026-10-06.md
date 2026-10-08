# AI request / native phone video isolation

## Report and observed baseline

The phone preview stayed smooth while the desktop stream stalled during Tinkro AI processing. Before this patch, live telemetry showed native phone capture at 30 FPS but transmission around 1–2 FPS, approximately 25 kbps actual send bitrate and 30 kbps target bitrate. Receiver REMB was about 20.7 kbps, with zero reported packet loss, zero jitter-buffer overflows and an empty decoder queue. Received frame geometry was 1920 × 1080.

After the user reopened the stream, a separate baseline with no AI work active still showed roughly 1–2 FPS and low target bitrate. Therefore these observations do not establish AI as the sole cause of every bitrate collapse. Later stale/disconnected statistics are not treated as an active-stream measurement.

## Reproduced defects and changes

1. `AssistantService.start_wiring_review` held the media receipt lock while waiting for debug/session state, persistence and conversation projection. Both deliberately delayed debug creation and delayed conversation persistence blocked native frame receipt before the fix. The operation now uses the existing context-publication guard with the same lock order as workspace publication; the media lock is held only while copying the current workspace. Duplicate-request, ownership, workspace and Pi-busy checks remain intact.
2. `CountedVideoTrack.recv` awaited periodic status reporting, and `MobileService.on_video_metrics` ran its lock/notification work on the RTC event loop. Delayed reporting reproduced blocked reception/scheduling. Reporting is now optional background work with at most one report in flight; overlapping reports are skipped rather than queued. Status application and notification run in a worker, and notification is outside the update lock. Closing cancels the pending report.
3. Deferred metrics validate active generation and age. Old dimensions/color metadata cannot replace newer native-frame geometry after rotation. Native receipts, not status reports, remain authoritative for stream freshness.
4. Added a timing-only RTC event-loop monitor, exposed through existing diagnostics. It records scheduling lag separately from RTP jitter/loss and rate-limits warnings. One monitor serves active streams and is cleaned up when the last stream closes.

No parallel camera pipeline, larger media buffer, forced bitrate, resolution reduction, frontend changes or hardware behavior changes were introduced in this patch.

## Verification

48 test-case executions total, within the requested 50:

| Check | Executions | Result |
| --- | ---: | --- |
| Delayed review create/save before fix | 2 | Expected failures reproducing blocked receipt |
| Shared wiring start after fix | 11 | Passed |
| Delayed metrics/reporting before fix | 2 | Expected failures reproducing blocked receive/scheduling |
| Metrics, counted-track and report cancellation checks after fix | 7 | Passed |
| RTC diagnostics, native codecs and lifecycle checks | 9 | Passed |
| Other debug/media isolation and stale-metrics cases | 14 | Passed |
| Native receipt versus metrics liveness checks | 3 | Passed |

Final relevant coverage: 44 distinct passing cases. Python compilation and scoped `git diff --check` passed. The only test warning was the existing Starlette/httpx TestClient deprecation.

Coverage includes workspace publication during a delayed review start, receipt during slow notification, bounded reporting, report cancellation, rotation/generation/expiry rejection, read-only diagnostic sampling, publisher/viewer cleanup and failed-close ownership. Native aiortc H264 and VP8 loopback tests use synthetic 320 × 240 frames; they are not physical-phone or Full HD acceptance tests.

## Deployment and remaining acceptance

After explicit user authorization, restarted the verified backend process tree on 2026-10-06. New supervisor PID 41528 and backend PID 14492; existing HTTPS gateway PID 37556 was preserved. Desktop root and config returned 200. Phone `/mobile` and the proxied `/api/mobile/web-ca` returned 200 using TLS certificate and hostname verification with the existing local CA explicitly supplied. No OS trust settings were changed. The saved debug session remains paused with `backend_restarted`; no AI or hardware job was replayed. Startup reported the configured MX Brio webcam was unavailable; phone pairing/stream must be reconnected independently.

No real AI request, phone camera action, GPIO test or Pi execution was initiated during verification. Existing unrelated workspace changes were preserved.

After phone reconnection, measure the same stream before and during one AI request: phone capture/sent FPS, received FPS, target/actual bitrate, receiver REMB, RTP loss/jitter, decoder backlog and the new local event-loop lag. Confirm 1920 × 1080 (or portrait counterpart), orientation changes and desktop continuity on the physical phone. Do not claim the idle low-bitrate behavior or all real-network stalls are resolved until this comparison passes.
