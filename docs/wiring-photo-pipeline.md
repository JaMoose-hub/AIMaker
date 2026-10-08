# Shared POC wiring-photo pipeline

The three-photo wiring review shares the POC's exit observations and native-pixel
colour audit. Fast mode observes exits, labels, terminal states and Pi positions
in one compact cloud call. Thorough mode retains separate exit and pin calls.
The shared implementation lives in `app/photo_observations.py` and
`app/wiring_photo_pipeline.py`; the standalone POC imports the same primitives.
`GuidedWiringReview` owns user actions, budget, persistence and revision guards,
not perception/image preparation.

## Data flow

1. Verify each frozen photograph's capture ID, SHA-256 and oriented size.
   Decode a copy, apply EXIF orientation and ICC-to-sRGB conversion. The Demo
   sends a separate analysis copy: long edge at most **2048**, JPEG quality **92**,
   4:4:4 chroma (subsampling 0). Smaller images/crops stay lossless PNG and are
   never enlarged. Crop from the original before applying this bound. Keep original
   photos, hashes and native pixels for the POC audit. Record source dimensions,
   source crop, supplied dimensions, encoding and supplied hash separately.
   This supersedes the earlier full-resolution-PNG-only transmission rule.
2. **Fast mode (`v11-row-evidence`):** one budgeted `fast_photo_review` request
   returns one connector list per supplied view: original-normalized wire exit,
   visible colour, label/housing association, Pi row/column candidate and short
   evidence. Independent module-terminal observations include bare terminals.
   No symptom, expected wiring or previous diagnosis is sent as visual evidence.
   Board layout and module pin labels are naming references. The server expands
   this compact response into the existing validated inventory and pin models;
   it does not make a second cloud call or infer full wire routes. Continue with
   the local pixel audit and deterministic comparison below.
3. **Thorough mode — exit inventory:** one budgeted image request identifies housing wire exits,
   insulation colours, visibility and optional small wire regions. It receives
   no expected pins, expected wire counts or wiring answers. Coordinates are
   normalized 0..1000 in the full original overview, including when inspecting
   a detail crop. Duplicate/foreign IDs, nonfinite coordinates and reversed
   regions fail closed.
4. **Local pixel audit (both modes):** the original POC HSV vote samples native pixels at
   the proposed exit. Its result and disagreement are retained separately.
   It neither replaces semantic colour nor establishes a physical pin.
5. **Thorough mode — pin/route review:** a second, independent image request reads labels,
   orientation, header rows and actual attachment, retaining inventory IDs. Its
   compact output omits repeated colour, position and exit-evidence fields; the
   application restores them from the first observation and new pin evidence.
   Both prompts request one short concrete sentence per observation. No third
   model call is needed to produce the chat summary.
   An unknown pin does not erase its exit/colour. Matching colours and intended
   connections cannot establish a strand or a wrong pin. Existing deterministic
   comparison rules and explicit human review still own the final workflow.

## Stability and cost

- All requests use the existing session's consent, chosen model, restricted
  bridge, six-call session cap and one shared 210-second analysis deadline.
  Fast analyses reserve one call; thorough analyses reserve the one or two calls
  required by the current source cache. No fallback model or automatic retry is added.
- Inventory cache keys include pipeline version, requested model/effort/mode,
  photograph round, capture ID, hash, crop and module identity. Unchanged Pi views
  can be reused when changing modules. A retaken view is independently recomputed.
- In thorough mode, a successfully completed inventory is saved behind the same round/revision
  guard. If pin review fails, a manual retry can reuse that inventory, consuming
  only one new request. Late results cannot attach to a newer photograph/round.
- Partial rechecks replace the changed view and keep source-matching observations
  from the other views. Full-route claims may survive only when both endpoint
  sources and their input keys remain unchanged; a changed endpoint invalidates
  its old route. New partial-view observations do not invent a full route.
  Conflicting/duplicate colours remain advisory; no automatic wiring confirmation,
  GPIO operation or testing is introduced.
