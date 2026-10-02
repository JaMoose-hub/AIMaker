import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createCaptureCountdown } from "./captureCountdown";

export function useCaptureCountdown(scope: string, enabled: boolean, surface: RefObject<HTMLElement>) {
  const [remaining, setRemaining] = useState<number | null>(null);
  const mounted = useRef(true);
  const latest = useRef({ scope, enabled });
  const countdown = useRef<ReturnType<typeof createCaptureCountdown> | null>(null);
  if (!countdown.current) countdown.current = createCaptureCountdown(value => { if (mounted.current) setRemaining(value); });
  const timer = countdown.current;
  useLayoutEffect(() => { latest.current = { scope, enabled }; }, [scope, enabled]);
  useEffect(() => { if (!enabled) timer.cancel(); return () => timer.cancel(); }, [scope, enabled, timer]);
  useEffect(() => {
    mounted.current = true;
    const onHidden = () => { if (document.hidden) timer.cancel(); };
    const onEscape = (event: KeyboardEvent) => { if (event.key === "Escape") timer.cancel(); };
    document.addEventListener("visibilitychange", onHidden);
    document.addEventListener("keydown", onEscape);
    return () => {
      mounted.current = false; timer.cancel();
      document.removeEventListener("visibilitychange", onHidden);
      document.removeEventListener("keydown", onEscape);
    };
  }, [timer]);
  function run<T>(action: () => T | Promise<T>) {
    return timer.run(action, () => mounted.current && latest.current.scope === scope && latest.current.enabled &&
      !document.hidden && Boolean(surface.current?.getClientRects().length) && !surface.current?.closest("[hidden]"));
  }
  return { remaining, run, cancel: timer.cancel };
}
