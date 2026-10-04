# Workflow spacing, deployment height, and quieter endpoints

## Changes

- Desktop workflow spacing increased from 6px to `clamp(16px, 2vw, 28px)`; intrinsic button widths and compact touch layout remain unchanged.
- The existing deployment panel and grid fill the available work-pane height. Editors and logs use spare vertical space; the saved editor-height preference is retained as a minimum. Narrow panes can stack and scroll.
- Removed the two outer guidance halos on Pi/module live endpoints and frozen photo endpoints. Centre dots, outlines, selected-pin hit targets, labels, connection colours, and coordinate/trust safeguards remain unchanged.
- React review: no new hooks, effects, state owners, remounts, or inference/deployment requests; decorative SVG nodes only were removed.

## Verification

- `node --test tools/workflow_cluster.test.mjs tools/deploy_columns.test.mjs tools/photo_overlay_style.test.mjs tools/component_header.test.mjs tools/pi_header_guide.test.mjs tools/live_guide_notices.test.mjs`: 41 passed.
- `npm run build`: passed; existing chunk-size advisory only.
- Independent deployment fixture at 1280×720: panel and work pane both ended at y=708; workflow gap was 25.6px; long editor content scrolled internally.
- AI collapse/expand preserved the edited fixture draft. Increasing AI pane width reduced the work pane to about 735px, produced a single deployment column, and enabled vertical work-pane scrolling without document horizontal overflow.
- Real live overlay components with synthetic same-frame packets: 0 outer halos, 2 centre markers, 1 connection. Production-bundle photo fixture: 0 outer halos, 2 centre markers, 1 connection. Console errors were empty in all three fixtures.
- The in-app browser viewport override did not change its actual 1280×720 dimensions. A separate 390px browser rendering was therefore not verified; compact breakpoint rules are covered by source/CSS tests, and available-pane responsiveness was verified by resizing the AI pane.
- Screenshots: `deploy-space-and-nav.png`, `live-endpoints-without-rings.png`, `photo-endpoints-without-rings.png`.

These are software/UI checks using isolated fixtures, not real-camera detection, Pi deployment, GPIO, or electrical acceptance. The user's current tab, photo, and draft were not refreshed or modified.
