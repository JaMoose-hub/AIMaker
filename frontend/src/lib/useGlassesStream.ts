import { useCallback, useEffect, useRef, useState } from "react";
import { createGlassesMutationQueue, createGlassesSessionSettings, glassesRestoreError, requestGlassesStream, sameGlassesCamera, type GlassesSettings, type GlassesStatus } from "./glasses";

export function useGlassesStream() {
  const [status, setStatus] = useState<GlassesStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [watching, setWatching] = useState(false);
  const [pending, setPending] = useState(false);
  const generation = useRef(0);
  const queue = useRef(createGlassesMutationQueue());
  const sessionSettings = useRef(createGlassesSessionSettings());
  const stopRequested = useRef(false);

  const change = useCallback((method: "PUT" | "DELETE", settings?: GlassesSettings) => {
    const revision = ++generation.current;
    stopRequested.current = method === "DELETE";
    setPending(true);
    setWatching(true);
    setError(null);
    setStatus(current => current ? { ...current, state: method === "DELETE" ? "restoring"
      : settings && current.state === "running" && sameGlassesCamera(current.requested, settings) ? "running" : "switching" } : null);
    // Esc during startup must restore only after its PUT has reached the server.
    const operation = queue.current(method, settings);
    void operation.then(next => {
      if (revision !== generation.current) return;
      sessionSettings.current.observe(next);
      setStatus(next);
    }).catch((reason: unknown) => {
      if (revision === generation.current) setError(String(reason));
    }).finally(() => {
      if (revision === generation.current) setPending(false);
    });
  }, []);
  const start = useCallback(() => change("PUT", sessionSettings.current.forStart()), [change]);
  const apply = useCallback((settings: GlassesSettings) => change("PUT", settings), [change]);
  const stop = useCallback(() => change("DELETE"), [change]);

  useEffect(() => {
    if (!watching || pending) return;
    let disposed = false;
    let timer = 0;
    const revision = generation.current;
    async function poll() {
      try {
        const next = await requestGlassesStream("GET");
        if (disposed || revision !== generation.current) return;
        sessionSettings.current.observe(next);
        setStatus(next);
        setError(null);
        if (stopRequested.current && !next.active && !["starting", "switching", "restoring", "stopping"].includes(next.state)) {
          setWatching(false);
          return;
        }
      } catch (reason) {
        if (!disposed && revision === generation.current) setError(String(reason));
      } finally {
        if (!disposed) timer = window.setTimeout(poll, 500);
      }
    }
    void poll();
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [watching, pending]);

  return { status, error, pending, start, apply, stop,
    restoreError: glassesRestoreError(stopRequested.current, pending, status, error) };
}
