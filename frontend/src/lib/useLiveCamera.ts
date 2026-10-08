import { useCallback, useEffect, useRef, useState } from 'react';
import type { AppConfig } from './types';
import type { MobileSession } from './mobile';
import { currentLiveCameraStatus, liveCameraRequest, type LiveCameraStatus } from './liveCameraState';
export type { LiveCameraStatus } from './liveCameraState';

export function useLiveCamera(config: AppConfig | null, onConfig: (config: AppConfig) => void) {
  const [reading, setReading] = useState<{ value: LiveCameraStatus | null; at: number }>({ value: null, at: 0 });
  const [clock, setClock] = useState(Date.now);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const flight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const selection = useRef<AbortController | null>(null);
  const latest = useRef(config); latest.current = config;
  const resize = useRef({ key: '', attempts: 0, at: 0 });
  const accept = useCallback((value: LiveCameraStatus) => {
    const at = Date.now(); setReading({ value, at }); setClock(at);
  }, []);
  useEffect(() => {
    mounted.current = true;
    setPending(false);
    return () => { mounted.current = false; epoch.current++; selection.current?.abort(); flight.current = false; };
  }, []);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const ticker = setInterval(() => setClock(Date.now()), 250);
    const poll = async () => {
      const owner = epoch.current;
      const current = () => !disposed && owner === epoch.current && !flight.current;
      try {
        if (flight.current) return;
        const next = await liveCameraRequest<LiveCameraStatus>('/api/camera/live-source', {}, 5000, abort.signal);
        if (!current()) return;
        if (next.runtime_revision !== latest.current?.runtime_revision) {
          const restored = await liveCameraRequest<AppConfig>('/api/config', {}, 5000, abort.signal);
          if (!current() || restored.runtime_revision !== next.runtime_revision) return;
          onConfig(restored);
        }
        if (current()) accept(next);
      } catch { /* A failed status poll does not erase a still-valid metadata lease. */ }
      finally { if (!disposed) timer = setTimeout(() => void poll(), 1000); }
    };
    if (config) void poll();
    return () => { disposed = true; abort.abort(); clearTimeout(timer); clearInterval(ticker); };
  }, [config?.runtime_revision, config?.camera_source, config?.camera_identity, onConfig, accept]);

  const select = useCallback(async (kind: 'webcam' | 'phone', session?: MobileSession | null) => {
    if (flight.current || !mounted.current) return false;
    const owner = ++epoch.current, abort = new AbortController();
    selection.current = abort;
    const current = () => mounted.current && owner === epoch.current;
    flight.current = true; setPending(true); setError('');
    setReading({ value: null, at: 0 });
    try {
      const result = await liveCameraRequest<LiveCameraStatus & { ok?: boolean; detail?: string }>('/api/camera/live-source', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, session_id: session?.session_id, generation: session?.stream.generation }) }, 15000, abort.signal);
      // A failed switch may have rolled back with a new runtime revision.
      const restored = await liveCameraRequest<AppConfig>('/api/config', {}, 5000, abort.signal);
      if (!current()) return false;
      onConfig(restored);
      if (result.ok === false) throw new Error(result.detail ?? result.error ?? 'camera_switch_failed');
      accept(result); return true;
    } catch (cause) {
      if (current()) {
        setError(cause instanceof Error ? cause.message : String(cause));
        // A timed-out POST may have completed server-side. Reconcile before retry.
        try {
          const restored = await liveCameraRequest<AppConfig>('/api/config', {}, 5000, abort.signal);
          if (current()) onConfig(restored);
        } catch { /* The next bounded status poll will try again. */ }
      }
      return false;
    } finally {
      if (current()) { flight.current = false; setPending(false); }
      if (selection.current === abort) selection.current = null;
    }
  }, [onConfig, accept]);
  const reconnect = useCallback(async () => {
    const identity = latest.current?.camera_identity;
    const sid = identity?.split(':');
    if (latest.current?.camera_source !== 'phone' || sid?.[0] !== 'phone' || !sid[1] || flight.current) return;
    const owner = epoch.current;
    try {
      const session = await liveCameraRequest<MobileSession>(`/api/mobile/session?session_id=${encodeURIComponent(sid[1])}`);
      if (!mounted.current || owner !== epoch.current || identity !== latest.current?.camera_identity
          || latest.current?.camera_source !== 'phone' || session.stream.generation !== Number(sid[2])) return;
      await select('phone', session);
    } catch (cause) {
      if (mounted.current && owner === epoch.current) setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [select]);
  const status = currentLiveCameraStatus(reading.value, reading.at, config, clock);
  const sizeKey = status?.pending_size?.join('x');
  useEffect(() => {
    if (pending || status?.kind !== 'phone' || status.error !== 'phone_dimensions_changed' || !sizeKey) return;
    const key = `${status.session_id}:${status.generation}:${sizeKey}`;
    const now = Date.now();
    if (resize.current.key !== key) resize.current = { key, attempts: 0, at: 0 };
    if (resize.current.attempts >= 2 || (resize.current.attempts > 0 && now - resize.current.at < 5000)) return;
    resize.current.attempts++; resize.current.at = now;
    // Re-selecting resets the runtime/geometry before accepting the new pixel scale.
    void reconnect();
  }, [pending, status?.kind, status?.error, status?.session_id, status?.generation, sizeKey, clock, reconnect]);
  return { status, pending, error, select, reconnect };
}
