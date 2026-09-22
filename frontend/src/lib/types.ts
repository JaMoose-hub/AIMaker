/**
 * Shared types — mirror docs/api-contract.md (v1.0) and
 * schemas/board-profile.schema.json exactly. Keep in sync with both.
 */

/** Localized text object, e.g. { "zh-TW": "...", "en": "..." }. */
export type I18nText = Record<string, string>;
export type Locale = "zh-TW" | "en";

/* ------------------------------------------------------------------ */
/* REST: GET /api/config                                               */
/* ------------------------------------------------------------------ */

export interface AppConfig {
  board_id: string;
  runtime_revision: number;
  default_locale: string;
  video_size: [number, number];
  detector: string;
  camera_source: string;
  realtime_tracking?: boolean;
  component_vision?: {
    enabled: boolean;
    primary_component_id: string | null;
    components: Array<{
      id: string;
      model_path: string;
      profile_path: string;
      input_size: number | null;
      confidence_threshold: number | null;
      keypoint_threshold: number | null;
    }>;
  };
  accuracy: AccuracySummary;
  verification_runtime?: {
    vlm_enabled: boolean;
    vlm_provider: string;
    vlm_model: string;
    vlm_insertion_enabled: boolean;
    vlm_timeout_s: number;
    vlm_worker: {
      running: boolean;
      queued_step_id: string | null;
      inflight_step_id: string | null;
      submitted_step_ids: string[];
      last_outcome: Record<string, unknown> | null;
    } | null;
    electrical_enabled: boolean;
  };
}

export interface AccuracySummary {
  status: "ready" | "warning";
  physical_gate_ready: boolean;
  pitch_px: number;
  px_per_mm: number;
  min_pitch_px: number;
  min_px_per_mm: number;
  camera_calibrated: boolean;
  camera_quality_ok: boolean;
  camera_quality_status: string | null;
  camera_rms_reprojection_error_px: number | null;
  camera_max_view_rms_px: number | null;
  camera_coverage_fraction: number | null;
  feature_count: number;
  warnings: string[];
}

/* ------------------------------------------------------------------ */
/* WebSocket: /ws/detections                                           */
/* ------------------------------------------------------------------ */

export type TrackingState = "searching" | "locked" | "stale";

export interface MotionDisplayQuality {
  partial?: boolean;
  object_supported?: boolean;
  visible_pin_count?: number;
  hidden_pin_count?: number;
  outline_only?: boolean;
  support_ratio?: number;
  interrupted?: boolean;
  recovering?: boolean;
  recovered?: boolean;
  reason?: string | null;
}

export interface HelloMessage {
  type: "hello";
  board_id: string;
  runtime_revision: number;
  video_size: [number, number];
}

/** Per-pin detection: source-image pixel coords; v=false means off-screen. */
export interface DetectionPin {
  id: string;
  x: number;
  y: number;
  c: number;
  v: boolean;
}

export interface BodyEvidence {
  box: [number, number, number, number];
  confidence: number;
  source: string;
  /** Present only after transporting a paired detector image to this frame. */
  outline?: [number, number][];
  frame_id?: number;
  source_frame_id?: number;
  age_ms?: number;
  display_only?: boolean;
  /** Eye marks body-only results when observed corners are clipped by the frame. */
  partial?: boolean;
}

export interface DetectionMessage {
  type: "detection";
  board_id: string;
  body?: BodyEvidence | null;
  runtime_revision: number;
  frame_id: number;
  ts_ms: number;
  tracking: TrackingState;
  confidence: number;
  video_size: [number, number];
  pose_mode?: "pnp_8pt" | "hybrid_4pt" | "feature_fallback";
  pose_landmarks_visible?: number;
  /** Board outline corners in source pixels, or null. */
  outline: [number, number][] | null;
  /** Live projected header scale in source-frame pixels, when pin metadata is available. */
  geometry?: {
    pitch_px: number;
    px_per_mm: number;
  };
  /** Diagnostic pose evidence; separate from the aggregate confidence score. */
  pose_quality?: MotionDisplayQuality & {
    path?: "detect" | "track" | "stale" | "yolo" | "reference_sift";
    inliers?: number;
    reproj_px?: number;
    inlier_board_area_frac?: number;
    stability?: "tracking" | "deadband" | "occlusion_hold" | "jump_hold" | string;
    motion_px?: number;
    /** Final-pin p90 displacement and independent fresh-image anchor evidence. */
    pin_motion_px?: number;
    image_motion_px?: number;
    image_support?: number;
    visible_fraction?: number;
  };
  pins: DetectionPin[];
}

