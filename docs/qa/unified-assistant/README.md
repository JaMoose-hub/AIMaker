# Unified assistant QA — 2026-10-02

All checks use isolated data and simulated AI. No paid generation, real webcam, Pi deployment, GPIO test, SSH operation, or production-project reset was performed. UI fixtures report simulated connection status; screenshots are not hardware evidence. The fake image adapter copies the existing sample into a new temporary artifact solely to test persistence and display.

## Regression

| Check | Result |
| --- | --- |
| `frontend/npm test` (includes typecheck + production build) | 543 passed; 0 failures |
| New assistant frontend tests | 8 passed; includes double-submit, reload request ID, late result ownership, draft preservation, Demo isolation, adoption/backup failures and pagination |
| Maker stage render tests | 8 passed, including retained photo PoC and 03 in-place diagnosis |
| New assistant backend tests | 21 passed |
| Full backend regression | 2,087 passed, 2 skipped, 4 pre-existing failures |
| Original backend baseline | 2,066 passed, 2 skipped, same 4 failures |
| Production build | Passed; Vite still warns about the >500kB JS chunk |
| `git diff --check` | Passed (line-ending normalization warnings only) |

The existing failures are unchanged:

- `test_backend_core.py::test_config_loads_yaml_relative_to_backend_dir`
- `test_backend_core.py::test_default_config_enables_both_component_models`
- `test_pin_regions.py::test_component_reference_refresh_requires_material_hand_and_three_frames[hw-123]`
- `test_project_images.py::test_prompt_disambiguates_imu_from_pir_without_adding_a_module`

Full local logs are retained in ignored `.tmp-unified-assistant-baseline/frontend-final.log` and `backend-final.log`. Final focused tests cover the last chat-clear/session-context hardening as well.

## Browser checks

The production bundle was served by `tools/maker-stage-preview.mjs --assistant` on **18780**, proxying only assistant and artifact endpoints to the temporary fake backend **18781** (`tests.assistant_preview`). All other writes are blocked or explicitly simulated. The live 8100 app was not restarted.

[`layout-matrix.json`](layout-matrix.json) records **48 passing combinations**: dark/light × English/Traditional Chinese × 1651/1440/1352/390 px × 01/02/03. Each checks one composer, stable conversation ID, no page errors, no horizontal overflow and no business writes. The camera stays mounted across mobile work/AI tabs. Additional checks cover 1352×520, keyboard width boundaries 320/520/reset 400, visible focus and collapse/expand retaining the same input and camera nodes.

Walkthrough verified in the real browser against fake services:

1. Open Demo from 02: formal maker state remains byte-for-byte unchanged; same camera DOM node remains mounted.
2. Built-in confirmation: **0 model calls / 0 image calls**, canonical three-wheel/motor image loaded.
3. Submit a change: exactly one `PlanningReply`, **0 images**; v2 checklist unconfirmed, old result retained.
4. Try built-in after modification: blocked with restore-or-generate guidance.
5. Explicit AI generation: one `DesignProposal` and one **fake** image call; image loaded from a new `/api/design/images/{id}`, not the canonical sample URL.
6. Leave and refresh: independent Demo result recovered; formal conversation unaffected.
7. 03 “Help me check”: stays on `deploy`; code and typed draft retained. A text reply appears in the common history.
8. Adopt the fake result: backup exactly matches the previous fixture, a new formal conversation is created, stage becomes 01 / blueprint. Canonical Demo remains available. Busy, stale and storage failure paths are covered by unit tests, not real hardware.

Representative screenshots:

- [Built-in Demo](demo-builtin-dark-en-1651.png)
- [Changed checklist](demo-changed-dark-en-1651.png)
- [Simulated generated preview](demo-generated-fake-en-1651.png)
- [Adopted fixture / blueprint](adopted-fake-blueprint.png)
- [Dark deployment](deploy-dark-en-1651.png) / [Light deployment](deploy-light-en-1651.png)
- [Mobile AI, dark](ai-dark-en-390.png) / [Mobile AI, light](ai-light-zh-TW-390.png)
- [Low-height 01](stage0-dark-en-1352x520.png), [02](stage1-dark-en-1352x520.png), [03](stage2-dark-en-1352x520.png)

## Deliberate limits

