# Cloud wiring photo check

## Scope

The project Pin guide offers **AI check** in preparation and active wiring steps.
It uses the selected image-capable Codex model through the existing ChatGPT-authenticated
App Server bridge. It does not use image generation, Ollama, local wire tracing,
local color judgments, legacy verification fusion, or electrical tests.
The supported module catalog is unchanged: Pi 5, HC-SR04, HW-123 and MRD-TF240.

Local object detection/tracking is used solely to obtain crop coordinates. A cloud
opinion is never an electrical measurement or an automatic manual confirmation.
This deliberately supersedes the earlier proposed local-CV + cloud wire-verdict fusion.

## Capture contract

- On click only, capture original camera context. Add neighboring-pin detail crops
  only when both targets have valid localization.
- Prefer the existing same-frame image/tracking packet. `display_only` poses remain
  fallible crop hints; they are NOT promoted to wiring evidence.
- With real-time tracking off, use the atomic Pi/frame and module/frame pairs.
  Each crop uses its own source frame; the age is <=1s and inter-frame gap <=250ms.
  Different frames and their timestamps are disclosed to the model and UI.
- Missing, stale/held/recovering, mismatched-size/frame, offscreen or wrong-module
  localization falls back to a fresh original camera overview (`capture.mode=overview`),
  with no projected target coordinates or historical anchors. Local recognition is
  not a prerequisite. Before endpoint inspection, one optional cloud region-location
  turn proposes whole-header/module/breadboard context boxes for missing details.
  Local code validates each box independently and crops the original decoded pixels
  to PNG, retaining the overview, exact source frame, bounds and neutral reading copy.
  These `context_crops` are fallible object crops, NOT accurate pin localization or
  extra viewpoints. One invalid/unlocatable region does not discard the other crop.
  Absent objects/unreadable pins remain uncertain; no generated detail or guessed labels.
- Never substitute the latest image under a historical pose. No camera frame, invalid
  pixels or a frame older than 1s fails before calling the cloud. Synthetic camera
  sources cannot be submitted as physical evidence.
- Pictures contain no frontend overlay, artificial expected wire, or generated concept.
  The projected pin coordinates are separately labeled as fallible hints.
- The cloud must independently inspect identity/orientation/connector bases and the
  visible wire path. Matching colors alone do not prove the same wire.
- Preserve independent Pi camera calibration warnings; cloud advice does not upgrade
  the existing physical verification gate or calibrated accuracy claim.

## API and lifecycle

### Independent endpoint inspections (updated 2026-09-13)

This replaces the single-turn inspection described in the historical sections below.
One button press now runs **module contacts -> Pi contacts -> wire route**, with
separate ephemeral Codex turns. The requested model and reasoning effort are preserved;
there is no silent upgrade. Normally at most three calls; missing endpoint details
add at most one localization call (60s cap), so the fallback maximum is four.
Endpoint/route calls retain the 90s per-turn cap and shared 210s pipeline deadline.
There is no automatic retry. A route call occurs only after BOTH endpoints are target;
empty/wrong/uncertain/occluded endpoints skip that extra call. This can consume more
quota than the previous single-turn check; the UI discloses localization and max_calls.

`app/cloud_connector_inspection.py` provides the dedicated endpoint schema and prompts.
Each relevant pin position records bare tip / housing / breadboard / hidden / uncertain, separately
from connector color and exact target identity. Pi numbering and pin-1 orientation
hints come from the existing board Profile/capture, never a new AI-specific pin table.
Hints are explicitly fallible; neither a hint nor a color proves insertion. The route
turn cannot rewrite the independently observed endpoint states. Contradictory pin
inventory/connector references demote the result; they cannot upgrade it.

Two new `pi_contact` / `component_contact` PNGs focus on the pin/housing interface,
with generous margins for the housing and wire exit. Originals remain unchanged.
Integer nearest-neighbor copies preserve decoded source pixels, and metadata records
exact source crop, rotation and scale. These are NOT new angles or super-resolution.
The Pi reading image is quarter-rotated so the hinted pin-1 end is up, only when
pin-1 and another odd-row anchor are available. Otherwise it remains unrotated.
Module prompts include the existing Profile's canonical viewing orientation. Neither
operation proves the physical pin identity. Conflicting inventories lose their pin
assignments in the displayed result, while raw observations remain in stage diagnostics.
If the cloud also cannot locate regions, inspection still uses the overview. Nothing new runs in
the video tracking loop; no GPIO, deployment or manual confirmation is changed.