/** Independent small-component pose and profile-projected pin positions. */
export interface ComponentPoseMessage {
  type: "component_pose";
  component_id: string;
  body?: BodyEvidence | null;
  frame_id: number;
  ts_ms: number;
  tracking: TrackingState;
  confidence: number;
  video_size: [number, number];
  outline: [number, number][] | null;
  pose_quality?: MotionDisplayQuality & {
    stability?: "tracking" | "deadband" | "occlusion_hold" | "jump_hold" | string;
    motion_px?: number;
    visible_fraction?: number | null;
  };
  pins: DetectionPin[];
  /** Raw model output shown only for diagnostics; never trusted by wiring logic. */
  diagnostic?: {
    detected: true;
    reason: "invalid_quad" | string;
    box: [number, number, number, number] | null;
    pins: DetectionPin[];
  };
}

/** Generic YOLO11-Seg component detections for the active board. */
export interface ComponentSegmentMessage {
  type: "component_segments";
  frame_id: number;
  ts_ms: number;
  video_size: [number, number];
  detections: Array<{
    class_id: number;
    class_name: string;
    confidence: number;
    box: [number, number, number, number];
    polygon: [number, number][];
  }>;
}

/* ------------------------------------------------------------------ */
/* WebSocket: wire_trace (docs/wire-recognition-design.md §3/§4 —      */
/* the "type" extension point api-contract.md §2 already documents)   */
/* ------------------------------------------------------------------ */

export type WireEndpointKind = "pin" | "floating" | "ambiguous_tie";

/**
 * A wire endpoint is never guessed — exactly one of the three shapes below
 * (design doc §2 Stage D "honesty contract"):
 *   { kind: "pin", pin_id, confidence }                  — resolved
 *   { kind: "floating", confidence: 0 }                  — nothing near enough
 *   { kind: "ambiguous_tie", candidates: [...] }          — 2+ equally-close pins
 * `px` (the endpoint's own detected source-pixel location, the skeleton
 * terminal point) is present ONLY for "floating"/"ambiguous_tie" - a
 * resolved "pin" endpoint carries `pin_id` instead and has no `px` at all
 * (see backend/app/wire_worker.py's _endpoint_message; this was previously
 * mis-typed as always-present, which caused a real "whole screen goes
 * blank" crash on 2026-07-28 - see WireOverlay.tsx's resolvePoint for the
 * fix). Consumers must look up a "pin" endpoint's screen position via its
 * `pin_id` against live pin data, and must handle that pin not currently
 * being visible - never assume `px`/`pin_id` are both there.
 */
export interface WireEndpoint {
  kind: WireEndpointKind;
  /** Present only when kind is "floating" or "ambiguous_tie". */
  px?: [number, number];
  /** Present only when kind === "pin". */
  pin_id?: string | null;
  /** Present only when kind === "ambiguous_tie": the tied candidate pin ids. */
  candidates?: string[];
  /** Resolution-independent source-frame coordinate. For kind="pin", this
   * is the live projected pin center; for floating/tie it is the observed
   * wire terminal. */
  normalized_px?: [number, number];
  /** Geometry diagnostics for capture/tuning; not an electrical verdict. */
  distance_px?: number;
  margin_px?: number;
  snap_margin_px?: number;
  confidence: number;
}

export type WireConnectionStatus = "candidate" | "partial" | "uncertain" | "floating";

export interface WireConnectionCandidate {
  /** Geometric candidate only; the Rule Engine must still check electrical safety. */
  status: WireConnectionStatus;
  pin_ids: string[];
  endpoint_kinds: WireEndpointKind[];
  confidence: number;
  endpoints?: Array<{
    object_id: string | null;
    pin: string | null;
    kind: WireEndpointKind;
    position: [number, number] | null;
  }>;
}

