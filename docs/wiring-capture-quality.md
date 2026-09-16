# Wiring capture quality update — 2026-09-09

## Scope

No training, hardware actions, local wire recognition, automatic confirmation,
model/effort changes, or deployment changes. The existing Codex bridge and
three-stage endpoint/route inspection remain in place.

## Implemented

- MotionFrameState retains the latest immutable FrameSlot alongside its exact
  pose packet under one lock. Raw pixels never enter the JSON display packet.
  Capture rejects mismatched frame/sequence/timestamp and expired pairs.
- Cloud checks sample at most nine candidates during a 650ms post-request window.
  Only the winning pair and current candidate are retained, not a video recording.
  Crops are encoded only after selection. Both endpoints remain paired; the
  existing detector fallback declares its timestamp skew (at most 250ms).
- Candidates with useful locator crops are preferred because they also include
  the overview. Within that group, rank the weaker endpoint's local edge-detail
  score, penalized for exposure clipping. This is a heuristic, not calibrated
  blur/occlusion detection; noise or textured hands may score well. It does not
  prove correct pin identity, visible contact, insertion or continuity.
- Pre-request frames are excluded. No fresh frame means a clear capture error,
  not reuse of an old image. Missing local recognition still permits a fresh
  overview. Runtime changes abort the capture.
- Pin crops encompass the visible projected header plus housing/wire-exit
  context. Crops use lossless PNG from source pixels; overview uses JPEG.
  Original camera compression cannot be undone. Hidden/offscreen header ends
  cannot be recovered; projected positions remain explicitly fallible hints.
- Both endpoint calls receive the relevant overview for orientation. Prompts
  require orientation -> contact inventory -> pin identity -> target comparison,
  and request one specific useful follow-up view when evidence is missing.
- Existing inspection UI and photo URLs remain compatible; MIME types and
  temporary file extensions follow the actual encoded bytes.

## Verification and limitations

- 184 related backend tests passed; 74 frontend guide tests passed and the
  TypeScript/Vite build succeeded. No frontend component changes were needed.
- Backend restarted with the existing physical-camera/hybrid configuration.
  Read-only status checks confirmed 1920x1080 FFmpeg capture, live tracking
  frames, ChatGPT login, and CUDA inference/preprocessing for all four models.
  These status checks are not a new cloud image-inspection accuracy trial.
- Run from backend: `.venv/Scripts/python.exe -m pytest tests/test_wiring_capture.py
  tests/test_cloud_wiring.py tests/test_cloud_connectors.py
  tests/test_motion_tracking.py tests/test_motion_rebase.py -q`.
- Tests cover raw source identity, exact PNG pixel equality, full-header context,
  post-request selection, runtime changes, duplicate candidates, overview fallback,
  no hardware/manual state mutation and existing cloud schema contracts.
- Offline real-image heuristic check on existing `wiring-contact-live-64ba64bf`
  321x321 captures: original module score 6.1452 vs Gaussian-blurred 1.6124;
  original Pi score 6.3057 vs blurred 1.4880. These are relative image-quality
  scores, NOT recognition probabilities or cloud correctness measurements.
- No new real cloud verdicts or physical handheld/wiring accuracy acceptance
  were collected for this update. Camera calibration, physical occlusion tests,
  wrong-pin ground truth and model accuracy remain pending on-site validation.
- Source trace: capture.selection stores bounded candidate measurements and the
  selected index; capture.views stores crop bounds, source frame IDs and encoding.

OpenAI image limitations informed the prompt's separation of visible evidence
from precise pin identity: https://developers.openai.com/api/docs/guides/images-vision
