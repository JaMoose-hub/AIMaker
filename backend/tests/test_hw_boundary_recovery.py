from pathlib import Path
import cv2
import numpy as np
import pytest

from app.component_worker import ComponentVisionProfile, orient_component_corners_from_pin_row, project_component_pins
from app.vision.yolo_pose import BoardPoseObservation
from app.vision.motion_tracking import MotionTrack

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('index', [1, 2, 3])
def test_september13_dark_pcb_complete_row_recovery(index):
    import json
    from app.component_worker import _recover_fragmented_hw_boundary
    base = ROOT / 'runs/acceptance/2026-09-13/HW-light-baseline-model-failures'
    if not (base / f'{index}.png').exists():
        pytest.skip('optional exact on-site source unavailable')
    frame = cv2.imread(str(base / f'{index}.png'))
    data = json.loads((base / f'{index}.json').read_text())['component_pose']['pose_quality']['orientation_input']
    obs = BoardPoseObservation(np.array(data['corners']), data['confidence'],
        np.array(data['keypoint_confidences']), tuple(data['box']))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    fixed = orient_component_corners_from_pin_row(frame, obs, profile)
    assert fixed is not None
    assert cv2.isContourConvex(fixed.corners_px.astype(np.float32))
    # A fresh model box and a dark color proposal still cannot invent a row.
    assert _recover_fragmented_hw_boundary(np.full_like(frame, 60), obs, profile) is None
    mapping = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]),
                                         fixed.corners_px.astype(np.float32))
    covered = frame.copy()
    row = cv2.perspectiveTransform(np.float32([[[0,.76],[1,.76],[1,1.08],[0,1.08]]]), mapping)[0]
    cv2.fillConvexPoly(covered, np.rint(row).astype(np.int32), (65,65,65))
    assert _recover_fragmented_hw_boundary(covered, obs, profile) is None

@pytest.mark.parametrize('folder', ['HW-source-failures', 'HW-return-source-failures'])
@pytest.mark.parametrize('index', [1,2,3])
def test_exact_model_source_perspective_failures(index, folder):
    import json
    base = ROOT / 'runs/acceptance/2026-09-11' / folder
    if not (base / f'{index}.png').exists():
        pytest.skip('optional on-site source unavailable')
    frame = cv2.imread(str(base / f'{index}.png'))
    packet = json.loads((base / f'{index}.json').read_text())
    data = packet.get('component_pose', packet.get('message'))['pose_quality']['orientation_input']
    obs = BoardPoseObservation(np.array(data['corners']),data['confidence'],
        np.array(data['keypoint_confidences']),tuple(data['box']))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    result = orient_component_corners_from_pin_row(frame,obs,profile)
    assert result is not None
    assert cv2.isContourConvex(result.corners_px.astype(np.float32))

@pytest.mark.parametrize('turn', range(4))
def test_fragmented_blue_pcb_on_gray_noise_recovers_with_holes(turn):
    from app.component_worker import _recover_fragmented_hw_boundary
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HW-dark-after-confirmation-fix-01/failure-003-source.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    q = np.float64([[976.492,591.059],[921.375,487.295],[1020.408,450.754],[1073.505,558.192]])
    box = np.float64([[919.199,431.486],[1075.881,611.549]])
    for _ in range(turn):
        width = frame.shape[1]
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        q = np.column_stack([q[:,1], width-1-q[:,0]])
        box = np.column_stack([box[:,1], width-1-box[:,0]])
        box = np.array([box.min(0), box.max(0)])
    obs = BoardPoseObservation(q,.44,np.ones(4),(*box[0],*box[1]))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    fixed = orient_component_corners_from_pin_row(frame, obs, profile)
    assert fixed is not None
    assert cv2.contourArea(fixed.corners_px.astype(np.float32)) > 12000
    assert _recover_fragmented_hw_boundary(np.full_like(frame,80), obs, profile) is None
    # Cover both mounting holes while retaining the visible row: fragmented
    # color alone must not authorize the new fallback.
    if turn == 0:
        covered = frame.copy()
        cv2.rectangle(covered,(957,461),(984,590),(160,160,160),-1)
        assert _recover_fragmented_hw_boundary(covered, obs, profile) is None

@pytest.mark.parametrize('turn', range(4))
def test_saved_collapsed_chip_quad_recovers_pcb_and_row(turn):
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HW-dark-after-fix-diagnostic-01/scene-after-sample.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    corners = np.float64([[980.7138,656.6948], [1000.4399,657.3585],
                          [1010.1227,674.7120], [982.9136,675.8342]])
    box = np.float64([[925.8448,589.6708], [1047.5442,742.1738]])
    for _ in range(turn):
        width = frame.shape[1]
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        corners = np.column_stack([corners[:, 1], width-1-corners[:, 0]])
        box = np.column_stack([box[:, 1], width-1-box[:, 0]])
        box = np.array([box.min(0), box.max(0)])
    obs = BoardPoseObservation(corners, .616, np.ones(4), (*box[0], *box[1]))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    assert orient_component_corners_from_pin_row(frame, obs, profile, allow_boundary_recovery=False) is None
    result = orient_component_corners_from_pin_row(frame, obs, profile)
    assert result is not None
    assert abs(cv2.contourArea(result.corners_px.astype(np.float32))) > 10000
    # Convert projected row back to original photo coordinates: all pins must
    # land on the visible right-hand pad column, not on the central chip.
    pins = project_component_pins(profile, result.corners_px, .616, (frame.shape[1], frame.shape[0]))
    xy = np.array([(p.x, p.y) for p in pins])
    for _ in range(turn):
        height = frame.shape[0]
        xy = np.column_stack([height-1-xy[:, 1], xy[:, 0]])
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    assert np.all((xy[:, 0] > 1020) & (xy[:, 0] < 1045))
    assert np.ptp(xy[:, 1]) > 95
    # Uniform gray cannot invent a PCB/row from the model confidence.
    assert orient_component_corners_from_pin_row(np.full_like(frame, 80),
        BoardPoseObservation(np.float64([[980,656],[1000,657],[1010,674],[982,675]]),
                             .616, np.ones(4), (925,589,1048,743)), profile) is None

