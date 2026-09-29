# Tinkro visual identity (2026-09-29)

## Scope and compatibility

The public product name is now **Tinkro**. The five stages, state ownership,
page split ratios, saved drafts, wiring confirmations, calibration transforms,
fixed tests, FIFO execution and Pi deployment behavior are unchanged.

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
| Brand navy | `#203065`: compact logo plaque, five-stage tool tray, links and key headings; no full-width header fill |
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
- Isolated browser checks: all five stages at 1440px; no document horizontal
  overflow in five stages at 390px (Chinese), 768px and 320px (English).
  Debug manual-tool switching, guide steps and deployed-code surface inspected.
- Live UI reloaded without stopping the backend/Pi. Saved 11/11 wiring progress
  and historical result labels persisted; the camera settings dialog was opened
  for visual inspection without changing camera or resolution.
- Maker-studio follow-up: 288 frontend tests and production build passed. Live
  five-stage navigation at 390px had no document horizontal overflow; desktop
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
