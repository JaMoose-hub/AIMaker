# Accuracy verification loop

The backend now exposes enough evidence to tune the MVP against real camera
captures instead of tuning by overlay appearance alone.

Each live `wire_trace` also includes `geometry` (`pitch_px`, `px_per_mm`,
`snap_radius_over_pitch`) and each endpoint may include `snap_margin_px`.
These fields make scale-dependent regressions visible in logs and replay
reports; normalized endpoint/path coordinates remain in source-frame space.
The frontend also applies a freshness gate to wire traces: it hides paths and
pin connection states when the trace is more than 45 source frames behind the
current locked detection (or when the delivered size changes). At 30 fps this
is a 1.5 s upper bound, preventing a stalled trace or camera switch from
presenting old source-pixel geometry as a current connection.
The high-rate `detection` message also exposes `geometry.pitch_px` and
`geometry.px_per_mm` as soon as the board pin lattice is locked, so a low-scale
delivered stream is visible even when no wire has been detected yet.

## What is authoritative

1. `DetectionResult` projects the board profile and GPIO lattice into source
   video pixels.
2. Wire tracing segments and follows the visible wire geometry. Board-contained
   color/ridge blobs are suppressed, while a thin component crossing the
   projected board boundary is retained so a wire resting over the PCB is not
   cut before endpoint tracing.
3. Pose matching keeps at most one camera keypoint for each reference
   descriptor before homography RANSAC; repeated header texture therefore
   cannot inflate the inlier count without adding independent geometry.
4. Homography inliers must also cover at least 5% of the board reference area;
   a local repeated-texture patch cannot extrapolate into a trusted full-board
   pose. The threshold retains the tested partial-occlusion case.
5. `snap_endpoint()` resolves a pin only when the projected header lattice has
   one acceptable identity. A tie stays `ambiguous_tie`; no pin is guessed.
6. The temporal stabilizer requires repeated evidence before a wire is shown,
   normalizes reversed skeleton paths, scales its track-association radius
   with the observed pin pitch so neighboring wires are less likely to merge,
   and lets a fresh floating/ambiguous endpoint override an old pin vote.
7. The future Rule Engine decides electrical validity. `wire_trace.connection`
   is only a geometric candidate.

For a resolved `pin` endpoint, the backend keeps the observed skeleton
terminal for attachment/motion analysis but serializes `normalized_px` and
`connection.endpoints[].position` from the current projected pin center. The
replay harness uses that same canonical position when matching against
annotated pin truth; floating/ambiguous endpoints still use their observed
pixels. This keeps assignment metrics aligned with the GPIO overlay instead
of inheriting the ferrule or segmentation-cut offset. Replay also reports
`raw_endpoint_error_*` from the original skeleton terminal, so a correct pin
assignment cannot hide a large physical endpoint or segmentation offset.

Guidance keeps the source wire and endpoint side attached to every new-pin
observation. A single wire producing one new endpoint can report `wrong_pin`
with that source; multiple new endpoints on one wire, or new endpoints from
multiple wires, remain `uncertain` instead of being collapsed into a false
wrong-pin verdict.

The optional VLM is advisory-only. Its response must pass
`schemas/scene-understanding.schema.json`; malformed, uncertain, or timed-out
responses are retained as diagnostics and cannot change pin assignment or a
guidance result.

## Capture checklist

### Recommended MVP capture rig

Use one fixed USB UVC webcam, preferably a Logitech C920/C920e, at 1920x1080
and 30 fps. Mount it on a rigid arm above the board, with the board occupying
roughly 30--45% of the frame width; the current physical target is about
162 mm camera-to-board distance and 8--10 px/mm at the header. Use a matte
neutral-gray work surface, diffuse 5000--6500 K LED light, and disable or lock
autofocus, auto-exposure, and auto-white-balance after framing. Connect the
camera directly to the host (avoid an unpowered hub). The Windows path defaults
to DirectShow; `msmf` is an explicit fallback for cameras that require it.
The capture queue defaults to one frame (`camera.buffer_size: 1`) because the
backend's `FrameBus` is already latest-only; a deeper UVC queue adds motion
latency and can make a correct tracker appear to drift. This property is a
best-effort driver hint and is not treated as a calibration failure when a
camera ignores it.
Verify the resolution shown by the live stream, not only the requested config:
the backend reports the delivered frame size and rejects a profile captured at
low scale. On Windows, the capture path negotiates MJPG before requesting
1920x1080 because some UVC drivers otherwise fall back to 1280x720.
If that mode returns a black frame, the backend tries YUY2 and then the
driver-default mode; any lower delivered resolution remains visible and fails
the physical scale gate instead of being silently treated as 1080p. Each
candidate is allowed a bounded three-frame UVC warm-up, so a transient first
black frame does not force a fallback; a candidate that stays black is still
rejected. The camera picker uses the same probe helper, so selecting a device
and opening the live stream apply the same signal/scale decision.