Jobs expose `inspection.phase`, actual `effort`, `max_calls` and completed `stages`
(input image names, latency and raw structured observation). Errors retain completed
stage evidence but do not return a successful result. UI shows progress and a compact
per-pin inventory in Details; legacy result rendering remains supported.

Breadboard contact is not forced into a direct female-housing verdict. The cloud
reports the identified module pin's insertion hole and jumper hole independently,
including row, column, visible insertion and confirmed board/numbering/topology.
Only distinct holes in the same standard A-E or F-J terminal strip can support a
`breadboard_link` claim. Different rows, center-gap crossings, power rails, hidden
chains or unreadable insertion points do not establish a link. This is consistency
checking of cloud observations, not a measurement of internal continuity. UI shows
the two reported holes and preserves unknown results. Pin identity still comes from
actual labels/orientation, never wire color or user-provided expected answers.

Nullable breadboard fields remain compatible with saved legacy replies locally,
but exported cloud schemas explicitly require every property (nullable when absent),
omit defaults and keep `$ref` free of sibling descriptions. Regression tests check
these provider constraints, not only local Pydantic validation.

#### Real-photo regression evidence (not a general accuracy benchmark)

Saved results are in `runs/diagnostics/wiring-connectors-20260909/`:

- `contact-isolated-medium`: Sol/medium, current failed frame's module reading image:
  correctly distinguishes three exposed pins, brown GND housing and loose orange plug.
- `contact-isolated-55-low`: same module image, GPT-5.5/low: same contact distinction.
- `contact-staged-55-low`: old saved full capture, GPT-5.5/low: module correct but Pi
  pin-1 direction reversed. This intermediate failure is retained, not hidden.
- `contact-staged-55-ref`: same original capture with existing Profile numbering and
  fallible orientation hints: module housing and loose orange plug distinguished;
  Pi brown/tan housing distinguished from loose red/orange plugs. The model reports
  GND-to-P6 and a traceable path (`looks_matched`). This is a cloud visual opinion,
  not an independently measured exact-Pi-pin or electrical verification. Cloud stage
  latencies were 16.84 + 27.73 + 8.74 seconds in this one replay, not a performance SLA.
- `contact-negative-trig-55-low`: unchanged current module image, requested TRIG
  instead of GND: correctly reports TRIG bare, while preserving the plugged GND.

Additional live-camera artifacts are in `runs/diagnostics/wiring-contact-live-64ba64bf/`:

- `baseline.json`: actual browser-triggered GPT-5.5/low check, 78.0 seconds over three
  cloud stages. The module's brown fitted plug and loose orange plug were distinguished.
  Pi contact appearance was recognized, but exact numbering and the endpoint conclusion
  conflicted; the result was `uncertain`, not a pass. Manual progress stayed at 1/14.
- `upright-staged`: the same original photos with the Pi rotation change. Contact
  appearance was still recognized, but module label order and Pi identity were inconsistent.
  Both endpoint conclusions were demoted. Rotation alone did NOT fix exact-pin accuracy.
- `final-component`: request, prompt and derived images were saved after the final
  schema wording/canonical-orientation clarification, but no result artifact was returned.
  This attempt is incomplete and must not be counted as a successful recognition test.

The implementation improves separation of visible contact from uncertain pin identity;
it has NOT demonstrated reliable exact-pin verification. No further retries were used
to select a favorable final result. Only a small set of saved captures and one
unconnected-pin counterexample are covered.
Do not claim general reliability for wrong adjacent Pi pins, occlusion, alternate
angles, HW-123 or TFT without more labeled physical examples. No new side-angle photo
was available or invented. Test fixtures are never fed as expected model answers or
injected into the current user result.

Code regression validation: 180 related backend tests, 70 frontend tests, bilingual
key parity (588 keys), TypeScript and Vite build passed. These validate contracts,
pixel-preserving crops, lifecycle and rendering, not real-world recognition accuracy.

