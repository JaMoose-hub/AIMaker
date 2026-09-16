import type { DetectionMessage, WireTraceMessage } from "./types";

/**
 * Wire tracing is intentionally throttled, while pose detections run at the
 * camera cadence.  Do not keep presenting a wire path after it has drifted
 * too far from the live source frame: the path is source-pixel geometry, not
 * a board-relative object that can safely be stretched onto a new pose.
 *
 * At 30 fps, 45 source frames is 1.5 s.  This is long enough to tolerate a
 * slow trace tick, but short enough that a stalled worker, camera switch, or
 * frame-id reset cannot leave an old connection looking current.
 */
export const MAX_TRACE_FRAME_LAG = 45;

export function isWireTraceFresh(
  trace: WireTraceMessage | null,
  detection: DetectionMessage | null,
): boolean {
  if (!trace || !detection || detection.tracking !== "locked") return false;
  if (trace.board_tracking !== "locked") return false;
  if (trace.video_size) {
    if (trace.video_size[0] !== detection.video_size[0] || trace.video_size[1] !== detection.video_size[1]) {
      return false;
    }
  }
  const lag = detection.frame_id - trace.frame_id;
  return lag >= 0 && lag <= MAX_TRACE_FRAME_LAG;
}
