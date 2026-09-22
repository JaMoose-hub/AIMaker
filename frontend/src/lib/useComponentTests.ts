import { useEffect, useRef, useState } from "react";
import { makerRequest, type ProjectDesign, type ProjectGuideState } from "./maker";
import { componentTestKey, componentTestRequest, type ComponentTestRun, type ComponentTestStatus } from "./componentTests";

export function useComponentTests(design: ProjectDesign, session: ProjectGuideState) {
  const [status, setStatus] = useState<ComponentTestStatus>({ connected: false, test_busy: false, active: null, results: [] });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const endpoint = `pi/component-tests?project_id=${encodeURIComponent(design.id)}`;
  useEffect(() => {
    mounted.current = true;
    epoch.current += 1;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      const version = epoch.current;
      try {
        const next = await makerRequest<ComponentTestStatus>(endpoint, undefined, controller.signal);
        if (!controller.signal.aborted && version === epoch.current && !inFlight.current) {
          setStatus(next); setError(current => current === "connection_lost" ? null : current);
        }
      } catch {
        if (!controller.signal.aborted) setError("connection_lost");
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(poll, 1000);
      }
    }
    void poll();
    return () => { mounted.current = false; controller.abort(); window.clearTimeout(timer); };
  }, [endpoint]);

  async function send(path: string, body: unknown) {
    if (inFlight.current) return;
    inFlight.current = true; epoch.current += 1; setPending(true); setError(null);
    try {
      const next = await makerRequest<ComponentTestStatus>(path, body);
      if (mounted.current) { setStatus(next); if (next.ok === false) setError(next.error ?? "program_error"); }
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "connection_lost");
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }
  async function connect() {
    if (inFlight.current) return;
    inFlight.current = true; epoch.current += 1; setPending(true);
    try {
      const reply = await makerRequest<{ok: boolean}>("pi/connect", {});
      if (mounted.current) { setError(reply.ok ? null : "connection_lost"); setStatus(await makerRequest<ComponentTestStatus>(endpoint)); }
    } catch { if (mounted.current) setError("connection_lost"); }
    finally { inFlight.current = false; if (mounted.current) setPending(false); }
  }
  return { status, error, pending, connect,
    // Only an explicit local edit invalidates a run. A passive/stale browser tab
    // must never cancel a test started by another tab.
    invalidate: (cid?: string) => {
      const run = status.active ?? status.results.at(-1);
      if (run?.project_id === design.id && (!cid || run.component_id === cid) && !run.invalidated)
        return send(`pi/component-tests/${run.id}/action`, { action: "invalidate", guide_key: "" });
      return Promise.resolve();
    },
    start: (cid: string) => {
      if (!status.execution) { setError("executor_restart_required"); return Promise.resolve(); }
      return send("pi/component-tests", {...componentTestRequest(design, session, cid), request_id:crypto.randomUUID()});
    },
    action: (run: ComponentTestRun, action: string, extra: Record<string, unknown> = {}) => send(`pi/component-tests/${run.id}/action`,
      { action, guide_key: componentTestKey(design, session, run.component_id), ...extra }),
  };
}
