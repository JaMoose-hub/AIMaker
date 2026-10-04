# Component test AI help: conditional entry and background evidence

Historical implementation evidence: the test-help button now uses the short deterministic invitation described in [the subsequent QA](test-help-invitation-20261004.md). The model-backed `sendTestHelp` transport remains available, but App no longer dispatches it from this button. The validation results below describe the earlier implementation.

## Behavior

- `ComponentTestCard` offers Ask AI for help only for a matching, valid failed/inconclusive test, the latest failed execution job for that wiring, or an active test with an actual connection/progress problem.
- Untested API/setup errors, normal running/awaiting-confirmation states, passed/cancelled tests, invalidated history, different revisions/components/projects and superseded queued tests do not expose that action. Saved failures may remain eligible if their project, revision and guide key still match.
- The click handler rechecks the current target and eligibility. Double clicks, stale callbacks and unmounted cards cannot send another request. Delivery errors remain retryable only for the same eligible target.

## Evidence transport

`componentTestHelpRequest` returns readable `text` separately from a cloned background `context`. App sends that context through the existing `SendRequest.context.component_test_help` field with `target: debug`. This reuses the existing backend and requires no backend implementation change or restart.

The background context contains selected project/revision/component/run identity, outcome, reason, samples, bounded logs/detail, selected-component expected wiring, and advisory evidence limits. It cannot bind another project/component/run. A failed preflight without a run ID or classified reason replaces the previous issue's binding explicitly.

Only the readable text becomes a user chat message, including shared phone history. Hidden facts do not enter the composer draft or published phone workspace hash. The existing model prompt treats context as data; a failed test is not a wiring verdict. Hardware operations, automatic wiring confirmation and code changes are not dispatched by this action.

## Verification

- Frontend helper, assistant transport and component tests: 78 passed.
- Related project guide, floating dock, debug-session and execution controls: 76 passed. The execution test loader now resolves the real shared header hook; existing FIFO/stop/handoff assertions remain intact.
- Backend assistant contract and paired-phone public history: 24 passed, including three new background-context cases. Full evidence reaches the model prompt; public messages/jobs exclude internal request JSON.
- Production TypeScript/Vite build passed; translation parity passed (761 keys).
- Isolated browser with real ComponentTestCard, helper, useAssistant, UnifiedAssistant and MobileWebApp passed: failure and missing-dependency entry visible; passed, untested, cancelled, stale and old-version entry hidden. HC-SR04+ and TFT sends contain only the selected component's 4/7 expected connections in background evidence; visible requests are 64/80 characters, with no raw JSON. Draft and 11 manual wiring confirmations survive. The paired phone shows the same short history at 390 x 844 with no horizontal overflow. No Pi/debug API was invoked and the published phone workspace contains no hidden test-help evidence.
- Screenshots and captured mock requests are in `runs/test-help-qa-20261004/`. The live 8100 homepage serves the current compiled frontend successfully. No backend restart is needed for this change; the user can refresh the existing page.

All verification uses software fixtures and mock assistant transport. No cloud model, Pi command or physical hardware test was run for this UI change. The user browser's existing conversation was not refreshed or reset.
