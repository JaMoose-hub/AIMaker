/** Browser-only transport/presentation diagnostics; independent of camera and app state. */
export interface ViewerSample {
  id: string;
  timestamp: number;
  framesDecoded?: number;
  bytesReceived?: number;
  packetsReceived?: number;
  packetsLost?: number;
  jitterBufferDelay?: number;
  jitterBufferEmittedCount?: number;
  width?: number;
  height?: number;
  codec?: string;
}
export interface ViewerMetrics {
  decodeFps: number | null;
  receiveMbps: number | null;
  jitterBufferMs: number | null;
  packetLossPercent: number | null;
  width: number | null;
  height: number | null;
  codec: string | null;
}
export const emptyViewerMetrics = (): ViewerMetrics => ({ decodeFps: null, receiveMbps: null,
  jitterBufferMs: null, packetLossPercent: null, width: null, height: null, codec: null });
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
export const mobileMeasurementFresh = (measuredAtMs: number | null | undefined, nowMs = Date.now(), maxAgeMs = 2500) =>
  finite(measuredAtMs) && measuredAtMs > 0 && nowMs >= measuredAtMs && nowMs - measuredAtMs <= maxAgeMs;
/** Only a locally completed start can establish a first-frame waiting deadline. */
export function mobileReconnectWaitMs(receiveAgeMs: number | null, startedAtMs: number | null | undefined, nowMs = Date.now()): number | null {
  if (!finite(startedAtMs) || startedAtMs <= 0 || !finite(nowMs) || nowMs < startedAtMs) return null;
  return finite(receiveAgeMs) && receiveAgeMs >= 0 ? receiveAgeMs : nowMs - startedAtMs;
}
/** One automatic retry per explicit start; capture/foreground ownership always takes precedence. */
export function mobileReconnectEligible(input: { active: boolean; publishing: boolean; foreground: boolean; wanted: boolean;
  busy: boolean; capturePending: boolean; attempted: boolean; receiveAgeMs: number | null }) {
  return input.active && input.publishing && input.foreground && input.wanted && !input.busy && !input.capturePending
    && !input.attempted && input.receiveAgeMs !== null && input.receiveAgeMs >= 5000;
}
export async function restartMobileStream(stop: () => Promise<void>, start: () => Promise<void>, current: () => boolean): Promise<boolean> {
  if (!current()) return false;
  await stop();
  if (!current()) return false;
  await start();
  return current();
}
const delta = (current: number | undefined, previous: number | undefined) =>
  finite(current) && finite(previous) && current >= previous && previous >= 0 ? current - previous : null;

export function readViewerSample(report: RTCStatsReport): ViewerSample | null {
  let sample: ViewerSample | null = null;
  report.forEach(entry => {
    if (sample || entry.type !== "inbound-rtp" || (entry.kind !== "video" && entry.mediaType !== "video") || entry.isRemote || !finite(entry.timestamp)) return;
    const codec = typeof entry.codecId === "string" ? report.get(entry.codecId)?.mimeType : undefined;
    sample = { id: `${entry.id}:${entry.ssrc ?? ""}`, timestamp: entry.timestamp,
      framesDecoded: entry.framesDecoded, bytesReceived: entry.bytesReceived,
      packetsReceived: entry.packetsReceived, packetsLost: entry.packetsLost,
      jitterBufferDelay: entry.jitterBufferDelay, jitterBufferEmittedCount: entry.jitterBufferEmittedCount,
      width: entry.frameWidth, height: entry.frameHeight, codec: typeof codec === "string" ? codec : undefined };
  });
  return sample;
}

