import type { ProjectDesign } from "./maker";
import type { ComponentPoseMessage, DetectionMessage, DetectionPin } from "./types";

export interface PhotoWire {
  wire_id: string;
  component_id: string;
  board_pin: string;
  component_pin: string;
  connection_kind: "direct" | "divider";
}
export interface PhotoPlan {
  catalog_version: string;
  profile_versions: ProjectDesign["profile_versions"];
  component_ids: string[];
  wires: PhotoWire[];
}
export type PhotoOverlayMode = "corrected" | "raw" | "photo";
export type PhotoCandidatePin = Pick<DetectionPin, "id" | "x" | "y" | "v">;
export interface PhotoLocalization {
  object_id: string;
  status: "located" | "uncertain" | "not_found";
  method: string;
  reason: string;
  evidence: Record<string, unknown>;
  raw_outline_px: [number, number][] | null;
  corrected_outline_px: [number, number][] | null;
  /** Diagnostic profile projection. Never a trusted GPIO position. */
  candidate_pins?: PhotoCandidatePin[];
}
export interface PhotoCapture {
  capture_id: string;
  session_id: string;
  image_url: string;
  captured_at: string | number;
  image_sha256: string;
  frame_id: number;
  video_size: [number, number];
  runtime_revision: number;
  camera_id: string;
  detection: DetectionMessage;
  components: ComponentPoseMessage[];
  quality: Record<string, unknown>;
  localization?: PhotoLocalization[];
  wires: PhotoWire[];
  stale?: boolean;
}
export type PhotoWireVerdict = "matched" | "suspected" | "uncertain";
export interface PhotoEndpointObservation {
  state: "target" | "other" | "empty" | "occluded" | "uncertain";
  observed_pin: string | null;
  evidence: string;
}
export interface PhotoWireResult {
  wire_id: string;
  verdict: PhotoWireVerdict;
  board_observation: PhotoEndpointObservation;
  component_observation: PhotoEndpointObservation;
  wire_observation: { same_wire: "consistent" | "different" | "uncertain";
    visibility: "traceable" | "partially_visible" | "not_visible"; evidence: string };
  note: string;
}
export interface PhotoCheckJob {
  job_id: string;
  status: "queued" | "checking" | "running" | "completed" | "failed";
  capture_id: string;
  frame_id: number;
  image_sha256: string;
  results: PhotoWireResult[];
  summary?: string;
  error?: string | null;
  electrical_verified: false;
}
export interface PhotoResultsRecord { captureId: string; binding: string; values: Record<string, PhotoWireResult> }

export function mergePhotoResults(previous: PhotoResultsRecord | null, captureId: string, binding: string, results: PhotoWireResult[]): PhotoResultsRecord {
  return { captureId, binding, values: {
    ...(previous?.captureId === captureId && previous.binding === binding ? previous.values : {}),
    ...Object.fromEntries(results.map(result => [result.wire_id, result])),
  } };
}

export function photoPlanForProject(project: ProjectDesign): PhotoPlan {
  return { catalog_version: project.catalog_version, profile_versions: project.profile_versions ?? {},
    component_ids: [...project.component_ids], wires: project.wiring.map(wire => ({
      wire_id: wire.id, component_id: wire.componentId, board_pin: wire.boardPin,
      component_pin: wire.componentPin, connection_kind: wire.connectionKind,
    })) };
}

export function photoWireBinding(wires: readonly PhotoWire[]): string {
  return JSON.stringify(wires.map(wire => [wire.wire_id, wire.component_id, wire.board_pin,
    wire.component_pin, wire.connection_kind]));
}

export function photoPlanBinding(plan: PhotoPlan | null, project?: ProjectDesign | null): string {
  if (!plan) return "";
  return JSON.stringify([project?.id ?? "photo-wiring-poc", project?.revision ?? 1,
    plan.catalog_version, plan.profile_versions ?? {}, photoWireBinding(plan.wires)]);
}

