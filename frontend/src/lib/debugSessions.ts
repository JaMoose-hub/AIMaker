import { useEffect, useRef, useState } from "react";
import { makerRequest } from "./maker";
import type { DebugContext, DebugIssue } from "./debug";

export type DebugSessionStatus = "diagnosing" | "awaiting_capture" | "awaiting_ready" | "testing" |
  "awaiting_visual" | "awaiting_repair" | "awaiting_trial_visual" | "complete" | "paused" | "stopped" | "error";
export type CaptureTarget = "overview" | "hc_target" | "tft_screen" | "pi_header" | "module_header";
export interface CaptureTask { target: CaptureTarget; instruction: string; attempts: number }
export interface VisualObservation {
  id: string; capture_ids: string[]; target: CaptureTarget; seen: string;
  visibility: "clear" | "uncertain" | "blocked"; suggested_action: string; created_at: number;
  explanation?: string; next_step?: string; source?: "codex_cloud"; model?: string | null;
  observation_kind?: "visual" | "conversation";
}
export interface DebugEvidence {
  id: string; url: string; target: CaptureTarget; frame_id: number; source: string; available?: boolean;
  captured_at: string | number; test_id?: string | null; phase?: string | null;
  quality?: { warnings?: string[]; [key: string]: unknown } | null;
  stability?: { stable?: boolean; [key: string]: unknown } | null;
}
export interface CaptureFeedback { quality?: DebugEvidence["quality"]; stability?: DebugEvidence["stability"] }
export type DebugResponseMode = "fast" | "thorough";
export interface DebugMessage {
  id: string; role: "user" | "assistant"; text: string; created_at: number;
  capture_ids?: string[]; model?: string | null; effort?: string | null; elapsed_ms?: number;
}
export interface DebugSession {
  id: string; status: DebugSessionStatus; phase: string; symptom: string; instruction: string;
  model?: string | null; hardware_ready?: boolean; hardware_blocker?: string | null;
  capture_task: CaptureTask | null; observations: VisualObservation[]; evidence: DebugEvidence[];
  framing_feedback?: CaptureFeedback | null;
  test_results?: { id: string; component_id: string; outcome: string; phase?: string; reason?: string | null; guide_key?: string; invalidated?: boolean }[];
  trial_result?: { id: string; outcome: string; phase?: string; reason?: string | null } | null;
  camera_verdict?: "read_current_frame" | "display_abnormal" | "inconclusive" | null;
  jobs: { id: string; kind: string; state: string; run_id?: string; component_id?: string; error?: string; owner?: string }[];
  diagnosis?: { case_id?: string; issues?: DebugIssue[] } | null;
  report?: { confirmed: string[]; uncertain: string[]; next_step: string } | null;
  budget?: { model_calls: number; max_model_calls: number; tests: Record<string, number>; max_tests_per_component: number; captures: number; max_captures: number };
  binding?: { target_id?: string; project_id?: string | null; code_hash?: string; wiring_hash?: string; test_keys?: Record<string, string> };
  current_target?: boolean; camera_current?: boolean; camera?: { source: string; runtime_revision: number; camera_id?: string | null };
  model_busy?: boolean;
  messages?: DebugMessage[]; response_mode?: DebugResponseMode;
  model_started_at?: number | null; model_elapsed_ms?: number | null; model_capture_ids?: string[];
  error?: string | null; updated_at: number;
}
export type DebugSessionAction = "ready" | "capture" | "continue" | "message" | "stop" | "start_trial" | "analyse" | "context_changed";

/** A wire binding is a keyed map; JSON property order does not change it. */
export function sameDebugTestKeys(left: Record<string, string> = {}, right: Record<string, string> = {}) {
  return Object.keys(left).length === Object.keys(right).length &&
    Object.entries(left).every(([id, key]) => right[id] === key);
}

const STORAGE_KEY = "boardvision.ai-debug-session.v1";
const POLL_MS = 1500;
const storageKey = (projectId: string) => `${STORAGE_KEY}:${encodeURIComponent(projectId)}`;
const isTerminal = (status: DebugSessionStatus) => status === "complete" || status === "stopped" || status === "error";

function readStoredSession(projectId: string | null): string | null {
  if (!projectId || typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(storageKey(projectId));
    return stored && stored.length < 200 ? stored : null;
  } catch { return null; }
}

