# Demo chat verification — 2026-10-01

## Change

Loading Demo now adds the built-in user prompt and a prewritten assistant reply to the **left conversation panel**, alongside the existing project preview/image. Each bubble is labelled Sample chat / 示範對話. Sample replies remain complete rather than going through real-AI long-reply summarization.

- Language is selected when loading Demo; reloading replaces the previous sample pair, not real messages.
- Custom composer drafts, approved project, code, wiring progress and hardware state remain unchanged.
- Sample messages retain their local `source: demo` marker on restore. Twenty real messages plus the two sample messages can be saved without Demo evicting real history.
- Real AI requests exclude sample messages and keep the existing role/text API shape. No cloud generation, image generation or hardware request is introduced.
- Clearing chat / starting a new project clears the sample messages, never the bundled three-wheel/two-motor Demo image.

## Automated verification

`npm test`: **513 passed, 0 failed**, i18n check and TypeScript/Vite production build passed. Log: `frontend/demo-chat-tests.log` (local generated test log).

Coverage includes localized prompt/reply rendering, complete sample text, deduplication, preservation of 20 real messages, saved-state restore, invalid/failed/busy loads, real follow-up request isolation, draft protection, clear/reset, preview confirmation and image retention. Existing real AI reply presentation tests remain passing.

Build output: `/assets/index-8ZZ9bAkr.js`. HTTP GET on the existing port 8100 returned 200 and references this bundle. Existing bundle-size warning (>500 kB) remains. No backend files changed for this task, and no backend suite was rerun.

## Browser verification

Using the agent-browser and agent-browser-verify skill checklists through the supported cua_repl browser API, tested the real components and previewDemo state transition on the isolated origin `127.0.0.1:18770` (no backend proxy; network connections denied). Default viewport 1280×720, no production tab reload/reset.

- Chinese and English: Load Demo displays user and assistant bubbles in the left chat and the approved fixed image on the right.
- Unsent custom text survives Demo loading.
- Reloading Demo retains the preview-replacement confirmation and leaves exactly two sample bubbles.
- English sample reply is complete; no Read full reply control hides its limitations.
- Clearing the isolated chat retains the preview/image and custom composer text.
- No captured console warnings or errors; no blank page or framework error overlay.
- Temporary preview server and agent-created tab closed afterward.

Screenshots: [Chinese](demo-chat-zh.png), [English](demo-chat-en.png). These show isolated UI fixtures, not a live AI generation or Pi hardware result.

## React review

Applied the react-best-practices checklist: functional state updates, immutable message handling, bounded persisted history, effect keyed to conversation changes (including same-length Demo replacements), existing accessible log/labels and confirmation guards retained. No new dependency, global listener, timer, fetch waterfall or business API added.

No real AI requests, Pi tests, deployments, Git commits/pushes or changes to the user's live browser draft were performed.