This establishes software behavior with mocks, not physical pin alignment, live camera framing, TFT confirmation, model answer quality, network failover, or Pi runtime acceptance. Long content remains scrollable on small/low-height displays. Existing theme tests cover token contrast; screenshots alone do not establish accessibility conformance. The old photo-wiring PoC is preserved and its existing tests still run, but it is not promoted or validated as part of the new assistant.

The branch remains uncommitted. Implementation followed the AI generation persistence skill using local storage instead of a cloud database, the custom-pipeline guidance in AI Elements, React lifecycle review, and agent-browser verification.

## Follow-up: model menu inside chat

The shared model menu now sits below the AI input, opening upward. It reuses the same state, model/effort validation, login, outside-click and Escape handlers; the photo PoC/HUD entry points remain unchanged. The mobile toolbar uses the vacated space for Pi controls.

- Full frontend regression: **546 passed**, production build passed (same chunk-size warning).
- Added checks cover model placement in all stages/Demo and both languages, preservation of project/draft on selection, and the separate HUD/PoC entry points.
- Isolated browser checks: 1651×871 dark/English, 390×871 light/Chinese, and 1352×520. The menu fits inside the viewport; short screens retain page scrolling to reach the composer. Model and effort changes preserved draft, design, preview, code, guide and history; Escape returned focus to the menu summary. No console errors or AI/Pi operations.
- [Desktop menu](model-menu-dark-1651.png), [mobile menu](model-menu-light-390.png).

Used React best-practices review and agent-browser/agent-browser-verify for this move. Production backend was not restarted; no Git commit or push.

### Compact brain trigger

The later compact variant replaces the separate footer row with a brain icon immediately before Send, inside the input border. The selected model remains in the localized tooltip/accessibility name; the existing menu/login/effort logic is reused. Standalone PoC/HUD menus keep their text variant.

Full frontend regression: **547 passed**, build passed (same bundle-size warning). Browser checks on isolated 18780/18781 confirmed desktop keyboard Enter/Escape/focus, model/effort changes preserving project/draft/history, and mobile 44×44px targets. The upward popover remains inside the viewport at 1651×871 dark/English and 390×871 light/Chinese, with no horizontal overflow or page errors. No paid generation, production restart or Pi operation.

- [Desktop compact composer](brain-model-dark-1651.png)
- [Mobile compact composer](brain-model-light-390.png)
- [Mobile expanded settings](brain-model-open-light-390.png)

## Follow-up: stacked wiring workspace

The old desktop side-guide rules had higher specificity than the unified layout, leaving an unintended third column. The scoped `assistant-wiring-stage` layout now keeps the existing camera/2D surface above a full-width wiring card. Guide visibility and Demo share the camera toolbar. The desktop card separates its scrollable instructions from its action column; mobile restores a bottom action row. Explicit camera minimum-height overrides prevent the old mobile camera size from covering the card.

- All frontend `*.test.mjs` files: **555 passed**, including a new App render/visibility regression. `npm run build` passed with the existing bundle-size warning.
- The full `npm test` entry is **not green**: its initial i18n check reports the unrelated concurrently added `MobileCompanion.tsx` literal URL placeholder. That component was not changed by this layout task.
- `tools/wiring-layout-browser-qa.ps1` uses only isolated 18780/18781 fixtures, recording geometry, overflow, toolbar placement, accessible action focus and page errors in `wiring-layout-matrix.json`. Collapse/expand additionally compares the camera DOM node and serialized project state at 1413px.
- Existing mobile context sync requests belong to separate in-progress work and are blocked by this offline fixture, not treated as a layout-generated hardware operation. No production workspace, paid model, real camera or Pi operation was used.
- React review kept the existing camera and guide components mounted; no wiring/test handlers or pin/overlay geometry were changed.

Seven layout combinations passed: 1651/1413/1352/1100×871 desktop, 390×871 in both themes/languages, and 1352×520. Screenshots use an offline camera fixture; its connection warning is expected and is not a live-camera test result.

- [1413px dark wiring](wiring-layout-dark-zh-TW-1413x871.png)
- [390px light wiring](wiring-layout-light-en-390x871.png)
- [Low-height wiring](wiring-layout-light-en-1352x520.png)

### Clear physical-pin endpoints

Removed the Pi 1–20 row-count diagram from the project guide. Its active card now shows the module pin and physical Pi pin as two endpoints, with signal/row information subordinate. The module's complete pin strip remains in the collapsed instructions. Changing wire/module resets only the guide body's scroll position.

