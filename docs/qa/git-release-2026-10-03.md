# Pre-push check — 2026-10-03

## Scope

Desktop assistant/wiring UI, shared Webcam/phone source, mobile browser page, mobile APIs and HTTPS helpers, photo localization, and the existing native Expo prototype are included. Local configuration, credentials, certificates, pairing state, runtime photos, generated outputs, and QA screenshots/JSON remain local. The separate `tools/gpio_photo_poc` experiment is not part of this application release.

The mobile story is `/mobile` → authenticated pairing/stream APIs → existing latest-frame bus and model workers → shared desktop tracking and saved-photo overlays. Mobile browser and desktop entry points are lazy-loaded separately. Stream, socket, event-listener and object-URL cleanup were reviewed with the React best-practices checklist.

## Current checks

- 39 backend cases passed: mobile authorization/API, browser photo handling, phone source switching and freshness, photo-reference safeguards, and three targeted photo-geometry cases.
- 64 frontend cases passed: mobile web page, shared phone source, photo-capture lifecycle, component overlay scope, and shared photo/live overlay styles.
- Three native mobile API cases passed; the whole native package passed TypeScript checking.
- Frontend production build passed, including the separate `MobileWebApp` JS/CSS chunks.
- Translation parity passed: 761 keys in Traditional Chinese and English.
- Existing warnings: the desktop JS chunk exceeds 500 kB; the backend test client reports a Starlette/httpx deprecation warning.
- The native prototype README also retains earlier dependency-audit and New Architecture compatibility caveats. Those are not represented as resolved by this source push or by TypeScript/API checks.

The planned case count missed dynamically generated frontend cases. Actual total was **106**, exceeding the user's 100-case ceiling by six. This was disclosed and no further tests were executed.

## Evidence and limits

The immediately preceding real Webcam check located Pi, HC-SR04 and TFT, displayed the expected GND → Pi Pin 6 photo link, and resumed live tracking after capture. See [Webcam evidence](webcam-capture-2026-10-03.md). Screenshot and raw packet paths in QA notes refer to local-only evidence; they are intentionally not included in Git.

The photo-geometry correction also passed saved-photo replay, but the running backend still predates that correction because the earlier restart was blocked. Uploading source does not restart the application. A manual backend restart and a fresh phone capture remain necessary for live confirmation of that fix. This check did not perform new phone-camera/Safari testing, Pi execution, electrical verification, native iOS/Android builds, or a full test-suite run.

Review used the verification and React best-practices skills; software tests and previous live UI evidence were kept distinct from pending real-device acceptance.
