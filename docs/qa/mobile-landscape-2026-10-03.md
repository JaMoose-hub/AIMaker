# Phone landscape output — 2026-10-03

**Historical attempt, superseded:** unconditional portrait-to-90° rotation below was rejected by the user and removed. These screenshots and tests document that earlier attempt, not the current behavior. Current publication requires sideways phone orientation and decoded landscape camera frames; see [Phone orientation QA](mobile-orientation-2026-10-03.md).

Scope: phone-web publisher pixels, source ownership and canonical photo dimensions. No production phone, camera, Pi, model or cloud operation was performed.

## Implementation

The phone requests a 1920×1080 rear-camera source but does not trust ideal constraints or track metadata to determine orientation. A single decoded source feeds one landscape canvas track before RTC publication. Portrait frames rotate clockwise 90° in full; landscape frames retain their orientation. Other aspect ratios are proportionally letterboxed, never cropped or stretched. Default output is 1920×1080; selected or constraint-fallback 720p is 1280×720. Smaller native sources may be upscaled, not enhanced. UI reports camera input and output separately.

Local phone preview and local JPEG capture use that same normalized stream. Desktop decoding, mobile inference and server capture receive the normalized pixels through the existing transport. Older photos and their geometry remain untouched. Background/cancellation/native-camera ending dispose the decoder/output/source; source rotation alone does not reacquire the camera. The RAF fallback does not repaint a frozen camera timestamp as fresh evidence.

## Isolated browser evidence

`frontend/tools/mobile-capture-preview.mjs`, loopback 18789, exercises the real phone-web hook, publisher normalization and saved-photo UI. Camera input is a browser-native synthetic canvas stream; RTC negotiation, network counters, inference and geometry are test doubles. FPS and GPIO in this fixture are not device measurements or physical evidence.

- Portrait input: 1080×1920; normalized video element and outgoing canvas track: 1920×1080. Four corner colors prove actual clockwise pixel rotation, with a 5-level RGB tolerance for video/JPEG color conversion.
- Canonical phone JPEG: 1920×1080, quality 0.95; uploaded JPEG header, saved image natural size, capture metadata and SVG viewBox agree. Native camera acquisition stays 1 and stop count stays 0 while capturing and navigating to Photo.
- Input rotates to 1920×1080 during publication: output stays 1920×1080, corner colors return to unrotated order, camera acquisition remains 1 and stop count 0. No additional publisher/permission prompt.
- Explicit 720p restart: normalized track, video element, uploaded JPEG and saved photo are 1280×720. One deliberate restart acquires camera 2 and stops camera 1; taking the photo does not restart it.
- Final Stop closes both mocked peers, stops both native streams exactly once and removes the hidden source decoder. No page errors remained.

The browser driver required explicitly scrolling the capture button into view before clicking; unsuccessful off-screen attempts made no capture requests. An initial strict RGB-equality assertion was corrected for ordinary video color conversion. These were QA harness issues, not changes to production capture semantics.

[Landscape source](unified-assistant/phone-landscape-rotated-source.png), [normalized photo](unified-assistant/phone-landscape-photo.png).

## Automated checks and limits

Before the user's new testing cap, the full frontend suite passed 660 tests, i18n parity and production build; the existing >500 kB bundle warning remains. A subsequent UI test verifies native-vs-output labels and absence of invented FPS. Final scoped verification is limited to the 53 tests in mobile_browser, mobile_capture and mobile_web, plus a build; future testing does not automatically run the full suite and stays within 100 tests per round.

Targeted backend RTC ownership, stream capture and no-webcam regressions passed 46 tests using injected fakes and isolated storage; see [backend log](unified-assistant/phone-landscape-backend.log). The scoped frontend plus backend total is 99 tests. No backend implementation was changed. [Scoped frontend log](unified-assistant/phone-landscape-focused.log). Production 8100 was read only and served rebuilt `index-fhk1bSvz.js`; neither production stream nor backend was restarted.

Update requires refreshing the phone web page and restarting preview so the new publisher is loaded. Refresh desktop assets as needed; do not restart Pi. Actual Safari canvas support, sideways framing, encoder adaptation, sustained FPS, battery/heat, network throughput and real GPIO correctness still require device verification. Output size does not mean additional native sensor detail. Complete-frame preview may still letterbox a non-16:9 workspace; the existing vertical splitter changes workspace proportions without cropping contacts.