- Full `npm test` now passed: **560 tests**, i18n check and production build (the separate mobile placeholder issue from the earlier run is no longer present). Same bundle-size warning.
- Existing profile-driven mapping tests cover all supported module pins; a new bilingual regression explicitly distinguishes TFT GND → **physical Pin 20** from row position 10. Divider warnings and mapping fallbacks are retained.
- Isolated browser: 1651×871 dark/Chinese and 390×871 light/English. The entire endpoint card fits within its scroll area, no Pi row-count diagram, no horizontal overflow/page errors, collapsed module reference opens successfully. A scrolled TFT step resets from 89px to 0px on Next, displaying the next physical endpoint.
- [Desktop endpoints](wiring-endpoints-dark-1651.png), [mobile endpoints](wiring-endpoints-light-390.png). Offline fixture warnings are expected. No real AI requests, camera or Pi actions were performed.

### Wiring instructions and action column

Separated the existing component-test presentation into `instructions` and `actions` views sharing the same guide-owned controller. The left side holds wiring/test instructions, results and safety notes. The right side holds navigation and independently scrollable test controls, including stop and physical-screen confirmation. Removed the duplicate guide AI-help button; the shared AI panel remains available.

- Full `npm test`: **567 passed**, i18n and production build passed; existing large-bundle warning remains. Four new regression cases cover bilingual placement, physical-screen options, disconnected/foreign/stale stop controls, and single consent/sample controls. Existing standalone test-card views remain unchanged.
- `tools/wiring-actions-browser-qa.ps1`: **7 combinations passed** (1413/1651/1352/1100×871, 390×871 dark/Chinese and light/English, 1352×520). Ready, disconnected, awaiting visual confirmation and lost-connection scenarios use only read-only fixture records.
- Checked correct left/right placement, no horizontal overflow or page errors, reachable test controls, navigation remaining outside test scrolling, unchanged serialized project state, and disabled confirmation until code/colors are selected. Selection was checked without submitting it. Fixture reports **zero model/image calls**, and no Pi/test business writes occurred.
- React Best Practices review retained the single test hook and exact run-bound confirmation logic. agent-browser / agent-browser-verify provided isolated rendered-page checks, not live hardware evidence.
- [Desktop ready](wiring-actions-ready-dark-zh-TW-1413x871.png), [desktop display confirmation](wiring-actions-visual-dark-zh-TW-1651x871.png), [mobile confirmation](wiring-actions-visual-light-en-390x871.png), [matrix](wiring-actions-matrix.json). Backend-offline camera warnings are expected in this fixture. Real 8100 data, camera and Pi were not operated.

### Chat role colors and composer glow

Unified-chat selectors now outrank legacy gray bubble rules: user messages use blue backgrounds, AI messages use teal backgrounds, with role labels and existing alignment retained. Both themes define their own surfaces/borders/label colors. The composer restores the earlier purple-blue-teal gradient border and soft glow, with stronger focus and non-interactive decorative layers. Its outer focus ring replaces the duplicate textarea ring. No message/controller behavior changed.

- `npm run test:theme`: **28 passed**, including two new unified-chat style regressions. Production build passed with the existing bundle-size warning. This CSS-only follow-up did not rerun the complete frontend/backend suites.
- agent-browser / agent-browser-verify: isolated 1413px dark and light, plus 390px light. Rendered role-name, metadata and message contrast all exceeded **4.5:1** (minimum observed **5.57:1**). Distinct bubble backgrounds, focus glow, no horizontal overflow or page errors, and unobstructed send/model controls were checked. Model selectors were clickable on desktop and mobile; no message was submitted.
- [Dark chat](chat-colors-dark-1413.png), [light chat](chat-colors-light-1413.png), [mobile chat](chat-colors-light-390.png). Built-in demo dialogue supplied the messages; no paid AI, real project mutation or Pi operation was used.

### Compact wire steps without inner scrolling

Active wire cards now grow with their content instead of using a fixed-height body/action scroll pane. The default card shows the module pin, physical Pi pin, short power-off/BLK reminders and navigation. Idle test instructions and saved records stay available in collapsed reference details. Running/disconnected tests, current errors, pending jobs and new results remain visible; their controls retain the existing controller and safety checks. The separate completed-module overview keeps its existing layout.

React Best Practices review preserved hook ownership, test identity, manual confirmations and hardware handlers. agent-browser / agent-browser-verify use only the isolated preview, including the screenshot's confirmed TFT CS → Pin 24 state. Small/low-height windows and expanded reference material use outer workspace/page scrolling, not a scroll pane inside the active card. No production project, camera, paid model or Pi operation was used.