/** Interval averages only: a new SSRC, a counter reset, or absent support is not zero. */
export function viewerMetricDelta(previous: ViewerSample | null, current: ViewerSample | null): ViewerMetrics {
  const result = emptyViewerMetrics();
  if (!current) return result;
  result.width = finite(current.width) && current.width > 0 ? current.width : null;
  result.height = finite(current.height) && current.height > 0 ? current.height : null;
  result.codec = current.codec ?? null;
  if (!previous || previous.id !== current.id || !finite(current.timestamp) || !finite(previous.timestamp) || current.timestamp <= previous.timestamp) return result;
  const seconds = (current.timestamp - previous.timestamp) / 1000;
  const frames = delta(current.framesDecoded, previous.framesDecoded), bytes = delta(current.bytesReceived, previous.bytesReceived);
  result.decodeFps = frames === null ? null : frames / seconds;
  result.receiveMbps = bytes === null ? null : bytes * 8 / seconds / 1e6;
  const delay = delta(current.jitterBufferDelay, previous.jitterBufferDelay);
  const emitted = delta(current.jitterBufferEmittedCount, previous.jitterBufferEmittedCount);
  result.jitterBufferMs = delay !== null && emitted !== null && emitted > 0 ? delay * 1000 / emitted : null;
  const received = delta(current.packetsReceived, previous.packetsReceived);
  // Late arrivals can reduce cumulative loss. They are not negative interval loss.
  const lost = finite(current.packetsLost) && finite(previous.packetsLost) ? Math.max(0, current.packetsLost - previous.packetsLost) : null;
  result.packetLossPercent = received !== null && lost !== null && received + lost > 0 ? lost * 100 / (received + lost) : null;
  return result;
}

interface PresentationSource {
  requestVideoFrameCallback?: (callback: (now: number, metadata: { presentedFrames: number }) => void) => number;
  cancelVideoFrameCallback?: (id: number) => void;
  getVideoPlaybackQuality?: () => { totalVideoFrames: number; droppedVideoFrames: number };
}

/** Sampling is driven by the caller's 1 Hz timer, not a React update for every frame. */
export function observeVideoPresentation(video: PresentationSource, now = () => performance.now()) {
  let disposed = false, frameCallback: number | null = null;
  let usingCallbacks = typeof video.requestVideoFrameCallback === "function";
  let presented: number | null = null;
  let previous: { count: number; time: number } | null = null;
  const playbackCount = () => {
    try {
      const quality = video.getVideoPlaybackQuality?.();
      return quality && finite(quality.totalVideoFrames) && finite(quality.droppedVideoFrames)
        && quality.totalVideoFrames >= quality.droppedVideoFrames ? quality.totalVideoFrames - quality.droppedVideoFrames : null;
    } catch { return null; }
  };
  const schedule = () => {
    if (disposed || !usingCallbacks) return;
    try {
      frameCallback = video.requestVideoFrameCallback!((time, metadata) => {
        frameCallback = null;
        if (disposed) return;
        if (finite(metadata.presentedFrames) && metadata.presentedFrames >= 0) {
          presented = metadata.presentedFrames;
          if (!previous) previous = { count: presented, time };
        }
        schedule();
      });
    } catch { usingCallbacks = false; previous = null; presented = null; }
  };
  schedule();
  if (!usingCallbacks) {
    const count = playbackCount();
    if (count !== null) previous = { count, time: now() };
  }
  return {
    sample(time = now()): number | null {
      if (disposed) return null;
      const count = usingCallbacks ? presented : playbackCount();
      if (count === null || !finite(time)) { previous = null; return null; }
      const last = previous;
      previous = { count, time };
      if (!last || time <= last.time || count < last.count) return null;
      return (count - last.count) * 1000 / (time - last.time);
    },
    stop() {
      disposed = true;
      if (frameCallback !== null) {
        try { video.cancelVideoFrameCallback?.(frameCallback); } catch { /* Late callbacks still see disposed. */ }
      }
      frameCallback = null; previous = null; presented = null;
    },
  };
}

/** An optional browser target, not a claim about achieved buffering or latency. */
export function requestLowJitterBuffer(receiver: unknown, targetMs = 20): boolean {
  if (!receiver || typeof receiver !== "object" || !("jitterBufferTarget" in receiver)) return false;
  try { (receiver as { jitterBufferTarget: number | null }).jitterBufferTarget = targetMs; return true; }
  catch { return false; }
}
