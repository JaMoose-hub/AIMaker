import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchConfig } from './api';
import type { AppConfig } from './types';
import type { MobileSession } from './mobile';

export interface LiveCameraStatus {
  kind: 'webcam' | 'phone'; session_id: string | null; generation: number | null;
  runtime_revision: number; ready: boolean; error: string | null;
}

export function useLiveCamera(config: AppConfig | null, onConfig: (config: AppConfig) => void) {
  const [status, setStatus] = useState<LiveCameraStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const flight = useRef(false);
  const revision = config?.runtime_revision;
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch('/api/camera/live-source', { signal: abort.signal });
        if (!response.ok) throw new Error('live_source_unavailable');
        const next: LiveCameraStatus = await response.json();
        if (!disposed && !flight.current) {
          setStatus(current => JSON.stringify(current) === JSON.stringify(next) ? current : next);
          if (next.runtime_revision !== revision) {
            const current = await fetchConfig();
            if (!disposed && !flight.current) onConfig(current);
          }
        }
      } catch {
        if (!disposed && !flight.current) setStatus(null);
      }
      if (!disposed) timer = setTimeout(() => void poll(), 1000);
    };
    if (config) void poll();
    return () => { disposed = true; abort.abort(); clearTimeout(timer); };
  }, [revision, config?.camera_source, onConfig]);

  const select = useCallback(async (kind: 'webcam' | 'phone', session?: MobileSession | null) => {
    if (flight.current) return false;
    flight.current = true; setPending(true); setError('');
    try {
      const response = await fetch('/api/camera/live-source', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, session_id: session?.session_id, generation: session?.stream.generation }) });
      const result = await response.json();
      // A failed switch may have rolled back with a new runtime revision.
      const current = await fetchConfig();
      onConfig(current);
      if (!response.ok || result.ok === false) throw new Error(result.detail ?? result.error ?? 'camera_switch_failed');
      setStatus(result); return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause)); return false;
    } finally { flight.current = false; setPending(false); }
  }, [onConfig]);
  const reconnect = useCallback(async () => {
    if (!status?.session_id || flight.current) return;
    try {
      const response = await fetch(`/api/mobile/session?session_id=${encodeURIComponent(status.session_id)}`);
      if (!response.ok) throw new Error('mobile_session_unavailable');
      const session: MobileSession = await response.json();
      await select('phone', session);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [status?.session_id, select]);
  return { status, pending, error, select, reconnect };
}
