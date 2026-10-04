import { useEffect, useRef, useState } from "react";
import { makerRequest } from "./maker";
import type { DebugContext, DebugIssue } from "./debug";
import type { ProjectDesign } from "./maker";
import type { FrozenCircuitProfile } from "./circuitLayout";
import type { WiringReviewAction, WiringReviewState } from "./wiringReview";
import type { WiringChatFlow } from "./wiringChat";

export type DebugSessionStatus = "diagnosing" | "awaiting_capture" | "awaiting_ready" | "testing" |
  "awaiting_visual" | "awaiting_repair" | "awaiting_trial_visual" | "complete" | "paused" | "stopped" | "error";
export type CaptureTarget = "overview" | "hc_target" | "tft_screen" | "pi_header" | "module_header";
export interface CaptureTask { id?: string; target: CaptureTarget; instruction: string; attempts?: number; attempt?: number;
  wiring_target?: DebugContext["wiring_target"] }
export interface VisualObservation {
  id: string; capture_ids: string[]; target: CaptureTarget | "conversation"; seen: string;
  visibility: "clear" | "uncertain" | "blocked"; suggested_action: string; created_at: number;
  explanation?: string; next_step?: string; source?: "codex_cloud"; model?: string | null;
  observation_kind?: "visual" | "conversation";
  wire_ids?: string[]; initial_focus_wire_id?: string | null;
}
export interface DebugEvidence {
  id: string; url: string; target: CaptureTarget; frame_id: number; source: string; available?: boolean;
  captured_at: string | number; test_id?: string | null; phase?: string | null;
  quality?: { warnings?: string[]; [key: string]: unknown } | null;
  stability?: { stable?: boolean; [key: string]: unknown } | null;
  session_id?: string; check_id?: string;
  views?: { name: string; url?: string; available?: boolean; frame_id?: number; ts_ms?: number; size?: number[]; source_view?: string; crop?: number[]; adds_no_detail?: boolean;
    mime_type?: string; sha256?: string; rotation_ccw_quarter_turns?: number }[];
  same_frame?: boolean; capture_skew_ms?: number; mode?: string;
  camera_id?: string; runtime_revision?: number; sha256?: string;
  selection?: { elapsed_ms?: number; candidate_count?: number; method?: string; requested_ts_ms?: number };
  wiring_target?: DebugContext["wiring_target"];
}
export interface CaptureFeedback { quality?: DebugEvidence["quality"]; stability?: DebugEvidence["stability"] }
export type DebugResponseMode = "fast" | "thorough";
export interface DebugMessage {
  id: string; role: "user" | "assistant"; text: string; created_at: number;
  capture_ids?: string[]; model?: string | null; effort?: string | null; elapsed_ms?: number;
  session_id?: string; check_id?: string;
  wiring_flow?: WiringChatFlow;
  diagram_refs?: { snapshot_id: string; wire_ids: string[]; caption?: string; initial_focus_wire_id?: string }[];
}
export interface DiagramSnapshot {
  id: string; schema_version: "debug-diagram-v1"; created_at: number; project_id: string; project_revision: number;
  target?: DebugContext["wiring_target"]; design: ProjectDesign;
  render_snapshot: FrozenCircuitProfile & { catalog_version?: string; profile_versions?: ProjectDesign["profile_versions"] };
}
export interface DebugConversation {
  id: string; project_id: string; messages: DebugMessage[]; check_ids: string[];
  archived?: boolean;
  evidence?: DebugEvidence[]; diagrams?: DiagramSnapshot[]; updated_at?: number;
}
export type DebugPurpose = "debug" | "wiring_review";
export interface DebugSession {
  id: string; status: DebugSessionStatus; phase: string; symptom: string; instruction: string;
  model?: string | null; hardware_ready?: boolean; hardware_blocker?: string | null;
  capture_task: CaptureTask | null; observations: VisualObservation[]; evidence: DebugEvidence[];
  framing_feedback?: CaptureFeedback | null;
  test_results?: { id: string; component_id: string; outcome: string; phase?: string; reason?: string | null; guide_key?: string; invalidated?: boolean }[];
  trial_result?: { id: string; outcome: string; phase?: string; reason?: string | null } | null;
  camera_verdict?: "read_current_frame" | "display_abnormal" | "inconclusive" | null;
  jobs: { id: string; kind: string; state: string; run_id?: string; component_id?: string; error?: string; owner?: string }[];
  diagnosis?: { case_id?: string; issues?: DebugIssue[]; hardware_blocker?: string | null } | null;
  report?: { confirmed: string[]; uncertain: string[]; next_step: string } | null;
  budget?: { model_calls: number; max_model_calls: number; tests: Record<string, number>; max_tests_per_component: number; captures: number; max_captures: number };
  binding?: { target_id?: string; project_id?: string | null; code_hash?: string; wiring_hash?: string; test_keys?: Record<string, string> };
  current_target?: boolean; camera_current?: boolean; camera?: { source: string; runtime_revision: number; camera_id?: string | null };
  model_busy?: boolean;
  messages?: DebugMessage[]; response_mode?: DebugResponseMode;
  conversation_id?: string; purpose?: DebugPurpose; diagrams?: DiagramSnapshot[];
  conversation_current?: boolean;
  wiring_target?: DebugContext["wiring_target"];
  wiring_edit_ready?: boolean;
  wiring_review?: WiringReviewState | null;
  model_started_at?: number | null; model_elapsed_ms?: number | null; model_capture_ids?: string[];
  error?: string | null; updated_at: number;
}
export type DebugSessionAction = "ready" | "capture" | "continue" | "message" | "stop" | "start_trial" | "analyse" | "context_changed" | "start_debug" | "prepare_wiring" | "wiring_review";

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
  const [conversation, setConversation] = useState<DebugConversation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [resetVersion, setResetVersion] = useState(0);
  const flight = useRef(false);
  const staleFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const restartReceipt = useRef<{ projectId: string; requestId: string; conversationId?: string } | null>(null);

  useEffect(() => {
    epoch.current++;
    setSessionId(readStoredSession(projectId));
    setRecord(null);
    setConversation(null);
    setError("");
    restartReceipt.current = null;
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
        let savedId: string | null = null;
        if (sessionId) {
          try { next = await makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(sessionId)}`, undefined, controller.signal); }
          catch (cause) {
            if ((cause as {status?: number}).status !== 404 && !(cause instanceof Error && cause.message === "session_not_found")) throw cause;
            next = null;
          }
          if (!canAdopt()) return;
          // Older clients could save another project's global live check here.
          // Detach that pointer without deleting the check or its conversation.
          if (next?.binding?.project_id !== projectId || next?.conversation_current === false) next = null;
          if (next && next.current_target !== false) savedId = next.id;
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
        if (!canAdopt()) return;
        const history = await makerRequest<{ conversation: DebugConversation | null }>(`debug/conversations?project_id=${encodeURIComponent(projectId!)}`, undefined, controller.signal);
        if (canAdopt()) {
          const ownHistory = history.conversation?.project_id === projectId && !history.conversation.archived ? history.conversation : null;
          // A different tab may have restarted this project's wiring round.
          // Never merge its old saved check back into the new conversation.
          if (next?.binding?.project_id === projectId && (next.conversation_current === false ||
            (ownHistory && next.conversation_id && next.conversation_id !== ownHistory.id))) { next = null; savedId = null; }
          // Global live work stays visible for an explicit stop, but it is not
          // this project's history. Retain an existing own saved check instead.
          if (next?.binding?.project_id === projectId && next.current_target !== false) savedId = next.id;
          else if (next && (isTerminal(next.status) || next.current_target === false)) next = null;
          // A late poll cannot replace a newly created session or its pointer.
          if (savedId && savedId !== sessionId) { saveSession(projectId, savedId); setSessionId(savedId); }
          else if (!savedId && sessionId) { forgetSession(projectId); setSessionId(null); }
          setRecord(next);
          setConversation(ownHistory);
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

  async function create(context: DebugContext, symptom: string, model: string, effort: string, responseMode: DebugResponseMode = "fast", options: { purpose?: DebugPurpose; initial_action?: "message" | "capture" | "collect" } = {}) {
    if (flight.current || !projectId || context.project?.id !== projectId) return undefined;
    const conversationId = conversation?.project_id === projectId ? conversation.id :
      record?.binding?.project_id === projectId ? record.conversation_id : undefined;
    flight.current = true; const version = ++epoch.current; setPending(true); setError("");
    try {
      const next = await makerRequest<DebugSession>("debug/sessions", {
        context, symptom, model: model || null, effort, response_mode: responseMode, request_id: crypto.randomUUID(),
        purpose: options.purpose ?? "debug", ...(conversationId ? { conversation_id: conversationId } : {}),
        ...(options.initial_action ? { initial_action: options.initial_action } : {}),
      });
      if (!mounted.current || version !== epoch.current) return undefined;
      setRecord(next); setSessionId(next.id); saveSession(projectId, next.id);
      return next;
    } catch (cause) {
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { flight.current = false; if (mounted.current) setPending(false); }
  }
  function adoptReview(next: DebugSession) {
    if (!mounted.current || !enabled || !projectId || flight.current || next.binding?.project_id !== projectId
      || next.conversation_current === false || next.current_target === false || !next.wiring_review
      || ["stopped", "complete", "error"].includes(next.status) || next.phase === "backend_restarted") return false;
    epoch.current++;
    setRecord(next); setSessionId(next.id); saveSession(projectId, next.id); setError("");
    return true;
  }

  async function restartConversation() {
    if (flight.current || staleFlight.current || !projectId) throw new Error("ai_reset_pending");
    const receipt = restartReceipt.current?.projectId === projectId ? restartReceipt.current : {
      projectId, requestId: crypto.randomUUID(),
      conversationId: conversation?.project_id === projectId ? conversation.id : undefined,
    };
    restartReceipt.current = receipt;
    flight.current = true; const version = ++epoch.current; setPending(true); setError("");
    try {
      const result = await makerRequest<{ conversation: DebugConversation }>("debug/conversations/restart", {
        project_id: projectId, request_id: receipt.requestId,
        ...(receipt.conversationId ? { expected_conversation_id: receipt.conversationId } : {}),
      });
      const fresh = result.conversation;
      if (!fresh?.id || fresh.project_id !== projectId || fresh.archived || !Array.isArray(fresh.messages) ||
        !Array.isArray(fresh.check_ids) || fresh.messages.length || fresh.check_ids.length)
        throw new Error("ai_reset_unconfirmed");
      if (!mounted.current || version !== epoch.current) return false;
      forgetSession(projectId); setSessionId(null); setRecord(null); setConversation(fresh);
      setResetVersion(value => value + 1); restartReceipt.current = null;
      return true;
    } catch (cause) {
      const status = (cause as { status?: number }).status;
      if (version === epoch.current && status === 409) restartReceipt.current = null;
      if (status === 404 || status === 405 || status === 422) throw new Error("wiring_backend_restart_required");
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
      throw cause;
    } finally { flight.current = false; if (mounted.current) setPending(false); }
  }

  async function action(actionName: DebugSessionAction, context?: DebugContext, text?: string, responseMode?: DebugResponseMode,
    wiringReview?: WiringReviewAction, createdSessionId?: string) {
    // A collect-only session can be created and populated within one user action,
    // before React has rendered its returned record.
    const targetId = createdSessionId ?? record?.id;
    if (flight.current || !targetId || (context && context.project?.id !== projectId)) return undefined;
    flight.current = true; const version = ++epoch.current; setPending(true); setError("");
    try {
      const next = await makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(targetId)}/actions`, {
        action: actionName, ...(context ? { context } : {}), request_id: crypto.randomUUID(), ...(text ? { text } : {}), ...(responseMode ? { response_mode: responseMode } : {}),
        ...(wiringReview ? { wiring_review: wiringReview } : {}),
      });
      if (!mounted.current || version !== epoch.current) return undefined;
      setRecord(next);
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
      if (mounted.current && version === epoch.current) { setRecord(next); return next; }
    } catch (cause) {
      if (mounted.current && version === epoch.current) setError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { staleFlight.current = false; }
  }

  return { record, conversation, pending, error, resetVersion, restartConversation, create, adoptReview, action, contextChanged };
}
