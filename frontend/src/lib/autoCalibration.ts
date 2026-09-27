import type { DistanceAdvice } from "./boardDistance";
import type { DetectionMessage } from "./types";

export type AlignmentIssue = "waitingFrame" | "searching" | "boundary" | "moveCloser"
  | "poseUnverified" | "realtimeRequired";

export type AlignmentEvidence =
  | { kind: "supported"; context: string; frameId: number; tsMs: number; pitchPx: number }
  | { kind: "issue"; issue: AlignmentIssue };

export interface AlignmentRun {
  context: string;
  firstTs: number;
  lastTs: number;
  lastFrameId: number;
  count: number;
  pitchPx: number;
}

export const emptyAlignmentRun = (): AlignmentRun => ({
  context: "", firstTs: 0, lastTs: 0, lastFrameId: -1, count: 0, pitchPx: 0,
});

/** Image tuning may run at any scale; this only limits the subsequent GPIO pose claim. */
export function postTuneAlignmentIssue({ distance, synchronized }: {
  distance: DistanceAdvice;
  synchronized: boolean;
}): AlignmentIssue | null {
  if (!synchronized) return "realtimeRequired";
  if (distance.state === "moveCloser" && distance.pitchPx !== null && distance.minimumPx !== null
    && distance.pitchPx < distance.minimumPx) return "moveCloser";
  return null;
}

/** Read-only check of the same-frame GPIO correction already used by the display tracker. */
export function inspectAlignment({ detection, distance, receivedAtMs, now, synchronized }: {
  detection: DetectionMessage | null;
  distance: DistanceAdvice;
  receivedAtMs: number;
  now: number;
  synchronized: boolean;
}): AlignmentEvidence {
  if (!synchronized) return { kind: "issue", issue: "realtimeRequired" };
  if (!detection || receivedAtMs <= 0 || now - receivedAtMs < 0 || now - receivedAtMs > 650)
    return { kind: "issue", issue: "waitingFrame" };
  if (detection.board_id !== "raspberry-pi-5") return { kind: "issue", issue: "searching" };
  if (detection.pose_quality?.reason === "pcb_boundary_unverified"
    || (detection.tracking !== "locked" && distance.boundaryUnverified))
    return { kind: "issue", issue: "boundary" };
  if (distance.sampleFresh && distance.pitchPx !== null && distance.minimumPx !== null
    && distance.pitchPx < distance.minimumPx)
    return { kind: "issue", issue: "moveCloser" };
  if (detection.tracking !== "locked" || !distance.sampleFresh || distance.pitchPx === null
    || distance.minimumPx === null || !Array.isArray(detection.outline) || detection.outline.length !== 4)
    return { kind: "issue", issue: "poseUnverified" };
  const quality = detection.pose_quality;
  const offset = quality?.pin_alignment_offset_px;
  const regions = quality?.pin_regions;
  const supported = regions ? Object.values(regions).filter((region) => region?.supported === true).length : 0;
  const visible = detection.pins.filter((pin) => pin.v).length;
  if (quality?.object_supported !== true || quality.outline_only || supported < 24 || visible < 24
    || !Array.isArray(offset) || offset.length !== 2 || !offset.every(Number.isFinite)
    || !Number.isFinite(detection.ts_ms) || !Number.isFinite(distance.pitchPx))
    return { kind: "issue", issue: "poseUnverified" };
  return {
    kind: "supported",
    context: `${detection.board_id}:${detection.runtime_revision}:${detection.video_size.join("x")}`,
    frameId: detection.frame_id,
    tsMs: detection.ts_ms,
    pitchPx: distance.pitchPx,
  };
}

/** Require several different, scale-consistent source frames; one lucky lock is not calibration. */
export function advanceAlignment(run: AlignmentRun, evidence: AlignmentEvidence) {
  if (evidence.kind !== "supported") return { run: emptyAlignmentRun(), ready: false };
  if (run.context === evidence.context && evidence.frameId <= run.lastFrameId)
    return { run, ready: false };
  if (run.context !== evidence.context || evidence.tsMs <= run.lastTs
    || evidence.tsMs - run.lastTs > 1000
    || (run.pitchPx > 0 && Math.abs(evidence.pitchPx / run.pitchPx - 1) > .12)) {
    const next = { context: evidence.context, firstTs: evidence.tsMs, lastTs: evidence.tsMs,
      lastFrameId: evidence.frameId, count: 1, pitchPx: evidence.pitchPx };
    return { run: next, ready: false };
  }
  const next = { ...run, lastTs: evidence.tsMs, lastFrameId: evidence.frameId,
    count: run.count + 1, pitchPx: evidence.pitchPx };
  return { run: next, ready: next.count >= 4 && next.lastTs - next.firstTs >= 450 };
}
