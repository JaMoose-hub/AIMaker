"""Application assembly.

build_app() wires: config -> ProfileStore -> (SyntheticScene if synthetic
camera) -> FrameSource -> detector (app.vision.factory) -> CaptureService +
VisionWorker, and registers all API routes.

Injection seams: tests pass their own config / detector / source (and skip
app.vision entirely - the vision factory and synthetic scene are only
imported lazily at lifespan startup when nothing was injected).

The uvicorn entrypoint "app.main:app" is provided lazily via module
__getattr__ so that merely importing this module (e.g. from tests) does not
load the real profile or the vision package.
"""
from __future__ import annotations

from app.components.availability import RETIRED_COMPONENT_IDS, retired_target

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import calibrate as api_calibrate
from app.api import controllers as api_controllers
from app.api import camera_focus as api_camera_focus
from app.api import camera_tuning as api_camera_tuning
from app.api import camera_modes as api_camera_modes
from app.api import cameras as api_cameras
from app.api import glasses as api_glasses
from app.api import guidance as api_guidance
from app.api import routes as api_routes
from app.api import video as api_video
from app.api import ws as api_ws
from app.api import vlm as api_vlm
from app.api import cloud_wiring as api_cloud_wiring
from app.cloud_wiring import CloudWiringService
from app.api import wiring as api_wiring
from app.api import pi as api_pi
from app.api import debug as api_debug
from app.api import design as api_design
from app.api import tracking as api_tracking
from app.api.static import mount_frontend
from app.api.ws import DetectionBroadcaster
from app.capture.bus import FrameBus
from app.capture.service import CaptureService
from app.component_worker import ComponentPoseState, ComponentPoseWorker
from app.component_segmentation_worker import (
    ComponentSegmentationState,
    ComponentSegmentationWorker,
)
from app.components.store import ComponentStore
from app.config import AppConfig, ComponentVisionTargetConfig, load_config
from app.electrical.serial_link import UnoQSerialLink
from app.profiles.store import ProfileStore
from app.query.service import QueryService
from app.runtime import BoardRuntimeManager
from app.pi_deploy import PiDeployer
from app.motion_worker import MotionFrameState, MotionOverlayWorker
from app.vision.endpoint_color import GuidanceColorPreviewState
from app.vision.guidance import GuidanceState
from app.vision.wire_state import WireTraceState
from app.vision_worker import DetectionState, VisionWorker
from app.wire_worker import (
    DEFAULT_RUNTIME_MIN_PIN_PITCH_PX,
    DEFAULT_RUNTIME_MIN_PX_PER_MM,
    WireTraceWorker,
)
from app.vlm.service import OllamaOpenAIProvider, VlmService
from app.verification.state import VerificationState
from app.verification.electrical_worker import ElectricalVerificationWorker
from app.verification.color_vlm_worker import WireColorVlmWorker
from app.verification.final_worker import FinalWiringVlmWorker
from app.verification.visual_worker import InsertionVlmWorker

log = logging.getLogger(__name__)


def _build_source_and_scene(config: AppConfig, profile, board_profile_dir: Path, scene):
    """Build the frame source (+ scene when synthetic). Lazy vision imports
    happen inside app.capture.sources.create_frame_source."""
    from app.capture.sources import create_frame_source

    return create_frame_source(config, profile, board_profile_dir, scene)


def _mock_should_animate(config: AppConfig, profile, board_profile_dir: Path, scene) -> bool:
    """Whether a "mock" detector should play its canned demo trajectory.

    True for every legitimate demo context: a SyntheticScene, the synthetic
    camera source, or a board that already has a real calibrated reference
    (mm_to_px + reference image written by POST /api/calibrate). False only
    for the gap this exists to close: "detector: mock" left as a stand-in
    for a real device/window camera pointed at a board that was never
    calibrated (PipelineDetector.load() would raise FileNotFoundError for
    it). Faking a locked pose there draws an animated overlay disconnected
    from the real, stationary board, and starves CalibratePanel's manual
    alignment guide of the "not locked" state it needs to appear.
    """
    if scene is not None or config.camera.source == "synthetic":
        return True
    return (board_profile_dir / profile.reference.image).is_file()