- Receipts include image inputs/hashes, per-stage elapsed times, model receipts,
  cache use, pipeline version and local-vote provenance. Limit requested source
  pixels to 48 million before decoding the batch; larger sources fail visibly.
  Analysis derivatives are explicitly recorded as resized, not original pixels.
  `analysis_mode`, `cloud_call_count` and `pipeline_elapsed_ms` distinguish actual
  cloud work and complete pipeline timing; the enclosing review retains its full
  elapsed time. The last model-call timer is not the total user waiting time.
  `poc-exit-pin-demo-2048-v3` also retains view-level header observations when
  the wire-exit/connector inventory is empty.

## Demo reply

### Row-position checks and unlocated issues

`row_position_check` prioritises a check when the module label and colour are
unambiguous and each of two source-valid Pi views has exactly one candidate of
that colour. The two candidates must agree on inner/outer row, disagree with
the intended row, and include at least one clearly visible housing base. Missing
seats, repeated colours, conflicting observations and independently traced routes
block this inference. Exact column estimates are not required to agree.

Since `v11-row-evidence`, a Pi seat may retain an observed row with `column=null`.
The housing-base region, source binding and visible board-centre/edge orientation
are still required. The model explains why the column cannot be counted; identifying
the Pin 1 end is unnecessary for a row-only observation. The server leaves its
`pin_id=null`, and the UI says the position within the row is unknown. These seats
can support a guarded row-position check, but cannot supply an exact GPIO or a
reciprocal pin-swap finding. Free-text descriptions are not parsed into row identity.

This lower-strength finding remains `uncertain` and says to check the named
wire's position; it does not name a confirmed wrong pin, declare a swap, or prove
that same-colour ends are one strand. Missing-terminal and stronger reciprocal
swap findings retain priority. If every result is merely uncertain and no specific
clue is available, the main card says the issue has not been located and does not
automatically point to the first GND wire. Per-wire manual review remains available.

### Useful suspicions before complete route confirmation

`poc-exit-pin-demo-2048-v8-candidate-seat` identifies a concrete suspected wiring problem without demanding
an entire visible wire route from three endpoint close-ups. Pi observations now
record the observed inner/outer row, column counted from the Pin 1/2 end, visible
housing-base region, orientation anchor and counting evidence. A partially hidden
position may be estimated from visible pin pitch and intervening empty/occupied
positions, with that estimate stated in the evidence; every boundary need not be
visible. Equally plausible unresolved positions remain unknown. The application
maps those observed positions through the saved board profile. An exit coordinate
or the requested photographing row cannot supply a pin identity. These remain
photo-based position candidates, not a measurement of internal metal contact.

A reciprocal mismatch between two known module endpoints and two independently
located Pi endpoints may produce `suspected / reciprocal_endpoint_swap`. The
comparison groups agreeing views of the same pin, checks competing colours and
contradictions, and treats colour correspondence as a hypothesis. The resulting
`candidate_board_pin` and partner wire are distinct from route-confirmed observed
endpoints. `same_wire` remains uncertain. Colour agreement alone never produces
an automatic pass, and non-direct connections are not treated as colour swaps.

Chat leads with the suspected pair and one manual check. The underlying endpoint
observations, expected pins, source images and limits remain in the existing
details. A clear module label is retained when its physical contact is hidden.
The user does not need another generic retake merely because the full wire path
is outside these close-ups. This advisory comparison adds no cloud request.

### Module labels and attachment are separate

`poc-exit-pin-demo-2048-v5-module-identity` treats module photographs separately
from Pi header photographs. Pi views still require board orientation, row identity
and independently observed attachment. Module views read their own printed labels,
housing positions and wire exits; Pi row/counting rules do not apply.

