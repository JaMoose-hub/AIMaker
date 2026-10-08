import type { AppConfig } from './types';

export interface LiveCameraStatus {
  kind: 'webcam' | 'phone'; session_id: string | null; generation: number | null;
  runtime_revision: number; ready: boolean; error: string | null;
  pending_size?: [number, number] | null;
}
export const LIVE_CAMERA_STATUS_TTL_MS = 2500;

/** A status lease is not a video/pose lease; those keep their stricter expiry. */
export function currentLiveCameraStatus(value: LiveCameraStatus | null, receivedAt: number,
    config: AppConfig | null, now: number): LiveCameraStatus | null {
  if (!value || !config || !Number.isFinite(receivedAt) || !Number.isFinite(now) || now < receivedAt
      || now - receivedAt > LIVE_CAMERA_STATUS_TTL_MS || value.runtime_revision !== config.runtime_revision) return null;
  if (config.camera_source !== 'phone') return value.kind === 'webcam' ? value : null;
  const identity = config.camera_identity?.split(':');
  return value.kind === 'phone' && identity?.[0] === 'phone' && identity[1] === value.session_id
    && Number(identity[2]) === value.generation ? value : null;
}

/** Deadlines include body parsing and settle even for a non-cooperating fetch. */
export async function liveCameraRequest<T>(url: string, init: RequestInit = {}, timeoutMs = 5000,
    signal?: AbortSignal): Promise<T> {
  const abort = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const deadline = new Promise<never>((_, reject) => {
    cancel = () => { reject(signal?.reason ?? new DOMException('Camera request cancelled', 'AbortError')); abort.abort(); };
    timer = setTimeout(() => { reject(Error('live_camera_timeout')); abort.abort(); }, timeoutMs);
    if (signal?.aborted) cancel(); else signal?.addEventListener('abort', cancel, { once: true });
  });
  try {
    if (signal?.aborted) return await deadline;
    const work = fetch(url, { ...init, cache: 'no-store', signal: abort.signal }).then(async response => {
      const body = await response.json();
      if (!response.ok) throw Error(body?.detail ?? 'live_source_unavailable');
      return body as T;
    });
    return await Promise.race([work, deadline]);
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', cancel); }
}