def _build_detector(config: AppConfig, profile, board_profile_dir: Path, scene):
    """Build the detector via the vision factory (lazy import: the module is
    developed in parallel and must not be required by backend unit tests)."""
    from app.vision.factory import create_detector

    return create_detector(
        config.detector, profile, board_profile_dir, scene,
        mock_animate=_mock_should_animate(config, profile, board_profile_dir, scene),
        horizontal_fov_deg=config.camera.horizontal_fov_deg,
        camera_calibration_path=config.camera.calibration_path,
        use_camera_calibration=config.camera.source != "xreal",
        yolo_model_path=config.yolo_pose.model_path_for(profile.board.id),
        yolo_reference_recovery_model_path=config.yolo_pose.pi_reference_recovery_model_path,
        yolo_keypoint_count=config.yolo_pose.keypoint_count_for(profile.board.id),
        yolo_input_size=config.yolo_pose.input_size,
        yolo_confidence_threshold=config.yolo_pose.confidence_threshold_for(
            profile.board.id
        ),
        yolo_keypoint_threshold=config.yolo_pose.keypoint_threshold,
        yolo_nms_iou_threshold=config.yolo_pose.nms_iou_threshold,
        yolo_max_reprojection_error_px=config.yolo_pose.max_reprojection_error_px,
        yolo_stability_deadband_px=config.yolo_pose.stability_deadband_px,
        yolo_deadband_exit_confirm_frames=config.yolo_pose.deadband_exit_confirm_frames,
        yolo_jump_threshold_fraction=config.yolo_pose.jump_threshold_fraction,
        yolo_jump_confirm_frames=config.yolo_pose.jump_confirm_frames,
        yolo_occlusion_hold_frames=config.yolo_pose.occlusion_hold_frames,
        yolo_occlusion_visibility_ratio=config.yolo_pose.occlusion_visibility_ratio,
        yolo_visibility_warmup_frames=config.yolo_pose.visibility_warmup_frames,
        yolo_runtime_backend=config.yolo_pose.runtime_backend,
        yolo_directml_device_id=config.yolo_pose.directml_device_id,
        yolo_cuda_device_id=config.yolo_pose.cuda_device_id,
    )


def _build_vlm_service(config: AppConfig) -> VlmService:
    """Build the advisory VLM boundary without coupling it to CV startup."""
    if not config.vlm.enabled or config.vlm.provider == "none":
        return VlmService()
    if config.vlm.provider == "ollama":
        return VlmService(
            OllamaOpenAIProvider(config.vlm.endpoint, config.vlm.model),
            timeout_s=config.vlm.timeout_s,
            retries=config.vlm.retries,
        )
    return VlmService()


def _component_targets(config: AppConfig) -> list[ComponentVisionTargetConfig]:
    component_cfg = config.component_vision
    if component_cfg.components:
        return [target for target in component_cfg.components if not retired_target(target.id, target.profile_path)]
    if retired_target("legacy", component_cfg.profile_path):
        return []
    return [
        ComponentVisionTargetConfig(
            id="legacy",
            model_path=component_cfg.model_path,
            profile_path=component_cfg.profile_path,
            input_size=component_cfg.input_size,
            confidence_threshold=component_cfg.confidence_threshold,
            keypoint_threshold=component_cfg.keypoint_threshold,
            nms_iou_threshold=component_cfg.nms_iou_threshold,
            interval_s=component_cfg.interval_s,
            reacquire_min_visible_fraction=component_cfg.reacquire_min_visible_fraction,
        )
    ]