`module_pin_id` and `module_pin_evidence` preserve a visible label-to-housing
association even when the PCB hides the attachment. They never restore a guarded
`pin_id`, prove seating/continuity, or confirm a wire. Existing structured model
labels with uncertain contact can supply this observation; prose is not parsed
into a new identity, and detached housings cannot supply it. Historical saved
results are not rewritten.

Recognized module labels retain their wire colours in chat/details. The flow moves
to missing Pi evidence rather than repeatedly requesting the same module photo.
If only attachment remains uncertain, it asks for a manual seating/route check.
Truly ambiguous module label-to-housing associations still request a module view.
This change adds no model request and preserves the two-stage image budget.

`poc-exit-pin-demo-2048-v6-visual-seat` further defines `covers_pin` as visible
external housing placement at a header position. An opaque female housing normally
hides its internal metal tip; that alone is not a reason to erase an observed
position. A hidden housing base, ambiguous row/column, or unresolved orientation
still remains uncertain. Pi orientation may use visible board landmarks; a printed
number 1 is not mandatory. Count actual header columns including empty positions,
not the order of wire exits. Profile row/position metadata is a naming reference,
not projected-image proof. Visual placement never certifies insertion depth or
electrical contact.

Visible header condition and identified connected pins are separate evidence.
The second model response can report uncovered pin tips, visible housings,
occlusion or uncertainty, even with zero connectors. A bare shank below a housing
is not an uncovered pin tip; neither condition proves which wire is missing.
Uncovered tips and detached housings remain photo observations with a manual
placement check, rather than automatically becoming a request for a clearer photo.
Old completed observations retain the model's view-level wording without parsing
it into a new fault verdict. The summary binds that wording to its photo source.
This uses the same two model calls. Human confirmation and hardware results remain
separate.

The existing shared chat first shows one concise finding and one next step for
the photo set. When several uncertain wires need the same missing view, recommend
that view once. Suspected wrong connections take priority. Two rounds without
progress stop the retake recommendation and offer tracing the wire manually.
The backend freezes the summary and its result rows on the original message;
legacy messages use their own result or an exactly matching review revision.

The primary desktop action retakes only the recommended view. Expected
connections, endpoint candidates, POC colour votes, timing, original text and
per-wire human decisions remain available in collapsed sections. Manual review
is optional for reading the AI result; confirmed guide pins still require the
original explicit per-wire action. Reading a summary never confirms any wire.
The phone uses the same read-only result card and retains its existing action
permissions. For a result-stage retake it directs the user to the desktop retake
control; the initial phone photo-request actions remain available as before.
Earlier photo/analysis instructions and framing examples are
collapsed; user messages and failures remain visible, with error details retained.

Ask for only the missing endpoint's view; a pin that is visible in one Pi view
does not require another photo just because it is hidden in the other. Guide
controls and hardware tests retain their existing ownership. This presentation
adds no model call or hardware flow. Smaller inputs and shorter replies are not
claims of unchanged visual accuracy or guaranteed inference latency.

## Photo delivery visibility

### Inner and outer Pi header photos

New photo reviews use `capture_plan: pi_rows_v1` and still collect three views:
Pi inner row (toward the board centre), Pi outer row (toward the board edge), and
the module header. Existing `pi_side_a` / `pi_side_b` transport IDs remain stable.
Each new saved Pi photo records its intended `target_row`; the analysis manifest
provides a source-bound `requested_row` to both existing cloud stages. These are
capture instructions, not evidence that the row was actually visible or identified.

The user photographs the inner row from the board-centre side and the outer row
from outside the board edge, at an angle that exposes the connector insertion
bases. Keep a board corner/orientation landmark and nearby header context in each
view. The framing illustration highlights the requested row. A full overview and
any manually selected crop continue to come from the same original photograph.
No additional photo step or cloud request is introduced.