- Full `npm test` passed, including i18n and production build (existing bundle-size warning). The separate all-`*.test.mjs` run passed **592 tests**; targeted guide/test/stage regressions passed **62 tests**. New regressions cover collapsed idle/history content, physical endpoints/BLK safety, live/foreign/disconnected tests and fresh errors/results.
- `tools/wiring-compact-browser-qa.ps1`: **7 combinations passed**, covering 1413/1651/1352/1100×871, 390×871, and 1352×520, dark/light and Chinese/English. Body and control content fit without inner scrolling; reference expands/closes with Escape/focus restored and without changing wiring records. No horizontal overflow, page errors or hardware writes. Fixture reported zero model/image calls.
- After rebuilding and restarting only the isolated preview, latest-bundle smoke checks passed at 1413×871 and 1352×520 with a lost test: visible warning/Stop, disabled physical-screen confirmation, and no inner scrolling. Production 8100 was only read to verify that it serves rebuilt assets; it was not restarted.
- [Latest desktop](wiring-compact-latest-1413.png), [mobile](wiring-compact-ready-light-en-390x871.png), [latest disconnected test](wiring-compact-latest-lost.png), [layout matrix](wiring-compact-matrix.json). Camera offline warnings are intentional fixture behavior, not a hardware result.

### AI orb and composer controls

The desktop text toggle is now a 46px accessible button containing a CSS-lit orb, subtle flowing color and a directional chevron. Its collapsed 64px rail retains the orb, AI label and unread indicator without unmounting the chat or camera. The existing model/effort menu and submit action share a capsule with a round gradient arrow; pending/disabled states remain distinct. CSS animation uses transforms, no new graphics dependency or render timer. Reduced motion disables both orb flow and panel-width transitions. Legacy non-chat model menus and mobile Workspace/AI tabs are unchanged.

- Full `npm test`, including i18n and production build, passed; the existing large-bundle warning remains. New regression tests cover localized collapse/unread labels, both panes staying mounted, every send-disable guard, pending indication and reduced-motion styles.
- React Best Practices review preserved state ownership and native keyboard/ARIA semantics. The `assistant-orb-browser-qa.ps1` fixture checks keyboard collapse/reopen, camera/chat/input node identity, unchanged draft/design/code/wiring, click targets, model-menu bounds/Escape focus, blank-input disabling and reduced motion. It never submits a message or invokes a Pi/camera action.
- All five browser combinations passed: 1413×871 dark/Chinese and light/English, 1100×871 with a 320px chat pane, 390×871 light/English, and 1352×520 dark/Chinese. No page errors, horizontal overflow or hardware writes; mobile model/send targets are 44px. Reduced-motion checks passed. The isolated fixture reported zero model/image calls, and production 8100 was only read to verify the rebuilt CSS.
- [Desktop orb and composer](ai-orb-open-dark-1413x871.png), [collapsed orb](ai-orb-collapsed-dark-1413x871.png), [light theme](ai-orb-open-light-1413x871.png), [mobile controls](ai-orb-open-light-390x871.png), [matrix](ai-orb-matrix.json). Camera-offline messages are expected fixture behavior, not a live hardware result.

### Compact assistant tools

The shared wiring chat now groups focus switching, 10-second photo capture and a tools disclosure into one toolbar. Photo style, inspection records and manual tests live in the initially hidden settings area. Current pin context and a Suggestions disclosure share the next line, replacing the always-visible question chips in stage 02 only. Stop, countdown cancellation, current instructions and errors remain outside collapsed settings. The standalone debugging composer is unchanged.