#### Schema compatibility hotfix (2026-09-09)

The final endpoint field description made Pydantic emit `description` beside `$ref`
at `properties.endpoint`. The real Codex provider rejected this with
`invalid_json_schema` / HTTP 400 before inspecting images. Local response validation
and the previous mocked-cloud tests did not catch that request-schema restriction.
The field is now a bare reference; its state meanings remain in the endpoint prompt.
No model, capture, response field, wiring progress or deployment behavior changed.

A regression test reproduces the rejected reference shape before the fix, recursively
checks all three wiring schemas, and checks the actual schemas passed to the mocked
bridge in all inspection stages. Related backend tests now pass 183/183.
One real GPT-5.5/low endpoint replay returned valid structured data after the fix:
`runs/diagnostics/wiring-contact-live-64ba64bf/schema-ref-fix.json` (request/capture/prompt
alongside it). This validates cloud schema acceptance, not general exact-pin accuracy.
The [official Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas)
documents the supported subset and bare definition-reference examples; the specific
sibling-keyword rejection was established by the actual provider error.

Replay tooling now supports `--staged`, isolated `--endpoint`, explicitly chosen
`--photo`, `--model`, `--effort`, and `--component-pin` counterexamples. `--run` is always
required for cloud use; save request/capture/result artifacts and use unique output
names. Snapshot downloading ignores derived views and preserves original hashes.
Normal runtime photos still expire after 15 minutes in memory.