export function acceptPhotoPlan(plan: PhotoPlan): boolean {
  return Boolean(plan && typeof plan.catalog_version === "string" && Array.isArray(plan.component_ids)
    && plan.component_ids.length > 0 && plan.component_ids.every(id => ["hc-sr04", "mrd-tf240-8p-cs"].includes(id))
    && new Set(plan.component_ids).size === plan.component_ids.length && Array.isArray(plan.wires) && plan.wires.length > 0
    && new Set(plan.wires.map(wire => wire?.wire_id)).size === plan.wires.length
    && plan.wires.every(wire => wire && [wire.wire_id, wire.board_pin, wire.component_pin].every(value => typeof value === "string" && value.length > 0)
      && plan.component_ids.includes(wire.component_id) && ["direct", "divider"].includes(wire.connection_kind)));
}

function sizeValid(size: unknown): size is [number, number] {
  return Array.isArray(size) && size.length === 2 && size.every(value => Number.isFinite(value) && value > 0);
}
function sameSize(left: unknown, right: [number, number]) {
  return sizeValid(left) && left[0] === right[0] && left[1] === right[1];
}
function pinsValid(pins: unknown, size: [number, number]): pins is DetectionPin[] {
  return Array.isArray(pins) && new Set(pins.map(pin => pin?.id)).size === pins.length && pins.every(pin =>
    pin && typeof pin.id === "string" && Number.isFinite(pin.x) && Number.isFinite(pin.y)
    && typeof pin.v === "boolean" && (!pin.v || (pin.x >= 0 && pin.x <= size[0] && pin.y >= 0 && pin.y <= size[1])));
}
function poseValid(pose: DetectionMessage | ComponentPoseMessage, capture: PhotoCapture): boolean {
  return Boolean(pose && pose.frame_id === capture.frame_id && sameSize(pose.video_size, capture.video_size)
    && ["locked", "searching", "stale"].includes(pose.tracking) && pinsValid(pose.pins, capture.video_size)
    && (pose.outline === null || (Array.isArray(pose.outline) && pose.outline.length === 4
      && pose.outline.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)))));
}
function quadValid(value: unknown): value is [number, number][] {
  return Array.isArray(value) && value.length === 4 && value.every(point => Array.isArray(point)
    && point.length === 2 && point.every(Number.isFinite));
}
export function photoPoseFor(capture: PhotoCapture, objectId: string) {
  return objectId === "raspberry-pi-5" ? capture.detection : capture.components.find(pose => pose.component_id === objectId);
}
export function photoLocalizationFor(capture: PhotoCapture, objectId: string): PhotoLocalization {
  const current = capture.localization?.find(item => item.object_id === objectId);
  if (current) return current;
  const pose = photoPoseFor(capture, objectId);
  return { object_id: objectId, status: pose?.body || pose?.outline ? "uncertain" : "not_found", method: "model_only",
    reason: "localization_not_validated", evidence: {}, raw_outline_px: pose?.outline ?? null, corrected_outline_px: null };
}
/** A model confidence/locked flag alone is never a reliable GPIO coordinate. */
export function reliablePhotoPose(capture: PhotoCapture, objectId: string) {
  const localization = photoLocalizationFor(capture, objectId);
  const pose = photoPoseFor(capture, objectId);
  return localization.status === "located" && localization.evidence.board_geometry_verified === true
    && localization.evidence.pin_geometry_verified === true && quadValid(localization.corrected_outline_px) && pose?.tracking === "locked" ? pose : null;
}
export function photoModelConfidence(capture: PhotoCapture, objectId: string): number | null {
  const localization = photoLocalizationFor(capture, objectId);
  const pose = photoPoseFor(capture, objectId);
  const value = localization.evidence.model_confidence ?? pose?.body?.confidence
    ?? (pose?.pose_quality as { model_confidence?: number } | undefined)?.model_confidence;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}
