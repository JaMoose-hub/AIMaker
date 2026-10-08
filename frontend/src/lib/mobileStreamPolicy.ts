import type { BrowserRtcStats } from './mobileBrowserRtc';

export interface StreamQualityPolicy {
  scale: number; lastSample: number; changedAt: number; bad: number; good: number; disabled: boolean;
}
export const initialStreamQuality = (): StreamQualityPolicy => ({ scale: 1, lastSample: 0, changedAt: 0, bad: 0, good: 0, disabled: false });

/** Fresh transport counters only. A bitrate cap is not a measured link capacity. */
export function nextStreamQuality(state: StreamQualityPolicy, stats: BrowserRtcStats, now: number,
    nativeShortEdge: number, nativeLongEdge = nativeShortEdge * 16 / 9): StreamQualityPolicy {
  const stamp = stats.measuredAtMs, interval = stats.sampleIntervalMs;
  if (state.disabled || stamp === undefined || stamp <= state.lastSample || now < stamp || now - stamp > 2500
      || interval === undefined || interval < 250 || interval > 2500) return state;
  const consecutive = state.lastSample > 0 && stamp - state.lastSample <= 2500;
  const pressure = (stats.captureFps ?? 0) >= 20 && stats.sendFps !== undefined && stats.sendFps < 12
    && ((stats.targetBitrateKbps !== undefined && stats.targetBitrateKbps < 1200)
        || stats.qualityLimitationReason === 'bandwidth' || stats.qualityLimitationReason === 'cpu');
  const healthy = (stats.sendFps ?? 0) >= 20 && (stats.targetBitrateKbps ?? 0) >= 3500
    && stats.qualityLimitationReason !== 'bandwidth' && stats.qualityLimitationReason !== 'cpu';
  const next = { ...state, lastSample: stamp,
    bad: pressure ? (consecutive ? state.bad : 0) + 1 : 0,
    good: healthy ? (consecutive ? state.good : 0) + 1 : 0 };
  // Automatic adaptation must not turn a Full-HD selection into 720p/540p.
  // An explicitly selected native 720p source stays at scale 1, never smaller.
  const maxScale = Math.max(1, Math.min(2, nativeShortEdge / 1080, nativeLongEdge / 1920));
  if (state.scale > maxScale)
    return { ...next, scale: maxScale, changedAt: now, bad: 0, good: 0 };
  const smaller = [1, 1.5, 2].find(scale => scale > state.scale && scale <= maxScale);
  if (next.bad >= 3 && smaller && (!state.changedAt || now - state.changedAt >= 10000))
    return { ...next, scale: smaller, changedAt: now, bad: 0, good: 0 };
  if (next.good >= 15 && state.scale > 1 && now - state.changedAt >= 30000)
    return { ...next, scale: state.scale === 2 ? 1.5 : 1, changedAt: now, bad: 0, good: 0 };
  return next;
}

/** Bound browser APIs that may hang, including stats collection and parameters. */
export async function rtcOperation<T>(work: Promise<T>, timeoutMs = 2000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([work, new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(Error('phone_rtc_operation_timeout')), timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}

/** Only changes transmitted pixels; the original camera/photo track stays intact. */
export async function setBrowserStreamScale(sender: RTCRtpSender, scale: number): Promise<void> {
  const parameters = sender.getParameters();
  if (!parameters.encodings?.length) throw Error('phone_stream_scale_unsupported');
  parameters.encodings[0].scaleResolutionDownBy = scale;
  await rtcOperation(sender.setParameters(parameters));
  if (sender.getParameters().encodings?.[0]?.scaleResolutionDownBy !== scale)
    throw Error('phone_stream_scale_unsupported');
}
