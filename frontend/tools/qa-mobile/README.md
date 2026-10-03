# Desktop mobile companion QA — 2026-10-02

`node tools/mobile-preview.mjs` serves the actual desktop components with an isolated synthetic transport on `127.0.0.1:18788`. This fixture does not call production APIs, acquire a camera, run AI, or contact the Pi. Its canvas video, FPS values, GPIO coordinates, and assistant reply are synthetic UI inputs, not hardware evidence.

## Automated checks

- Full-suite baseline `npm test`: **558 passed**, including localization checks, existing frontend suites, TypeScript, and Vite production build.
- After the final inherited-media indicator, context-epoch publication, and retry snapshot update, focused assistant/mobile/photo suites: **45 passed**, followed by localization, TypeScript, and Vite build checks.
- Regression coverage includes workspace stage/code/round/model publication, draft stability, exact frozen-image identity, receive-only RTC cleanup, late SDP and view responses, local preview expiry, actual CUDA diagnostic semantics, and attachment capture IDs.
- The QR library is a lazy chunk. The existing large-chunk warning remains.
- Inherited-media regression covers both languages, current context epoch and current workspace round, replaced photos, and a record whose round has not caught up with the new capture. Clearing chat republishes its new context epoch; ordinary typing still does not republish.
- New text sends persist the exact referenced asset/capture IDs (or explicit absence) with their existing retry ID. A failed send keeps that photo in the composer and request after a newer capture or reload. Legacy outboxes without a reference snapshot retain their original request shape and fingerprint.

## Browser checks (Chrome through computer-use)

- Pairing entry shows QR code, code, and editable LAN address.
- Receive-only viewer displays synthetic 1920×1080 video; decoded preview FPS and recognition FPS have separate labels.
- The fixture repeats the same preview sequence; after its 1.5-second lease expires, the desktop shows Finding despite repeated Locked snapshots.
- Frozen photo uses the existing passive GPIO overlay and exact natural image dimensions. Next/Previous, 1:1, and Fit work. Wire selection issues PUT `/view` for the same capture.
- Check this wire posts the photo asset, capture, context, and wire IDs into the original conversation. Its attachment can reopen the photo; the existing chat draft remains unchanged.
- Stage/code changes publish a new workspace snapshot and show the update hint.
- Disconnect removes the live viewer and disables photo AI actions. Existing photo review and wire navigation remain available locally.
- Photo panel verified at desktop and narrow viewport settings (1280×800 and 390×844 overrides). Narrow controls wrap and remain reachable by scrolling.

Artifacts: `desktop-photo.jpg`, `phone-photo-narrow.jpg`, `shared-chat.jpg`, and compact `requests.json`.

## Not verified here

Physical iPhone pairing, native camera handoff, real WebRTC relay, Wi-Fi throughput, real preview FPS, model accuracy, and physical GPIO correctness. Those require the native phone build and backend integration checks. Closing this desktop panel only releases its viewer; it does not stop the phone publisher or alter the Webcam/Photo PoC capture lifecycle.
