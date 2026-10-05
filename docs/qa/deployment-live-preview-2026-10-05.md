# Stage 03 actual-camera preview

Implemented a compact actual-image monitor above the execution output, with
the editor on the left and the shared AI conversation on the far right.
The existing deployment splitter and draft persistence remain in use.

## Source and safety

- App retains one VideoView and its existing tracking/source owner across stages.
- VideoView portals only a presentation component into stage 03. There is no
  second tracking hook, getUserMedia call, camera acquisition or Pi status poll.
- The shared Webcam/phone source selector moves to the preview header. The
  picture has no recognition/wiring overlays and uses contain, not cropping.
- Source changes, unavailable phone frames and backend loss hide stale images.
- Native fullscreen displays the same panel. The source menu portals into
  the fullscreen element, closes on fullscreen changes and cleans up listeners.
- Output metadata is expandable; runtime/network errors, stop-owner guards,
  queue rules, voltage/spec blockers and diagnostic access remain available.
- No Pi connection, deployment, stop, backend restart, recapture or real
  camera-source mutation was performed during this verification.

## Checks

- 53 distinct targeted tests passed across deployment_preview (4),
  pi_execution (16), deploy_columns (4), deploy_split (7), maker_stage (14),
  image_view_controls (8).
- The initial three preview fixture imports failed because its loader only
  rewrote double-quoted imports. After supporting both quote styles, the
  four preview tests passed. This was a test-loader issue, not a production
  compilation error.
- `npm run build`: TypeScript and production build passed; Vite retains its
  existing large-chunk warning.
- `npm run check:i18n`: 761 matching keys; accessibility/copy check passed.
- Current localhost root and new index asset both returned HTTP 200.

## Browser evidence

1. Isolated production-bundle fixture: stage 03 preview and one source selector;
   synthetic Webcam/phone switching; edited draft survives 03 → 02 → 03;
   fullscreen enter/exit and source menu inside fullscreen; no console errors.
2. At 1280 × 720 the editor and output cards end at about y=689; the actual
   image card is about 235px tall. There is no document horizontal overflow.
3. At the observed 672 × 871 viewport, the work area stacks and scrolls without
   horizontal overflow. The normal narrow-screen work/AI tabs remain intact.
4. The isolated deployment preview was also supplied with read-only JPEGs from
   the already running localhost FrameBus (phone source, 1920 × 1080). The
   image updates and the full hardware composition fits the monitor. The
   fixture's code, Pi state and AI text are simulated, not actual execution.

Screenshot: `screenshots/deployment-live-preview-20261005.png`.
This establishes software/presentation behavior, not electrical correctness,
functional hardware acceptance, phone reconnect reliability or deployment success.

Reproduction: `node --test tools/deployment_preview.test.mjs tools/pi_execution.test.mjs tools/deploy_columns.test.mjs tools/deploy_split.test.mjs tools/maker_stage.test.mjs tools/image_view_controls.test.mjs` from frontend.
