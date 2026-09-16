"""Application configuration.

Loads backend/config.yaml (located relative to this file, robust to cwd) via
pydantic-settings, with environment-variable overrides:

    BOARDVISION_DETECTOR=pipeline
    BOARDVISION_CAMERA__DEVICE_INDEX=1     (nested delimiter "__")

Priority: init kwargs > env vars > config.yaml > field defaults.

`load_config()` additionally resolves `profile_dir` / `frontend_dist` to
absolute paths, relative to the directory containing the YAML file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# backend/app/config.py -> backend/config.yaml
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG_YAML = _BACKEND_DIR / "config.yaml"

# Module-level override so load_config(path) can direct the YAML source
# (settings_customise_sources has no access to per-call arguments).
_active_yaml_path: Path = _DEFAULT_CONFIG_YAML


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8100


class CameraConfig(BaseModel):
    source: Literal["synthetic", "device", "window", "xreal"] = "synthetic"
    device_index: int = 0  # cold-start default only; POST /api/cameras/select
                           # changes the *running* source without touching this
    width: int = 1280      # device/synthetic only; source=window follows the
    height: int = 720      # captured window's client-area size instead
    fps: float = 30.0
    # Prefer a one-frame driver queue: FrameBus is already latest-only, so a
    # deep UVC queue only adds motion latency between the real board and the
    # pose/wire decision. Drivers may ignore this best-effort property.
    buffer_size: int = Field(default=1, ge=1, le=8)
    # ``opencv`` uses cv2.VideoCapture. ``ffmpeg`` selects the camera's native
    # DirectShow MJPEG mode and feeds compressed frames through a latest-only
    # pipe, which is required for C920 1080p30 on this Windows host.
    capture_backend: Literal["opencv", "ffmpeg"] = "opencv"
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_device_name: str = "HD Pro Webcam C920"
    # Fallback only when the profile has no measured camera.json. The shipped
    # MVP camera is a Logitech C920; a different lens should override this or
    # use checkerboard calibration instead.
    horizontal_fov_deg: float | None = 70.42
    max_probe_index: int = 4  # GET /api/cameras probes indices 0..max_probe_index
    # source=window only: first visible window whose title contains this
    # substring (case-insensitive) becomes the video source - e.g. "iPhone"
    # matches a phone-mirror window. See WindowCaptureSource.
    window_title: str = "iPhone"
    # source=device only: which OS capture API cv2.VideoCapture uses.
    # DirectShow is the stable Windows path for the MVP webcam setup. The
    # C920's Media Foundation FrameServer was observed to wedge on open even
    # in a fresh process; DirectShow opened the same device immediately.
    # MSMF remains an explicit opt-in for devices that require it.
    capture_api: Literal["msmf", "dshow"] = "dshow"
    # Optional UVC controls for a repeatable physical accuracy session.
    # They are opt-in because exposure units and supported ranges vary by
    # camera/driver. Keep autofocus enabled while framing; set
    # lock_auto_focus after the image is sharp, optionally with a
    # driver-specific focus value. DirectShow commonly uses 0.25 for manual
    # exposure mode.
    lock_auto_focus: bool = False
    focus: float | None = None
    lock_auto_exposure: bool = False
    lock_auto_white_balance: bool = False
    exposure: float | None = None
    gain: float | None = None
    white_balance_temperature: float | None = None
    # Opt-in Windows FFmpeg path: apply exact UVC properties without a second
    # OpenCV video session, then read back again after the stream has started.
    native_uvc_controls: bool = False
    uvc_image_controls: dict[Literal["brightness", "contrast", "saturation", "sharpness", "backlight_compensation"], int] = Field(default_factory=dict)
    # Shared physical-camera calibration. Board-local camera.json remains a
    # compatibility fallback for profiles created before this option.
    calibration_path: Path | None = Path("../calibration/c920-1080p.json")


class WireTraceConfig(BaseModel):
    enabled: bool = True
    interval_s: float = 0.5
    # Active guidance steps use a faster confirmation cadence. This changes
    # only the worker throttle; the CV pass and conservative verdict rules
    # remain identical in idle and active modes.
    guidance_interval_s: float = 0.3
    # Narrowed subset of app.vision.wire_tracer.WIRE_COLOR_BANDS (10 total) -
    # see app.wire_worker.DEFAULT_COLORS for why these 5 specifically
    # ("black" removed 2026-07-28: matched desk clutter/surface too heavily
    # in live testing on this setup; "brown" added the same day after
    # empirically verifying it segments cleanly; "blue" removed 2026-07-28
    # for the same reason as black, then re-added 2026-07-29 after a
    # saturation-floor fix - see wire_tracer.WIRE_COLOR_BANDS["blue"]).
    colors: list[str] = Field(
        default_factory=lambda: ["red", "yellow", "green", "brown", "blue"]
    )
    # Runtime physical-scale safety gate. ``None`` lets build_app choose the
    # safe default: enabled for a real pipeline source, disabled for the
    # synthetic/mock demo. A physical header pitch below 18 px is too small
    # for reliable endpoint assignment even when pose matching itself locks.
    min_pin_pitch_px: float | None = None
    # The UNO Q header pitch is 2.54 mm, so this independent density gate
    # prevents 18px/pitch from being accepted as a physical-quality stream.
    min_px_per_mm: float | None = None
    # M20/M21 hue-agnostic ridge channel (wire_tracer.segment_edge_ridge).
    # Default False - a deliberate deviation from the design doc's default-on:
    # its constants were calibrated 2026-07-29 on saved frames only, and the
    # M20 acceptance gate (live neutral-color wire + false-positive count on
    # a wire-free desk) has not run yet. Flip the default after it passes.
    edge_agnostic_enabled: bool = False


class VlmConfig(BaseModel):
    # Disabled by default: the CV path must work offline and independently.
    enabled: bool = False
    provider: Literal["none", "ollama"] = "none"
    endpoint: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3-vl:8b"
    timeout_s: float = 8.0
    retries: int = 1
    insertion_enabled: bool = True
    insertion_interval_s: float = Field(default=1.5, ge=0.2, le=30.0)


class ElectricalVerificationConfig(BaseModel):
    """Optional UNO Q Serial functional verification (safe/read-only)."""

    enabled: bool = False
    port: str | None = None
    timeout_s: float = Field(default=2.0, ge=0.2, le=15.0)
    sample_interval_s: float = Field(default=0.25, ge=0.05, le=5.0)
    window_s: float = Field(default=6.0, ge=1.0, le=60.0)
    min_delta_fraction: float = Field(default=0.08, gt=0.0, le=1.0)


class YoloPoseConfig(BaseModel):
    """Board locator supporting legacy four-point and Pi 5 eight-point models."""

    model_path: Path = Path("../models/board-pose.onnx")
    # Keep every supported board paired with the pose model trained for that
    # exact geometry. `model_path` remains the explicit/fallback override for
    # custom profiles and tests.
    board_model_paths: dict[str, Path] = Field(default_factory=dict)
    # Optional Pi-only object detector; its corners NEVER drive GPIO overlays.
    body_fallback_model_path: Path | None = None
    pi_reference_recovery_model_path: Path | None = None
    # Preferred markerless 8-point models. A missing file deliberately falls
    # back to board_model_paths so a not-yet-trained model never breaks video.
    board_8pt_model_paths: dict[str, Path] = Field(default_factory=dict)
    input_size: int = Field(default=960, ge=320, le=1920)
    confidence_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    # Detection confidence is model-specific. Fine-tuned models can produce
    # well-localized keypoints with a more conservative objectness score, so
    # keep per-board overrides paired with board_model_paths.
    board_confidence_thresholds: dict[str, float] = Field(default_factory=dict)
    keypoint_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    nms_iou_threshold: float = Field(default=0.45, gt=0.0, le=1.0)
    max_reprojection_error_px: float = Field(default=8.0, gt=0.0, le=50.0)
    # Temporal stability guard. Small pose changes are held exactly still;
    # large jumps require agreement across several frames. A sudden loss of
    # visible blue PCB area is treated as hand/object occlusion.
    stability_deadband_px: float = Field(default=2.00, ge=0.0, le=5.0)
    deadband_exit_confirm_frames: int = Field(default=5, ge=1, le=30)
    jump_threshold_fraction: float = Field(default=0.025, gt=0.0, le=0.25)
    jump_confirm_frames: int = Field(default=3, ge=1, le=15)
    occlusion_hold_frames: int = Field(default=60, ge=1, le=300)
    occlusion_visibility_ratio: float = Field(default=0.80, gt=0.0, le=1.0)
    visibility_warmup_frames: int = Field(default=5, ge=1, le=60)
    runtime_backend: Literal["opencv", "directml", "cuda"] = "opencv"
    directml_device_id: int = Field(default=0, ge=0, le=16)
    cuda_device_id: int = Field(default=0, ge=0, le=16)

    def model_path_for(self, board_id: str) -> Path:
        preferred = self.board_8pt_model_paths.get(board_id)
        if preferred is not None and preferred.is_file():
            return preferred
        return self.board_model_paths.get(board_id, self.model_path)

    def keypoint_count_for(self, board_id: str) -> int:
        preferred = self.board_8pt_model_paths.get(board_id)
        return 8 if preferred is not None and preferred.is_file() else 4

    def confidence_threshold_for(self, board_id: str) -> float:
        threshold = self.board_confidence_thresholds.get(
            board_id, self.confidence_threshold
        )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(
                f"YOLO pose confidence threshold for {board_id!r} must be "
                f"between 0 and 1, got {threshold}"
            )
        return threshold


class ComponentVisionConfig(BaseModel):
    """Independent small-component pose runtime (disabled in mock demo)."""

    enabled: bool = False
    model_path: Path = Path("../models/photoresistor-pose.onnx")
    profile_path: Path = Path(
        "../profiles/components/photoresistor-module/vision_profile.json"
    )
    input_size: int = Field(default=768, ge=320, le=1280)
    interval_s: float = Field(default=0.30, ge=0.05, le=5.0)
    confidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    keypoint_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    nms_iou_threshold: float = Field(default=0.45, gt=0.0, le=1.0)
    stability_deadband_px: float = Field(default=2.0, ge=0.0, le=8.0)
    deadband_exit_confirm_frames: int = Field(default=5, ge=1, le=30)
    jump_threshold_fraction: float = Field(default=0.025, gt=0.0, le=0.25)
    jump_confirm_frames: int = Field(default=3, ge=1, le=10)
    occlusion_hold_s: float = Field(default=2.0, ge=0.1, le=30.0)
    occlusion_visibility_ratio: float = Field(default=0.80, gt=0.0, le=1.0)
    visibility_warmup_frames: int = Field(default=5, ge=1, le=30)
    reacquire_confirm_frames: int = Field(default=4, ge=2, le=15)
    reacquire_min_visible_fraction: float = Field(default=0.45, ge=0.05, le=1.0)
    hand_fraction_threshold: float = Field(default=0.08, ge=0.01, le=0.50)
    runtime_backend: Literal["opencv", "directml", "cuda"] = "opencv"
    directml_device_id: int = Field(default=0, ge=0, le=16)
    cuda_device_id: int = Field(default=0, ge=0, le=16)
    # Optional multi-component runtime.  When empty, the legacy single
    # model_path/profile_path fields above remain authoritative.  Each target
    # may override the expensive model-specific knobs while inheriting the
    # temporal stability settings from this parent config.
    primary_component_id: str | None = None
    components: list["ComponentVisionTargetConfig"] = Field(default_factory=list)

    @field_validator("components", mode="before")
    @classmethod
    def _parse_components_json(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return json.loads(stripped)
        return value


class ComponentVisionTargetConfig(BaseModel):
    id: str
    model_path: Path
    profile_path: Path
    input_size: int | None = Field(default=None, ge=320, le=1280)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    keypoint_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    nms_iou_threshold: float | None = Field(default=None, gt=0.0, le=1.0)
    interval_s: float | None = Field(default=None, ge=0.05, le=5.0)
    reacquire_min_visible_fraction: float | None = Field(
        default=None, ge=0.05, le=1.0
    )


class ComponentSegmentationConfig(BaseModel):
    """Generic board-component segmentation runtime."""

    enabled: bool = False
    model_path: Path = Path("../models/pi5-components-seg.onnx")
    class_names: list[str] = Field(
        default_factory=lambda: [
            "CPU", "Ethernet", "GPIO", "HDMI", "RAM", "RAM-3",
            "Raspberry", "micro-hdmi",
        ]
    )
    input_size: int = Field(default=640, ge=320, le=1280)
    interval_s: float = Field(default=0.35, ge=0.05, le=5.0)
    confidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    class_confidence_thresholds: dict[str, float] = Field(default_factory=dict)
    mask_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    nms_iou_threshold: float = Field(default=0.45, gt=0.0, le=1.0)
    max_detections: int = Field(default=30, ge=1, le=100)


class PiDeployConfig(BaseModel):
    host: str = "192.168.50.174"
    port: int = 22
    username: str = "pet"
    password: SecretStr = SecretStr("")
    remote_dir: str = "/home/pet/Desktop/Pi_deployer"
    timeout_s: float = Field(default=10.0, gt=0, le=60)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOARDVISION_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    pi_deploy: PiDeployConfig = Field(default_factory=PiDeployConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    wire_trace: WireTraceConfig = Field(default_factory=WireTraceConfig)
    vlm: VlmConfig = Field(default_factory=VlmConfig)
    electrical_verification: ElectricalVerificationConfig = Field(
        default_factory=ElectricalVerificationConfig
    )
    yolo_pose: YoloPoseConfig = Field(default_factory=YoloPoseConfig)
    component_vision: ComponentVisionConfig = Field(default_factory=ComponentVisionConfig)
    component_segmentation: ComponentSegmentationConfig = Field(
        default_factory=ComponentSegmentationConfig
    )
    detector: Literal["mock", "pipeline", "hybrid"] = "mock"
    board: str = "arduino-uno-q"
    profile_dir: Path = Path("../profiles")
    frontend_dist: Path = Path("../frontend/dist")
    default_locale: str = "zh-TW"
    jpeg_quality: int = 80
    detection_hz: float = 30.0
    # Vision already has independent board/component/capture workers. A large
    # nested OpenCV pool oversubscribes the CPU while model inference is CUDA.
    opencv_num_threads: int = Field(default=2, ge=1, le=32)
    realtime_tracking: bool = False  # Pi5 + HC-SR04 display-only trial
    runtime_revision: int = Field(default=1, ge=1)

    @property
    def video_size(self) -> tuple[int, int]:
        return (self.camera.width, self.camera.height)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_source = YamlConfigSettingsSource(
            settings_cls,
            yaml_file=_active_yaml_path if _active_yaml_path.is_file() else None,
        )
        # init > env > .env > yaml > secrets  (env overrides the YAML file)
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)


def _resolve(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else (base / path).resolve()


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load AppConfig from a YAML file (default: backend/config.yaml) + env.

    profile_dir / frontend_dist are resolved to absolute paths relative to
    the YAML file's directory (so it works regardless of cwd).
    """
    global _active_yaml_path
    yaml_path = Path(config_path).resolve() if config_path else _DEFAULT_CONFIG_YAML
    _active_yaml_path = yaml_path
    try:
        cfg = AppConfig()
    finally:
        _active_yaml_path = _DEFAULT_CONFIG_YAML
    base = yaml_path.parent if yaml_path.is_file() else _BACKEND_DIR
    cfg.profile_dir = _resolve(cfg.profile_dir, base)
    cfg.frontend_dist = _resolve(cfg.frontend_dist, base)
    if cfg.camera.calibration_path is not None:
        cfg.camera.calibration_path = _resolve(cfg.camera.calibration_path, base)
    cfg.yolo_pose.model_path = _resolve(cfg.yolo_pose.model_path, base)
    if cfg.yolo_pose.body_fallback_model_path is not None:
        cfg.yolo_pose.body_fallback_model_path = _resolve(cfg.yolo_pose.body_fallback_model_path, base)
    if cfg.yolo_pose.pi_reference_recovery_model_path is not None:
        cfg.yolo_pose.pi_reference_recovery_model_path = _resolve(cfg.yolo_pose.pi_reference_recovery_model_path, base)
    cfg.yolo_pose.board_model_paths = {
        board_id: _resolve(model_path, base)
        for board_id, model_path in cfg.yolo_pose.board_model_paths.items()
    }
    cfg.yolo_pose.board_8pt_model_paths = {
        board_id: _resolve(model_path, base)
        for board_id, model_path in cfg.yolo_pose.board_8pt_model_paths.items()
    }
    cfg.component_vision.model_path = _resolve(cfg.component_vision.model_path, base)
    cfg.component_vision.profile_path = _resolve(cfg.component_vision.profile_path, base)
    cfg.component_vision.components = [
        target.model_copy(
            update={
                "model_path": _resolve(target.model_path, base),
                "profile_path": _resolve(target.profile_path, base),
            }
        )
        for target in cfg.component_vision.components
    ]
    cfg.component_segmentation.model_path = _resolve(
        cfg.component_segmentation.model_path, base
    )
    return cfg
