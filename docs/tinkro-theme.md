# Tinkro Pro visual identity (Style 23, 2026-09-30)

## Scope and compatibility

The public product name is now **Tinkro**. The three visible pages are
**01 Design & blueprint → 02 Wiring + AI debug → 03 Deploy & run**. Concept and
Blueprint remain views within page 01. Page 02 includes the AI conversation and
manual test, repair and trial tools. Saved `debug` page values restore to page 02.
State ownership, saved drafts, wiring confirmations, calibration transforms,
fixed tests, FIFO execution and Pi deployment behavior remain compatible.

The visual layer is `frontend/src/tinkro.css`, imported after the existing
component and responsive styles. This deliberately preserves the existing React
architecture instead of introducing a new UI library or remounting workflows.

Public labels, page metadata, assistant identity strings and newly generated
program comments use Tinkro. `boardvision.*` localStorage keys, environment
variables, API/schema identifiers, remote directories and `boardvision-pi.service`
remain compatible. Existing drafts, previous AI messages and deployed programs
are not rewritten to change their branding or hashes. Historical text may still
contain the old name. Backend identity strings take effect at the next ordinary
backend restart; this visual update does not require interrupting the camera or Pi.

## Current visual rules

The approved Style 23 document supplies the Pro palette, typography and component
treatment. The reference's sidebar, fourth workflow stage and example wiring
are **not** adopted. The existing three stages, resizable panes and guide/AI tabs
remain the navigation model. Warm paper, dot patterns and thick/asymmetric card
borders have been removed.

| Token role | Dark | Light |
| --- | --- | --- |
| Canvas | `#0a0b10` | `#f3f4f7` |
| Panel / raised | `#12141b` / `#171a22` | `#ffffff` / `#f7f8fb` |
| Border / strong | `#23262f` / `#2f333f` | `#e2e5ec` / `#cfd4de` |
| Text / secondary / muted | `#e8eaf0` / `#a4a9b8` / `#7f869a` | `#10131c` / `#454c5e` / `#646b7e` |
| Link / selection text | `#7faee6` | `#2a5f9e` |
| Success / warning / error text | `#3dd68c` / `#f5a524` / `#ff7b82` | `#0d7148` / `#9a5b00` / `#b3262f` |

Brand navy `#203065`, blue `#417abe` and action teal `#16b9a6` remain. Cards use
8px corners, controls 6px, tags 4px. UI text uses the local Segoe/system/CJK stack;
code, pins and logs use system monospace. No new package or web font is needed.
Normal actions have no glow. The original wordmark retains its image glow; only
AI input surfaces add aurora decoration. Keyboard focus uses a separate 2px outline.
Color transitions are 120ms and respect reduced motion.

Primary actions use dark `#04241f` ink on teal, not white. Confirmation actions
are tonal; other actions remain outlined/text buttons. User/AI messages share
8px conversation surfaces. Candidate projects and code proposals are dashed and
explicitly marked unapplied until existing confirmation handlers apply them.
Theme styling does not rewrite AI replies or manufacture test evidence.

The original PNG and SVG brand assets are unchanged. The compact header uses
the complete supplied `public/brand/tinkro-dark.png` wordmark, not an SVG symbol
with typeset text. Its SHA-256 matches the user-supplied transparent PNG. It has
an accessible Tinkro image label and retains the Vibe Maker Studio subtitle.
The 128 x 40 CSS image window (112 x 35 in the integrated workspace header)
trims transparent canvas space without stretching or editing the source.
Light mode adds a dark backing behind the white wordmark;
dark mode uses the header surface. See [logo verification](qa/brand-logo/README.md).
The integrated desktop header puts brand, three stages, AI model, Pi connection,
execution and Settings on one row with 4px vertical padding. Controller, language
and theme live in a non-modal Settings disclosure; they keep the same mounted
controls and handlers. Escape returns focus to Settings, and outside clicks or
tabbing away close it. Normal save-success text is omitted; storage failures
remain visible alerts outside Settings. Runtime/Pi errors can add a row without
squeezing navigation. At widths up to 1200px the header wraps; up to 960px,
controls retain 44px targets. See [settings header verification](qa/header-settings/README.md)
and the [earlier compact header baseline](qa/compact-workspace-header/README.md).
Camera, photo thumbnails,
circuit drawing, code and output logs retain dark surfaces. Optical HUD / Eye
modes bypass ordinary workspace paint. Electrical colors, pixels, pin
coordinates, mirroring, homographies and detection models remain untouched.