The shorter endpoint contract and fixed-photo comparisons follow
[OpenAI's prompting/evaluation guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.5).
[Image spatial-localization limits](https://developers.openai.com/api/docs/guides/images-vision#limitations)
still apply; decomposition and crops do not guarantee correctness.

### Structured connector evidence and readable input copies (2026-09-09)

This supersedes the earlier prompt-only change below. The model now returns
`visual_observations` before its endpoint conclusions: each visible candidate has
an ID, position, housing contact (`covers_pin`, `detached`, `uncertain`), rear-exit
insulation color, and evidence. Each header separately records target identification,
target tip visibility and an optional target connector ID. A visible metal shank
between PCB and housing is not evidence that a Dupont plug is detached: distinguish
the distal tip from the shank and fixed black header strip.

`reconcile_opinion` checks only internal consistency of those model fields. It cannot
detect a visually wrong but internally consistent answer. Contradictory endpoint
claims are demoted to uncertain, with `consistency_issues` shown in the UI; they are
never promoted to a match. Candidate colors remain in the inventory even when no
candidate can be associated with the requested pin. No pixel color recognition,
wire classifier, manual completion, electrical verification or deployment is added.

For located captures the original 3 (or asynchronous 4) JPEGs remain byte-identical.
Two additional `pi_reading` / `component_reading` PNGs expose enlarged close-ups to
the model and the photo disclosure. Component rotation uses the existing vision
profile's pin-row order and fallible captured pin hints, rounded to a quarter-turn.
The Pi copy is enlarged only. Integer nearest-neighbor scaling (up to 3x, 1024px
bound for the existing crop sizes) preserves decoded source pixels exactly;
there is no enhancement, inpainting, generated wire or invented pin. Derived view
metadata names its source, rotation and scale; original coordinates are not copied
onto rotated views. With no valid crops, the original overview-only path is unchanged.

App Server `localImage` inputs explicitly request `detail: original`, verified
against this installation's generated `TurnStartParams` / `ImageDetail` schema.
The selected model/effort, single request per button press and 120-second timeout
remain unchanged. This is on-demand work, not an extra real-time video pass.
The [official image input guidance](https://developers.openai.com/api/docs/guides/images-vision#limitations)
notes small-text, rotation and spatial-localization limitations; readable copies
do not guarantee pin accuracy. The prompt is shorter and observation-oriented,
following [official prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6#prompting-best-practices).

The compact findings distinguish an empty target, a visible housing whose pin is
unknown, and an unreadable wire color. Detached candidates are in Details rather
than being presented as the target wire. A traceable candidate route is shown even
when the exact target endpoint remains unconfirmed; this is not a matched verdict.

#### Fixed-photo replay, not a hardware pass

Diagnostic originals/baseline/hashes and actual responses are saved locally in
`runs/diagnostics/wiring-connectors-20260909/`. They are not production defaults,
not fed as expected answers, and not inserted as a current camera result.
`tools/replay_cloud_wiring.py` saves a cached job with `--capture-url`; `--run` is
an explicit opt-in for exactly one real cloud request, with no automatic retries.
The diagnostic files persist until manually removed; normal UI captures still
use the existing 15-minute memory-only cache.

- Original failed job: `c6cd4425026b425b82aec3233961207d`, frame 3452, HC-SR04 GND
  to Pi Pin 6. Both tips were reported empty; module evidence claimed all four
  tips were bare.
- Replay `connector-v2`: new observation schema/prompt, same three images,
  GPT-5.6-Sol / medium. Still incorrectly reported the module's brown connector
  detached. Its JSON was saved successfully; a Windows stdout encoding error
  happened only when printing it, not during the cloud request. Runner now uses UTF-8.
- Replay `connector-v3`: same unchanged original pixels plus the two reading
  copies, same model/effort, explicit original detail. The raw cloud response
  identified the brown housing covering HC-SR04 GND, the three neighboring bare
  tips, and the separate orange dangling housing. It traced the brown wire to a
  Pi connector, but did not establish the exact Pi pin. The reconciled verdict
  remains `uncertain`, with no consistency errors and no electrical verification.

This is a single positive regression case after an unsuccessful intermediate
version, not a recognition-accuracy benchmark. Adjacent Pi pins, different scenes,
occlusion and the other modules still need labeled real-photo evaluation. Unit tests
cover all three profile rotations, lossless pixel correspondence, original hashes,
PNG MIME types, contradictory fields, legacy UI responses and no hardware mutations.

Verification completed: 127 related backend tests, 67 frontend tests, i18n parity
and the production build passed. Restarted BoardVision, reloaded the final bundle,
and verified the camera, original GPT-5.6-Sol selection and saved 1/14 manual records.
Pi plus all three component models and preprocessing report CUDA without fallback.
Browser fixture checks covered candidate-contact details and empty-target wording;
no browser console errors were recorded. No live-camera check, manual confirmation,
Pi deployment or electrical test was triggered during the restart verification.

### Connector-first observations and result reading window (2026-09-09)

The photo prompt now separates four tasks: observe individual Dupont housings,
follow each rear wire exit to visible insulation, match observed connectors to the
requested pins, then trace the route in the overview. Endpoint evidence retains
visible neighboring or dangling connectors instead of treating an unknown target
color as an absence of all wires. The fixed black header strip, individual housing
and colored insulation are distinct objects. `empty` requires an independently
identified, visibly bare target pin; adjacent bare pins and hidden bases do not
justify that claim. No capture-specific color/pin answer is hard-coded.

This uses the existing structured opinion fields and one cloud call. Models,
effort, photo pixels/crops, target catalog and verdict rules are unchanged.
The numbered observation stages and bounded example follow the official
[prompt-structure guidance](https://developers.openai.com/api/docs/guides/prompt-engineering#message-formatting-with-markdown-and-xml).

Jobs now expose `completed_at`. The 30-second result reading window begins on
successful completion, not capture: a 47-second cloud response no longer expires
solely due to its own latency. The backend uses a private monotonic completion
timestamp; the frontend uses the returned completion time. Legacy results without
it fall back to capture time. Captured-at/frame metadata are never rewritten.
Movement/loss, runtime change and camera failure observed during the pending call
remain sticky historical flags after completion; the reading window never revives
those results. Fifteen-minute cache retention is still measured from submission.

Regression tests exercise simulated 47/119-second calls for both crop and overview
captures, completion-window boundaries, in-flight movement/loss/runtime/camera
failure, legacy frontend responses and malformed timestamps. No real cloud
request is made by these tests; real-photo accuracy still needs a labeled comparison.

Verification: 104 related backend tests and 62 frontend tests pass, including i18n
parity and the production build. BoardVision was restarted and the new bundle loaded
in the browser. Pi 5 and all three component models/preprocessing report CUDA with
no fallback; the camera and Pin overlays resumed. Existing 1/14 manual records and
GPT-5.6-Sol selection were preserved. No new cloud photo request, manual confirmation
or Pi deployment was triggered; temporary old photo results were cleared by restart.

### Color and path observations (2026-09-09)

The same single cloud request now returns independent `wire_colors.board` and
`wire_colors.component` observations (insulation color, visibility and evidence),
a cloud color comparison, and `wire_path` visibility/evidence. Color observations
remain available when the exact pin or the whole route is uncertain. The compact
guide is unchanged; Details shows both colors, expandable color evidence, and the
observed route/obstruction. Older in-flight results without these fields still render.

The prompt distinguishes insulation from connector housings, PCB/LED colors and
adjacent wires; it forbids assuming colors from GND/VCC conventions. A crossing
does not automatically imply uncertainty when the visible paths can be distinguished.
An ambiguous crossing or hidden identity still cannot establish the same wire.
Matching colors do not imply a matching connection; a color difference alone is
not a wrong-wire verdict. A positive overall result requires both target endpoints,
a consistent wire identity and a traceable path. Clear path evidence may still be
useful when the color name is uncertain.

No additional cloud calls, local color classifier, model/effort change, image
enhancement, detector change or automatic guide confirmation is introduced.
Regression fixtures verify the contract, not real-photo recognition accuracy;
accuracy improvements require labeled before/after tests on identical real captures.

Verification for this change: 125 related backend tests and 52 frontend tests pass,
along with i18n parity and the TypeScript/Vite build. Component render tests cover
Chinese/English color evidence and older responses. Restarted BoardVision and loaded
the new bundle; the camera/guide/AI button render, the existing 1/14 manual records
remain, and all four detector/preprocessing backends report CUDA. Page reload returns
the transient guide to preparation; it does not erase the saved manual records.
No cloud photo request or real-photo before/after accuracy evaluation was run for
this change; no claim of measured color-recognition improvement is made.

### Endpoints

`POST /api/guidance/cloud-checks` accepts project id/revision, catalog/profile versions,
exact wire/module/pins/connection kind, selected model/effort and locale. Validate
against the shared catalog before starting. No Pi credentials, source code, user
conversation, or arbitrary file paths are accepted.

The response is `202 {job_id}`. Poll `GET /api/guidance/cloud-checks/{job_id}` once per
second while pending; `capturing -> checking -> completed|failed`. Results include
the original images via `/images/{name}`, capture time, source frame ids/crops,
model, timing, endpoint opinions and `authority=visual_advisory`.

The service shares the design service's busy reservation. One cloud check at a time;
do not queue an old photo behind design/image generation. The bridge verifies image
input capability, disables tools/image generation, enforces the per-stage/total deadlines above,
and never silently substitutes a model or automatically retries billable work.
Polling errors offer **Read result**, not another cloud request. Missing/expired jobs
offer a new capture. Navigation/unmount cancels frontend polling, not a cloud call
already sent; background work still releases its reservation on completion/failure.

Pictures/results stay in a bounded memory cache (12 jobs); endpoints expire after
15 minutes and a backend restart clears them. Temporary image input files are cleaned
after the complete inspection. Browser project storage never stores cloud photo verdicts.

## UI and boundaries

The compact guide shows a button and a short status; Details contains the cloud's
reasoning and expandable exact photos. Collapse never changes wiring progress.

### Result template and readable typography (2026-09-09)

Results now use a fixed presentation: conclusion, the expected target, three short
observation rows (Pi end, module end, wire route), and a highlighted next step.
Observed pin/color/path values come from the existing cloud result, never a local
wire classifier. Next-step copy is a deterministic UI suggestion based on which
endpoint/path is unclear or wrong; it does not rewrite the AI verdict. Divider,
stale-photo, busy and error states remain distinct from a visual match.

Full AI prose, per-endpoint color evidence, limitations and model/capture metadata
are collapsed separately from the photo disclosure. Internal photo IDs in prose
are displayed with human-readable view names, without changing the observation.
The compact camera card uses short conclusion/action copy and the existing buttons.
Details prioritizes the result above module progress. Headings use 20px, primary
body text 16px with 1.8 line height, solid backgrounds and clear section spacing.
The Chinese font stack, contrast, narrow wrapping and keyboard focus are explicit.

This is frontend-only: no prompt, model selection, API, capture, GPIO or deployment
changes and no extra cloud request. Re-reading a failed poll still resumes the same
job; a stale/error/busy state cannot display an earlier green success headline.
60 frontend tests, i18n parity and the production build pass. Browser verification
covered the actual result component with labeled test fixtures (Chinese/English,
expandable evidence and historical status), a 390px viewport without horizontal
overflow, and the production guide with preserved 1/14 manual records. Actual
production typography reports 20px headings and 16px / 28.8px body text. No cloud
photo request or physical wiring verification was performed for this UI change.
The local-only fixture gallery is reproducible with
`node frontend/tools/cloud_wiring_preview.mjs` at `http://127.0.0.1:8111/`;
its buttons are disabled and all data is explicitly labeled as test-only.

### Guide lifecycle

The project guide has an always-visible **Restart wiring** action. It resets the
module/step and this project's manual wiring records, preserving design, conversation
and code drafts. Each restart increments a run key, so a pending earlier cloud result
cannot appear in the new run, including when restarting on the same first step.
Start/next/manual confirmation do not require localization, a backend connection or
preparation/power-off checkboxes. Electrical instructions remain non-blocking information.
This changes the project guide only, not the independent legacy wiring guide.

Loss/movement of the localized target marks a cropped result historical; absence of
localization alone does not invalidate an overview result. A changed runtime/camera,
camera disconnection or 30s since successful completion marks either result historical. It cannot turn current
again just because tracking recovers. Changing steps, project version, restarting or
leaving the guide hides the previous card. Always label capture-time-only:
wire movement without board movement is **not** automatically detected locally.

Results: `looks_matched`, `suspected_issue`, `uncertain`, `needs_review`.
ECHO/divider cannot become a complete match: concealed breadboard topology and resistor
values still require manual/electrical verification. Existing unresolved hardware
warnings and deployment restrictions remain unchanged.

No percentage is shown as calibrated accuracy. No next-step advance, confirmation,
power-on, program change, upload to Pi or deployment follows a visual opinion.

## Exhibition workflow checks (2026-09-09)

- Frontend regression tests cover manual start/advance with no checks or detector
  evidence, restarting from every phase, resetting only wiring records, and overview
  result expiry independent of localization.
- Backend regression tests cover overview fallback across invalid/missing local
  tracking, operation with real-time tracking off and no model poses, no local wire
  or color verdict calls, and rejection of missing/stale/invalid/synthetic photos.
- The fallback does not improve local object detection or manufacture Pin overlays.
- Verification: 244 related backend tests, 48 frontend tests, i18n parity and
  TypeScript/Vite production build passed. Restarted the local backend and loaded
  the new production bundle in the browser.
- Live browser check: with no TFT localization, Start and AI check were enabled and
  no preparation checkboxes were present. One actual GPT-5.6-Luna request sent a
  1920x1080 original overview for TFT GND -> Pi Pin 20; the model returned uncertain
  because the specified TFT was not visible. The exact photo loaded in Details.
  Existing manual records remained 8/14; no physical confirmation or deployment
  was triggered. Restart reset behavior was tested with fixtures, without clearing
  the user's saved records during browser verification.

## Verification (2026-09-08)

- Unit/API tests cover source-frame crops, all three module identities, hidden/stale
  targets, profile/pin mismatch, cloud format/error handling, single flight, retention,
  model image capability, disabled tools, and zero manual/deployment mutation.
- Frontend tests cover request allowlisting, capture-age/pose-loss handling and existing
  workflow regressions; TypeScript/Vite build and i18n parity checked.
- One actual GPT-5.6-Luna camera check completed for HC-SR04 GND -> Pi Pin 6:
  cloud reported no visible connecting wire at either endpoint. Original 1920x1080
  overview and both 321x321 crops loaded. Manual progress remained 0/14.
- Observed tracking display around 21-22fps; this is not a controlled performance benchmark.
- Real correct-wire / adjacent-pin / crossing-wire / occlusion accuracy remains to be
  evaluated on labeled captures. The successful cloud roundtrip is not hardware validation.

Protocol reference: https://learn.chatgpt.com/docs/app-server#turns