The C920/C920e is a practical MVP choice because it provides 1920x1080 at
30 fps and is compatible with Microsoft DirectShow. A global-shutter USB3
industrial camera is a later upgrade for motion or production fixtures, not a
prerequisite for this one-board MVP.

The camera picker treats an all-black frame as unavailable. This matters when
the C920 is already held by Teams or browser software: an opened handle and a
1920x1080 report alone are not proof that a usable image stream exists.
The capture guard also rejects near-black frames whose mean 8-bit intensity is
below 1.0; a handful of sensor/compression speckles is not treated as a valid
stream.

When the live application uses a non-synthetic source with the real `pipeline`
detector, the wire worker also applies a runtime scale gate before color
segmentation. If the projected adjacent-header pitch is below 18 source pixels
or the density is below 8 px/mm (or either measurement cannot be made), it
publishes an empty trace with
`suppressed_reason:"scale_below_minimum"` and does not make endpoint or
guidance claims. This is intentionally stricter than merely letting pose
matching lock: a low-scale pose can be geometrically plausible while the wire
endpoint decision is not resolvable. Synthetic/mock demo paths keep the gate
disabled unless `wire_trace.min_pin_pitch_px` or `wire_trace.min_px_per_mm` is
set explicitly.

For a repeatable real-camera session, run the capture tool below after the
backend is serving `/video`. It writes a profile snapshot, `pin_truth.json`,
JPEG bursts, declaration truth, and a `manifest.json` under the explicit
output directory:

```powershell
backend\.venv\Scripts\python.exe tools\capture_groundtruth.py `
  --out datasets\wire-truth\s01 `
  --rows JDIGITAL,JANALOG
```

Replay does not open a camera and pairs predicted endpoints to truth only by
source-pixel distance, so a wrong `pin_id` cannot improve the denominator:

```powershell
backend\.venv\Scripts\python.exe tools\replay_accuracy.py `
  --dataset datasets\wire-truth\s01 --json
```

By default the capture tool also runs the same `PipelineDetector` against each
saved JPEG and stores `tracking`, projected pins, confidence, and pose in
`pose.jsonl`. Replay can use those frozen records instead of clicked pin truth:

```powershell
backend\.venv\Scripts\python.exe tools\replay_accuracy.py `
  --dataset datasets\wire-truth\s01 --pose-mode recorded --json
```

`--no-record-pose` remains available for a lightweight legacy capture. Such a
dataset must use the default `truth-pins` replay mode; `recorded` mode rejects
`tracking: "not_recorded"` rather than silently substituting annotation truth.
Each captured scene now stores `pitch_px`, `px_per_mm`, and a scale status.
The default policy marks below 18 px/pitch as `reject` and below 20 px/pitch
as `below_recommended`; those scenes may help diagnose geometry, but must not
be counted as the physical 8--10 px/mm accuracy gate.

For pose-filter diagnostics, the replay harness also supports two modes that
require the captured `profile/` snapshot. `sequential` keeps one
`PipelineDetector` alive across the burst, exercising LK/One-Euro state;
`perframe` creates a fresh detector for every JPEG and is diagnostic only:

```powershell
backend\.venv\Scripts\python.exe tools\replay_accuracy.py `
  --dataset datasets\wire-truth\s01 --pose-mode sequential --json

backend\.venv\Scripts\python.exe tools\replay_accuracy.py `
  --dataset datasets\wire-truth\s01 --pose-mode perframe --json
```

Both modes use the same board exclusion polygon, wire stabilizer, and
attachment classifier as the live worker. This keeps pose-regression results
separate from the frozen `recorded` gate while still measuring the actual
end-to-end replay path.

Use the final camera, resolution, mounting height, lighting, and desk surface.
Capture at least these clips:

