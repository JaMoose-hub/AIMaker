"""Read-only backend identity, including explicit accelerated-runtime fallback."""
from app.vision.yolo_pose import OpenCvYoloPoseLocator, DirectMlYoloPoseLocator


def locator_status(locator, requested):
    if locator is None:
        return {'requested_backend': requested, 'actual_backend': 'not_loaded', 'available': False}
    if callable(getattr(locator, 'diagnostics', None)):
        return locator.diagnostics()
    actual = 'opencv' if isinstance(locator, OpenCvYoloPoseLocator) else 'unknown'
    providers = []
    device_id = None
    if isinstance(locator, DirectMlYoloPoseLocator):
        actual = 'directml'
        if locator._session is not None:
            providers = locator._session.get_providers()
        device_id = locator.device_id
    return {'requested_backend': requested, 'actual_backend': actual,
            'available': bool(getattr(locator, 'available', False)),
            'providers': providers, 'device_id': device_id,
            'fallback_reason': 'Requested accelerator did not load' if actual == 'opencv' and requested != actual else None}


def inference_status(state):
    import cv2
    cfg = state.config
    detector = getattr(state, 'detector', None)
    primary = getattr(detector, 'primary', detector)
    board = locator_status(getattr(primary, '_locator', None), cfg.yolo_pose.runtime_backend)
    board['id'] = state.runtime_manager.snapshot().board_id
    fallback_tracker = getattr(getattr(detector, 'fallback', None), '_tracker', None)
    board['reference_color_roi_enabled'] = getattr(
        getattr(fallback_tracker, 'params', None), 'color_roi_enabled', None)
    board['reference_sift_frame_max_px'] = getattr(
        getattr(fallback_tracker, 'params', None), 'sift_frame_max_px', None)
    recovery = getattr(primary, '_reference_recovery', None)
    reference = locator_status(getattr(recovery, 'roi_locator', None), cfg.yolo_pose.runtime_backend)
    reference['id'] = board['id'] + '-roi'
    components = []
    workers = list(getattr(state, 'component_workers', []))
    legacy = getattr(state, 'component_worker', None)
    if legacy is not None:
        workers.append(legacy)
    for worker in workers:
        result = locator_status(getattr(worker, '_locator', None), cfg.component_vision.runtime_backend)
        result['id'] = getattr(getattr(worker, '_profile', None), 'component_id', 'unknown')
        result['webcam_motion_handoff'] = (bool(getattr(getattr(worker, '_tracker', None), 'motion_handoff', False))
                                            and not bool(getattr(worker, '_yolo_only', False)))
        components.append(result)
    body_fallback = getattr(state, 'body_worker', None)
    body = locator_status(getattr(body_fallback, 'locator', None), cfg.yolo_pose.runtime_backend)
    body['display_only'] = True
    body['max_hz'] = 1000 / body_fallback.interval_ms if body_fallback is not None else 0
    glasses = getattr(state, 'glasses_stream', None)
    eye_worker = getattr(glasses, '_yolo_worker', None)
    return {'board': board, 'board_reference': reference, 'components': components, 'body_fallback': body,
            'eye': eye_worker.snapshot() if eye_worker is not None else None,
            'opencv_num_threads': cv2.getNumThreads(),
            'motion_tracking': {'backend': 'opencv', 'cuda': False},
            'note': 'Provider availability is not a per-operator GPU audit; mixed CPU shape operators may remain.'}
