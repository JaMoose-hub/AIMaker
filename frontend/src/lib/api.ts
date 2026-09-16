import type {
  AppConfig,
  BoardProfile,
  CalibrateRequest,
  CalibrateResponse,
  CamerasResponse,
  ControllersResponse,
  ControllerSelectRequest,
  ControllerSelectResponse,
  GuidanceAdvanceMode,
  QueryRequest,
  QueryResponse,
  SelectCameraRequest,
  SelectCameraResponse,
  VerificationUpdateMessage,
} from "./types";

/**
 * REST helpers (api-contract.md §1). All URLs are relative so they work both
 * behind the Vite dev proxy and when the backend serves the built dist/.
 */

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`GET ${url} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchConfig(): Promise<AppConfig> {
  return getJson<AppConfig>("/api/config");
}

export function fetchControllers(): Promise<ControllersResponse> {
  return getJson<ControllersResponse>("/api/controllers");
}

export async function postSelectController(
  boardId: string,
): Promise<ControllerSelectResponse> {
  const body: ControllerSelectRequest = { board_id: boardId };
  const response = await fetch("/api/controllers/select", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as ControllerSelectResponse;
  if (!response.ok && payload.ok !== false) {
    throw new Error(`POST /api/controllers/select failed with status ${response.status}`);
  }
  return payload;
}

export function fetchBoardProfile(boardId: string): Promise<BoardProfile> {
  return getJson<BoardProfile>(`/api/boards/${encodeURIComponent(boardId)}`);
}

export async function postQuery(text: string, locale: string): Promise<QueryResponse> {
  const body: QueryRequest = { text, locale };
  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST /api/query failed with status ${response.status}`);
  }
  return (await response.json()) as QueryResponse;
}

/**
 * POST /api/calibrate (api-contract.md §6). The backend replies HTTP 200 for
 * both success and expected failures (`{ok: false, error, message}`); only a
 * malformed request body or a genuine server error produces a non-2xx here.
 */
export async function postCalibrate(cornersPx: [number, number][]): Promise<CalibrateResponse> {
  const body: CalibrateRequest = { corners_px: cornersPx };
  const response = await fetch("/api/calibrate", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST /api/calibrate failed with status ${response.status}`);
  }
  return (await response.json()) as CalibrateResponse;
}

/**
 * GET /api/cameras (api-contract.md §7) — scans available device-camera
 * indices and returns a thumbnail snapshot of each.
 */
export function fetchCameras(): Promise<CamerasResponse> {
  return getJson<CamerasResponse>("/api/cameras");
}

/**
 * POST /api/cameras/select (api-contract.md §7) — switches the running
 * capture thread to a different device index. HTTP 200 for both success and
 * expected failure, mirroring postCalibrate's convention.
 */
export async function postSelectCamera(index: number): Promise<SelectCameraResponse> {
  const body: SelectCameraRequest = { index };
  const response = await fetch("/api/cameras/select", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST /api/cameras/select failed with status ${response.status}`);
  }
  return (await response.json()) as SelectCameraResponse;
}

export interface GuidanceStepRequest {
  expected_pin_id: string;
  expected_role?: string;
  component_id?: string;
  hint_color?: string;
  step_id?: string;
  advance_mode?: GuidanceAdvanceMode;
}

export interface GuidanceStepResponse {
  ok: boolean;
  step_id?: string;
  error?: string;
  error_code?: string;
  params?: Record<string, unknown>;
  message?: string;
}

export interface GuidanceCheckResponse {
  ok: boolean;
  status?: "idle" | "collecting" | "queued" | "inflight" | "complete" | "error" | "unavailable" | "started";
  step_id?: string;
  generation?: number;
  sample_target?: number;
  required_agreement?: number;
  connections?: Array<{
    board_pin: string;
    component_pin: string;
    state: "inserted_target" | "inserted_adjacent" | "empty" | "occluded" | "uncertain";
    confidence: number;
    evidence: string;
  }>;
  note?: string;
  elapsed_s?: number;
  error?: string;
  error_code?: string;
  params?: Record<string, unknown>;
  message?: string;
}

/** Authoritative live state for the currently active wiring-guide step. */
export interface GuidanceStateResponse {
  active: boolean;
  verification: VerificationUpdateMessage | null;
}

export type GuidanceColorCheckStatus = "match" | "mismatch" | "partial" | "unknown" | "ambiguous";
export type GuidanceColorEndpointName = "board" | "component";
export type GuidanceColorSampleStatus = "sampled" | "unknown" | "ambiguous";

