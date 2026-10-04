# Photo guidance selection clarification — 2026-10-04

## Scope

- Make the selected component, component pin and Pi physical pin explicit above the photo.
- Separate choosing an inspected wiring step from zoom-only component focus.
- Use the existing `reviewProjectWire` / `resumeProjectGuide` path: retain confirmations, wiring run, checks, original cursor and component-test bindings.
- Explain missing endpoints, unmatched photo plans, divider connections and historical records. History identifies project, revision, run or invalidation changes.
- Preserve exact target matching and trusted endpoint gating. A recognized HC-SR04+ never substitutes for a selected TFT endpoint. Also match connection kind.
- The wiring picker floats without resizing the photo; selection and Escape close it. No capture, inference, AI or hardware action occurs when browsing wires.

## Validation

- `node --test tools/gpio_photo_workspace.test.mjs tools/photo_guidance_state.test.mjs tools/photo_overlay_style.test.mjs`: 29/29, run twice (58 test executions total).
- `npm run build`: TypeScript and Vite pass. Existing desktop chunk-size warning remains.
- `npm run check:i18n`: pass, 761 keys per locale.
- Isolated browser fixture (`gpio-photo-preview.mjs`, `photo-case=missing-tft`), dark and light: page loads, no console errors, missing TFT reason shown, explicit HC VCC/ECHO selection renders a wire, focus preserves selected wire, return restores original TFT step, selecting closes the picker, hidden guide stays hidden. Picker open/closed photo viewport remained 825 × 278 CSS pixels during the measured run.
- The original reported capture `04be6f0cd39c43219be2d7c18aaa9ede` expired before replay. Browser verification instead uses a saved October 3 image/geometry pair with a SHA-256 binding check and an explicit simulated TFT failure. It is UI validation, not fresh recognition or hardware acceptance.
- Screenshots are local ignored diagnostic artifacts under `backend/runs/diagnostics/photo-guidance-20261004/`.

## Boundaries

No live capture, Pi/GPIO/electrical test, cloud photo check, model training, backend restart or Git push. The real user's tab was not refreshed, preserving its in-memory records. Refresh is needed for the new frontend and may require recapturing a photo. Concurrent changes to `floatingGuide.css` and its tests were left untouched.
