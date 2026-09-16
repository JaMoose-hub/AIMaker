"""ROI optimization must preserve the full-frame material decision exactly."""
import cv2
import numpy as np
import pytest

from app.component_worker import (
    ComponentPoseTracker, ComponentVisionProfile, refine_component_corners_from_pcb,
)
from app.vision.yolo_pose import BoardPoseObservation


@pytest.mark.parametrize("cid", ["hc-sr04", "hw-123", "mrd-tf240-8p-cs"])
@pytest.mark.parametrize("offset", [(0, 0), (-87, -65), (530, 350), (900, 700)])
def test_roi_fraction_matches_legacy_full_frame(cid, offset):
    frame = np.random.default_rng(18).integers(0, 256, (480, 640, 3), dtype=np.uint8)
    corners = np.float64([[75.4, 53.9], [188.6, 66.1], [163.3, 166.9], [57.4, 151.2]]) + offset
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    material = cv2.inRange(hsv, np.uint8([75, 30, 12]), np.uint8([145, 255, 255]))
    if cid == "mrd-tf240-8p-cs":
        material |= cv2.inRange(hsv, np.uint8([0, 0, 0]), np.uint8([179, 255, 95]))
    polygon = np.zeros(frame.shape[:2], np.uint8)
    cv2.fillConvexPoly(polygon, np.rint(corners).astype(np.int32), 255)
    expected = cv2.countNonZero(material & polygon) / max(cv2.countNonZero(polygon), 1)
    tracker = ComponentPoseTracker(ComponentVisionProfile(cid, (("GND", .5, 1.),)))
    assert tracker._visible_fraction(frame, corners) == pytest.approx(expected, abs=1e-12)


def test_material_conversion_is_bounded_to_polygon(monkeypatch):
    frame = np.zeros((1080, 1920, 3), np.uint8)
    quad = np.float64([[100, 100], [250, 100], [250, 200], [100, 200]])
    original = cv2.cvtColor
    sizes = []
    def record(image, code):
        sizes.append(image.shape[:2])
        return original(image, code)
    monkeypatch.setattr(cv2, "cvtColor", record)
    ComponentPoseTracker._blue_fraction(frame, quad)
    assert sizes == [(101, 151)]


@pytest.mark.parametrize("box", [
    (100, 80, 240, 180), (-20, 40, 110, 160), (400, 270, 500, 340),
    (10, -15, 150, 85), (0, 0, 480, 320),
])
def test_pcb_contour_roi_matches_full_frame_morphology(monkeypatch, box):
    frame = np.random.default_rng(32).integers(0, 256, (320, 480, 3), dtype=np.uint8)
    # Large blue regions, holes and fragmented edges exercise closing/opening
    # across the model ROI as well as at the physical image boundary.
    for x in range(0, 480, 37):
        cv2.rectangle(frame, (x, 0), (x + 27, 319), (160, 80, 20), -1)
    for y in range(0, 320, 29):
        cv2.line(frame, (0, y), (479, y), (0, 0, 0), 2)
    bx1, by1, bx2, by2 = box
    bw, bh = bx2 - bx1, by2 - by1
    margin = .12 * max(bw, bh)
    x1, y1 = max(0, int(np.floor(bx1 - margin))), max(0, int(np.floor(by1 - margin)))
    x2, y2 = min(480, int(np.ceil(bx2 + margin))), min(320, int(np.ceil(by2 + margin)))
    close_size = max(3, int(round(min(bw, bh) * .035)))
    close_size += 1 - close_size % 2
    origin = (max(0, x1 - close_size - 2), max(0, y1 - close_size - 2))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    expected_masks = []
    for lower, upper in [((80, 45, 20), (140, 255, 255)), ((75, 30, 12), (145, 255, 255))]:
        blue = cv2.inRange(hsv, np.uint8(lower), np.uint8(upper))
        full = np.zeros(frame.shape[:2], np.uint8)
        full[y1:y2, x1:x2] = blue[y1:y2, x1:x2]
        full = cv2.morphologyEx(full, cv2.MORPH_CLOSE, np.ones((close_size, close_size), np.uint8))
        full = cv2.morphologyEx(full, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        expected_masks.append(full)
    original_find = cv2.findContours
    original_color = cv2.cvtColor
    seen_masks, color_shapes = [], []

    def record_contours(mask, mode, method):
        reconstructed = np.zeros(frame.shape[:2], np.uint8)
        ox, oy = origin
        reconstructed[oy:oy + mask.shape[0], ox:ox + mask.shape[1]] = mask
        seen_masks.append(reconstructed)
        return original_find(mask, mode, method)

    def record_color(image, code):
        color_shapes.append(image.shape[:2])
        return original_color(image, code)

    monkeypatch.setattr(cv2, "findContours", record_contours)
    monkeypatch.setattr(cv2, "cvtColor", record_color)
    corners = np.float64([[bx1, by1], [bx2, by1], [bx2, by2], [bx1, by2]])
    refine_component_corners_from_pcb(frame, BoardPoseObservation(corners, .8, np.ones(4), box))
    assert color_shapes == [(y2 - y1, x2 - x1)]
    assert len(seen_masks) == 2
    for actual, expected in zip(seen_masks, expected_masks):
        np.testing.assert_array_equal(actual, expected)