export interface GuidanceColorEndpoint {
  color: string | null;
  confidence: number;
  reason: string;
  /** Median CIE Lab colour of the accepted insulation pixels. */
  lab?: [number, number, number];
  /** Evidence from the five-frame manual sampling burst. */
  sample_count?: number;
  stable_hits?: number;
  temporal_consensus?: number;
  temporal_stable?: boolean;
  /** Actual UNO Pin sampled; may be the adjacent electrically identical GND. */
  pin_id?: string;
  electrically_equivalent?: boolean;
  pixels?: number;
  radial_span_px?: number;
  /** HSV evidence that a thin same-colour segment approaches this target pin. */
  pin_proximity?: number;
  /** Distance from target pin centre to the first sampled insulation pixel. */
  nearest_pin_distance_px?: number;
  /** Start radius used for the displayed proximity score after housing calibration. */
  proximity_reference_radius_px?: number;
  /** More than one plausible coloured line leaves this target Pin. */
  ambiguous?: boolean;
  competing_components?: number;
  competing_colors?: string[];
}

/** Advisory colour consistency from the insulation just beyond each connector. */
export interface GuidanceColorCheckResponse {
  ok: boolean;
  step_id?: string;
  frame_id?: number;
  status?: GuidanceColorCheckStatus;
  confidence?: number;
  /** The lower of the two endpoint Pin-proximity scores. */
  connection_proximity?: number;
  /** Lab chroma distance (ΔEab); lower values support same-colour evidence. */
  lab_delta_e?: number;
  reason?: string;
  board?: GuidanceColorEndpoint;
  component?: GuidanceColorEndpoint;
  advisory?: boolean;
  error?: string;
  error_code?: string;
  params?: Record<string, unknown>;
  message?: string;
}

/** One saved local HSV sample from either the UNO Q or Sensor end. */
export interface GuidanceColorSampleResponse {
  ok: boolean;
  endpoint?: GuidanceColorEndpointName;
  step_id?: string;
  frame_id?: number;
  status?: GuidanceColorSampleStatus;
  sample?: GuidanceColorEndpoint;
  advisory?: boolean;
  error?: string;
  error_code?: string;
  params?: Record<string, unknown>;
  message?: string;
}

export interface GuidanceColorVlmCheckResponse {
  ok: boolean;
  status?: "idle" | "queued" | "inflight" | "complete" | "error" | "unavailable";
  step_id?: string;
  frame_id?: number;
  board_color?: string;
  component_color?: string;
  same_color?: GuidanceColorCheckStatus;
  confidence?: number;
  board_evidence?: string;
  component_evidence?: string;
  note?: string;
  elapsed_s?: number;
  error?: string;
  error_code?: string;
  params?: Record<string, unknown>;
  message?: string;
}

/** Activate one guided-wiring target. The backend snapshots current occupancy. */
export async function postGuidanceStep(body: GuidanceStepRequest): Promise<GuidanceStepResponse> {
  const response = await fetch("/api/guidance/step", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`POST /api/guidance/step failed with status ${response.status}`);
  }
  return (await response.json()) as GuidanceStepResponse;
}

/** Clear the active guided-wiring target. */
export async function deleteGuidanceStep(): Promise<void> {
  const response = await fetch("/api/guidance/step", {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`DELETE /api/guidance/step failed with status ${response.status}`);
  }
}

/** REST fallback while a fresh WebSocket verification update is pending. */
export function fetchGuidanceState(): Promise<GuidanceStateResponse> {
  return getJson<GuidanceStateResponse>("/api/guidance/state");
}

async function postGuidanceCheck(url: string): Promise<GuidanceCheckResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`POST ${url} failed with status ${response.status}`);
  }
  return (await response.json()) as GuidanceCheckResponse;
}

/** Start one five-frame dual-endpoint geometry check. */
export function postGuidanceGeometryCheck(): Promise<GuidanceCheckResponse> {
  return postGuidanceCheck("/api/guidance/geometry-check");
}

/** Read the frozen/manual geometry collection status. */
export function fetchGuidanceGeometryCheck(): Promise<GuidanceCheckResponse> {
  return getJson<GuidanceCheckResponse>("/api/guidance/geometry-check");
}

/** Save one endpoint colour sample; the UI compares the two saved samples locally. */
export function postGuidanceColorSample(
  endpoint: GuidanceColorEndpointName,
): Promise<GuidanceColorSampleResponse> {
  return postGuidanceCheck(`/api/guidance/color-check/${endpoint}`) as Promise<GuidanceColorSampleResponse>;
}

/** Freeze one current view and ask the VLM to compare visible endpoint colours. */
export function postGuidanceColorVlmCheck(): Promise<GuidanceColorVlmCheckResponse> {
  return postGuidanceCheck("/api/guidance/color-vlm-check") as Promise<GuidanceColorVlmCheckResponse>;
}

/** Read the manual wire-colour VLM job without sending another model request. */
export function fetchGuidanceColorVlmCheck(): Promise<GuidanceColorVlmCheckResponse> {
  return getJson<GuidanceColorVlmCheckResponse>("/api/guidance/color-vlm-check");
}

/** Start or restart the final Sensor AO -> UNO Q A0 Serial challenge. */
export function postGuidanceElectricalCheck(): Promise<GuidanceCheckResponse> {
  return postGuidanceCheck("/api/guidance/electrical-check");
}
