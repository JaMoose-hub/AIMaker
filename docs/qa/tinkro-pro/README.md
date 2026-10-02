# Tinkro Pro — verification record

Date: 2026-09-30. Base revision: `88cc484ccd5b5e2f27c2ac4fe7070e66d749ff41`.
Presentation-only change; no Git commit or push performed.

## Scope and safety

Screenshots show actual React components on isolated loopback fixture origins
(`18770` / `18774`), with synthetic project/AI/camera data. They are not generated
product designs, camera accuracy evidence, physical wiring verification, actual
Pi output or cloud generation results. Fixtures deny fetch/WebSocket and replace
hardware hooks; no hardware test/deployment or paid AI request was started.
The production browser was not reloaded or its stored project modified.

The running `8100` server was checked read-only: `/theme.js` returned HTTP 200
as JavaScript, and `/` referenced the final built app bundle and early theme
bootstrap. A backend restart is unnecessary for this frontend-only release.

## Automated regression

| Check | Result |
| --- | --- |
| `npm test` | **455 passed**, 0 failed |
| Locale parity | 757 keys, Chinese/English parity |
| Theme/preference/presentation group | 19 passed, included in total |
| TypeScript + production Vite build | Passed; existing large-chunk warning remains |
| `git diff --check` | Passed |
| Backend `.venv/Scripts/python.exe -m pytest tests -q` | **1992 passed, 4 failed, 2 skipped** |

Backend failure identities exactly match the known pre-theme baseline; no backend
file was changed:

- `test_backend_core.py::test_config_loads_yaml_relative_to_backend_dir`:
  local MX Brio configuration vs the test's C920 expectation.
- `test_backend_core.py::test_default_config_enables_both_component_models`:
  local TFT lit/wired model vs the old model filename expectation.
- `test_pin_regions.py::test_component_reference_refresh_requires_material_hand_and_three_frames[hw-123]`.
- `test_project_images.py::test_prompt_disambiguates_imu_from_pir_without_adding_a_module`.

The existing Starlette test-client deprecation warning remains. These four
unrelated failures were not hidden, marked passing or changed as part of theming.

Theme tests execute the early bootstrap and compiled preference module in a VM:
default dark, saved light, invalid value, denied storage, session-only switching,
cross-tab filtering, listener cleanup and only-theme-key writes. They also check
early first-paint CSS, accessible translated controls, exact palette/radii,
composited text/status/tonal/diff contrast >= 4.5:1, stylesheet order, preserved
electrical tokens and optical isolation. Theme code has no business API access.

## Browser matrix

Browser interactions used the Codex in-app browser, not the live product origin.
Every viewport was checked against actual `innerWidth` (not just requested size).

| Matrix | Dimensions | Languages / themes | Result |
| --- | --- | --- | --- |
| Design, guide, deployment | 1651×871, 1440×900, 1352×871, 390×844, 1352×600 | zh-TW + en; dark + light | **60/60**, no horizontal overflow or offscreen controls |
| Real wiring workspace: guide + AI tabs | Same five sizes | zh-TW + en; dark + light | **40/40**, no horizontal overflow, offscreen controls or normal UI text contrast findings |

Additional checks: blueprint, product dialog, expanded diagram, model menu,
execution menu/stop confirmation, parts menu, camera tools and direction
calibration, empty/initial generation, image phase, failed image, pending concept,
runtime/storage errors and code-repair proposal. Model/execution/parts menus were
also checked at 390px in both themes. Camera menu Escape restored focus to its
trigger with a visible 2px outline. No repair/stop/deploy confirmation was submitted.

The DOM contrast audit used final colors after the 120ms transition, compositing
ancestor backgrounds. Normal UI text passed >=4.5:1. Disabled controls and
preserved electrical drawing/camera content are not accessibility-certification
claims. Token tests additionally verify common status and diff pairs.

An initial fixture-only Blueprint error revealed missing structural-part purpose
text. The synthetic data was corrected and Blueprint/dialog checks rerun. No
new browser exceptions appeared after that correction. Early transition-color
samples were rerun after paint settled; final checks have no contrast findings.

## Theme-switch invariants

Before/after DOM comparisons passed for:

- Unsent design text, conversation, version labels and resized split width.
- Unsent deployment code and editor content.
- Active generation status and unconfirmed preview/version.
- Current wiring step, manual progress and side-pane width.
- AI history, unsent AI text and selected wiring.
- Entire 2D diagram SVG markup plus geometry (no wire or contact changes).
- Actual `VideoView` image URL, image/overlay bounds, transforms and SVG markup.
- Theme preference surviving a browser reload.

The selector is the only theme subscriber; App is not keyed/remounted. Unit tests
and isolated fetch/WebSocket guards verify no theme-driven business request path.
This is not a claim that live camera, cloud or Pi transport was exercised.

## Saved screenshots

- [Dark design, 1651](design-dark-1651.jpg) / [Light design, 1651](design-light-1651.jpg)
- [Dark design, 390](design-dark-390.jpg) / [Light design, 390](design-light-390.jpg)
- [Light 2D wiring](wiring-light-1651.jpg) / [Dark AI + diagram](ai-diagram-dark-1651.jpg)
- [Dark mobile guide](wiring-dark-guide-390.jpg) / [Light mobile guide](wiring-light-guide-390.jpg)
- [Dark mobile AI](wiring-dark-ai-390.jpg) / [Light mobile AI](wiring-light-ai-390.jpg)
- [Dark camera tools](camera-tools-dark.jpg) / [Light camera tools](camera-tools-light.jpg)
- [Dark proposal](proposal-dark.jpg) / [Light proposal](proposal-light.jpg)
- [Dark deployment error](deploy-error-dark.jpg) / [Light deployment error](deploy-error-light.jpg)
- [Repair confirmation](repair-confirm-light.jpg)

## Reproduce

From `frontend`, run `npm test`, then `npm run preview:theme` and
`node tools/wiring-ai-preview.mjs` in separate terminals. Use the visible theme
and language selectors; compare state before/after switching. Fixture queries
include `?locale=en&generation=first`, `?deployState=failed&runtimeError&storageError`,
and wiring `?scenario=2d&locale=en`, `?scenario=overlay&locale=en`,
`?scenario=repair&locale=en`. Do not point these checks at live hardware.

Return temporary viewport overrides to default and stop the fixture servers when
finished. Existing full browser QA scripts remain available; their old warm-paper
visual assertions were updated where applicable, but they were not run as a
second browser-automation stack during this session.
