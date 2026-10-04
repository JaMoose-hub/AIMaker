# Photo and guide synchronization — 2026-10-04 follow-up

## Observed cause

One fresh Webcam capture on the running local application reproduced the confusion. HC-SR04+ had validated endpoints and could render VCC wiring; TFT had a detected body but `invalid_model_geometry`, no validated outline and no pins. Component IDs were not swapped. The photo's model-name buttons only zoomed the image, while completed-module guide tabs opened the test card. These independent actions made photo selection and wiring guidance appear inconsistent.

Capture: `7b7d1ea4706f4c199ffbec7e9937dcec`, 1920 × 1080, frame 16770. TFT body confidence was approximately 0.728; body detection does not establish pin identity.

## Change

- Replace the compact photo's zoom-only component buttons with explicit component and pin selectors using the shared guide inspection cursor.
- In photo mode, guide module tabs inspect that module's wiring, including already-confirmed modules, rather than jumping to the test card.
- Reveal the guide when a photo wire is chosen. Preserve the original cursor, manual confirmations and test bindings; returning restores the original step.
- Clear obsolete inspection state on normal, non-photo module selection.
- Label detected body-only objects as “已辨識 · 腳位未定位”. Their diagnostic boxes never create endpoints or wiring lines.
- Keep the endpoint zoom control explicitly named and grouped with the other zoom tools.

This supersedes the earlier popup-picker and hidden-guide behavior described in `photo-guidance-selection-20261004.md`.

## Validation in this follow-up

- First targeted Node run: 51/51 executions passed (`photo_guidance_state`, `photo_overlay_style`, `gpio_photo_workspace`, `project_guide`).
- Final targeted Node run: 21/21 executions passed (`photo_guidance_state`, `photo_overlay_style`). Total: 72 test executions, including repeated cases; below the user's 100-test limit.
- Final `npm run build`: TypeScript and Vite passed; existing bundle-size warning remains. An earlier build encountered a concurrently changing, unrelated `WiringReviewCard` interface; that file was not modified for this fix.
- `git diff --check`: passed.
- Isolated browser replay used the real capture above, with its image hash checked, without rerunning inference. HC ECHO selected in the photo matched guide ECHO → Pin 12 and rendered one line. The guide's next step changed both views to VCC → Pin 1.
- Selecting TFT from the lower guide or photo selected TFT's own pins. SCL matched Pin 23 in both views; its unvalidated endpoint correctly produced no line. Switching back to HC GND matched Pin 6, not TFT GND's Pin 20.
- Manual progress stayed 11/11 throughout inspection. “返回原步驟” restored the original test-review card. Browser error log was empty.

Proof screenshots: `photo-guide-sync-hc.png` and `photo-guide-sync-tft.png` (local ignored artifacts).

## Boundaries

This verifies UI state synchronization and rendering with one real Webcam capture plus isolated replay. It does not establish fresh phone recognition, TFT pin localization, electrical continuity, Pi execution or functional test success. No cloud AI call, model change, backend restart or Git push was performed. The real user tab was not refreshed, preserving its in-memory photo. Refresh and recapture are needed to use the newly built frontend.