export interface WireInstance {
  wire_id: number;
  /**
   * One of the conventional dupont-wire colors (red/orange/yellow/green/
   * blue/purple/black/gray/white). Informational only — NOT an electrical
   * fact; must never be used as a stand-in for wiring-correctness (design
   * doc §6).
   */
  color: string;
  confidence: number;
  /**
   * True if the trace crossed at least one skeleton junction and used a
   * min-curvature continuation heuristic to pick a branch — degrade
   * certainty in the UI/AI response even when both endpoints resolved to
   * known pins (design doc §2/§3).
   */
  ambiguous: boolean;
  /**
   * Which detection channels produced this instance (M21): ["color"] (HSV
   * band), ["edge"] (hue-agnostic ridge — color will be "unknown"), or
   * ["color","edge"] when both channels agreed on the same pin pair and
   * were merged (higher confidence).
   */
  detection_methods: string[];
  /** Non-zero means the skeleton crossed an unresolved junction. */
  crossed_junction_count?: number;
  /** Source-image pixel coords, in path order — same space as detection pins. */
  path: [number, number][];
  /** Optional normalized path, each coordinate in [0, 1] source-frame space. */
  path_normalized?: [number, number][];
  connection?: WireConnectionCandidate;
  attachment?: "inserted" | "resting" | "unknown";
  attachment_confidence?: number;
  endpoint_a: WireEndpoint;
  endpoint_b: WireEndpoint;
}

export interface WireTraceMessage {
  type: "wire_trace";
  board_id: string;
  frame_id: number;
  ts_ms: number;
  board_tracking: TrackingState;
  video_size?: [number, number];
  geometry?: {
    pitch_px: number;
    px_per_mm: number;
    min_pitch_px?: number;
    min_px_per_mm?: number;
    snap_radius_px: number;
    snap_radius_over_pitch: number;
  };
  /** No wire verdict was published because the live stream was below the
   * physical endpoint-assignment scale gate. */
  suppressed_reason?: "scale_below_minimum" | string;
  wires: WireInstance[];
}

export type GuidanceStatus = "pending" | "correct" | "wrong_pin" | "uncertain";
export type GuidanceAdvanceMode = "confirm" | "auto";

/** REST POST /api/guidance/step step metadata (L2/L3 safety gate). */
export interface GuidanceStepInfo {
  step_id: string;
  expected_pin_id: string;
  expected_role: string | null;
  component_id: string | null;
  hint_color: string | null;
  advance_mode: GuidanceAdvanceMode;
}

/**
 * Per-tick verdict for the active guided-wiring step (M22, api-contract §2).
 * The verdict is produced purely by geometry (snap_endpoint + set/string
 * comparison); `ai_hint` is an advisory-only side channel (M24/M29) that by
 * construction can never change `status` — render it visually distinct from
 * the authoritative checkmark, never as a substitute.
 */
export interface GuidanceCheckMessage {
  type: "guidance_check";
  board_id: string;
  step_id: string;
  frame_id: number;
  ts_ms: number;
  board_tracking: TrackingState;
  expected_pin_id: string;
  status: GuidanceStatus;
  /** Only present when status === "wrong_pin" — names the pin actually hit. */
  actual_pin_id?: string;
  /** Optional audit provenance for the endpoint used by the verdict. */
  source_wire_id?: number;
  source_endpoint?: "a" | "b";
  confidence: number;
  ai_hint: { present_guess: boolean; note: string } | null;
  /** Machine-readable explanation when status is uncertain. */
  reason?: string;
  /** Supplemental before/after evidence at both guided endpoints. This is a
   * visual candidate only and must not be presented as electrical proof. */
  visual_check?: {
    status: "baseline" | "pending" | "candidate" | "uncertain";
    reason: string;
    confidence?: number;
    board_change?: number;
    component_change?: number;
    stable_hits?: number;
  };
}

export type VerificationEvidenceStatus = "pass" | "fail" | "uncertain" | "unavailable";
export type VerificationLevel = "none" | "geometry" | "visual" | "electrical";
export type VerificationVerdict =
  | "unverified"
  | "position_matched"
  | "visual_verified"
  | "verified"
  | "wrong_pin"
  | "not_inserted"
  | "electrical_mismatch"
  | "evidence_conflict"
  | "evidence_incomplete"
  | "uncertain";