- empty board, top view;
- empty board, 20--30 degree oblique view;
- board rotated 90 and 180 degrees;
- one wire at each header row, including a wire that stops just before the pin;
- two neighboring pins with the endpoint deliberately between them;
- red, yellow, green, blue, brown, and any neutral-color wires used by the MVP;
- hand/partial occlusion and a board move out of frame;
- wire-free desk with the same lighting.

For each frame or replay, record the ground-truth pin id and whether the wire
is physically plugged in. Report:

- pin projection median and p95 pixel error;
- resolved-pin accuracy, ambiguous rate, and floating false-positive rate;
- `distance_px` and `margin_px` distributions from wire endpoints;
- temporal flip count per minute;
- dangerous false assignment rate.

The replay report also includes frame-normalized wire recall, canonical endpoint
error in pin-pitch units, the separate `raw_endpoint_error_*` diagnostic from
the skeleton terminal, same-row-neighbour error rate, empty-scene false
positives per frame, flips per minute, and (in `recorded` mode) pin projection
error against the independently clicked row truth.

The MVP gate is resolved pin assignment >= 0.90, fewer than 30 endpoint flips
per minute, and dangerous false assignment rate <= 0.02. When a clip cannot
support one of these measurements, keep it out of the pass/fail aggregate
instead of treating an unobserved endpoint as correct.

The current synthetic gate is already automated in
`backend/tests/test_vision_pipeline_accuracy.py`. It includes an integration
case that recovers a pipeline pose, overlays a wire on the same source frame,
verifies that `wire_tracer.trace()` resolves the projected pin identity, and
covers 90/180/270-degree orientation cases across 1280x720 and 1920x1080.
A real-camera gate still requires labeled captures; synthetic tests cannot
prove lighting, camera calibration, USB capture, or physical endpoint
visibility.

An unlabeled real-frame smoke check is available from
`wire_trace_debug_blue_excl.jpg`: the current detector locks 32 pins and the
wire path yields one stable blue candidate to `5V` with the other endpoint
remaining `floating`. This is useful for regression diagnosis only; without
ground-truth labels it is not an accuracy pass.

Latest bounded hardware smoke (2026-08-03) opened the currently available
`USB2.0 HD UVC WebCam` as device index 0, but the delivered stream was
1280x720 and its frame showed the ceiling/person rather than the UNO Q; the
pipeline consequently stayed `searching` with zero pins. The run is evidence
of capture health and source selection only, not a CV failure or an accuracy
pass. The expected C920 device was not present in the Windows camera list.

## Live tuning order

1. Calibrate camera intrinsics and verify the actual frame size.
   `camera.json.image_size` is the checkerboard capture size; the runtime now
   scales `fx/fy/cx/cy` for a same-aspect-ratio stream such as 1280x720 to
   1920x1080. A 4:3/16:9 change is rejected to the safe fallback because the
   driver crop origin is otherwise unknown.
   Only a `camera.json` with `quality_status: "ok"` is loaded by the runtime;
   legacy files without that evidence use the FOV fallback and keep the
   physical gate unready.
   For a repeatable physical session, first let autofocus produce a sharp
   image, then enable `camera.lock_auto_focus` (and set the optional
   driver-specific `camera.focus` value if needed). Enable
   `camera.lock_auto_exposure` and `camera.lock_auto_white_balance` after the
   image is correctly exposed; the optional `exposure`, `gain`, and
   `white_balance_temperature` values are passed through as best-effort UVC
   controls.
   `tools/calibrate_camera.py` now refuses to write `camera.json` when the
   overall checkerboard RMS exceeds 1.5 px, any view exceeds 3.0 px, or the
   detected corner union covers less than 20% of the image; use its reported
   `coverage_fraction` and per-view RMS values when deciding whether to retake
   checkerboard images.
2. Tune board pose/projection until pin p95 is within the target.
3. Tune endpoint exclusion and lattice thresholds using the neighboring-pin
   clip; prefer `ambiguous_tie` over a wrong pin.
4. Tune color/ridge masks using the wire-free desk clip as the false-positive
   control.
5. Tune temporal confirmation only after single-frame geometry is stable. The
   worker is idle-throttled at `interval_s=0.5`; an active guidance step uses
   `guidance_interval_s=0.3` for faster confirmation without changing the
   perception or verdict rules.
6. Add electrical Rule Engine checks after geometric candidates are reliable.
