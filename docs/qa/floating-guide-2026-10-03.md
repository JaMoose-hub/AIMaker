# Floating wiring guide and stable diagram viewport

## Scope

The standard unified wiring workspace now places its existing guide in a translucent lower-left overlay. A left-bottom toggle opens/closes it without changing the live, schematic, or frozen-photo viewport bounds. Existing progress, camera, photo and AI state remain mounted. Display-only and standalone layouts retain their previous behavior. Escape/close return focus to the toggle only when focus was inside the guide.

## Jitter diagnosis and fix

The original diagram measured its height with rounded `offsetHeight`, then used the measured width/height as the stage minimum. Fractional pixel overflow could trigger a scrollbar, changing the next measurement and repeatedly toggling scrollbars.

In an isolated 1651 × 871 browser, the original build alternated between client sizes **1213 × 629** and **1198 × 614** during a 40-frame diagnostic sample. The corrected build remained **1183 × 629** (scroll size also 1183 × 629) at fit-to-view. A zoomed view remained **1183 × 614** with the expected scrollable content of **1242 × 766**. Returning to fit restored the initial stable dimensions.

The viewport now measures fractional height before paint, uses CSS percentage stage minimums, and keeps stable scrollbar gutters in the step diagram. Geometry, wiring definitions and recognition data are unchanged.

## Verification

- `npm run build`: passed; existing large-chunk warning remains.
- 42 unique Node test cases passed across floating guide, circuit zoom, step diagram, split geometry and image-view controls. **59 test executions including reruns**, below the user's 100-run ceiling.
- One existing test referenced the retired `WiringViewToggle` in App. It now exercises the actual `ImageViewControls` callback plus `changeImageView`, verifying source, cursor, conversation, confirmation and test-signature preservation.
- Live view and frozen-photo view retained exact DOM identity and bounds across guide open/close: x12, y113.390625, width1215, height745.609375.
- Diagram open/close and zoom/fit checks showed no recurring dimension oscillation or runtime errors.
- Dark 1651 × 871, light 1413 × 871, and narrow 700 × 850 layouts visually checked. Desktop active-step body fits without scrolling. Narrow layout permits contained scrolling when needed; no horizontal page overflow. Final narrow panel starts at y406, below the source controls ending at y399.
- Escape hides the panel and focuses the persistent toggle with `aria-expanded=false`.
- Final built CSS was loaded into the isolated browser for the final narrow layout check.

Screenshots are in `backend/runs/diagnostics/photo-links-20261003/`: `float-dark-live.png`, `float-light-live.png`, `float-diagram-stable.png`, and `float-narrow-final.png`.

The browser used the existing isolated GPIO replay fixture on port 18806 with frozen image/detection data. The fixture and browser were closed afterward. No real GPIO test, deployment, cloud request, model retraining, backend restart, or user-tab reload was performed. These are software/UI checks, not hardware or real-scene acceptance.