export function photoOverlayObjects(capture: PhotoCapture, mode: PhotoOverlayMode) {
  if (mode === "photo") return [];
  return ["raspberry-pi-5", ...capture.components.map(pose => pose.component_id)].map(objectId => {
    const localization = photoLocalizationFor(capture, objectId);
    // A detected object must not disappear just because pin refinement failed.
    // Raw candidates stay explicitly uncertain and NEVER supply wire endpoints.
    return { objectId, localization, outline: mode === "raw" ? localization.raw_outline_px : localization.corrected_outline_px ?? localization.raw_outline_px,
      pins: mode === "corrected" ? reliablePhotoPose(capture, objectId)?.pins.filter(pin => pin.v) ?? [] : [],
      candidatePins: mode === "corrected" && localization.status !== "located" ? localization.candidate_pins ?? [] : [] };
  });
}
export interface PhotoFocusBox { x: number; y: number; width: number; height: number }
/** Names only: never promote a raw model box to a usable wire endpoint. */
export function photoMissingEndpoints(capture: PhotoCapture, wire: PhotoWire): string[] {
  return [
    ["raspberry-pi-5", wire.board_pin], [wire.component_id, wire.component_pin],
  ].filter(([id, pin]) => !locatedPhotoPin(reliablePhotoPose(capture, id), pin)).map(([id]) => id);
}
export function photoFocusBox(capture: PhotoCapture, objectId?: string, wire?: PhotoWire): PhotoFocusBox | null {
  const points: [number, number][] = [];
  if (wire) {
    const a = locatedPhotoPin(reliablePhotoPose(capture, "raspberry-pi-5"), wire.board_pin);
    const b = locatedPhotoPin(reliablePhotoPose(capture, wire.component_id), wire.component_pin);
    if (!a || !b) return null;
    for (const pin of [a, b]) points.push([pin.x, pin.y]);
  } else if (objectId) {
    const localization = photoLocalizationFor(capture, objectId);
    const outline = localization.corrected_outline_px ?? localization.raw_outline_px;
    if (outline) points.push(...outline);
    else {
      const box = photoPoseFor(capture, objectId)?.body?.box;
      if (box) points.push([box[0], box[1]], [box[2], box[3]]);
    }
  }
  if (!points.length) return null;
  const [width, height] = capture.video_size;
  const x = Math.min(width - 1, Math.max(0, Math.min(...points.map(point => point[0])) - 75));
  const y = Math.min(height - 1, Math.max(0, Math.min(...points.map(point => point[1])) - 75));
  const right = Math.max(0, Math.min(width, Math.max(...points.map(point => point[0])) + 75));
  const bottom = Math.max(0, Math.min(height, Math.max(...points.map(point => point[1])) + 75));
  return { x, y, width: Math.max(1, right - x), height: Math.max(1, bottom - y) };
}
/** Leave room for fractional CSS layout so fitting cannot create its own scrollbars. */
export function photoFitScale(videoSize: [number, number], viewportWidth: number, viewportHeight: number) {
  const [width, height] = videoSize;
  return Math.max(0.05, Math.min((viewportWidth - 4) / width, (viewportHeight - 4) / height));
}
export function photoFocusView(box: PhotoFocusBox, viewportWidth: number, viewportHeight: number) {
  const scale = Math.min(4, Math.max(0.05, Math.min((viewportWidth - 20) / box.width, (viewportHeight - 20) / box.height)));
  return { scale, left: Math.max(0, (box.x + box.width / 2) * scale - viewportWidth / 2),
    top: Math.max(0, (box.y + box.height / 2) * scale - viewportHeight / 2) };
}
function localizationValid(capture: PhotoCapture, plan: PhotoPlan) {
  if (capture.localization === undefined) return true;
  const ids = new Set(["raspberry-pi-5", ...plan.component_ids]);
  return Array.isArray(capture.localization) && new Set(capture.localization.map(item => item?.object_id)).size === capture.localization.length
    && capture.localization.every(item => {
      if (!item || !ids.has(item.object_id) || !["located", "uncertain", "not_found"].includes(item.status)
        || typeof item.method !== "string" || typeof item.reason !== "string" || !item.evidence || typeof item.evidence !== "object" || Array.isArray(item.evidence)
        || !(item.raw_outline_px === null || quadValid(item.raw_outline_px))
        || !(item.corrected_outline_px === null || quadValid(item.corrected_outline_px))
        || (item.candidate_pins !== undefined && !pinsValid(item.candidate_pins, capture.video_size))) return false;
      const pose = photoPoseFor(capture, item.object_id);
      if (item.status !== "located") return !pose || (pose.tracking !== "locked" && pose.pins.length === 0);
      if (!pose || pose.tracking !== "locked" || item.evidence.board_geometry_verified !== true
        || item.evidence.pin_geometry_verified !== true || !quadValid(item.corrected_outline_px) || !quadValid(pose.outline)) return false;
      return item.corrected_outline_px.every((point, index) => Math.hypot(point[0] - pose.outline![index][0], point[1] - pose.outline![index][1]) <= 0.25);
    });
}

