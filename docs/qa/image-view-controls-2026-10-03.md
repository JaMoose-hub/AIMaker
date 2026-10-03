# Image views and camera sources — 2026-10-03

## Scope and concurrent work

The side conversation owns view/source UI grouping only. The active conversation
`BoardVision 程式修改` owns the shared phone/Webcam source, tracking and capture
pipeline. The user authorized notifying that conversation of the division.

- Added `ImageViewControls.tsx` / `.css`: Live view, Wiring diagram, Wiring photo.
- `App.tsx` keeps the existing guide, photo and `useLiveCamera` state/handlers.
  Returning to live view does not select/restart a source.
- `MobileCompanion.tsx` uses the same controls portal for an independent source
  select. The portal host stays mounted but hidden in reference views.
- An unpaired phone opens the existing pairing panel, without selecting phone.
- Calibration and pending switches disable all views; an active capture keeps
  the existing photo-view restriction while allowing diagram inspection.
- Wiring photo shows its capture origin/time, independent of the live source.
  Historical-record warnings and exact step-to-wire matching remain intact.

## Validation

- 13 targeted Node tests passed (`image_view_controls`, `gpio_photo_workspace`).
- TypeScript `tsc --noEmit` passed before the final one-line diagram-evidence
  preservation adjustment.
- Browser: isolated, in-memory component bundle on port 18806. No production
  backend proxies, camera devices, Pi, AI or pairing mutations.
- Dark desktop: inspected screenshot and fixed theme specificity so the active
  view has a clear blue selected state.
- Phone source → diagram → photo → live: source remains phone and simulated
  source switch count remains 1; guide step stays unchanged.
- 390 × 844 light theme: no horizontal page overflow; source select and views fit.
- Unpaired phone selection: pairing entry appears, source stays Webcam and
  simulated source switch count stays 0.
- No browser errors reported. Fewer than 100 test/check executions, including
  the initial visual check that exposed the theme override.

Screenshots: `image-view-controls-dark.png`,
`image-view-controls-light-narrow.png`.

## Not claimed

This is component interaction and layout validation, not full-App browser E2E
or live phone/Webcam recognition verification. No shared `dist` build, backend
restart, real camera switch or hardware test was performed in the side chat.
The parent conversation was notified to preserve these changes in its final
integrated build and to use the new view/source selectors in browser checks.