function saveSession(projectId: string | null, id: string) {
  if (!projectId || typeof window === "undefined") return;
  try { window.localStorage.setItem(storageKey(projectId), id); }
  catch { /* A session still works while this page stays open. */ }
}
function forgetSession(projectId: string | null) {
  if (!projectId || typeof window === "undefined") return;
  try { window.localStorage.removeItem(storageKey(projectId)); } catch { /* In-memory state still clears. */ }
}

export function useDebugSession(projectId: string | null, enabled: boolean) {
  const [sessionId, setSessionId] = useState<string | null>(() => readStoredSession(projectId));
  const [record, setRecord] = useState<DebugSession | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const flight = useRef(false);
  const staleFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    epoch.current++;
    setSessionId(readStoredSession(projectId));
    setRecord(null);
    setError("");
  }, [projectId]);

  useEffect(() => {
    const update = (event: StorageEvent) => {
      if (projectId && event.key === storageKey(projectId)) setSessionId(readStoredSession(projectId));
    };
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, [projectId]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled || !projectId) return;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      const version = epoch.current;
      const canAdopt = () => !controller.signal.aborted && mounted.current && version === epoch.current && !flight.current;
      try {
        let next: DebugSession | null;
        if (sessionId) {
          try { next = await makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(sessionId)}`, undefined, controller.signal); }
          catch (cause) {
            if ((cause as {status?: number}).status !== 404 && !(cause instanceof Error && cause.message === "session_not_found")) throw cause;
            next = null;
          }
          if (!canAdopt()) return;
          // A saved finished session remains readable, but another tab may
          // already have started a new one on this Pi. Always surface that
          // active session, including one for another project.
          if (!next || next.current_target === false || isTerminal(next.status)) {
            const active = (await makerRequest<{active: DebugSession | null}>("debug/sessions", undefined, controller.signal)).active;
            if (active) {
              next = active;
            } else if (next?.current_target === false) {
              next = null;
            }
          }
        } else {
          next = (await makerRequest<{active: DebugSession | null}>("debug/sessions", undefined, controller.signal)).active;
        }
        if (canAdopt()) {
          // Adopt record, selected id and storage together. A late poll from
          // the stopped session must not overwrite a newly created session.
          if (next && next.id !== sessionId) { saveSession(projectId, next.id); setSessionId(next.id); }
          else if (!next && sessionId) { forgetSession(projectId); setSessionId(null); }
          setRecord(next);
          setError("");
        }
      } catch (cause) {
        if (canAdopt())
          setError(cause instanceof Error ? cause.message : "connection_lost");
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(poll, POLL_MS);
      }
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); mounted.current = false; };
  }, [enabled, projectId, sessionId]);

  async function create(context: DebugContext, symptom: string, model: string, effort: string, responseMode: DebugResponseMode = "fast") {
    if (flight.current || !projectId) return undefined;
    flight.current = true; const version = ++epoch.current; setPending(true); setError("");
    try {
      const next = await makerRequest<DebugSession>("debug/sessions", {
        context, symptom, model: model || null, effort, response_mode: responseMode, request_id: crypto.randomUUID(),
      });
      if (mounted.current && version === epoch.current) { setRecord(next); setSessionId(next.id); saveSession(projectId, next.id); }
      return next;
    } catch (cause) {
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { flight.current = false; if (mounted.current) setPending(false); }
  }

  async function action(actionName: DebugSessionAction, context: DebugContext, text?: string, responseMode?: DebugResponseMode) {
    if (flight.current || !record) return undefined;
    flight.current = true; const version = ++epoch.current; setPending(true); setError("");
    try {
      const next = await makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(record.id)}/actions`, {
        action: actionName, context, request_id: crypto.randomUUID(), ...(text ? { text } : {}), ...(responseMode ? { response_mode: responseMode } : {}),
      });
      if (mounted.current && version === epoch.current) setRecord(next);
      return next;
    } catch (cause) {
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { flight.current = false; if (mounted.current) setPending(false); }
  }

  // A local draft, wiring or camera change must interrupt an autonomous worker
  // immediately, even while another UI request is waiting on the model.
  async function contextChanged(context: DebugContext) {
    if (!record || staleFlight.current) return;
    staleFlight.current = true;
    const version = ++epoch.current;
    try {
      const next = await makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(record.id)}/actions`, {
        action: "context_changed", context, request_id: crypto.randomUUID(),
      });
      if (mounted.current && version === epoch.current) setRecord(next);
    } catch (cause) {
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { staleFlight.current = false; }
  }

  return { record, pending, error, create, action, contextChanged };
}
