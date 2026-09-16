import numpy as np
import pytest

from app.vision.yolo_pose import BoardPoseObservation
from app.vision.yolo_profile_detector import _pi_corner_box_consistent


def obs(points, box):
    return BoardPoseObservation(np.array(points, dtype=float), .32,
                                np.ones(4), box)


@pytest.mark.parametrize('points,box,expected', [
    ([[1512.81,411.61],[1748.58,492.17],[1686.06,633.88],[1448.63,543.54]],
     (1354.43,272.03,1876.97,754.22), False),
    ([[213.72,508.68],[337.27,536.32],[317.91,607.89],[175.89,573.83]],
     (59.97,310.62,545.63,743.63), False),
    ([[1023.39,338.88],[770.94,741.72],[576.14,587.81],[797.46,207.11]],
     (497.88,108.46,1142.11,830.18), True),
    ([[441.97,382.16],[416.25,837.61],[171.18,829.83],[179.28,379.04]],
     (41.09,272.62,605.13,943.00), True),
])
def test_captured_raw_pi_model_hypotheses(points, box, expected):
    # Raw model outputs on saved on-site TFT negatives / true Pi positives.
    assert bool(_pi_corner_box_consistent(obs(points, box))) is expected


def test_invalid_and_rotation():
    p = np.array([[0,0],[100,0],[100,60],[0,60]], dtype=float)
    assert _pi_corner_box_consistent(obs(p, (0,0,100,60)))
    assert _pi_corner_box_consistent(obs(np.roll(p, 2, axis=0), (0,0,100,60)))
    assert not _pi_corner_box_consistent(obs(p, (0,0,0,60)))
    p[0,0] = np.nan
    assert not _pi_corner_box_consistent(obs(p, (0,0,100,60)))