def _build_component_pose_worker(
    *,
    config: AppConfig,
    target: ComponentVisionTargetConfig,
    bus: FrameBus,
    component_pose_state: ComponentPoseState,
    broadcaster: DetectionBroadcaster,
) -> ComponentPoseWorker:
    component_cfg = config.component_vision
    return ComponentPoseWorker(
        bus=bus,
        state=component_pose_state,
        model_path=target.model_path,
        profile_path=target.profile_path,
        publish=broadcaster.publish_threadsafe,
        # This tracker is used only by the ordinary Webcam worker path.
        # Eye's yolo_only branch remains separate.
        webcam_motion_handoff=target.id in ('hc-sr04', 'mrd-tf240-8p-cs'),
        # Webcam components target at least a 10 Hz schedule. The worker
        # deducts processing time; overloaded cycles never queue old frames.
        interval_s=min(target.interval_s or component_cfg.interval_s, .10),
        input_size=target.input_size or component_cfg.input_size,
        confidence_threshold=(
            target.confidence_threshold
            if target.confidence_threshold is not None
            else component_cfg.confidence_threshold
        ),
        keypoint_threshold=(
            target.keypoint_threshold
            if target.keypoint_threshold is not None
            else component_cfg.keypoint_threshold
        ),
        nms_iou_threshold=(
            target.nms_iou_threshold
            if target.nms_iou_threshold is not None
            else component_cfg.nms_iou_threshold
        ),
        runtime_backend=component_cfg.runtime_backend,
        directml_device_id=component_cfg.directml_device_id,
        cuda_device_id=component_cfg.cuda_device_id,
        deadband_px=component_cfg.stability_deadband_px,
        deadband_exit_confirm_frames=component_cfg.deadband_exit_confirm_frames,
        jump_threshold_fraction=component_cfg.jump_threshold_fraction,
        jump_confirm_frames=component_cfg.jump_confirm_frames,
        occlusion_hold_s=component_cfg.occlusion_hold_s,
        occlusion_visibility_ratio=component_cfg.occlusion_visibility_ratio,
        visibility_warmup_frames=component_cfg.visibility_warmup_frames,
        reacquire_confirm_frames=component_cfg.reacquire_confirm_frames,
        reacquire_min_visible_fraction=(
            target.reacquire_min_visible_fraction
            if target.reacquire_min_visible_fraction is not None
            else component_cfg.reacquire_min_visible_fraction
        ),
        hand_fraction_threshold=component_cfg.hand_fraction_threshold,
    )