The model must identify the board direction and physical row from actual pixels
before assigning a pin. Camera left/right or the requested row label cannot
establish pin numbers. Hidden insertion points remain uncertain. Legacy two-side
photos and frozen chat messages retain their original meaning; a new capture plan
does not silently relabel them. Plan and row targets participate in cache identity.

Saving a crop keeps its original photo and explicit photo selection. It does not
send a new model request. Start analysis submits the full overview and the saved
crop; ordinary text chat receives the saved photo/analysis state without new
images. Chat distinguishes missing views from a complete set awaiting analysis,
and only refers to findings whose existing analysis input key matches the current
captures, hashes, crops, component, round and model policy.

Desktop crop controls distinguish unsaved coordinates, saved inputs awaiting
analysis and a completed analysis of that exact region. The shared desktop/phone
receipt lists overview/detail dimensions and explicitly labels reused views.
Completed labels require matching review/round, source capture/hash/size and crop
pixels. A retained old receipt cannot certify a changed crop. Historical messages
cannot borrow a newer review's receipt. These labels report image delivery and
analysis completion, not correct wiring or electrical continuity.

## Plain-language wiring guidance

### Identified uncovered module terminals

`poc-exit-pin-demo-2048-v9-module-terminals` adds a separate per-terminal module
inventory. The pin stage records a visible terminal's label, uncovered/covered/
uncertain state, supporting observation and optional region. Mixed occupied and
uncovered positions can coexist in the same photo. Pi connector observations
retain their existing row/column procedure. No extra model stage is added.

The server binds terminal observations to the module photo's capture ID, source
hash and dimensions. Only a known, source-current uncovered terminal that has an
expected design connection can produce `suspected / unconnected_terminal`.
Conflicting states or an identified covering connector block the accusation.
An optional terminal omitted from the design remains an observation, not a fault.
An empty exit inventory, an unknown label or an old free-text note does not prove
absence. Old results remain readable with an empty terminal list.

Missing-terminal findings take priority in the short summary and do not require
another photo when the terminal itself is already identified. The reply names
the module label and offers the designed connection; it does not invent a wire
colour or ask the user to trace a wire that is not visible. Human confirmation,
functional tests and electrical evidence remain separate.

The primary result names the component label and, when observed, its wire colour.
For a visible endpoint-colour mismatch, show a short suspected-miswire message,
the colour-difference reason and one tracing/checking action. A hidden connection
alone does not imply a loose connector or a miswire. Retain concrete observations
of uncovered pins or detached housings and distinguish them from insufficient views.

Physical Pin and GPIO references belong in expandable details. The optional
designed-position locator uses the saved expected board pin/index and the existing
Pi 5 J8 profile/row helper. If that pair no longer matches the profile, omit the
locator rather than substituting a current design wire. The diagram labels the
inner/outer rows and the starting end away from USB/Ethernet. It depicts a designed
connection, not a measured or photo-confirmed position.

The shared desktop/mobile summary can present stored structured evidence using
these labels without overwriting history, changing diagnosis status or recording
a manual confirmation. Viewing or switching the locator performs no hardware
action and requires no new cloud analysis.

## Accuracy acceptance

Software fixtures verify the integration and safety contracts, not a 95% real
scene success rate. Use independent, physically checked Pi 5 / HC-SR04+ / TFT
cases, grouped by capture session, with correct and intentionally incorrect
connections, repeated colours, occlusion, glare and varied cameras/light.
Reuse frozen POC inputs for paired regression comparisons, but keep those
development examples separate from held-out acceptance data.

Report insulation-colour accuracy, exact physical-pin accuracy, correct
endpoint/strand pairing and fault detection separately. The end-to-end metric
requires both endpoints and the fault finding to be correct; uncertain cases
must not disappear from the denominator. Also report coverage, missed faults,
false accusations, dangerous false passes, retakes and complete user-visible
P50/P95 time. A matching colour, local HSV vote, model confidence or pose mAP
is not electrical continuity, voltage or functional proof.