export interface VerificationEvidenceMessage {
  status: VerificationEvidenceStatus;
  score: number;
  quality: number;
  reason: string;
  method: string;
  as_of_ms: number;
  fresh_until_ms: number;
  details?: Record<string, unknown>;
}

export interface VerificationUpdateMessage {
  type: "verification_update";
  board_id: string;
  frame_id: number;
  ts_ms: number;
  active: true;
  target: {
    step_id: string;
    board_pin: string;
    component_pin: string | null;
    component_id: string | null;
    geometry_requested: boolean;
    geometry_complete: boolean;
    geometry_generation: number;
    electrical_supported: boolean;
    electrical_requested: boolean;
    electrical_generation: number;
  };
  evidence: {
    geometry: VerificationEvidenceMessage;
    visual: VerificationEvidenceMessage;
    electrical: VerificationEvidenceMessage;
  };
  fusion: {
    verdict: VerificationVerdict;
    verification_level: VerificationLevel;
    overall_confidence: number;
    verdict_confidence: number;
    score_cap: number;
    reason: string;
  };
}

/** Unknown `type` values must be ignored (forward compatibility). */
export type WsMessage =
  | HelloMessage
  | RuntimeChangedMessage
  | DetectionMessage
  | ComponentPoseMessage
  | ComponentSegmentMessage
  | WireTraceMessage
  | GuidanceCheckMessage
  | VerificationUpdateMessage
  | { type: string };

export interface RuntimeChangedMessage {
  type: "runtime_changed";
  board_id: string;
  runtime_revision: number;
}

export interface ControllerModelSummary {
  path: string;
  ready: boolean;
  keypoint_count: number;
  preferred_8pt_path: string | null;
  preferred_8pt_ready: boolean;
  fallback_active: boolean;
}

export interface ControllerSummary {
  board_id: string;
  name: I18nText;
  active: boolean;
  model: ControllerModelSummary;
  pose_landmarks: number;
  wiring_guide_available: boolean;
  electrical_verification_available: boolean;
}

export interface ControllersResponse {
  controllers: ControllerSummary[];
  current_board_id: string;
  runtime_revision: number;
}

export interface ControllerSelectRequest {
  board_id: string;
}

export type ControllerSelectResponse =
  | {
      ok: true;
      changed: boolean;
      board_id: string;
      runtime_revision: number;
      guide_was_active: boolean;
    }
  | {
      ok: false;
      error_code: string;
      params: Record<string, string | number>;
    };

/* ------------------------------------------------------------------ */
/* Board profile (schemas/board-profile.schema.json)                   */
/* ------------------------------------------------------------------ */

export type CapabilityType =
  | "digital_io"
  | "pwm"
  | "adc"
  | "i2c"
  | "spi"
  | "uart"
  | "interrupt"
  | "power"
  | "boot"
  | "reset"
  | "aref"
  | "nc";

export interface Chip {
  part: string;
  core?: string;
  max_clock_mhz?: number;
  os?: string;
  role_note?: I18nText;
}

export interface Capability {
  type: CapabilityType;
  role?: string;
  bus?: string;
  channel?: string;
  rail?: string;
  direction?: string;
  mcu_pin?: string;
  note?: I18nText;
}

export interface PinElectrical {
  voltage: number;
  max_current_ma?: number;
  five_volt_tolerant?: boolean;
}

export type WarningSeverity = "info" | "warning" | "danger";

export interface PinWarning {
  severity: WarningSeverity;
  text: I18nText;
}

export interface Pin {
  id: string;
  silkscreen: string;
  header: string;
  index: number;
  pos_mm: [number, number, number];
  capabilities: Capability[];
  electrical?: PinElectrical;
  description: I18nText;
  usage_examples?: I18nText[];
  warnings?: PinWarning[];
  tags?: string[];
}

export interface BoardInfo {
  id: string;
  name: I18nText;
  vendor: string;
  revision?: string;
  mcu: Chip;
  mpu?: Chip;
  logic_voltage: number;
  five_volt_tolerant: boolean;
  form_factor: string;
  outline_mm: [number, number];
  header_top_z_mm: number;
  docs_url?: string;
}

