# Workflow Reset — 2026-10-05

## Scope

- Added one compact `Reset` action to the Maker header, available in stages 01–03.
- A native modal confirms the scope; Cancel gets initial focus, Escape cancels before commit, and repeated confirmation is single-flight.
- Reuses `newMakerProject` and the existing current-work safety snapshots. Whole-workflow Reset uses a read-only guard: it never dispatches an AI stop, Pi stop, test, or deployment.
- Returns to stage 01 / concept with no approved project, candidate, code, confirmations, debug entry, current chat, or selected GPIO photos. Photo archives, remote conversation history, and AI/component/device preferences remain.
- Keeps the one existing live-camera owner and source selection. Does not reconnect or select another source.
- Stores the previous Maker state in `boardvision.maker.v1.before-new-project`, and the previous assistant conversation pointer in `boardvision.assistant.v1.before-new-project`. The latter is a JSON string or null. Storage failure keeps current state; failure committing the new Maker pointer rolls the chat pointer back.
- Maker deployment code is controlled by the workflow even before project confirmation, so an unrelated standalone draft cannot reappear after Reset. Standalone draft storage is not deleted.

## Software validation

54 distinct targeted tests passed after updating the previous no-project deployment expectation to the new controlled-draft behavior:

- `tools/workflow_reset.test.mjs`: 6 tests.
- `tools/maker_stage.test.mjs`: 16 tests.
- `tools/header_panels.test.mjs`: 10 tests, now including Reset in shared panel ownership permutations.
- `tools/wiring_edit.test.mjs`: 16 tests, including two strict whole-workflow guard tests.
- `tools/maker.test.mjs`: 6 selected tests matching `actual newProject|workflow Reset|new project removes`.

`npm run build` and `npm run check:i18n` passed. Vite still reports the existing >500 kB chunk advisory. `git diff --check` found no whitespace errors.

## Browser validation

Used the production bundle in the isolated `gpio-photo-preview.mjs` fixture on `127.0.0.1:18818`. All APIs and imagery were synthetic, with no real Pi, camera, model, backend mutations, or external requests.

- Cancel preserved the original project and wiring view and restored focus to Reset.
- Captured a synthetic GPIO photo, confirmed Reset, and observed stage 01 with empty concept/blueprint context.
- Reloaded the fixture with its one-time seed option: stage 01 remained; stage 03 code was blank; stage 02 photo view said no wiring photo.
- Simulated a running Pi program: confirmation stayed open and displayed the hardware-work blocker. Cancelling still showed the original project and wiring controls.
- Simulated an incomplete Pi snapshot: reset was blocked with an actionable English message; checked the light-theme modal visually.
- With the final build, selected synthetic phone streaming, confirmed Reset, and verified stage 01 / fresh chat; revisiting stage 02 still showed phone streaming and no confirmed project.
- Verified dark and light modal layouts and initial Cancel focus. Follow-up failure focus is restored to Cancel by an effect.

Screenshots:

- `screenshots/workflow-reset-confirm-20261005.png` — latest Chinese dark confirmation.
- `screenshots/workflow-reset-complete-20261005.png` — latest successful stage 01 reset.
- `screenshots/workflow-reset-blocked-20261005.png` — synthetic Pi-running blocker.

## Limits

This is software/UI verification, not electrical, real Pi, or physical camera acceptance. The user's active `127.0.0.1:8100` workspace was not reset or refreshed, its processes were not restarted, and no hardware program was stopped. Temporary fixture tabs and server are removed after QA. No commit or push is included in this change.
