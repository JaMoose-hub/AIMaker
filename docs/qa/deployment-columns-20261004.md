# Deployment code and output columns

The unified-workspace rule in `frontend/src/assistant.css` forced deployment
into a flex column, overriding the existing two-column deployment markup.
It now uses an equal-width auto-fit grid, with a 360px minimum per column
capped at the available width. The AI conversation stays in its own pane.

Validation on 2026-10-04:

- `node --test tools/deploy_columns.test.mjs`: 3/3 passed.
- `node tools/deploy-columns-preview.mjs`: isolated, memory-only build of the
  actual PiDeployPanel and AssistantWorkspace, with synthetic Pi state and
  networking/hardware actions disabled.
- 1280px desktop / 400px AI pane: two equal, aligned columns; no page overflow.
- 1280px desktop / 520px AI pane: stacked columns; draft unchanged; no overflow.
- 1651px desktop / long synthetic output: two aligned columns; output scrolls
  within its console; no overflow.
- 390px phone: stacked columns; draft unchanged; no overflow.
- No browser console errors or warnings. Offline deployment remains disabled.

Screenshot:
`C:/Users/james/.codex/visualizations/2026/10/04/01a10573-a0b8-76f3-9f33-a724c9be7566/deployment-columns.jpg`

Scope: layout only. No real Pi actions, backend restart, shared `frontend/dist`
build, or modification to deployment/code/output business logic. The source
change will be included in the next normal frontend build.