def test_orientation_failure_revokes_old_motion_pins():
    track = MotionTrack()
    track.message = {'pins': [{'id': 'VCC'}]}
    track.observe({'frame_id': 1, 'pose_quality': {'reason': 'pin_orientation_unverified'}},
                  np.zeros((100,100), np.uint8), 1.)
    assert track.message is None
    assert track.failure_reason == 'pin_orientation_unverified'


def test_mounting_holes_may_show_bright_background():
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HW-fragmented-fix-live-01/failure-003-source.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    obs = BoardPoseObservation(np.float64([[878.584,694.624],[892.694,582.905],
        [986.115,601.220],[971.293,715.118]]), .46,np.ones(4),(865.959,565.657,990.461,727.385))
    assert orient_component_corners_from_pin_row(frame, obs, profile) is not None


def test_reversed_collapsed_corners_still_reach_boundary_recovery():
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HW-dark-after-fix-diagnostic-01/scene-after-sample.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    corners = np.float64([[980.7138,656.6948], [1000.4399,657.3585],
                          [1010.1227,674.7120], [982.9136,675.8342]])[::-1].copy()
    obs = BoardPoseObservation(corners, .616, np.ones(4), (925.8448,589.6708,1047.5442,742.1738))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    assert orient_component_corners_from_pin_row(frame, obs, profile, allow_boundary_recovery=False) is None
    result = orient_component_corners_from_pin_row(frame, obs, profile)
    assert result is not None
    assert abs(cv2.contourArea(result.corners_px.astype(np.float32))) > 10000

def test_saved_skewed_quad_uses_complete_pcb_not_a_partial_crop():
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HW-boundary-fix-live-01/scene-after-sample.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    obs = BoardPoseObservation(np.float64([[989.1186,610.6436],[934.479,508.7017],
        [1018.995,454.2153],[1069.2611,560.4683]]), .3314, np.ones(4),
        (929.6799,458.3337,1066.8342,614.2688))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    assert orient_component_corners_from_pin_row(frame, obs, profile, allow_boundary_recovery=False) is None
    fixed = orient_component_corners_from_pin_row(frame, obs, profile)
    assert fixed is not None
    assert np.all(np.ptp(fixed.corners_px, axis=0) > [110,130])


@pytest.mark.parametrize('turn', range(4))
def test_nearby_blue_wire_does_not_expand_hw_boundary(turn):
    path = ROOT / 'runs/acceptance/2026-09-13/S08-TFT-HW-unplugged-01/frames/000000.jpg'
    if not path.exists():
        pytest.skip('optional on-site frame unavailable')
    frame = cv2.imread(str(path))
    # Paired raw model observation from the replay cache, not a later frame.
    corners = np.float64([[1151.765991,186.431946],[1266.357910,140.317383],
                         [1301.427002,226.043335],[1188.883057,269.827393]])
    box = np.float64([[1114.160645,99.314331],[1339.850464,303.864441]])
    # Independent visible PCB bounds, intentionally loose: this is boundary
    # recovery coverage, NOT a sub-pin accuracy assertion.
    bounds = np.float64([[1145,135],[1325,275]])
    for _ in range(turn):
        width = frame.shape[1]
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        corners = np.column_stack([corners[:, 1], width - 1 - corners[:, 0]])
        for rect in (box, bounds):
            transformed = np.column_stack([rect[:, 1], width - 1 - rect[:, 0]])
            rect[:] = [transformed.min(0), transformed.max(0)]
    obs = BoardPoseObservation(corners, .49960482, np.ones(4), (*box[0], *box[1]))
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hw-123/vision_profile.json')
    result = orient_component_corners_from_pin_row(frame, obs, profile)
    assert result is not None
    assert (result.corners_px >= bounds[0]).all()
    assert (result.corners_px <= bounds[1]).all()
    assert orient_component_corners_from_pin_row(np.full_like(frame, 80), obs, profile) is None


def test_fragment_grouping_never_invents_boundary_pixels():
    from app.component_worker import _hw_blue_point_groups
    mask = np.zeros((220, 220), np.uint8)
    cv2.rectangle(mask, (40, 40), (180, 150), 255, -1)
    cv2.rectangle(mask, (104, 40), (110, 150), 0, -1)
    cv2.line(mask, (0, 202), (35, 213), 255, 6)
    groups = list(_hw_blue_point_groups(mask, cv2.findNonZero(mask), split=True))
    assert len(groups) > 1
    assert groups[0][1] is False
    for points, isolated in groups[1:]:
        assert isolated
        xy = points.reshape(-1, 2)
        assert np.all(mask[xy[:, 1], xy[:, 0]] == 255)
        assert len(points) < cv2.countNonZero(mask)