/** The photograph and every drawn pose must have one source frame and binding. */
export function acceptPhotoCapture(capture: PhotoCapture, sessionId: string, plan: PhotoPlan): boolean {
  if (!capture || capture.session_id !== sessionId || !capture.capture_id || capture.stale
    || !Number.isSafeInteger(capture.frame_id) || capture.frame_id < 0
    || !Number.isSafeInteger(capture.runtime_revision) || capture.runtime_revision < 1
    || !sizeValid(capture.video_size) || !/^[a-f0-9]{64}$/i.test(capture.image_sha256 ?? "")
    || capture.image_url !== `/api/photo-wiring/captures/${encodeURIComponent(capture.capture_id)}/image`
    || typeof capture.camera_id !== "string" || !capture.camera_id || capture.detection?.board_id !== "raspberry-pi-5"
    || capture.detection?.runtime_revision !== capture.runtime_revision
    || !poseValid(capture.detection, capture) || !Array.isArray(capture.components)
    || new Set(capture.components.map(pose => pose?.component_id)).size !== capture.components.length
    || !capture.components.every(pose => plan.component_ids.includes(pose?.component_id) && poseValid(pose, capture)
      && (pose as ComponentPoseMessage & { runtime_revision?: number }).runtime_revision === capture.runtime_revision)
    || !Array.isArray(capture.wires) || photoWireBinding(capture.wires) !== photoWireBinding(plan.wires)
    || !localizationValid(capture, plan)) return false;
  return true;
}

export function acceptPhotoImageSize(capture: PhotoCapture, width: number, height: number): boolean {
  return width === capture.video_size[0] && height === capture.video_size[1];
}

