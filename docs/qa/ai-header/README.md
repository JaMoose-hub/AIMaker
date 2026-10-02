# Compact wiring AI header — 2026-10-01

- Removed the visible repeated AI heading and model/context line from the shared
  AI panel. Its localized accessible region name remains via `aria-label`.
- Kept stop-check/session, inspection records and manual-tool actions, including
  their original callbacks, busy state, focus handling and ARIA associations.
- Removed obsolete header-title/model styling and the reserved title column.
  The action row wraps as needed; the docked bottom gap is now 4px.
- No business API, session, conversation, wiring progress or Pi logic changed.

## Validation

- `npm run test:headers`, `npm run test:wiring-ai`, `npm run test:theme` passed.
  Added actual-render coverage for wiring/debug and inactive/active sessions:
  no visible title/model, accessible name retained, all relevant actions kept.
- `npm run build` passed (existing bundle-size advisory only).
- Isolated real-component browser fixture at localhost:18774: Chinese/dark at
  1651 x 871 and English/light at 390 x 844. No horizontal overflow or console
  warnings/errors. All three English actions fit inside the mobile viewport.
- Opened inspection records and manual tools, then returned to conversation;
  the unsent draft remained unchanged. No stop, test, capture or AI action run.
- Screenshots: [desktop](dark-zh.png), [AI panel](dark-panel.png),
  [English mobile](light-en-mobile.png). Synthetic fixture only, no production
  storage/hardware access. The user tab was not reloaded or modified.