## Theme preference

`ThemeSelect` appears below Language inside Settings in the Maker header;
non-Maker/HUD toolbars retain their existing inline controls. Choices
are **Dark / Light** (`深色 / 淺色`), with dark as the first-use default; there is
no system-following mode. Only `boardvision.theme.v1` is written. No project,
conversation, guide, code, backend schema or other saved preference is migrated.

`public/theme.js` runs synchronously in the document head, before app/CSS loading,
with minimal first-paint colors in `index.html`. It restores the saved preference
or falls back to dark if storage is unavailable/invalid. Storage failures do not
prevent in-session switching. `lib/theme.ts` updates the root `data-theme` and
browser theme-color metadata. `useSyncExternalStore` subscribes only the select,
not App: no keyed subtree, provider remount, reload, business API or polling.
Other tabs' theme changes synchronize without reacting to unrelated storage keys.

`tinkro.css` loads **after guideAi.css and all other component styles**. Its root
palette is separate from the legacy HUD variables; the ordinary workspace maps
the old semantic aliases locally. Do not move it earlier or replace electrical
`--cap-*` / `--wire-*` colors with brand tokens.

## Validation

### Pro dual-theme verification (current)

See [the Pro verification record and screenshots](qa/tinkro-pro/README.md).
The older sections below document earlier changes, not current Pro layout sizes
or current test counts. No Pi deployment/test or paid AI generation is part of
this visual verification. The frontend build is sufficient; no backend restart
is required for these presentation-only changes.

### Integrated workspace header (2026-09-30)

`WorkspaceHeader` is a presentation-only wrapper: Tinkro and the three workflow
entries share the top row; model, Pi/queue, controller, language and saved-draft
status share the settings strip below. Existing callbacks and request ownership
stay in App / the original controls. The non-maker header and display-mode
exclusion remain intact. Storage failures stay visible as alerts; connection and
runtime errors wrap instead of covering the workspace.

Isolated browser verification uses the same header, model menu, Pi connection
control and runtime toolbar as production. Six viewport widths (1352, 1651,
1024, 768, 390 and 320) were checked in Chinese and English, plus desktop/mobile
error states. All 14 scenarios passed: navigation, menu bounds, model selection,
Escape focus restoration, outside dismissal, controller/language callbacks and
no document horizontal overflow. Normal 1352/1651 desktop header height is
106px. Preview console errors were zero; mock wiring IDs were corrected to be
unique per component. The preview has no backend proxy and rejects hardware/cloud
actions. It does not verify production camera, GPIO alignment or Pi behavior.

Repeat the isolated header verification with:

```powershell
cd frontend
node tools/workspace-header-preview.qa.mjs
```

The output report and screenshots are under
`frontend/tools/workspace-header-preview-artifacts/`.

### Project generation feedback (2026-09-30)

The concept image area now uses a blue/teal orbit and animated dots while an
actual App-owned AI job is active. `DesignStudio` receives `makerAI.phase`
and derives its presentation from `state.aiJobId`: inference and image generation
have distinct labels. Login/demo pending state alone does not animate this area.
There are no additional requests, timers, polling, progress percentages or
generated-image substitutes. The empty first-project view is covered as well.

Existing images stay visible with a compact status above them during revisions.
Completion/failure clears the job and removes the animation; persisted image
errors and confirmation/draft-consent guards are preserved. Reduced-motion
preferences disable both animations while retaining the status text. The old
redundant status at the bottom of the concept pane has been consolidated here.

Validation: all nine studio regression cases and the full `npm test` pipeline
(including production build) pass. The isolated browser runner
`frontend/tools/project-generation-preview.qa.mjs` passed 19 scenarios:
1651/1352/390px, both locales, first project/missing image/existing image,
phase changes, navigation away/back, success/failure/retry/stop, plus 320px
reduced motion. No browser errors or horizontal overflow; only isolated preview
assets were requested. Reports/screenshots are in
`frontend/tools/project-generation-preview-artifacts/`. These tests use synthetic
job phases, not actual cloud generation or camera/Pi/hardware validation.

