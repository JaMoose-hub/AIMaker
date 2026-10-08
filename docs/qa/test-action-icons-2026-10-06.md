# Compact function-test actions — 2026-10-06

## Follow-up: muted action colors

Added blue test/retest, purple AI help, neutral gray back and amber deferred-test styling. Passed navigation retains a distinct teal treatment. Labels remain the primary meaning; action colors do not certify test results. Disabled controls fade and desaturate; enabled hover/focus increases the tint. No behavior or service changes.

All four targeted icon tests passed, including the deferred-versus-passed style hook. TypeScript and production builds passed. The isolated browser preview rendered four 104×44px controls without console warnings/errors; keyboard focus remained visible. Calculated text contrast against the observed dark card background is 8.94–9.49:1 normally and 7.40–7.77:1 with the hover tint. These are UI checks, not hardware tests.

Current color preview: [Action colors](test-action-colors-2026-10-06.png).

## Follow-up: recognizable labels

After user feedback that icon-only controls were abstract, the four actions now pair icons with short visible labels: 重測 / AI 求助 / 返回 / 稍後測試 (Retest / Ask AI / Back / Test later). Full hover descriptions remain, and accessible names include the visible labels. Initial tests show 測試 / Test; passed navigation retains its destination label. No handlers or eligibility rules changed.

The React review kept this presentation-only, with no new state, effects, network requests or dependencies. TypeScript and Vite builds passed. The 13 icon/bottom-guide tests passed after updating the short accessible-name expectation. Chinese desktop and English 390px previews had no horizontal overflow or console errors; the four English action targets measured 104×44px. No backend restart or hardware/AI/stream operation was performed. The previous broader-suite limitations below remain; that broader suite was not rerun in this follow-up.

Current preview: [Icons with short labels](test-action-labels-zh-2026-10-06.png).

The original icon-only verification follows for historical context.

## Scope

Only the bottom guide's test/retest, AI help, back and continue/defer actions now use icons. Each has a localized accessible name and native hover description. Consent, sampling, stopping and screen-result confirmations retain text. Test/help eligibility, handlers, wiring progress and backend behavior are unchanged by this change.

Existing working-tree changes, including compact result/detail presentation changes, were preserved.

## Verification

- TypeScript project build passed; Vite production build passed (existing large-chunk warning).
- New icon tests: 4/4 passed, covering both languages, disconnected/busy states, help eligibility, deployment destination, non-inline views and explicit sampling/stop actions.
- Bottom guide layout tests: all 9 cases passed across the initial run and the targeted rerun after updating the expected button class.
- Component-test suite: 35/37 passed. The two failures expect heartbeat text inside the compact guide (`active tests show a fixed report timestamp...`, `new tests wait for their first report...`). That text is omitted by the pre-existing compact-details implementation; this icon change did not alter it. These failures remain unresolved and are not counted as passes.
- Browser check used a static rendering of the real components and CSS on an isolated local preview. Chinese 1280px and English 390px layouts had no horizontal overflow; all four targets measured 44×44px. Tab focus moved to AI help with a visible 2px focus outline. No preview console warnings/errors.
- No live Pi tests, AI requests, phone streaming operations or service restarts were performed.

Preview: [Chinese icon layout](test-action-icons-zh-2026-10-06.png).

Reproduce preview with `node tools/test-action-icons-preview.mjs` from `frontend`; open `http://127.0.0.1:18788/` or `/?lang=en`. This preview is static and does not invoke hardware or AI actions.
