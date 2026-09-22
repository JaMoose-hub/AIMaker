import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { connectPi, executionAction, fetchPiStatus, type PiResponse, type PiStatus } from "./piApi";

function useConnection() {
  const [status, setStatus] = useState<PiStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [networkError, setNetworkError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(false), mounted = useRef(false), epoch = useRef(0);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      const version = epoch.current;
      try {
        if (!active.current) {
          const next = await fetchPiStatus(controller.signal);
          if (!controller.signal.aborted && version === epoch.current) { setStatus(next); setNetworkError(false); }
        }
      } catch { if (!controller.signal.aborted && version === epoch.current) setNetworkError(true); }
      finally { if (!controller.signal.aborted) timer = window.setTimeout(poll, 1000); }
    }
    void poll();
    return () => { mounted.current = false; controller.abort(); window.clearTimeout(timer); };
  }, []);
  async function perform(action: () => Promise<PiResponse>) {
    if (active.current) return;
    active.current = true; epoch.current++; setPending(true); setError(null);
    try {
      const result = await action();
      if (mounted.current) { setStatus(result.status); setNetworkError(false); setError(result.ok ? null : result.error ?? "Pi operation failed"); }
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : "Pi operation failed");
      // Mutating requests are never automatically retried: poll the queue first.
    } finally { active.current = false; if (mounted.current) setPending(false); }
  }
  return { status, pending, networkError, error, perform,
    connect: () => perform(connectPi),
    action: (id: string, action: "confirm" | "cancel", owner?: string | null) => perform(() => executionAction(id, action, owner)),
  };
}
const Context = createContext<ReturnType<typeof useConnection> | null>(null);
export function PiConnectionProvider({ children }: { children: ReactNode }) {
  const value = useConnection();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function usePiConnection() {
  const value = useContext(Context);
  if (!value) throw new Error("PiConnectionProvider is required");
  return value;
}
