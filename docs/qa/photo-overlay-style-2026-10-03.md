# Frozen-photo / live overlay styling

Presentation-only change: photo recognition now uses the live `board-outline`, `pin-dot`, `guide-connection-line`, arrow and target-ring styles. Live and photo renderers share `recognitionStyle.ts` for component pin and connection colors. Board pin colors reuse the existing capability mapping. Live colors, inference, localization, electrical verdicts and selected-component scope are unchanged.

Photo-only differences remain intentional: static target rings (no live pulse); raw model outlines stay pink/dashed; uncertain geometry stays amber/dashed. A direct line still requires both independently accepted photo endpoints, and divider wiring never receives a direct decorative link. Rendering leaves original image and pose coordinates intact; the line has the live-style display-only endpoint clearance.

## Verification

- 61 distinct targeted Node tests passed; 68 executions including a seven-test rerun, below the user's 100-test cap.
- `npm run build` passed. Existing large-chunk warning remains.
- React review: shared pure palette, module-level board pin map, unique per-instance SVG marker IDs, no new subscriptions/effects or runtime dependency.
- Isolated agent-browser fixture replayed the saved 1920 × 1080 photograph with hash verification. Mock APIs only; no physical camera, Pi, cloud inference or hardware tests. The fixture's Webcam label is synthetic, not a claim about the original phone capture.
- Dark 1651 × 1000: photo GND wire RGB(180,190,205), signal wire RGB(102,223,255), outline RGB(73,214,255), 2.4 px outline and shared glow; wire width 1.5 px and dash 10/7.
- Light 1413 × 871: TFT GND highlight, fit and 1:1 zoom checked. Source viewBox remains `0 0 1920 1080`; target-ring animation is `none`; no app errors or error overlay.
- Live replay showed the same cyan recognition boxes. Its manual guide remained pose-gated, so live/photo line parity was verified through the shared stylesheet/palette and live-renderer tests, not by claiming an active live guide line in that fixture.
- Isolated browser/server closed after verification; user tab and production backend not restarted.

Screenshots retained in `backend/runs/diagnostics/photo-links-20261003/`: `style-photo-signal.png`, `style-photo-tft-light.png`, `style-photo-zoom.png`.