- Full `npm test`, including i18n and production build, passed with the existing bundle-size warning. Added bilingual hidden-tools/state/focus coverage, capture/countdown and disabled-guard checks, visible stop/error checks, and stage-specific suggestions regressions.
- React review retained session ownership, native controls, original action guards and capture countdown. Browser QA uses only isolated 18780/18781 fixtures, not the real 8100 project, camera or Pi. An Escape-propagation issue found during QA was fixed so closing settings does not collapse the wiring guide.
- Browser interaction checks passed at 1413×871 dark/Chinese and light/English, 1100×871 with a 320px pane, 390×871 light/English, and 1352×520 dark/Chinese. The low-height case was rerun after the test explicitly scrolled the suggestion trigger into view. Checks covered retained photo style, record/manual-tool access and return focus, suggestions filling only the draft, preserved camera/input nodes and project data, no page errors or hardware writes. Fixture totals: zero model/image calls.
- A final English-label refinement was rebuilt and smoke-checked at 1100px: even the 320px chat pane now keeps the default toolbar on one 42px-high row. Mobile controls retain 44px touch targets. Production 8100 serves the rebuilt styles; no production backend restart was needed.
- [Dark toolbar](ai-tools-dark-1413x871.png), [light toolbar](ai-tools-light-1413x871.png), [final narrow desktop](ai-tools-latest-1100.png), [mobile](ai-tools-light-390x871.png), [low-height result](ai-tools-matrix-1352.json). Offline camera messages are fixture behavior, not a hardware failure or test result.

### Concise component-test instructions (2026-10-02)

The completed-module strip is one line. Guide instructions show status and one short action for HC-SR04+ near/far sampling and TFT colors/code/visual confirmation. Heartbeat time, sample counts and setup diagnostics are in closed Test details. Empty/stale readings are not presented as live values. BLK caution, power-off reminder, historical-evidence labels and errors stay visible. Hardware handlers, run identity, Stop, consent and visual-confirmation guards are retained.

- Full `npm test` passed: **610 tests**, i18n and production build. The existing >500 kB bundle warning remains. New bilingual regressions cover nine phases, telemetry disclosure, stale/lost readings, manual records, BLK and historical visual evidence. React Best Practices review preserved hook ownership and native controls; no new dependency or hardware call.
- `tools/test-copy-browser-qa.ps1`: **8 isolated browser cases passed**. Near/far/sampling/red/visual at 1413x871 Chinese/dark, code at 1352x871 English/light, visual at 390x871 English/light, and lost connection at 1352x520 Chinese/dark. Desktop default information fits without inner scrolling; mobile retains scrolling. Details expand/collapse, controls are reachable, visual confirmation requires code/colors, lost state retains Stop, project state is unchanged, and no page errors, horizontal overflow or hardware writes occurred. No test result was submitted.
- agent-browser and agent-browser-verify used only 18780/18781. Fixture totals: zero model/image calls. Production 8100 was read only to verify rebuilt assets, not restarted. No camera or Pi operation was performed.
- [Distance instructions](test-compact-awaiting_near-dark-zh-TW-1413x871.png), [screen instructions](test-compact-screen-final.png), [English code display](test-compact-display_code-light-en-1352x871.png), [matrix](test-compact-matrix.json). Offline camera banners are intentional fixture behavior.

### Slim brand header (2026-10-03)

CSS-only header refinement: the unchanged wordmark now sits beside the Vibe Maker Studio descriptor, separated by a fine rule. Wide desktop header measures 45px. Responsive wrapping, menus, error rows and touch targets remain available. Browser verification found and fixed an existing mobile English control overlap by visually hiding the redundant Pi group label while retaining it for assistive technology.

- Full frontend `npm test` passed: 614 tests, i18n and production build. Existing bundle-size warning remains. Header regressions cover side-by-side branding, descriptor contrast, wordmark ratio, touch controls and accessible mobile label treatment.
- `tools/header-slim-browser-qa.ps1` passed all 7 cases: 1651/1440/1352/1210/1100x871, 390x871 and 1352x520, with both languages/themes represented. Verified no overlapping/clipped controls, all three stages, Settings expansion and its three controls, unchanged project state, no page errors/hardware writes, and 44px mobile targets. Widths 1210 and above measured 45px; 1100 and mobile wrap normally.
- agent-browser and agent-browser-verify used isolated 18780/18781 only, with zero model/image calls. Production 8100 was read to confirm rebuilt CSS; no restart, camera access or Pi operation.
- [Desktop](header-slim-dark-zh-TW-1651x871.png), [light/English](header-slim-light-en-1440x871.png), [mobile](header-slim-light-en-390x871.png), [matrix](header-slim-matrix.json). Offline-camera warnings are fixture behavior.

### Adjustable camera / wiring-card heights (2026-10-03)

02 now has an 18px horizontal drag track between the existing camera/2D pane and wiring card. Its independent `boardvision.guide-height.v1` preference survives refresh; double-click / Enter resets, arrows fine-tune, Shift uses larger steps, and Escape cancels a captured drag without collapsing the guide. Bounds retain usable camera and navigation space; longer instructions/actions scroll within their own pane when reduced. Hidden guides reclaim the camera area; narrow/very short layouts retain natural scrolling. Legacy board/HUD orientation and width preferences are unchanged.

