# Preview notification / RTC scheduling isolation

## Scope and reproduced defect

This side-conversation change preserves the existing network-watcher CIM ownership
fix and all other workspace changes. It does not restart services or change any
bitrate, buffer, resolution, model, GPIO, or wiring policy.

`MobileService.on_frame` already offloaded analysis but synchronously called
`accept_preview` afterward. That callback performed notification while retaining
the media lock, on the native RTC event loop. A deliberately delayed notification
prevented a scheduled native receipt callback from executing within 500 ms. The
same defect reproduced for a valid preview and a TTL-expired preview.

The post-analysis commit/notification now runs through `asyncio.to_thread`.
Atomic preview validation and mutation remain under the media lock in
`_accept_preview_state`; notification occurs after that lock is released and
reads current session state. The existing sampler still allows only one preview
task in flight. Generation, context, sequence, geometry and TTL validation are
unchanged; no additional frame queue or freshness extension was introduced.

## Verification

- Four new regressions passed: valid/expired analysis, both for the selected
  phone's synchronized-frame path and the standalone preview path. They verify
  that receipt on the RTC loop proceeds while notification is deliberately held.
- Forty existing regression cases passed covering recognition, rotation,
  invalid/foreign geometry, old-generation rejection, capture stability and
  media/persistence isolation.
- One pre-existing test still fails:
  `test_live_analysis_follows_desktop_step_but_keeps_frozen_phone_context_and_revokes_capture`.
  It expects a frozen phone context, while the current workspace updates it.
  Reconstructing only this patch's prior methods in an isolated Python process
  reproduces the identical assertion failure. No source files were reverted and
  no unrelated context contract was changed to make the test pass.
- 49 case executions: 44 passes, two deliberate blocking reproductions, one
  initial expired-fixture setup failure (corrected to predate the geometry epoch),
  and the pre-existing failure on both patched and pre-patch methods.
- Python compilation and scoped whitespace checks passed.

These are synthetic software tests, not physical-phone throughput acceptance.
The live phone stream was inactive during the subsequent investigation, and ten
tracking-frame requests returned 204/no image. A fresh on-device run is required
to measure capture/send/receive/display FPS and scheduling delay together.

## Deployment

The patch is saved but not loaded into the running backend. No service or phone
was stopped/restarted by this side conversation. Restart requires coordination
with the user/main task. After restart, validate physical 720p/1080p streaming
before/during AI and component-test work; this patch does not prove that the
separate low-bitrate behavior or every intermittent Wi-Fi stall is resolved.
