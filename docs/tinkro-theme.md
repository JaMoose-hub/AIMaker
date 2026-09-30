# Tinkro visual identity (2026-09-29)

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

## Visual rules

| Role | Color / treatment |
| --- | --- |
| Brand navy | `#203065`: integrated brand/workflow bar, links and key headings; workspace surfaces remain warm paper |
| Brand blue | `#417ABE`: principal workspace top borders, eyebrow markers, step rings and selection borders |
| Brand teal | `#16B9A6`: primary actions, current-step number and progress |
| Studio ink | `#253730`: neutral graphite detail and shadow tint |
| Workspace | `#DEDCD5` warm-gray dotted desk, `#EEEAE1` paper cards, `#E4E1D7` secondary surfaces |
| Links | `#203065`, original navy for small-text contrast |
| Secondary text | `#4E5F59`; muted text `#55605B` |
| Semantic status | Dark green / amber / red; never substitute brand color for electrical wire colors |
| Shapes | 8px controls; notebook-like asymmetric corners on principal cards, circular step numbers |

The maker-studio revision replaces the blue social-feed appearance with warm
paper, a compact navy tool tray, a subtle dot grid and drawing-paper frame.
The original `#203065` and `#417ABE` remain visibly present alongside teal;
blue is concentrated in navigation and accents rather than large page surfaces.
Conversation messages resemble margin-marked notes rather than blue chat bubbles.
Patterns are static CSS backgrounds outside live camera / circuit surfaces;
they never cover image pixels or add animation, content or interaction layers.

Primary buttons use dark ink on teal, **not** white on teal. Theme tests enforce
at least 4.5:1 contrast for the declared normal-text pairs; this is not a claim
of a complete accessibility audit. Existing system/CJK font stacks are retained;
no network font dependency is introduced. Common headings, focus outlines,
chat bubbles, disclosures, inputs, cards and warnings share semantic tokens.

The supplied transparent logo is preserved byte-for-byte in
`frontend/public/brand/tinkro-dark.png`; CSS crops excess transparent canvas at
display time. The favicon is a separate simple two-arc brand symbol. Camera,
circuit drawing, code and logs retain dark surfaces. Optical HUD / Eye display
modes explicitly bypass the light theme. No camera pixels, pin coordinates,
mirroring, homographies or detection models are modified.

## Validation

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