- 75 targeted geometry, stage, responsive, diagram and component-test regressions passed; a final 23-test stage/geometry/HUD check also passed after scoping the preference to Maker projects. i18n check and production build passed. The pre-existing bundle-size warning remains. No backend changes or hardware regression claims.
- `tools/guide-height-browser-qa.ps1` used native mouse/keyboard interactions to verify two-pane drag deltas, camera/guide node identity, unchanged project data, minimum/maximum bounds, Escape rollback, refresh persistence, double-click reset, wire/2D switching and guide collapse/reopen. Browser QA found and fixed Escape propagation into the page's guide-collapse handler.
- Four isolated layout cases passed: 1651x871 dark/Chinese, 1440x871 light/English with TFT visual-confirmation controls, 1352x520 dark/English and 390x871 light/English. No horizontal overflow, clipped desktop navigation, page errors or hardware writes. Fixture model/image calls remained zero. Production 8100 was only read to confirm rebuilt assets; no restart or real project/Pi/camera interaction.
- [Dragged split](guide-height-dragged-1651x871.png), [active wire / 2D](guide-height-active-2d-1651x871.png), [light TFT](guide-height-light-1440x871.png), [phone](guide-height-light-390x871.png), [matrix](guide-height-matrix.json). Offline-camera banners are intentional fixture behavior, not hardware evidence.
- Final production bundle `index-BgKwne1m.js` was smoke-checked on the isolated origin: horizontal separator rendered, ArrowUp changed its value from 56 to 53, and page errors remained empty. The same bundle is served by production 8100. Only owned QA processes/browser were closed afterward.

### Instructions / records disclosure hidden (2026-10-03)

At the user's request, the unified wiring card temporarily hides the entire Instructions & records disclosure using scoped CSS. Its records and state are not deleted; current endpoints, safety cautions, navigation, test controls and vertical resizing remain available. Earlier reference-expansion screenshots/checks above document the previous UI.

- 55 project-guide/component-test regressions and production build passed. Isolated 1651x871 browser checks confirmed zero-size / display:none in both review and active-wire states, retained controls and confirmed progress, no page errors or hardware writes, and zero model/image calls. Production 8100 serves the rebuilt assets; it was not restarted. Owned QA processes were closed.
- [Hidden disclosure](reference-hidden.png).

### Fit component tests to the wiring workspace (2026-10-03)

Completed-module tests retain the left instructions / right navigation-and-actions layout. The vertical splitter now reserves the intrinsic height of required test content rather than compressing it into an inner scroll pane. Existing preferred ratios are not rewritten by this automatic bound; keyboard and pointer resizing honor the same bound. Camera/overlay children remain mounted. Only guide content, not per-frame camera overlays, is watched for content changes.

TFT confirmation uses compact desktop code choices and paired action buttons. All four run-bound code choices, color confirmation, disabled confirmation guard, Stop, appearance-error alternatives and BLK caution remain. Optional expanded diagnostics and insufficient phone/short-window space still scroll instead of clipping. The hidden Instructions & records disclosure stays hidden; no records or hardware handlers were removed.

- 76 geometry, component-test, project-guide and stage regressions passed; i18n parity and production build passed with the existing bundle-size warning.
- The isolated 18780/18781 matrix covered 10 cases: Chinese HC-SR04+ near/far/sampling, TFT colors, English code display, Chinese/English visual confirmation, 390px phone and 1352x520 connection-loss UI. Default desktop instruction/action panes had equal client/scroll heights, all controls were inside their pane, and no page errors or hardware writes occurred. Optional diagnostics remained accessible. The fixture recorded zero model/image calls.
- A seeded `.95` camera preference was clamped without rewriting it. Native End-key and downward pointer drag respected the test-content minimum; camera node identity and project data were unchanged.
- Final two-column appearance-option refinement was rebuilt and smoke-checked again at 1413x871 dark/Chinese and 1352x871 light/English: no inner overflow or clipped controls; visual confirmation remained disabled until evidence selection. [Final Chinese](test-fit-final-zh.png), [final English](test-fit-final-en.png), [earlier 10-case matrix](test-compact-matrix.json).
- Production 8100 was read only to confirm rebuilt assets; no backend restart, production project change, real camera, Pi test/deployment or cloud generation was performed. Offline-camera banners in screenshots are intentional fixture behavior.

