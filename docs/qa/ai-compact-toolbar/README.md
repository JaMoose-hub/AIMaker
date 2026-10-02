# Compact AI collaboration toolbar

Verified 2026-10-01. Presentation-only change: the existing intent picker is passed into `AiDebugPanel`'s header alongside Stop, Check records and Manual test tools. Existing handlers, session ownership, countdown, conversation, camera layout and Pi operations are unchanged. Manual tools retain the intent picker; returning to chat keeps the mounted composer and its draft.

## Measurements

Isolated browser fixture, 1651×871 viewport and 700px right pane (matching the reported area):

- Before: mode picker + separate action header + spacing consumed 94px before the chat.
- After: one 28px toolbar plus 4px spacing, consuming 32px.
- Chat height increased from 334.33px to 396.33px: **62px recovered**. Pane and camera geometry did not change.
- Chinese and English both fit on one desktop row.
- At 390×844, English/light mode wraps into two rows, with 44px-high controls. The toolbar's client/scroll widths both measured 318px: no horizontal clipping.

## Verification

- Actual browser interactions: switch focus; open/close check records; open/close manual tools; verify the unsent draft survives all transitions. No mock action was submitted by these view changes.
- Keyboard Tab focus retained a visible solid outline; returning from tools restored focus to its trigger.
- Browser console: no errors observed.
- `npm test`: **485 passed, 0 failed**; locale parity 761 keys; TypeScript and production build passed. Existing large-bundle warning only.
- Production HTTP 8100 returned 200 and referenced the new `index-BAXPVu6f.js` / `index-DeaN-GRc.css` assets. Refresh the existing browser page to load them; no backend restart is needed.

Screenshots: [before](before.png), [desktop after](after-desktop.png), [phone English/light](mobile-en-light.png).

Browser verification used synthetic photos and mock APIs at loopback 18774. No paid AI request, physical capture, hardware test, Pi deployment, live project reset, Git commit or push was performed. The temporary tab and preview server were closed and the viewport override reset.