def build_app(
    config: AppConfig | None = None,
    *,
    detector=None,
    source=None,
    scene=None,
    profile_store: ProfileStore | None = None,
    wire_worker: WireTraceWorker | None = None,
    component_worker: ComponentPoseWorker | None = None,
    component_segmentation_worker: ComponentSegmentationWorker | None = None,
    vlm_service: VlmService | None = None,
    insertion_vlm_worker: InsertionVlmWorker | None = None,
    final_wiring_vlm_worker: FinalWiringVlmWorker | None = None,
    wire_color_vlm_worker: WireColorVlmWorker | None = None,
    electrical_worker: ElectricalVerificationWorker | None = None,
) -> FastAPI:
    config = config or load_config()
    store = profile_store or ProfileStore(config.profile_dir)
    profile = store.profile(config.board)
    board_profile_dir = store.board_dir(config.board)

    frame_bus = FrameBus()
    detection_state = DetectionState()
    wire_state = WireTraceState()
    component_pose_state = ComponentPoseState(
        primary_component_id=(None if config.component_vision.primary_component_id in RETIRED_COMPONENT_IDS
                              else config.component_vision.primary_component_id)
    )
    component_segmentation_state = ComponentSegmentationState()
    guidance_state = GuidanceState()
    guidance_color_preview = GuidanceColorPreviewState()
    verification_state = VerificationState()
    broadcaster = DetectionBroadcaster()
    query_service = QueryService(profile, config.default_locale)
    component_store = ComponentStore(config.profile_dir / "components")
    vlm_service = vlm_service or _build_vlm_service(config)
    runtime_manager = BoardRuntimeManager(
        config=config,
        profile_store=store,
        detector_builder=lambda runtime_profile, runtime_dir, runtime_scene: _build_detector(
            config, runtime_profile, runtime_dir, runtime_scene
        ),
    )

    def _publish_final_wiring(outcome: dict) -> None:
        """Promote the one-shot final VLM result into normal fusion state."""
        step_id = str(outcome.get("step_id", ""))
        if not step_id:
            return
        now_ms = time.monotonic() * 1000.0
        if outcome.get("status") == "complete":
            verification_state.set_final_visual_result(
                step_id,
                outcome.get("connections", []),
                note=str(outcome.get("note", "")),
                now_ms=now_ms,
            )
        else:
            verification_state.set_final_visual_error(
                step_id,
                error=str(outcome.get("error", "vlm_failed")),
                now_ms=now_ms,
            )
        message = verification_state.message(
            config.board,
            int(outcome.get("frame_id", 0) or 0),
            now_ms,
        )
        if message is not None:
            broadcaster.publish_threadsafe(message)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = app.state
        import cv2
        cv2.setNumThreads(config.opencv_num_threads)
        log.info('OpenCV worker pool: %d threads', cv2.getNumThreads())
        broadcaster.bind_loop(asyncio.get_running_loop())

        if state.source is None:
            state.source, state.scene = _build_source_and_scene(
                config, profile, board_profile_dir, state.scene
            )
        if state.detector is None:
            # create_detector() already calls detector.load().
            state.detector = _build_detector(config, profile, board_profile_dir, state.scene)
        else:
            # Injected detector (tests): backend guarantees load() ran
            # before the first detect() call.
            state.detector.load(profile, board_profile_dir)

        state.capture_service = CaptureService(state.source, frame_bus)
        state.vision_worker = VisionWorker(
            bus=frame_bus,
            detector=state.detector,
            state=detection_state,
            board_id=config.board,
            video_size=(config.camera.width, config.camera.height),
            detection_hz=config.detection_hz,
            publish=broadcaster.publish_threadsafe,
            runtime_revision=config.runtime_revision,
        )
        if (
            state.insertion_vlm_worker is None
            and config.vlm.enabled
            and config.vlm.insertion_enabled
            and vlm_service.provider is not None
        ):
            state.insertion_vlm_worker = InsertionVlmWorker(
                vlm_service,
                verification_state,
                config.board,
                publish=broadcaster.publish_threadsafe,
                min_interval_s=config.vlm.insertion_interval_s,
            )
        if (
            state.final_wiring_vlm_worker is None
            and config.vlm.enabled
            and config.vlm.insertion_enabled
            and vlm_service.provider is not None
        ):
            state.final_wiring_vlm_worker = FinalWiringVlmWorker(
                vlm_service,
                config.board,
                publish=_publish_final_wiring,
            )
        if (
            state.wire_color_vlm_worker is None
            and config.vlm.enabled
            and config.vlm.insertion_enabled
            and vlm_service.provider is not None
        ):
            state.wire_color_vlm_worker = WireColorVlmWorker(vlm_service)
        if (
            state.electrical_worker is None
            and config.electrical_verification.enabled
        ):
            electrical_cfg = config.electrical_verification
            state.electrical_worker = ElectricalVerificationWorker(
                verification_state,
                config.board,
                UnoQSerialLink(
                    electrical_cfg.port,
                    timeout_s=electrical_cfg.timeout_s,
                ),
                publish=broadcaster.publish_threadsafe,
                sample_interval_s=electrical_cfg.sample_interval_s,
                window_s=electrical_cfg.window_s,
                min_delta_fraction=electrical_cfg.min_delta_fraction,
            )
        # wire_worker: only auto-built when nothing was injected (mirrors the
        # detector/source injection seam) AND config.wire_trace.enabled is
        # true. An explicitly injected worker (tests) always runs regardless
        # of the enabled flag - injecting it is itself the explicit intent.
        if state.wire_worker is None and config.wire_trace.enabled:
            min_pin_pitch_px = config.wire_trace.min_pin_pitch_px
            if (min_pin_pitch_px is None
                    and config.detector in {"pipeline", "hybrid"}
                    and config.camera.source != "synthetic"):
                min_pin_pitch_px = DEFAULT_RUNTIME_MIN_PIN_PITCH_PX
            min_px_per_mm = config.wire_trace.min_px_per_mm
            if (min_px_per_mm is None
                    and config.detector in {"pipeline", "hybrid"}
                    and config.camera.source != "synthetic"):
                min_px_per_mm = DEFAULT_RUNTIME_MIN_PX_PER_MM
            state.wire_worker = WireTraceWorker(
                bus=frame_bus,
                detection_state=detection_state,
                state=wire_state,
                board_id=config.board,
                publish=broadcaster.publish_threadsafe,
                interval_s=config.wire_trace.interval_s,
                guidance_interval_s=config.wire_trace.guidance_interval_s,
                colors=config.wire_trace.colors,
                guidance_state=guidance_state,
                component_pose_state=component_pose_state,
                include_edge_agnostic=config.wire_trace.edge_agnostic_enabled,
                min_pin_pitch_px=min_pin_pitch_px,
                min_px_per_mm=min_px_per_mm,
                verification_state=verification_state,
            )
        if (
            state.component_worker is None
            and not state.component_workers
            and config.component_vision.enabled
        ):
            state.component_workers = [
                _build_component_pose_worker(
                    config=config,
                    target=target,
                    bus=frame_bus,
                    component_pose_state=component_pose_state,
                    broadcaster=broadcaster,
                )
                for target in _component_targets(config)
            ]
        if (
            state.component_segmentation_worker is None
            and config.component_segmentation.enabled
        ):
            component_cfg = config.component_segmentation
            state.component_segmentation_worker = ComponentSegmentationWorker(
                bus=frame_bus,
                state=component_segmentation_state,
                model_path=component_cfg.model_path,
                class_names=tuple(component_cfg.class_names),
                publish=broadcaster.publish_threadsafe,
                interval_s=component_cfg.interval_s,
                input_size=component_cfg.input_size,
                confidence_threshold=component_cfg.confidence_threshold,
                class_confidence_thresholds=component_cfg.class_confidence_thresholds,
                mask_threshold=component_cfg.mask_threshold,
                nms_iou_threshold=component_cfg.nms_iou_threshold,
                max_detections=component_cfg.max_detections,
            )
        state.capture_service.start()
        state.vision_worker.start()
        if config.realtime_tracking:
            from app.body_worker import BodyVisionWorker
            from app.vision.yolo_pose import create_yolo_pose_locator
            body_path = config.yolo_pose.body_fallback_model_path
            if (config.detector == 'hybrid' and config.camera.source != 'synthetic'
                    and body_path is not None and body_path.is_file()):
                state.body_worker = BodyVisionWorker(
                    frame_bus, runtime_manager, state.motion_frame_state,
                    create_yolo_pose_locator(
                        body_path, input_size=config.yolo_pose.input_size,
                        confidence_threshold=.55, keypoint_threshold=config.yolo_pose.keypoint_threshold,
                        runtime_backend=config.yolo_pose.runtime_backend,
                        cuda_device_id=config.yolo_pose.cuda_device_id,
                        directml_device_id=config.yolo_pose.directml_device_id,
                    ),
                )
                state.body_worker.start()
            state.motion_worker = MotionOverlayWorker(
                frame_bus, detection_state, component_pose_state,
                runtime_manager, state.motion_frame_state,
                body_state=state.body_worker,
            )
            state.motion_worker.start()
        if state.wire_worker is not None:
            state.wire_worker.start()
        if state.component_worker is not None:
            state.component_worker.start()
        for worker in state.component_workers:
            worker.start()
        if state.component_segmentation_worker is not None:
            state.component_segmentation_worker.start()
        if state.insertion_vlm_worker is not None:
            state.insertion_vlm_worker.start()
        if state.final_wiring_vlm_worker is not None:
            state.final_wiring_vlm_worker.start()
        if state.wire_color_vlm_worker is not None:
            state.wire_color_vlm_worker.start()
        if state.electrical_worker is not None:
            state.electrical_worker.start()
        log.info(
            "board-vision backend up: board=%s camera=%s detector=%s",
            config.board, config.camera.source, config.detector,
        )
        try:
            yield
        finally:
            await asyncio.to_thread(state.camera_tuner.close)
            state.glasses_stream.stop_yolo_worker()
            if state.motion_worker is not None:
                state.motion_worker.stop()
            if state.body_worker is not None:
                state.body_worker.stop()
            await asyncio.to_thread(state.pi_execution.close)
            await asyncio.to_thread(state.component_tests.close)
            await asyncio.to_thread(state.integration_trials.close)
            await asyncio.to_thread(state.pi_deployer.close)
            state.cloud_wiring_service.close()
            await asyncio.to_thread(state.design_service.bridge.close)
            if state.electrical_worker is not None:
                state.electrical_worker.stop()
            if state.insertion_vlm_worker is not None:
                state.insertion_vlm_worker.stop()
            if state.final_wiring_vlm_worker is not None:
                state.final_wiring_vlm_worker.stop()
            if state.wire_color_vlm_worker is not None:
                state.wire_color_vlm_worker.stop()
            if state.component_worker is not None:
                state.component_worker.stop()
            for worker in state.component_workers:
                worker.stop()
            if state.component_segmentation_worker is not None:
                state.component_segmentation_worker.stop()
            if state.wire_worker is not None:
                state.wire_worker.stop()
            state.vision_worker.stop()
            state.capture_service.stop()
            try:
                state.detector.close()
            except Exception:
                log.exception("detector.close() failed")
            broadcaster.unbind_loop()

    app = FastAPI(title="Board Vision backend", lifespan=lifespan)

    # Shared state (available to routes even before lifespan runs).
    app.state.config = config
    app.state.pi_deployer = PiDeployer(config.pi_deploy)
    from app.component_testing import ComponentTests
    app.state.component_tests = ComponentTests(app.state.pi_deployer)
    from app.pi_execution import PiExecution
    from app.integration_trials import IntegrationTrials
    app.state.integration_trials = IntegrationTrials(app.state.pi_deployer)
    app.state.pi_execution = PiExecution(app.state.pi_deployer, app.state.component_tests, app.state.integration_trials)
    app.state.design_service = api_design.DesignService()
    from app.debugging import DebugCases
    app.state.debug_cases = DebugCases(app.state.pi_deployer, app.state.component_tests, app.state.integration_trials,
                                      app.state.pi_execution, app.state.design_service.bridge)
    app.state.cloud_wiring_service = CloudWiringService()
    app.state.profile_store = store
    app.state.profile = profile
    app.state.frame_bus = frame_bus
    app.state.detection_state = detection_state
    app.state.wire_state = wire_state
    app.state.component_pose_state = component_pose_state
    app.state.motion_frame_state = MotionFrameState()
    app.state.motion_worker = None
    app.state.body_worker = None
    app.state.component_segmentation_state = component_segmentation_state
    app.state.guidance_state = guidance_state
    app.state.guidance_color_preview = guidance_color_preview
    app.state.verification_state = verification_state
    app.state.broadcaster = broadcaster
    app.state.query_service = query_service
    app.state.runtime_manager = runtime_manager
    app.state.component_store = component_store
    app.state.vlm_service = vlm_service
    app.state.detector = detector
    app.state.source = source
    from app.camera_tuning import CameraTuner
    app.state.camera_control_lock = threading.Lock()
    app.state.camera_tuner = CameraTuner(app.state)
    app.state.scene = scene
    app.state.capture_service = None
    app.state.vision_worker = None
    app.state.wire_worker = wire_worker
    app.state.component_worker = component_worker
    app.state.component_workers = []
    app.state.component_segmentation_worker = component_segmentation_worker
    app.state.insertion_vlm_worker = insertion_vlm_worker
    app.state.final_wiring_vlm_worker = final_wiring_vlm_worker
    app.state.wire_color_vlm_worker = wire_color_vlm_worker
    app.state.electrical_worker = electrical_worker

    from app.glasses import GlassesStreamManager
    app.state.glasses_stream = GlassesStreamManager(app.state)

    # API routes first, then the catch-all static mount at "/".
    app.include_router(api_routes.router)
    app.include_router(api_controllers.router)
    app.include_router(api_calibrate.router)
    app.include_router(api_cameras.router)
    app.include_router(api_glasses.router)
    app.include_router(api_camera_focus.router)
    app.include_router(api_camera_tuning.router)
    app.include_router(api_camera_modes.router)
    app.include_router(api_guidance.router)
    app.include_router(api_video.router)
    app.include_router(api_tracking.router)
    app.include_router(api_ws.router)
    app.include_router(api_vlm.router)
    app.include_router(api_wiring.router)
    app.include_router(api_pi.router)
    app.include_router(api_debug.router)
    app.include_router(api_design.router)
    app.include_router(api_cloud_wiring.router)
    mount_frontend(app, Path(config.frontend_dist))

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """Lazily build the uvicorn entrypoint `app.main:app` on first access."""
    if name == "app":
        global _app
        if _app is None:
            _app = build_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    logging.basicConfig(level=logging.INFO)
    # timeout_graceful_shutdown: without it uvicorn waits forever for the
    # endless MJPEG /video streams to finish, hanging every shutdown.
    uvicorn.run(
        "app.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        timeout_graceful_shutdown=3,
    )
