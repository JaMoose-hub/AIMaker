# Demo image fix — 2026-10-01

## Demo retention follow-up

The approved three-wheel/two-motor v2 image remains a bundled asset in
`frontend/public/demo`, separate from browser drafts and generated-image storage.
The New project tooltip/confirmation now explicitly says the Demo image is kept
and remains available through Load demo (Chinese and English).

Added regressions verify reset, discarded preview, cleared conversation and
missing saved browser state can all reload the same Demo image; new projects
start without a Demo image/current design. The static URL is never serialized
as a generated image or sent as an AI edit reference, and generated-artifact
validation rejects that URL. The file bytes remain unchanged.

`npm test`: **510 passed** including production build; existing bundle-size
advisory only. Log: `frontend/demo-retention-tests.log`. Live PNG still responds
200 with the same v2 SHA-256. No user project was reset, no image was deleted,
no AI or Pi operation was performed, and no live browser reset was used as a test.

## Current v2 correction: three wheels and visible motors

User rejected the stationary v1 illustration. Existing three-wheel project
images also lacked visible motors. The built-in imagegen tool edited
`5d8f91e23b1e40c889b2350910e69b71.png` to add two visible yellow gearmotors;
visual inspection confirmed three rubber wheels, two motor bodies, two round
acrylic plates and the retained sensor/Pi/display. Exact prompt: `motors-prompt.md`.

Current asset: `frontend/public/demo/distance-monitor-three-wheel-motors-v2.png`.
The sample is presentation-only and now displays the motor-only concept notice;
no motor is inserted into saved design data, BOM, 02 or 03. Original images and
the prior v1 sample are retained. No backend, Pi or cloud design jobs were changed.

Verification of v2:

- Full `npm test`: **508 passed** and production build passed. Existing bundle
  size warning only. Log: `frontend/demo-image-motors-tests.log`.
- Demo tests now assert the v2 PNG hash/dimensions, bilingual three-wheel/two-motor
  alt text, visible motors-excluded-from-workflow notice and unchanged project data.
- Live image response: **200**, `image/png`, 2,163,184 bytes,
  SHA-256 `4ced7d7fc35ed955d942f531e0d3286640e0f306c07b546c66724848e3cdb0fd`.
- Live HTML references `index-CEdiYfpk.js`. No forced refresh of the user tab.
- No additional browser interaction was performed for this asset replacement;
  the earlier screenshots below are explicitly **v1**, not v2 UI proof.

## Original v1 verification (historical)

## Cause and scope

Live `GET /api/design/demo` returned `source: demo` with both current modules,
but no `image`, `image_required` or `image_error`. The frontend had no bundled
Demo image and therefore rendered the generic missing-generated-image message.

The full-kit Demo now uses a versioned PNG in `frontend/public/demo` solely in
the presentation layer. The image is a byte-identical copy of a historical
project illustration (provenance in that directory's README). It is labelled
Demo in Chinese and English, not a fresh AI result or wiring verification.
AI images, errors, pending image requirements, other kits and concept-only
motors never use this sample. Existing actual images retain priority.

No backend schema, project storage, AI prompt, hardware flow or image artifact
was changed. No production page refresh, paid AI call, deployment, Pi restart
or physical test was performed. A page refresh loads the new frontend build;
no backend restart is needed for this fix.

## Verified

- `npm test`: **508 passed**, including TypeScript and Vite production build.
  The existing >500 kB bundle-size advisory remains. Log: `frontend/demo-image-tests.log`.
- New regression cases cover both locales, PNG dimensions/hash, fallback scope,
  unchanged generated images, AI confirmation guards, image-load failure/retry,
  preview/confirm/discard/restore, draft preservation and Demo without AI login.
- Actual `useMakerAI.loadDemo` tested with local responses: only the Demo GET is
  requested; no design generation POST and no existing draft/project overwrite.
- Browser: real React UI in loopback-only isolated preview, no API proxy,
  fetch/WebSocket denied, CSP `connect-src 'none'`. Clicking Load demo shows
  the PNG with `complete: true`, `naturalWidth: 1312`, `naturalHeight: 1199`
  in Chinese and English. Screenshots: `demo-zh.png`, `demo-en.png`.
- Browser console: no error/warning after fixing an isolated-fixture null
  assembly assumption. Initial fixture-only failure screenshot is retained as
  `fixture-before-fix.png`; production code was not responsible for that error.
- Live service `GET /demo/distance-monitor-v1.png`: **200**, `image/png`,
  1,969,449 bytes, SHA-256
  `04e08a59210e65a04afcde8b4884f632fe65b87875aedbb0a723ed7b69c12fb5`.
- Live HTML references new build `index-B8ZO7c53.js`.
- React review: sample is derived during render, no effect/fetch/new persistence,
  immutable inputs, explicit alternate text, local error/retry handling and no
  new image-generation side effect.
- `git diff --check`: no whitespace errors (existing line-ending advisories).

Skills used: `agent-browser`, `agent-browser-verify`, `react-best-practices`.
Browser interactions used the supported in-app browser API. The temporary
QA tab/server were closed; the user's original tab and draft were untouched.
