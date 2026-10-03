# Compact translucent wiring dock

User request: the floating guide obscured too much of the camera and did not look translucent.

## Changes

- Replaced the fixed 760px-wide, 280/340px-high panel with a content-sized dock (620px maximum width).
- Removed duplicate workspace title/progress; kept module selection, manual progress and restart in one header.
- Transparent nested surfaces; panel tint 56%, backdrop blur 3px rather than 80% and 16px.
- Condensed wire endpoints; one mounted test card contains both instructions and hardware controls. Logs, troubleshooting and wire review remain in the closed test-details disclosure.
- Live Stop, sampling, TFT code/color confirmation and abnormal-screen choices remain visible. Existing test keys, permissions, stale-result rules, stop consent, electrical warnings and progress actions are reused.
- Escape closes the floating guide and returns focus to its existing toggle; camera and test components stay mounted.

## Verification

- 77 automated test executions passed: 34 guide/layout/summary tests, then 37 existing component-test tests plus 6 dock regressions. No full suite was run; total stayed below the user's 100-test limit.
- Two production builds passed; existing >500 kB chunk warning remains.
- Separate offline fixture at port 18806, using a saved photo replay; no physical camera, Pi, cloud inference or real test request.
- Desktop active wiring: 620 x 175.1px, no internal scroll. Idle/stale and HC sampling: 620 x 183px, no internal scroll. Previous review panel was 760 x 340px (about 56% less area for the ordinary test state).
- TFT confirmation expands only for its required controls (369px high); code/three-color selection enables confirmation, opening/closing diagnostics retains choices. No result was submitted.
- Dark/light screenshots, 1413/1651px desktop widths and 390px narrow layout inspected. No horizontal overflow or fixture page errors.
- Escape/toggle preserves camera/test DOM identity, camera bounds, saved guide state and focus return.
- Production home at port 8100 returned HTTP 200 and exactly matched the current built index. No backend restart or user-tab reload performed.

Screenshots: `backend/runs/diagnostics/photo-links-20261003/dock-stale-final.png`, `dock-active-final.png`, `dock-active-narrow.png`, `dock-near-light.png`, `dock-tft-final.png`.

Skills applied: React Best Practices (derive presentation, reuse state/handlers), agent-browser and agent-browser-verify (isolated visual and interaction verification).

Scope: software/UI verification only, not GPIO continuity, voltage or physical module acceptance.
