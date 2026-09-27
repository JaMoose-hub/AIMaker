import { isWireTraceFresh } from "./traceFreshness";
import type { AccuracySummary, DetectionMessage, Pin, WireTraceMessage } from "./types";

export type DistanceState =
  | "offline" | "waitingFrame" | "searching" | "boardUnverified" | "waiting"
  | "moveCloser" | "addMargin" | "checkingTrace" | "scaleReady";

export interface PitchSample {
  boardId: string;
  runtimeRevision: number;
  videoSize: readonly [number, number];
  pitchPx: number;
  atMs: number;
}

export interface DistanceAdvice {
  state: DistanceState;
  pitchPx: number | null;
  minimumPx: number | null;
  targetPx: number | null;
  factor: number | null;
  sampleFresh: boolean;
  boundaryUnverified: boolean;
}

export interface BoardStatusRun {
  context: string;
  frameId: number;
  count: number;
}

/** UI wording only. Never supplies or extends a pin pose. */
export function advanceBoardStatus(
  previous: BoardStatusRun,
  context: string,
  detection: DetectionMessage | null,
  live: boolean,
): { run: BoardStatusRun; statusKey: string; pillClass: "locked" | "stale" | "searching"; poseLocked: boolean } {
  const run = previous.context === context ? { ...previous } : { context, frameId: -1, count: 0 };
  if (!live || detection?.tracking !== "locked" || detection.pose_quality?.outline_only
    || !detection.pins?.some((pin) => pin.v)) {
    run.count = 0;
    run.frameId = -1;
  } else if (run.frameId !== detection.frame_id) {
    run.frameId = detection.frame_id;
    run.count += 1;
  }
  const poseLocked = run.count >= 4;
  const statusKey = !live ? "status.waitingFrame" : poseLocked ? "status.locked"
    : detection?.tracking === "locked" || detection?.tracking === "stale" || hasCurrentBoardBody(detection)
      ? "status.posePending" : "status.searching";
  const pillClass = poseLocked ? "locked" : statusKey === "status.searching" ? "searching" : "stale";
  return { run, statusKey, pillClass, poseLocked };
}

const LAST_PITCH_MS = 2500;
const TRACE_LIVE_MS = 1500;

