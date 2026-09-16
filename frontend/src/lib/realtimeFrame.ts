import type { ComponentPoseMessage, DetectionMessage } from "./types";

export interface TrackingFrame {
  seq: number;
  frame_id: number;
  runtime_revision: number;
  board_id: string;
  image: string;
  detection: DetectionMessage;
  components: ComponentPoseMessage[];
  receivedAt: number;
}

/** Reject the previous camera mode during render, before hook cleanup runs. */
export function trackingDisplayFrame(frame: (TrackingFrame & { sourceKey: string }) | null,
  enabled: boolean, sourceKey: string, boardId: string | null, revision: number) {
  return enabled && frame?.sourceKey === sourceKey && frame.board_id === boardId
    && frame.runtime_revision === revision ? frame : null;
}

/** Reject old/foreign poses before decoding or displaying their image. */
export function acceptTrackingFrame(next: TrackingFrame, boardId: string | null, revision: number, after: number) {
  return next.board_id === boardId && next.runtime_revision === revision
    && Number.isFinite(next.seq) && next.seq > after
    && next.detection?.frame_id === next.frame_id
    && next.detection.board_id === boardId && next.detection.runtime_revision === revision
    && Array.isArray(next.components)
    && next.components.every((pose) => !["hc-sr04", "mrd-tf240-8p-cs"].includes(pose.component_id)
      || pose.frame_id === next.frame_id)
    && typeof next.image === "string" && next.image.startsWith("data:image/jpeg;base64,");
}

/** A camera/backend restart can reset sequence numbers without closing HTTP. */
export function trackingCursor(after: number, lastFrameAt: number, now: number) {
  return now - lastFrameAt > 600 ? -1 : after;
}

/** Same-frame overlays must not interpolate toward an older camera pose. */
export function isSynchronizedPose(detection: DetectionMessage | null) {
  return detection?.pose_quality?.stability === "yolo_direct"
    || detection?.pose_quality?.stability === "optical_flow"
    || detection?.pose_quality?.stability === "optical_flow_partial"
    || detection?.pose_quality?.stability === "motion_prediction"
    || detection?.pose_quality?.stability === "flow_lost";
}

/** Body geometry never fills outline/pins or upgrades the semantic tracking state. */
export function currentBodyOutline(pose: DetectionMessage | ComponentPoseMessage | null) {
  const body = pose?.body;
  if (!body || body.display_only !== true || body.frame_id !== pose?.frame_id
    || !Number.isFinite(body.age_ms) || body.age_ms! < 0 || body.age_ms! > 650
    || !body.outline || body.outline.length !== 4
    || !body.outline.every((p) => p.length === 2 && p.every(Number.isFinite))) return null;
  return body.outline;
}

export interface BodyRecognition {
  id: string;
  outline: [number, number][];
  /** Eye text placement only; raw body geometry stays available unchanged. */
  labelAnchorOutline?: [number, number][];
  /** Eye-only explanation for a current clipped body without located pins. */
  clipped?: boolean;
  pinsLocated: boolean;
  drawOutline: boolean;
}

function bodyOverlap(left: [number, number][], right: [number, number][]) {
  const bounds = (points: [number, number][]) => [
    Math.min(...points.map(point => point[0])), Math.min(...points.map(point => point[1])),
    Math.max(...points.map(point => point[0])), Math.max(...points.map(point => point[1])),
  ];
  const a = bounds(left), b = bounds(right);
  const intersection = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]))
    * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection;
  return union > 0 ? intersection / union : 0;
}

/** Show the same wiring model's body evidence without turning it into GPIO pose. */
export function currentBodyRecognitions(frame: TrackingFrame | null, glassesMode = false): BodyRecognition[] {
  if (!frame || frame.detection.frame_id !== frame.frame_id
    || frame.detection.runtime_revision !== frame.runtime_revision
    || frame.detection.board_id !== frame.board_id) return [];
  const candidates = [frame.detection, ...frame.components].flatMap(pose => {
    if (pose.frame_id !== frame.frame_id) return [];
    const outline = currentBodyOutline(pose);
    if (!outline) return [];
    const pinsLocated = pose.tracking !== "searching" && pose.pins.some(pin => pin.v);
    const labelAnchorOutline = glassesMode && pinsLocated && pose.outline?.length === 4
      && pose.outline.every(point => point.length === 2 && point.every(Number.isFinite))
      ? pose.outline : null;
    const confidence = pose.body!.confidence;
    if (!pinsLocated && (!Number.isFinite(confidence) || confidence < 0.30)) return [];
    return [{
      id: "component_id" in pose ? pose.component_id : pose.board_id,
      outline,
      ...(labelAnchorOutline ? { labelAnchorOutline } : {}),
      ...(glassesMode && !pinsLocated && pose.body!.partial === true ? { clipped: true } : {}),
      pinsLocated,
      drawOutline: pose.tracking === "searching" || !pose.outline?.length,
      confidence,
    }];
  });
  // Independently trained one-class models can name the same physical object.
  // Keep existing located-pin identities, then resolve body-only duplicates by
  // confidence. IoU (not containment) lets small modules remain on a large PCB.
  const retained = candidates.filter(candidate => candidate.pinsLocated);
  for (const candidate of candidates.filter(item => !item.pinsLocated).sort((a, b) => b.confidence - a.confidence)) {
    if (!retained.some(other => bodyOverlap(candidate.outline, other.outline) > 0.5)) retained.push(candidate);
  }
  return retained.map(({ confidence: _confidence, ...item }) => item);
}

export function bodyRecognitionStatus(frame: TrackingFrame | null) {
  if (!frame) return [];
  return ["raspberry-pi-5", "hc-sr04", "mrd-tf240-8p-cs"].map((id) => {
    const pose = id === frame.board_id ? frame.detection : frame.components.find((p) => p.component_id === id);
    const found = Boolean(pose && (currentBodyOutline(pose)
      || (pose.tracking === "locked" && pose.outline?.length === 4)));
    return { id, found };
  });
}

/** Only current display evidence, never a historical or inferred object pose. */
export function trackingNotices(frame: TrackingFrame | null) {
  if (!frame) return [];
  return [frame.detection, ...frame.components].flatMap((pose) => {
    const quality = pose.pose_quality;
    const id = "component_id" in pose ? pose.component_id : pose.board_id;
    if (quality?.reason === "pin_orientation_unverified")
      return [{ id, key: "camera.trackingOrientationPending" }];
    if (quality?.outline_only) return [{ id, key: quality.reason === "partial_support" || quality.reason === "pin_region_changed"
      ? "camera.trackingPartial" : "camera.trackingConfirming" }];
    if (quality?.partial) return [{ id, key: "camera.trackingPartial" }];
    if (quality?.stability === "flow_lost" && quality.interrupted)
      return [{ id, key: "camera.trackingObstructed" }];
    return [];
  });
}
