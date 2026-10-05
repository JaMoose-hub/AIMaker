# iPhone Safari smart adjustment

Implemented in the mobile **Stream / 串流** page, above the existing stream settings. The hook is owned by `useMobileBrowser`, not the camera tab, so a completed adjustment and its undo survive camera-tab unmount/remount.

## Behavior and safety

- One bounded check samples four fresh preview frames over approximately two seconds. Dark, clipped, low-detail and moving scenes produce advisory hints. Low detail is not a focus verdict or GPIO acceptance.
- Diagnostic canvas is downsampled only; published pixels, framing and wire colors are unchanged. No new camera, photo upload, model call, peer or backend pipeline is created.
- Exposure, focus and white-balance automatic modes are attempted only when the live track explicitly reports both supported modes and readable settings. Existing size, FPS and facing constraints are retained. Settings are read back and images compared; unchanged/worse results are reverted.
- Live bitrate reduction requires two distinct, recent counter-based reports indicating bandwidth limitation and slow sending. `RTCRtpSender` parameters must be supported and read back exactly. A cap is not actual throughput or proof of network improvement.
- CPU-limited high-resolution streams get a **720p recommendation** with an explicit confirm/restart button. Checking alone never restarts the stream.
- Cancel drains and rolls back pending changes; restore verifies the original settings. Failed restore remains explicit and retryable. Stop/source/workspace changes, page hiding and unmount cancel the check. Old results cannot apply to a new stream.
- Synchronous tune/capture/restart guards supplement disabled controls, so rapid clicks cannot bypass React state updates.

## Verification performed

| Check | Result |
| --- | --- |
| `node --test tools/phone_camera_tuning.test.mjs` | 20/20 passed |
| `node --test tools/mobile_test_help.test.mjs tools/mobile_wiring_review.test.mjs tools/mobile_wiring_chat.test.mjs` | 28/28 passed |
| `node --test --test-name-pattern='publisher\|permission\|H264' tools/mobile_browser.test.mjs` | 10/10 passed |
| `node --test tools/mobile_web.test.mjs` | 23/26 passed; three existing obsolete-export failures |
| `node node_modules/typescript/bin/tsc --noEmit` | passed |
| `node tools/check_i18n.mjs` | passed, 761 keys |
| isolated Vite production build | passed; existing large-chunk warning |
| `git diff --check` | passed; line-ending warnings only |

Across these 84 distinct cases, 81 passed and three failed. The three `mobile_web.test.mjs` failures call `MobileWiringPhotoDialogue`, which is not present in either current source or HEAD. This change did not remove that interface or revive the retired UI. No full-suite-green claim is made.

Production build was written to `C:\Users\james\AppData\Local\Temp\tinkro-phone-tune-build-1e665c34bbea4969b1eb12eabc5d27ea`, not the shared production `frontend/dist`.

### Browser evidence

Used `tools/phone-tuning-preview.mjs` on loopback port 18825, with the real mobile camera component, tuning hook, sampling and presentation. Frames and RTP counters were synthetic. No physical camera permission or production API/Pi/AI request was made.

Verified through visible controls:

- 12 → 8 Mbps cap, zero implicit restart; restore → 12 Mbps.
- Cancel leaves 12 Mbps unchanged.
- CPU reports produce a 720p suggestion; the stream changes only after explicit confirmation (one fixture restart).
- Unsupported control readback leaves settings unchanged and still shows dark/low-detail hints.
- Tab leave/return preserves the completed adjustment and restore action.
- Portrait 390×844 and 390×720, Traditional Chinese/dark and English/light. No horizontal overflow; smart/restore touch targets at least 44 px.
- No browser console warning/error in the fixture.

![Synthetic portrait QA, not an iPhone hardware result](screenshots/phone-smart-adjustment-2026-10-05.png)

The preview server/tab were stopped and temporary viewport override removed after verification.

## Not yet verified / deployment boundary

This is **not a real iPhone Safari camera or network acceptance test**. Real hardware must confirm track capabilities, parameter readback, local/received image quality, streaming continuity, CPU/bandwidth behavior and background recovery. No GPIO, electrical, functional or Pi result is implied.

This side task preserved the main thread's Reset and other dirty work, did not restart the running backend, did not overwrite its served frontend assets, and did not commit/push Git. A read-only HTTP check found the initial tuning implementation in the served `MobileWebApp-BZIDEFlz.js` (200), built at 11:44:24. The final synchronous operation guards were saved at 11:44:55, after that build, so the latest source still requires the main thread's next frontend build/refresh. No actual user's mobile page or stream was operated.
