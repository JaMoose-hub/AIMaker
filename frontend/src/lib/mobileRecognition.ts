import type { MobileSession } from "./mobile";
import type { ComponentPoseMessage, DetectionMessage } from "./types";

export interface MobileRecognition {
  source: "phone";
  session_id: string;
  generation: number;
  context_id: string;
  frame_seq: number;
  video_size: [number, number];
  valid_for_ms: number;
  /** Local monotonic deadline, set once by the desktop session controller. */
  display_deadline?: number;
  coordinates_are_hints_only: true;
  detection: DetectionMessage;
  components: (ComponentPoseMessage & { runtime_revision: number })[];
}
export type RecognitionLease = { key: string; deadline: number };

const liveContext = (session: MobileSession) => session.available_context?.context_id ?? session.context_id;

export function receivePhoneRecognition(previous: MobileSession | null, next: MobileSession | null, now: number): MobileSession | null {
  const sameSession = previous && next && previous.session_id === next.session_id
    && previous.conversation_id === next.conversation_id;
  if (sameSession) {
    // HTTP snapshots and socket events share this controller. None of these
    // monotonic counters may move backwards when a slower response arrives.
    if (Number.isInteger(previous.context_revision) && Number.isInteger(next.context_revision)
      && next.context_revision! < previous.context_revision!) return previous;
    if (next.view?.revision < previous.view?.revision
      || next.stream.generation < previous.stream.generation) return previous;
    if (next.stream.generation === previous.stream.generation
      && ((next.stream.preview_seq ?? Infinity) < (previous.stream.preview_seq ?? -Infinity)
        || (next.stream.video_receive_seq ?? Infinity) < (previous.stream.video_receive_seq ?? -Infinity)
        || !previous.stream.active && next.stream.active)) return previous;
  }
  const packet = next?.stream.recognition;
  if (!next || !packet) return next;
  // Once expiry/disconnection cleared a sample, only a new observation can
  // restore it. Remounting the preview must not grant a replay a fresh lease.
  if (sameSession && previous.stream.generation === next.stream.generation
    && liveContext(previous) === liveContext(next) && !previous.stream.recognition
    && packet.frame_seq <= (previous.stream.preview_seq ?? 0)) {
    return { ...next, stream: { ...next.stream, recognition: null } };
  }
  const old = previous?.stream.recognition;
  const same = old && old.session_id === packet.session_id && old.generation === packet.generation
    && old.context_id === packet.context_id && old.frame_seq === packet.frame_seq;
  const deadline = now + Math.max(0, Math.min(1500, packet.valid_for_ms || 0));
  return { ...next, stream: { ...next.stream, recognition: { ...packet,
    display_deadline: same && old.display_deadline !== undefined ? Math.min(old.display_deadline, deadline) : deadline } } };
}

/** Packet freshness is independent of capture-ready/Locked quality. Replays
 * cannot renew a sample, and a late result cannot replace a newer sequence. */
export function mobileRecognitionLease(session: MobileSession, now: number, previous: RecognitionLease): RecognitionLease {
  const p = session.stream.recognition;
  const owner = `${session.session_id}:${session.stream.generation}:${liveContext(session)}:`;
  const key = p ? `${owner}${p.frame_seq}` : owner;
  if (!session.stream.active || !session.stream.publisher_connected || !p
    || p.source !== "phone" || p.session_id !== session.session_id || p.generation !== session.stream.generation
    || p.context_id !== liveContext(session) || session.available_context?.conversation_id && session.available_context.conversation_id !== session.conversation_id
    || p.frame_seq !== session.stream.preview_seq || !Number.isSafeInteger(p.frame_seq) || p.frame_seq < 1
    || !Number.isFinite(p.valid_for_ms) || p.valid_for_ms <= 0) return { key, deadline: 0 };
  if (previous.key.startsWith(owner) && Number(previous.key.slice(owner.length)) > p.frame_seq) return previous;
  const deadline = Math.min(now + Math.min(1500, p.valid_for_ms), p.display_deadline ?? Infinity);
  return { key, deadline: key === previous.key ? Math.min(previous.deadline, deadline) : deadline };
}

/** Coordinates must match the actual decoded phone dimensions, not the
 * requested resolution or the hidden webcam. Live WebRTC markers are latest
 * sampled guidance, not exact-frame frozen-photo evidence. */
export function phoneRecognitionForDisplay(session: MobileSession, size: readonly [number, number], now: number, lease: RecognitionLease) {
  const p = session.stream.recognition;
  if (!p || now >= lease.deadline || lease.key !== `${session.session_id}:${session.stream.generation}:${liveContext(session)}:${p.frame_seq}`
    || p.coordinates_are_hints_only !== true || !size.every(n => Number.isFinite(n) && n > 0)
    || p.video_size?.[0] !== size[0] || p.video_size?.[1] !== size[1]) return null;
  const validPose = (pose: DetectionMessage | MobileRecognition["components"][number]) => pose?.frame_id === p.frame_seq
    && pose.runtime_revision === p.generation && pose.video_size?.[0] === size[0] && pose.video_size?.[1] === size[1]
    && ["locked", "searching", "stale"].includes(pose.tracking) && Array.isArray(pose.pins)
    && pose.pins.every(pin => pin != null && typeof pin.id === "string" && [pin.x, pin.y, pin.c].every(Number.isFinite))
    && (pose.outline == null || Array.isArray(pose.outline) && pose.outline.length === 4
      && pose.outline.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)));
  return p.detection?.board_id === "raspberry-pi-5" && validPose(p.detection) && Array.isArray(p.components)
    && p.components.every(validPose) ? p : null;
}