/** AI advice is tied to the frozen bytes; it never changes manual confirmations. */
function endpointValid(endpoint: PhotoEndpointObservation): boolean {
  return Boolean(endpoint && ["target", "other", "empty", "occluded", "uncertain"].includes(endpoint.state)
    && (endpoint.observed_pin === null || typeof endpoint.observed_pin === "string") && typeof endpoint.evidence === "string");
}
export function acceptPhotoCheck(job: PhotoCheckJob, capture: PhotoCapture, requestedWireId?: string, requestedJobId?: string): boolean {
  const allowed = new Set(capture.wires.map(wire => wire.wire_id));
  return Boolean(job && (!requestedJobId || job.job_id === requestedJobId) && job.capture_id === capture.capture_id && job.frame_id === capture.frame_id
    && job.image_sha256 === capture.image_sha256 && job.electrical_verified === false
    && ["queued", "checking", "running", "completed", "failed"].includes(job.status)
    && Array.isArray(job.results) && new Set(job.results.map(result => result?.wire_id)).size === job.results.length
    && job.results.every(result => allowed.has(result?.wire_id) && (!requestedWireId || result.wire_id === requestedWireId)
      && ["matched", "suspected", "uncertain"].includes(result.verdict)
      && endpointValid(result.board_observation) && endpointValid(result.component_observation)
      && result.wire_observation && ["consistent", "different", "uncertain"].includes(result.wire_observation.same_wire)
      && ["traceable", "partially_visible", "not_visible"].includes(result.wire_observation.visibility)
      && typeof result.wire_observation.evidence === "string" && typeof result.note === "string"
      && (result.verdict !== "matched" || (result.board_observation.state === "target" && result.component_observation.state === "target"
        && result.wire_observation.same_wire === "consistent" && result.wire_observation.visibility === "traceable"
        && capture.wires.some(wire => wire.wire_id === result.wire_id && wire.connection_kind === "direct"
          && wire.board_pin === result.board_observation.observed_pin && wire.component_pin === result.component_observation.observed_pin
          && locatedPhotoPin(reliablePhotoPose(capture, "raspberry-pi-5"), wire.board_pin)
          && locatedPhotoPin(reliablePhotoPose(capture, wire.component_id), wire.component_pin)))))
    && (job.status !== "completed" || (requestedWireId ? job.results.length === 1 : job.results.length === capture.wires.length)));
}

/** Serialize acquire/release across React StrictMode remounts and late HTTP replies. */
export function openPhotoSession(queue: { current: Promise<void> }, create: () => Promise<string>,
  release: (id: string) => Promise<unknown>, ready: (id: string) => void, failed: (error: unknown) => void) {
  let disposed = false;
  let token: string | undefined;
  let released = false;
  async function releaseOnce() {
    if (!token || released) return;
    await release(token);
    released = true;
  }
  const task = queue.current.catch(() => undefined).then(async () => {
    if (disposed) return;
    try {
      token = await create();
      if (disposed) await releaseOnce(); else ready(token);
    } catch (error) {
      await releaseOnce().catch(() => undefined);
      if (!disposed) failed(error);
    }
  });
  queue.current = task;
  return { close() {
    disposed = true;
    queue.current = queue.current.catch(() => undefined).then(() => releaseOnce()).then(() => undefined);
    return queue.current;
  } };
}

export function locatedPhotoPin(pose: DetectionMessage | ComponentPoseMessage | null | undefined, pinId: string) {
  if (!pose || pose.tracking !== "locked") return null;
  return pose.pins.find(pin => pin.id === pinId && pin.v) ?? null;
}

export function photoVerdictLabel(verdict: PhotoWireVerdict, locale: string): string {
  const labels = { matched: ["照片符合", "Photo matches"], suspected: ["疑似接錯", "Possible mismatch"],
    uncertain: ["無法確認", "Cannot confirm"] };
  return labels[verdict][locale === "en" ? 1 : 0];
}

export async function photoWiringRequest<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal; timeoutMs?: number } = {}): Promise<T> {
  const timeout = options.timeoutMs ? new AbortController() : null;
  const cancel = () => timeout?.abort(options.signal?.reason);
  if (options.signal?.aborted) cancel(); else options.signal?.addEventListener("abort", cancel, { once: true });
  const timer = timeout ? setTimeout(() => timeout.abort(new Error("Request timed out")), options.timeoutMs) : undefined;
  try {
    const response = await fetch(`/api/photo-wiring/${path}`, { method: options.method ?? "GET",
      headers: { Accept: "application/json", ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: timeout?.signal ?? options.signal });
    if (!response.ok) {
      let detail = "";
      try { const payload = await response.json(); detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload.error ?? ""); } catch { /* HTTP status remains useful. */ }
      throw new Error(`${response.status}${detail ? ` · ${detail}` : ""}`);
    }
    if (response.status === 204) return undefined as T;
    return await response.json() as T;
  } finally { clearTimeout(timer); options.signal?.removeEventListener("abort", cancel); }
}