export interface BoardReference {
  image: string;
  width_px: number;
  height_px: number;
  /** 3x3 homography, board-mm -> reference-image pixels. */
  mm_to_px: number[][];
  feature_mask?: string;
}

export interface PoseLandmark {
  id: string;
  role: "board_corner" | "header";
  pos_mm?: [number, number, number];
  pin_id?: string;
}

export type HeaderSide = "top" | "bottom" | "left" | "right";

export interface BoardHeader {
  id: string;
  name: I18nText;
  side: HeaderSide;
}

export type BusType = "i2c" | "spi" | "uart";

export interface Bus {
  id: string;
  type: BusType;
  pins: string[];
  note?: I18nText;
}

export interface BoardProfile {
  schema_version: "1.0";
  board: BoardInfo;
  reference: BoardReference;
  pose_landmarks?: PoseLandmark[];
  headers: BoardHeader[];
  buses?: Bus[];
  groups?: Record<string, string[]>;
  pins: Pin[];
}

/* ------------------------------------------------------------------ */
/* REST: POST /api/calibrate (api-contract.md §6)                      */
/* ------------------------------------------------------------------ */

export interface CalibrateRequest {
  /** Exactly 4 [x, y] points in source-video pixel space, order TL, TR, BR, BL. */
  corners_px: [number, number][];
}

export type CalibrateErrorCode =
  | "corners_invalid"
  | "no_frame"
  | "board_not_found"
  | "insufficient_scale"
  | "insufficient_features";

export interface CalibrateSuccess {
  ok: true;
  detector: string;
  reference_features: number;
  /** Deprecated compatibility field from pre-i18n backends. */
  message?: string;
  pitch_px?: number;
  px_per_mm?: number;
}

export interface CalibrateFailure {
  ok: false;
  error_code: CalibrateErrorCode;
  params: Record<string, unknown>;
  /** Deprecated compatibility alias. */
  error?: CalibrateErrorCode;
  message?: string;
  /** Present for insufficient_scale; source-video pixel scale diagnostics. */
  pitch_px?: number;
  px_per_mm?: number;
  min_pitch_px?: number;
  min_px_per_mm?: number;
}

/** HTTP 200 in both cases (api-contract.md §6) — real error codes are reserved for malformed requests. */
export type CalibrateResponse = CalibrateSuccess | CalibrateFailure;

/* ------------------------------------------------------------------ */
/* REST: GET /api/cameras, POST /api/cameras/select (api-contract.md §7) */
/* ------------------------------------------------------------------ */

export interface CameraInfo {
  index: number;
  device_id?: string;
  name?: string;
  /** Metadata proves presence, not that another app will release the stream. */
  selectable?: boolean;
  /** False if the device failed to open / produce a frame during the scan. */
  available: boolean;
  is_current: boolean;
  /** Additive diagnostic when a device opened but returned an all-black frame. */
  signal_status?: "black" | "live" | "not_checked";
  /** Present only when `available` (absent, not null, on unavailable entries). */
  width?: number;
  height?: number;
  /** Raw JPEG, base64-encoded, no `data:` prefix; absent when unavailable. */
  thumbnail_b64?: string;
}

export interface CamerasResponse {
  cameras: CameraInfo[];
  refreshable?: boolean;
}

export interface SelectCameraRequest {
  index: number;
  device_id?: string;
}

export type SelectCameraErrorCode =
  | "invalid_index"
  | "open_failed"
  | "same_as_current"
  | "camera_changed"
  | "camera_inventory_unavailable"
  | "camera_modes_unavailable"
  | "camera_worker_busy"
  | "camera_restore_failed"
  | "camera_adjustment_busy"
  | "not_applicable";

export interface SelectCameraSuccess {
  ok: true;
  index: number;
  width: number;
  height: number;
}

export interface SelectCameraFailure {
  ok: false;
  error_code: SelectCameraErrorCode;
  params: Record<string, unknown>;
  /** Deprecated compatibility alias. */
  error?: SelectCameraErrorCode;
  message?: string;
}

/** HTTP 200 in both cases, mirroring CalibrateResponse's convention. */
export type SelectCameraResponse = SelectCameraSuccess | SelectCameraFailure;
