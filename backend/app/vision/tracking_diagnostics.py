"""Bounded display-path diagnostics; never decides pose validity."""
from collections import Counter, deque


class TrackingDiagnostics:
    def __init__(self):
        self.events = deque(maxlen=24)
        self.reasons = Counter()
        self.previous = {}
        self.frames = 0
        self.over_budget = 0

    def record(self, packet, elapsed_ms, budget_ms):
        self.frames += 1
        self.over_budget += elapsed_ms > budget_ms
        for message in [packet['detection'], *packet['components']]:
            key = message.get('component_id', message.get('board_id', 'unknown'))
            quality = message.get('pose_quality', {})
            reason = quality.get('reason')
            state = (message.get('tracking'), reason)
            if self.previous.get(key) != state:
                self.events.append(dict(
                    object=key, frame_id=packet['frame_id'], ts_ms=packet['ts_ms'],
                    tracking=state[0], reason=reason,
                    model_age_ms=quality.get('model_source', {}).get('age_ms'),
                    processing_ms=elapsed_ms,
                ))
            self.previous[key] = state
            if reason:
                self.reasons[str(reason)] += 1
        return dict(frames=self.frames, over_budget_frames=self.over_budget,
                    reason_frames=dict(self.reasons), transitions=list(self.events))
