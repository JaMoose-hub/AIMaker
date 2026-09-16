# HW-123 pin-row orientation

The HW-123 uses the existing four-corner component model and unchanged
VCC, GND, SCL, SDA, XDA, XCL, AD0, INT profile. Its eight pads run along the
canonical bottom edge, from VCC on the left to INT on the right.

The 2026-09-03 breadboard capture reproduced a quarter-turn semantic error:
the PCB outline was in the right place, but the model's corner IDs placed
the pins on an adjacent edge. A fixed frontend offset or globally rotating
the profile would break views whose corner order is already correct.

`pin_row_orientation: true` in this component's vision profile opts into a
local image check after the existing PCB refinement. The worker evaluates
the four cyclic corner orders against bright solder pads separated by dark
gaps at the profile's expected row positions. At least seven of eight pads
must have enough local contrast, and competing orientations must have a
clear score margin. The selected order is applied to the corners and their
confidences before the existing tracker and pin projection.

If row evidence is missing or ambiguous, there is deliberately no fallback
to the unverified model orientation. The existing tracker briefly marks its
last trusted pose stale, then removes the pin overlay. Wiring guidance
already requires fresh, locked component poses. Occluded, low-resolution or
poorly bounded modules may therefore be unavailable until the row is visible
again. This is geometry evidence, not an electrical connection verdict.

Other components do not opt in; their models, projection, calibration and
wiring remain unchanged. No frontend mirror/letterbox offsets are added.

## Regression fixture

`backend/tests/fixtures/hw123-header-row.png` is a 180x140 crop from the
reported 1920x1080 camera frame, starting at source pixel (350, 710). It
contains only the sensor and adjacent breadboard, not the surrounding desk.
The test's pad centres were independently selected from this image in
VCC-to-INT order. These approximate image measurements are not metrology.

The component tests cover every cyclic model order at each of four image
rotations, lighting changes, uniform/ambiguous backgrounds, and stale-pose
expiry under occlusion. The actual ONNX model was also checked against the
full captured frame rotated by 0/90/180/270 degrees. Physical camera motion,
new hardware variants and arbitrary viewing angles still need live testing.

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_component_pose.py -q`
