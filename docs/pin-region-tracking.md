# Regional pin display tracking — 2026-09-09

## Scope and implementation

The fast display tracker now separates current whole-object transform support
from per-pin local appearance support. It does not identify wire color, insertion,
electrical continuity or the physical correctness of the original pin projection.
The same implementation serves Pi 5, HC-SR04, HW-123 and MRD-TF240.

- Existing LK forward/backward, spatial spread, RANSAC, shape/motion limits,
  bounded semantic lease and total-loss recovery rules remain intact.
- Each semantic seed retains one grayscale reference for local pin regions,
  independent of periodic flow feature replenishment. Partial support cannot
  silently turn an obstruction into the new pin reference.
- Batch-sample 17x17 patches under the current accepted planar transform. Require
  source/current texture, normalized correlation, contrast-relative residual and
  bounded exposure change. Textureless, offscreen or changed regions are withheld.
  These are image-support heuristics, not a hand detector or calibrated confidence.
- A valid object transform with partial support may emit only locally supported
  pins. All hidden coordinates continue to transform internally so their regions
  can recover from new images; unsupported coordinates are not sent to the UI.
- Complete image loss emits no old geometry. Semantic expiry still suppresses
  all pins. No timeout was extended and no velocity extrapolation was added.
- Fresh reference replacement requires three distinct, temporally/geometrically
  corroborated detector observations: Pi independent image confirmation, or known
  component material/hand evidence. Missing/held/skin-obstructed component results
  cannot refresh the template. Components permit up to 500ms between observations
  to accommodate their existing lower-rate detector updates; Pi remains 250ms.
- Frontend marks partial tracking explicitly; hidden pins are omitted. Cloud
  capture remains conservative on partial poses and can still use overview mode.
  No guide completion, wiring record or deployment is changed by tracking.

## Reproducible offline checks

From `backend`:

```powershell
.venv/Scripts/python.exe ../tools/replay_pin_visibility.py
.venv/Scripts/python.exe -m pytest tests/test_pin_regions.py tests/test_motion_tracking.py tests/test_motion_rebase.py tests/test_wiring_capture.py tests/test_cloud_wiring.py tests/test_cloud_connectors.py -q
```

The policy replay uses one fixed synthetic texture across four device envelopes,
three textured occlusion fractions (25%, 40%, 55%), and 20 moving frames each.
It is NOT four different physical-device recordings. The baseline applies the
old all-or-none pin policy to the same accepted flow trajectories, not an old
detector/model binary.

Observed policy comparison: old policy showed the uncovered test pin in 0/240
frames; regional policy showed it in 240/240. Covered test pin emitted 0/240;
object loss 0/240; both pins restored on the next clear frame in all 12 cases.
Known-transform pin error p95 per case was at most 0.109px on this procedural
image. This number is not absolute physical GPIO accuracy.

Additional existing Pi/HC camera-texture fixtures were rotated/scaled/translated
for 20 frames: Pi retained 799/800 pin instances; HC retained 80/80. The first
fixed-intensity residual gate incorrectly rejected high-contrast HC patches;
contrast-relative residual fixed that regression without removing correlation,
texture or blur checks. Recorded-fixture tests skip explicitly if those optional
local files are absent. HW/TFT physical texture coverage is not established here.

## Still pending on-site

Verification: 205 related backend tests passed (including the installed recorded
fixtures); 75 frontend tests, i18n parity and TypeScript/Vite build passed.
The isolated 40-pin region check measured p50 0.368ms / p95 0.507ms over 200
warm iterations on this workstation; this excludes inference/streaming/rendering.
After restart, eight read-only live samples retained Pi's 40 pins and HC's four
pins. HW/TFT were searching in those samples, so no live detection success is
claimed for them. All four models and preprocessing reported CUDA available.

Real hands, connector insertion/removal, lighting/focus changes and strong 3D
tilt can differ from these tests. A clear seed with an incorrect pin projection
can still track that incorrect location. A stable obstruction may resemble local
texture; appearance support is not proof that a pin tip is visible. Calibration,
absolute GPIO alignment and physical handheld performance remain separate work.
Do not present regression pass counts as real-world recognition accuracy.