/** A body box is not a GPIO pose, and an old body box is not a current sighting. */
export function hasCurrentBoardBody(detection: DetectionMessage | null): boolean {
  const body = detection?.body;
  return Boolean(body && Number.isFinite(body.confidence) && body.confidence >= 0.3
    && (body.frame_id === undefined || body.frame_id === detection?.frame_id)
    && (body.age_ms === undefined || (body.age_ms >= 0 && body.age_ms <= 650)));
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** Match the wire worker's J8 same-row pitch, not the 1-to-2 cross-row gap. */
export function projectedPinPitch(
  detection: DetectionMessage | null,
  pinsById: ReadonlyMap<string, Pin>,
): number | null {
  if (!detection || detection.tracking !== "locked" || detection.pose_quality?.outline_only) return null;
  const published = detection.geometry?.pitch_px;
  if (Number.isFinite(published) && Number(published) > 0) return Number(published);
  const rows = new Map<string, Array<{ index: number; x: number; y: number }>>();
  for (const point of detection.pins ?? []) {
    if (!point.v || !Number.isFinite(point.x) || !Number.isFinite(point.y)) continue;
    const pin = pinsById.get(point.id);
    if (!pin || !Number.isFinite(pin.index)) continue;
    const key = `${pin.header}:${pin.header === "J8" ? pin.index % 2 : 0}`;
    rows.set(key, [...(rows.get(key) ?? []), { index: pin.index, x: point.x, y: point.y }]);
  }
  const distances: number[] = [];
  for (const [key, row] of rows) {
    row.sort((a, b) => a.index - b.index);
    for (let i = 1; i < row.length; i++) {
      // A hidden pin must not turn a two-pitch gap into an apparent pitch.
      if (row[i].index - row[i - 1].index !== (key.startsWith("J8:") ? 2 : 1)) continue;
      const length = Math.hypot(row[i].x - row[i - 1].x, row[i].y - row[i - 1].y);
      if (length > 1e-6) distances.push(length);
    }
  }
  if (distances.length < 6) return null;
  const first = median(distances);
  return median(distances.filter((distance) => distance <= 1.35 * first));
}

export function currentPitchSample(
  detection: DetectionMessage | null,
  receivedAtMs: number,
  pinsById: ReadonlyMap<string, Pin>,
  now: number,
): PitchSample | null {
  if (!detection || receivedAtMs <= 0 || now - receivedAtMs > 1200) return null;
  const pitchPx = projectedPinPitch(detection, pinsById);
  if (pitchPx === null) return null;
  return {
    boardId: detection.board_id, runtimeRevision: detection.runtime_revision,
    videoSize: detection.video_size, pitchPx, atMs: receivedAtMs,
  };
}

export function distanceScaleAdvice({
  connected, detection, rawDetection, trace, traceReceivedAtMs, accuracy,
  currentSample, lastSample, now, boardId, runtimeRevision, videoSize,
}: {
  connected: boolean;
  detection: DetectionMessage | null;
  rawDetection: DetectionMessage | null;
  trace: WireTraceMessage | null;
  traceReceivedAtMs: number;
  accuracy: AccuracySummary | null;
  currentSample: PitchSample | null;
  lastSample: PitchSample | null;
  now: number;
  boardId: string | null;
  runtimeRevision: number | null;
  videoSize: readonly [number, number] | null;
}): DistanceAdvice {
  const boundaryUnverified = rawDetection?.pose_quality?.stability === "pcb_boundary_unverified"
    || detection?.pose_quality?.stability === "pcb_boundary_unverified"
    || detection?.pose_quality?.reason === "pcb_boundary_unverified";
  const freshTrace = trace && rawDetection && trace.board_id === rawDetection.board_id && traceReceivedAtMs > 0
    && now - traceReceivedAtMs <= TRACE_LIVE_MS && isWireTraceFresh(trace, rawDetection) ? trace : null;
  const minPitch = freshTrace?.geometry?.min_pitch_px ?? accuracy?.min_pitch_px;
  const minPxPerMm = freshTrace?.geometry?.min_px_per_mm ?? accuracy?.min_px_per_mm;
  const minimumPx = Number.isFinite(minPitch) && Number.isFinite(minPxPerMm)
    ? Math.max(Number(minPitch), Number(minPxPerMm) * 2.54) : null;
  const targetPx = minimumPx !== null && minimumPx > 0 ? Math.max(minimumPx * 1.2, minimumPx + 3) : null;
  const empty = { pitchPx: null, minimumPx, targetPx, factor: null, sampleFresh: false, boundaryUnverified };
  if (!connected) return { state: "offline", ...empty };

  const contextBoard = boardId ?? detection?.board_id;
  const contextRevision = runtimeRevision ?? detection?.runtime_revision;
  const contextSize = videoSize ?? detection?.video_size;
  const matchesCurrent = (sample: PitchSample | null) => Boolean(sample
    && sample.boardId === contextBoard
    && sample.runtimeRevision === contextRevision
    && (!contextSize || (sample.videoSize[0] === contextSize[0]
      && sample.videoSize[1] === contextSize[1])));
  const sample = matchesCurrent(currentSample) ? currentSample
    : matchesCurrent(lastSample) && lastSample && now - lastSample.atMs <= LAST_PITCH_MS ? lastSample : null;
  if (!sample || minimumPx === null || targetPx === null) {
    const state = !detection ? "waitingFrame"
      : detection.tracking === "locked" ? "waiting"
        : hasCurrentBoardBody(detection) || boundaryUnverified ? "boardUnverified" : "searching";
    return { state, ...empty };
  }
  const pitchPx = sample.pitchPx;
  const factor = Math.max(1, targetPx / pitchPx);
  const sampleFresh = sample === currentSample;
  const values = { pitchPx, minimumPx, targetPx, factor, sampleFresh, boundaryUnverified };
  if (pitchPx < minimumPx) return { state: "moveCloser", ...values };
  if (sampleFresh && freshTrace && !freshTrace.suppressed_reason && freshTrace.geometry)
    return { state: "scaleReady", ...values };
  return { state: pitchPx < targetPx ? "addMargin" : "checkingTrace", ...values };
}