### Compact assistant tools (2026-09-30)

The parts disclosure now sits beside Load demo / Clear conversation as a compact
`Parts · count` control. Its bounded, scrollable floating panel retains the
original catalog checkboxes, busy guards and functional state updates. Escape
and the close button return focus to the summary; outside clicks or keyboard
focus leaving the panel dismiss it. Selection does not start model/hardware work
or replace conversation, approved project, candidate, code or unsent input.

The fixed composer hint and bottom parts row no longer consume vertical space.
The confirmation hint remains visible inside the parts panel and accessible via
the textarea's `aria-describedby`. Opening the floating panel does not reduce
conversation height. In the same isolated 1651×871 Chinese layout, normal chat
height increased from 366.45px before the change to 425.55px (about 59px).

Validation: three new regression cases (13 studio tests total) and the complete
`npm test` / production build pass. The isolated runner below passed 16 scenarios:
1651/1352/390/320px, Chinese/English, idle/busy. Checks cover layout bounds,
keyboard/mouse dismissal, live checkbox counts, busy/empty-selection send guards
and navigation preserving unsent text and conversation. No browser errors or
horizontal overflow; only preview assets were requested. Screenshots were also
visually inspected at desktop and 320px English sizes.

```powershell
cd frontend
node tools/maker-assistant-tools-preview.qa.mjs
```

Reports/screenshots are under
`frontend/tools/maker-assistant-tools-preview-artifacts/`. This preview uses
synthetic state, not production draft storage, cloud calls, camera or Pi actions.
Read-only HTTP checks confirm the running 8100 service serves the rebuilt JS/CSS
with the new controls; the backend and Pi were not restarted.

The records below describe the earlier visual rebrand and four-/five-page
layouts, before testing/debugging was consolidated into page 02. Their test
counts and viewport results are historical, not verification of the current
three-page navigation. Integration validation is tracked separately in
[Wiring and AI integration](wiring-ai-integration.md#本次驗證紀錄).

- `npm test`: i18n parity, guides, headers, Pi execution, debug, responsive,
  calibration, theme tests and production build.
- Eleven theme regression cases cover warm paper surfaces, visible original-blue roles, the studio tool tray, public branding, local asset metadata,
  contrast, import order, HUD isolation, dark code surfaces, guide shadow reset,
  compatibility identifiers and the offline preview network boundary.
- Eight pre-existing Pi execution layout assertions referred to an older
  deployment page. They now assert the existing code-left / output-right UI;
  offline, queue, blank-draft and unresolved-wiring guards remain asserted.
- Focused backend suite: 201 passing tests for maker, Pi deployment, component
  tests, diagnosis and visual-debug session code. A separate 111-test alignment
  baseline passed before the presentation changes. No physical retest performed.
- Isolated browser checks: all five stages at 1440px before the four-stage merge; no document horizontal
  overflow in five stages at 390px (Chinese), 768px and 320px (English).
  Debug manual-tool switching, guide steps and deployed-code surface inspected.
- Live UI reloaded without stopping the backend/Pi. Saved 11/11 wiring progress
  and historical result labels persisted; the camera settings dialog was opened
  for visual inspection without changing camera or resolution.
- Maker-studio follow-up: 288 frontend tests and production build passed. Live
  five-stage navigation at 390px (before the four-stage merge) had no document horizontal overflow; desktop
  design, debugging and deployment surfaces were visually checked at the normal
  1651px viewport. Temporary viewport override was reset. No hardware test,
  deployment or cloud analysis was started during these visual checks.

The browser preview is a developer tool, not hardware evidence:

```powershell
cd frontend
npm run preview:theme
```

Visit `http://127.0.0.1:18770/`. It renders real workflow components with synthetic
state on a separate origin. It has no backend proxy; CSP blocks connections;
hardware/cloud hooks and fetch/WebSocket reject attempts. No production draft,
camera, Pi or cloud action is executed. Stop with Ctrl+C when finished.

The existing Vite bundle-size warning and Starlette test-client deprecation
warning are unrelated to this visual rebrand. Physical GPIO accuracy, real Pi
tests, cloud output quality and optical HUD field performance need their own
separate acceptance checks; software/style checks do not certify them.
