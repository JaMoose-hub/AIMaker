from pathlib import Path
from types import SimpleNamespace

from app.config import load_config
from app import main


def test_runtime_enables_only_reviewed_webcam_components(monkeypatch):
    config=load_config(Path(__file__).resolve().parents[1]/'config.yaml')
    monkeypatch.setattr(main,'ComponentPoseWorker',lambda **kwargs:kwargs)
    for target in config.component_vision.components:
        worker=main._build_component_pose_worker(config=config,target=target,bus=None,
            component_pose_state=None,broadcaster=SimpleNamespace(publish_threadsafe=lambda _:None))
        assert worker['webcam_motion_handoff'] == (target.id in ('hc-sr04','hw-123','mrd-tf240-8p-cs'))
        assert worker['model_path'] == target.model_path
        assert worker['interval_s'] <= .10


def test_eye_direct_component_path_does_not_call_webcam_tracker(monkeypatch):
    from app.component_worker import ComponentPoseWorker, ComponentPoseState
    from app.capture.bus import FrameSlot
    from test_motion_consensus import scene, observation
    image,quad=scene()
    profile=Path(__file__).resolve().parents[2]/'profiles/components/hc-sr04/vision_profile.json'
    locator=SimpleNamespace(available=True,locate=lambda _:observation(quad))
    worker=ComponentPoseWorker(bus=None,state=ComponentPoseState(),model_path='unused',profile_path=profile,
        publish=lambda _:None,locator=locator,webcam_motion_handoff=True)
    monkeypatch.setattr(worker._tracker,'update',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Webcam tracker used by Eye')))
    result=worker.detect_yolo_frame(FrameSlot(image,10,1000,10))
    assert result.tracking=='locked' and result.tracking_reason=='yolo_direct'
