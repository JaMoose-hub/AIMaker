"""Short bounded extrapolation for Webcam display only; never a model seed."""
from copy import deepcopy
import cv2
import numpy as np


class DisplayPrediction:
    def __init__(self):
        self.previous = None
        self.latest = None

    def apply(self, message):
        quality = message.get('pose_quality', {})
        if message.get('tracking') == 'locked' and quality.get('object_supported') and not quality.get('partial'):
            self.previous, self.latest = self.latest, deepcopy(message)
            return message
        if message.get('tracking') != 'searching':
            self.previous = self.latest = None
            return message
        if quality.get('reason') not in ('lk_support', 'lk_missing', 'spatial_support', 'homography_failed'):
            self.previous = self.latest = None
            return message
        if self.previous is None or self.latest is None:
            return message
        a, b = self.previous, self.latest
        dt = b['ts_ms'] - a['ts_ms']
        age = message['ts_ms'] - b['ts_ms']
        if not 0 < dt <= 100 or not 0 < age <= 120:
            self.previous = self.latest = None
            return message
        old, current = np.float32(a['outline']), np.float32(b['outline'])
        shift = (current-old) * (age/dt)
        diagonal = np.linalg.norm(current[2]-current[0])
        predicted = current + shift
        width, height = b['video_size']
        if (not np.isfinite(predicted).all() or np.max(np.linalg.norm(shift, axis=1)) > diagonal*.15
                or not cv2.isContourConvex(predicted) or cv2.contourArea(predicted, oriented=True)*cv2.contourArea(current, oriented=True) <= 0
                or np.any(predicted < 0) or np.any(predicted[:, 0] >= width) or np.any(predicted[:, 1] >= height)):
            return message
        h = cv2.getPerspectiveTransform(current, predicted)
        result = deepcopy(b)
        result.update(frame_id=message['frame_id'], ts_ms=message['ts_ms'], tracking='stale',
                      confidence=min(.49, b.get('confidence', 0)), outline=predicted.tolist(), body=None)
        for pin in result['pins']:
            p = cv2.perspectiveTransform(np.float32([[[pin['x'], pin['y']]]]), h)[0, 0]
            pin.update(x=float(p[0]), y=float(p[1]), v=bool(pin.get('v') and 0 <= p[0] < width and 0 <= p[1] < height))
        result['pose_quality'] = dict(stability='motion_prediction', path='prediction',
            predicted=True, display_only=True, recovering=True, object_supported=False,
            prediction_age_ms=age, prediction_source_frame_id=b['frame_id'],
            reason='short_motion_prediction', pin_evidence='prediction_not_observation')
        result.pop('geometry', None)
        return result
