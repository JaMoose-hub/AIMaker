"""Transport the legacy/manual calibration reference with displayed geometry."""
import cv2
import numpy as np


def transport_pin_alignment(message, matrix):
    alignment = message.get('pin_alignment')
    if not alignment or not alignment.get('accepted'):
        return
    centre = np.asarray(alignment.get('reference_center'), dtype=np.float64)
    offset = np.asarray(alignment.get('offset_px'), dtype=np.float64)
    if centre.shape != (2,) or offset.shape != (2,) or not np.isfinite([centre, offset]).all():
        message.pop('pin_alignment', None)
        return
    points = cv2.perspectiveTransform(np.array([[centre, centre + offset]]), matrix)[0]
    alignment['reference_center'] = points[0].tolist()
    alignment['offset_px'] = (points[1] - points[0]).tolist()
