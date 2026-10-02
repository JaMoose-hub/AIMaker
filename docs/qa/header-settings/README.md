# Compact header with Settings — 2026-10-01

Controller, language and theme are the existing `RuntimeToolbar` controls in a
native, non-modal Settings disclosure. Model, Pi and execution stay directly
accessible. Normal save-success text is removed; storage failure alerts and
runtime/Pi errors remain visible even with Settings closed. Error states may
add a row so the three stages are never squeezed into narrow columns.

## Verification

- Full `npm test` (all frontend suites, i18n and production build) passed.
- After the mobile placement/error-row refinements, `npm run test:theme`
  passed all 26 tests and the production build passed again. Nine header tests
  cover composition, failure visibility, callbacks, responsive sizing, localized
  disclosure, retained controls, controller guards and listener cleanup.
- Isolated actual-App fixture on port 18776: Chinese/dark and English/light,
  1651/1352 desktop and 390px phone. Header is 58.33px at desktop, compared
  with the previous 93px baseline: about 35px returned to the workspace.
  Escape closes Settings and returns focus to its summary; Enter opens it and
  Tab enters the controller selector. Clicking the text box closes it.
  Switching language/theme preserves the custom unsent draft and confirmed v1.
- Updated real-component fixture on port 18770: 1651px Chinese/dark,
  1440x650 English/light, 390x844 Chinese/dark. Settings, model and execution
  popovers fit in the viewport; no horizontal document overflow was observed.
  The three settings stack vertically on mobile, with 44px controls.
- Synthetic controller, Pi and storage failures at 1440x650 stay visible without
  opening Settings; navigation stays readable. See `errors-1440.png`.
- Screenshots in this folder are isolated fixtures, not the user's project or
  generated-image output. Original image and camera geometry are unchanged.

No production draft was changed, paid AI call sent, camera restarted, Pi test
started or deployment performed. The backend was not restarted. The running
8100 server serves the newly built frontend; refresh the page to load it.
The existing Vite bundle-size advisory remains unrelated to this header change.
