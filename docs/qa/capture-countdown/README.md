# Photo countdown and latest-reply scrolling

Verified on 2026-10-01. Frontend-only change; no backend schema, API, Pi service, or saved project format changes.

## Behavior

- User-triggered photos wait ten full seconds before submitting their existing action. A shared timer covers wiring-step capture, current-view/retake actions, starting photo-based debugging, applicable rechecks, calibration capture, and the legacy cloud photo-check control.
- The countdown is visible in Chinese/English and can be cancelled with its button or Escape. Duplicate clicks cannot shorten it or submit another request. Hiding/leaving the surface, changing its relevant context, losing camera readiness, or unmounting cancels pending photography.
- Photo requests capture fresh data after the delay, not an image cached when the button was clicked. Calibration reads the latest guide coordinates at completion.
- Cancellation does not claim to undo a request already submitted. Existing text-only chat and result-reading actions remain immediate.
- Continuous camera/pose previews and the backend's existing automatic diagnostic/test sampling are unchanged; this countdown gates frontend photo-start controls, not each video frame or internal test sample.
- AI chat follows the newest message's beginning instead of scrolling past it to the status card. Reading older messages preserves position and offers “View latest reply”. Image/card resizing retains the reply anchor until the reader scrolls manually.

## Automated checks

`npm test` completed successfully: **483 passed, 0 failed**, including 8 countdown tests and 5 chat-scroll tests. Locale parity: 761 keys. TypeScript and production Vite build passed. Only the existing large-bundle warning remains.

| Suite | Passed |
| --- | ---: |
| Language | 5 |
| Guides | 189 |
| Headers (includes countdown and scrolling) | 176 |
| Pin calibration | 4 |
| Theme | 26 |
| Wiring AI | 77 |
| Stages | 6 |

## Browser checks

Used the isolated `tools/wiring-ai-preview.mjs` page with `?scenario=countdown&locale=zh-TW` / `locale=en`, synthetic evidence, mock actions, and blocked external/API connections. The live user workspace was not reloaded or modified.

- Desktop 1651×871 and phone 390×844. Chinese and English countdown/cancel controls fit; the phone notice stayed in view with no horizontal overflow.
- Immediately after click: visible “10 seconds”, action counter unchanged. After the full countdown: exactly one `capture` action.
- Cancel, Escape, camera-ready loss, and switching from AI to the guide produced no extra capture action.
- New long reply began 8.7px below the chat top rather than at the following status card. Its beginning remained visible after resizing.
- While reading history, adding another long reply preserved `scrollTop = 776.67` and showed “View latest reply”. Clicking it positioned the latest reply 9px below the chat top.
- No browser console errors observed.

Screenshots: [desktop countdown](countdown-desktop.png), [latest reply](latest-reply-desktop.png), [history retained](reading-history.png), [phone English countdown](countdown-mobile-en.png).

No physical photos, paid model requests, Pi tests, hardware deployment, backend restart, Git commit, or push were performed. The live 8100 server continues serving the rebuilt frontend; refresh the existing page to load it.