### Phone preview in the main camera workspace (2026-10-03)

02 places the existing phone companion trigger immediately before Camera tools. Phone preview now uses the main video/2D area with a return-to-Webcam control, compact stream diagnostics and the existing canonical phone capture action. The companion still owns pairing, capture/retry, GPIO photo selection and chat attachments; portals relocate its UI without duplicating that controller. The phone panel is outside the collapsed AI surface. Webcam remains mounted but hidden; its countdown, device picker and calibration controls are unavailable over a phone preview. Source switching does not submit camera/Pi operations or clear confirmations, design, code or chat.

- react-best-practices informed single-owner state and receiver cleanup; agent-browser and agent-browser-verify validated the rendered build on isolated 18780/18781. `tools/maker-stage-preview.mjs?phone-preview=1` replaces RTC with a browser-only 720×1280 canvas stream. It never accesses a real camera or phone; absent network/recognition metrics stay unavailable, and its framing state is not labeled Locked.
- Full `npm test` passed: 651 frontend tests, i18n parity and production build. The existing >500kB chunk warning remains. The App stage test covers toolbar placement, preview/return, source-specific guards and retained project bindings. Mobile rendering tests cover closed diagnostics, disconnected state and narrow capture-footer space; the 2D handler test also checks exit from phone preview.
- The final browser matrix uses `tools/phone-main-browser-qa.ps1`: 1413×871 dark/Chinese, 1352×871 light/English, 1352×520 light/English and 390×871 light/English. It checks a single receiver, native preview/return actions, retained Webcam DOM/project data, panel fit, entry placement, main capture visibility and no unnecessary inner preview/horizontal overflow. The desktop case additionally opens the phone panel with AI collapsed. Narrow mode reserves preview space and uses 44px touch targets. Short windows retain page scrolling rather than clipping the workspace.
- Production 8100 was read only and served `index-CiuWklr3.js`; no backend restart, production project change, real-device streaming/capture, Pi test/deployment or model/image call was performed. The fixture reported `model_calls:[]` and `image_calls:0`. Existing capture regression tests use mocks; actual phone transport, throughput, GPIO accuracy and main-workspace capture still require device validation.
- [Desktop](phone-main-desktop.png), [light/English](phone-main-light-en.png), [short window](phone-main-short-en.png), [narrow workspace](phone-main-mobile-en.png). The synthetic test image is not hardware evidence. Architecture and next-stage source unification are documented in [camera-source-integration.md](../../camera-source-integration.md).

### Phone publisher landscape pixels (2026-10-03)

Historical attempt, superseded: this first implementation forced portrait input to rotate 90°. The user rejected that framing; the current implementation below removes it. Earlier checks and screenshots remain for provenance, not as evidence of current orientation behavior. [Earlier evidence and limits](../mobile-landscape-2026-10-03.md).

### Genuine sideways phone capture (2026-10-03)

Phone orientation and actual decoded camera dimensions are checked separately. Portrait is a local-only preview: no output track, stream-start or offer request. Only genuine landscape frames are proportionally drawn without rotation into 1920×1080 (or selected/fallback 1280×720). Returning to portrait stops publication, releases the source and revokes capture readiness; late readiness cannot revive a cancelled preview. Existing photos and their coordinate plane remain intact.

- 59 distinct focused mobile regressions were exercised, with one failed SSR attribute-order assertion corrected and rechecked: **60 automated test executions this round**, final scoped checks passing. TypeScript and production build passed; no full suite or backend tests were run. The existing bundle-size warning remains.
- Isolated browser checks covered portrait-only waiting, sideways screen with still-portrait pixels, genuine unrotated landscape publication, canonical 1920×1080 JPEG/geometry, portrait invalidation and English/light narrow-screen cancellation. Real synthetic video and production phone UI/hook were used; RTC, server readiness and geometry were fakes. No real phone, camera, Pi, cloud generation or production project was operated. Tests stayed below the 100-execution cap.
- React Best Practices informed single-owner direction listeners and cleanup; agent-browser / agent-browser-verify checked Chinese/dark and English/light views. Production 8100 was read only to verify rebuilt assets. [Detailed evidence and limitations](../mobile-orientation-2026-10-03.md), [local-only portrait](phone-orientation-light-wait.png), [unrotated photo](phone-orientation-photo.png).
