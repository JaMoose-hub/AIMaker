import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { applyDesign, designRequest, initialMaker, makerRequest, validDesign, type MakerState, type MakerStage, type ProjectDesign } from "./maker";
import { useI18n } from "./i18n";
import { MAKER_STORAGE } from "./makerMigration";
import { prepareProjectWiringEdit } from "./wiringEdit";
import type { DebugConversation } from "./debugSessions";
import type { DebugSession } from "./debugSessions";
import { componentTestKey } from "./componentTests";
import { currentWire } from "./maker";

export interface AssistantMessage {
  id: string; role: "user" | "assistant"; text: string; source: string; created_at: number | null;
  stage: MakerStage; capability: string; epoch: number; round: number; archived?: boolean;
  session_id?: string; evidence_ids?: string[];
  attachments?: { asset_id: string; id?: string; image_url: string; url?: string; thumbnail_url?: string; capture_id?: string;
    filename?: string; width?: number; height?: number; source?: string; type?: "image" | "video"; duration?: number; size?: number }[];
  capture_id?: string;
}
export interface AssistantJob {
  id: string; status: "running" | "completed" | "failed" | "unknown"; request_id: string;
  stage: MakerStage; capability: string; phase?: string; result?: ProjectDesign | null; error?: string;
  version?: { project_id?: string; revision?: number }; checklist_revision?: number;
}
export interface DesignChecklist {
  requirements: string[]; component_ids: MakerState["selected"];
  structure: NonNullable<ProjectDesign["assembly"]>["parts"];
  concept_only: NonNullable<ProjectDesign["concept_only_parts"]>;
}
export interface AssistantActiveMedia {
  asset_ids: string[]; capture_id?: string | null; attachments: NonNullable<AssistantMessage["attachments"]>; epoch: number; round: number;
}
export interface AssistantConversation {
  id: string; kind: "project" | "demo"; project_id: string | null; locale: string;
  messages: AssistantMessage[]; jobs: AssistantJob[]; before: number | null; total: number; context_epoch: number; round: number;
  active_media?: AssistantActiveMedia | null;
  demo: null | { state: "discussing" | "checklist_pending" | "generating" | "result_pending";
    revision: number; confirmed_revision: number | null; checklist: DesignChecklist;
    result: ProjectDesign | null; result_source: "builtin" | "ai" | null; job_id: string | null };
}
export function currentAssistantMedia(record: AssistantConversation | null, round: number): AssistantActiveMedia | null {
  const media = record?.active_media;
  return record?.kind === "project" && media?.asset_ids.length && media.epoch === record.context_epoch && media.round === round ? media : null;
}
const KEY = "boardvision.assistant.v1";
const DEMO_KEY = "boardvision.assistant-demo.v1";
export const newConversationId = () => crypto.randomUUID();
function savedId(key: string) {
  try { return localStorage.getItem(key) || newConversationId(); } catch { return newConversationId(); }
}
function rememberedJobs() {
  try { return new Set<string>(JSON.parse(localStorage.getItem(`${KEY}.delivered`) || "[]")); }
  catch { return new Set<string>(); }
}
export function mergeConversation(previous: AssistantConversation | null, next: AssistantConversation): AssistantConversation {
  if (!previous || previous.id !== next.id || (next.before !== null && next.before > previous.total)) return next;
  const messages = [...new Map([...previous.messages, ...next.messages].map(message => [message.id, message])).values()]
    .map(message => message.round < next.round && (["wiring", "debug"].includes(message.capability) ||
      (["guide", "deploy"].includes(message.stage) && !["design", "planning"].includes(message.capability))) ? { ...message, archived: true } : message);
  return { ...next, messages, before: previous.before === null ? null : Math.min(previous.before, next.before ?? 0) || null };
}
export function clearAcceptedDraft(current: string, sent: string) { return current.trim() === sent.trim() ? "" : current; }
export function resultBelongsToState(job: AssistantJob, state: MakerState) {
  const base = state.candidate ?? state.design;
  return (job.version?.project_id ?? null) === (base?.id ?? null) &&
    (job.version?.revision ?? null) === (base?.revision ?? null);
}
/** One payload builder for desktop messages and the paired phone's workspace. */
export function assistantWorkspacePayload(snapshot: MakerState, locale: string, selectedModel?: string,
  debugSession?: DebugSession | null, target: "auto" | "design" | "wiring" | "debug" = "auto", prompt = snapshot.prompt) {
  const wire = snapshot.design ? currentWire(snapshot.design, snapshot.guide) : undefined;
  return { stage: snapshot.stage, target,
    design: designRequest({ ...snapshot, prompt, aiIntent: "auto" }, locale, selectedModel || snapshot.aiModel || null),
    round: snapshot.guide.run ?? 0, context: { guide: snapshot.guide, deployment: snapshot.debug?.deployment,
      workspace_project_id: snapshot.design?.id ?? null,
      debug_session_id: debugSession && !["complete", "stopped", "error"].includes(debugSession.status) ? debugSession.id : null,
      debug_context: { guide_run: snapshot.guide.run ?? 0, guide_confirmations: snapshot.guide.confirmed,
        code: snapshot.code,
        test_keys: Object.fromEntries(snapshot.design?.component_ids.map(cid => [cid, componentTestKey(snapshot.design!, snapshot.guide, cid)]) ?? []),
        entry: snapshot.debug ?? {}, wiring_target: wire ? { component_id: wire.componentId, wire_id: wire.id } : null },
      preview_version: snapshot.candidate?.revision, project_version: snapshot.design?.revision } };
}
/** Desktop debug-session lifecycle does not change the phone's project snapshot. */
export function assistantMobileWorkspacePayload(...args: Parameters<typeof assistantWorkspacePayload>) {
  const workspace = assistantWorkspacePayload(...args);
  const { debug_session_id: _debugSessionId, ...context } = workspace.context;
  return { ...workspace, context };
}
/** A single App-owned controller; hiding a pane never cancels a submitted job. */
export function useAssistant(state: MakerState, setState: Dispatch<SetStateAction<MakerState>>, debugConversation: DebugConversation | null, debugSession?: DebugSession | null, selectedModel?: string) {
  const { locale } = useI18n();
  const [projectId, setProjectId] = useState(() => savedId(KEY));
  const [demoId] = useState(() => savedId(DEMO_KEY));
  const [demoOpen, setDemoOpen] = useState(() => { try { return localStorage.getItem(`${DEMO_KEY}.open`) === "true"; } catch { return false; } });
  const [project, setProject] = useState<AssistantConversation | null>(null);
  const [demo, setDemo] = useState<AssistantConversation | null>(null);
  const [demoDraft, setDemoDraft] = useState(() => { try { return localStorage.getItem(`${DEMO_KEY}.draft`) || ""; } catch { return ""; } });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const latest = useRef(state); latest.current = state;
  const activeId = useRef(projectId); activeId.current = projectId;
  const flight = useRef(false);
  const delivered = useRef(rememberedJobs());
  const retry = useRef<{ key: string; id: string; reference?: AssistantActiveMedia | null } | null>((() => {
    try { return JSON.parse(localStorage.getItem(`${KEY}.outbox`) || "null"); } catch { return null; }
  })());
  const importKey = useRef("");
  const debugImportKey = useRef("");
  const record = demoOpen ? demo : project;
  const id = demoOpen ? demoId : projectId;
  const busy = pending || Boolean(record?.jobs.some(job => job.status === "running"));
  const draft = demoOpen ? demoDraft : state.prompt;
  const setDraft = (text: string) => demoOpen ? setDemoDraft(text) : setState(previous => ({ ...previous, prompt: text }));

  useEffect(() => {
    try {
      localStorage.setItem(KEY, projectId); localStorage.setItem(DEMO_KEY, demoId);
      localStorage.setItem(`${DEMO_KEY}.open`, String(demoOpen)); localStorage.setItem(`${DEMO_KEY}.draft`, demoDraft);
      setStorageError(false);
    } catch { setStorageError(true); }
  }, [projectId, demoId, demoOpen, demoDraft]);

  const accept = useCallback((next: AssistantConversation) => {
    if (next.kind === "demo") { setDemo(previous => mergeConversation(previous, next)); return; }
    if (next.id !== activeId.current) return;
    setProject(previous => mergeConversation(previous, next));
    for (const job of next.jobs) {
      if (job.status !== "completed" || !validDesign(job.result) || delivered.current.has(job.id)) continue;
      delivered.current.add(job.id);
      try { localStorage.setItem(`${KEY}.delivered`, JSON.stringify([...delivered.current])); } catch { setStorageError(true); }
      // Late results remain in history, never overwrite a new version or project.
      setState(previous => activeId.current === next.id && resultBelongsToState(job, previous)
        ? { ...previous, candidate: job.result! } : previous);
    }
  }, [setState]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await makerRequest<AssistantConversation>(`assistant/conversations/${projectId}`);
        if (!stopped) { accept(value); setConnectionError(""); }
      } catch (cause) { if (!stopped) setConnectionError(String(cause)); }
      if (!stopped) timer = setTimeout(() => void poll(), 1500);
    }
    function connect() { void makerRequest<AssistantConversation>("assistant/conversations", { id: projectId, kind: "project", locale,
      project_id: latest.current.design?.id ?? null }).then(async value => {
      if (stopped) return;
      accept(value); setConnectionError("");
      if (!stopped) void poll();
    }).catch(cause => { if (!stopped) { setConnectionError(String(cause)); timer = setTimeout(connect, 5000); } }); }
    connect();
    return () => { stopped = true; clearTimeout(timer); };
  }, [projectId, accept]);

  useEffect(() => {
    if (project?.id !== projectId || !state.conversation.length) return;
    const key = JSON.stringify([projectId, state.conversation]);
    if (key === importKey.current) return;
    importKey.current = key;
    void makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/import`, {
      source_id: `maker:${projectId}`, messages: state.conversation, kind: "legacy-design",
    }).then(accept).catch(cause => { importKey.current = ""; setError(String(cause)); });
  }, [project, projectId, state.conversation, accept]);

  // Continue following demo jobs even after returning to the real project.
  useEffect(() => {
    if (!demoOpen && !demo) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await makerRequest<AssistantConversation>("assistant/conversations", { id: demoId, kind: "demo", locale });
        if (!stopped) accept(value);
      } catch (cause) { if (!stopped) setError(String(cause)); }
      if (!stopped) timer = setTimeout(() => void poll(), 1500);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [demoOpen, demoId, Boolean(demo), accept]);

  useEffect(() => {
    if (!project || !debugConversation || debugConversation.project_id !== state.design?.id) return;
    const key = JSON.stringify([projectId, debugConversation.id, debugConversation.messages]);
    if (debugImportKey.current === key) return;
    debugImportKey.current = key;
    void makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/import`, {
      source_id: `debug:${debugConversation.id}`, kind: "legacy-debug",
      messages: debugConversation.messages.map(message => ({ ...message, round: state.guide.run ?? 0 })),
    }).then(accept).catch(cause => { debugImportKey.current = ""; setError(String(cause)); });
  }, [project, projectId, debugConversation, state.design?.id, state.guide.run, accept]);

  async function perform(operation: () => Promise<AssistantConversation>) {
    if (flight.current) return false;
    flight.current = true; setPending(true); setError("");
    try { accept(await operation()); return true; }
    catch (cause) { setError(String(cause)); return false; }
    finally { flight.current = false; setPending(false); }
  }
  function requestId(key: string, reference?: AssistantActiveMedia | null) {
    if (retry.current?.key !== key || record?.jobs.some(job => job.request_id === retry.current?.id && job.status === "failed")) {
      retry.current = { key, id: newConversationId(), ...(reference === undefined ? {} : { reference: reference
        ? { ...reference, asset_ids: [...reference.asset_ids], attachments: reference.attachments.map(asset => ({ ...asset })) } : null }) };
    }
    try { localStorage.setItem(`${KEY}.outbox`, JSON.stringify(retry.current)); } catch { setStorageError(true); }
    return retry.current.id;
  }
  async function send(target: "auto" | "design" | "wiring" | "debug" = "auto") {
    const text = draft.trim();
    if (!text || busy || state.aiJobId) return false;
    const snapshot = latest.current;
    const workspace = assistantWorkspacePayload(snapshot, locale, selectedModel, debugSession, target, text);
    const key = JSON.stringify([id, text, workspace, record?.context_epoch]);
    const request_id = requestId(key, currentAssistantMedia(record, workspace.round));
    const reference = retry.current?.reference;
    // Old outboxes omit this field so their original server fingerprint remains valid.
    const mediaPayload = reference === undefined ? {} : { inherit_media: false,
      ...(reference ? { asset_ids: [...reference.asset_ids], capture_id: reference.capture_id ?? null } : {}) };
    const payload = { request_id, text, ...workspace, ...mediaPayload };
    const wasDemo = demoOpen;
    const accepted = await perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${id}/messages`, payload));
    if (accepted) {
      retry.current = null;
      try { localStorage.removeItem(`${KEY}.outbox`); } catch { setStorageError(true); }
      if (wasDemo) setDemoDraft(current => clearAcceptedDraft(current, text));
      else setState(current => activeId.current === id ? { ...current, prompt: clearAcceptedDraft(current.prompt, text) } : current);
    }
    return accepted;
  }
  async function confirmDemo(mode: "builtin" | "ai") {
    if (!demo?.demo || busy) return false;
    const revision = demo.demo.revision;
    const key = JSON.stringify([demoId, revision, mode]);
    return perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${demoId}/confirm`, {
      revision, mode, request_id: requestId(key), generation: mode === "ai"
        ? designRequest({ ...latest.current, prompt: "Confirmed demo checklist" }, locale, selectedModel || latest.current.aiModel || null) : null,
    }));
  }
  async function prepareConversation(project_id?: string) {
    const next = newConversationId();
    return makerRequest<AssistantConversation>("assistant/conversations", { id: next, kind: "project", locale, project_id });
  }
  function activateConversation(value: AssistantConversation) {
    activeId.current = value.id; importKey.current = ""; debugImportKey.current = "";
    setProjectId(value.id); setProject(value);
  }
  async function startConversation() {
    const next = await prepareConversation();
    activateConversation(next);
    return next.id;
  }
  async function adoptDemo() {
    const result = demo?.demo?.result;
    if (!result || !validDesign(result) || demo?.demo?.confirmed_revision !== demo?.demo?.revision || busy || flight.current || project?.jobs.some(j => j.status === "running") || latest.current.aiJobId) return false;
    const snapshot = latest.current;
    const expectedDemo = JSON.stringify(demo?.demo);
    flight.current = true; setPending(true); setError("");
    try {
      if (!await prepareProjectWiringEdit(snapshot.design?.id ?? "unassigned-project")) return false;
      if (latest.current !== snapshot || expectedDemo !== JSON.stringify(demo?.demo)) throw new Error("Project changed; review again");
      if ((result.image_required || result.source === "ai") && !result.image) throw new Error("The generated image is not ready");
      localStorage.setItem(`${MAKER_STORAGE}.before-demo-adoption`, JSON.stringify(snapshot));
      const adopted = applyDesign({ ...initialMaker(), aiModel: snapshot.aiModel, aiEffort: snapshot.aiEffort,
        aiExpectedOutputTokens: snapshot.aiExpectedOutputTokens }, { ...result, id: newConversationId() }, "design");
      adopted.designView = "blueprint";
      const nextConversation = await prepareConversation(adopted.design!.id);
      if (latest.current !== snapshot) throw new Error("Project changed; review again");
      localStorage.setItem(KEY, nextConversation.id);
      try { localStorage.setItem(MAKER_STORAGE, JSON.stringify(adopted)); }
      catch (cause) { localStorage.setItem(KEY, projectId); throw cause; }
      activateConversation(nextConversation);
      setState(adopted); setDemoOpen(false);
      return true;
    } catch (cause) { setError(String(cause)); return false; }
    finally { flight.current = false; setPending(false); }
  }
  async function archiveWiring(round: number) {
    return perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/reset`, { mode: "wiring", round }));
  }
  const mobileWorkspace = assistantMobileWorkspacePayload(state, locale, selectedModel, debugSession, "auto", state.design?.prompt || "Current Tinkro workspace");
  const draftKey = JSON.stringify([id, draft.trim(), assistantWorkspacePayload(state, locale, selectedModel, debugSession, "auto", draft.trim()), record?.context_epoch]);
  const pendingReference = retry.current?.key === draftKey && !record?.jobs.some(job => job.request_id === retry.current?.id && job.status === "failed")
    ? retry.current?.reference : undefined;
  const mediaReference = pendingReference === undefined ? currentAssistantMedia(record, mobileWorkspace.round)
    : pendingReference && record ? currentAssistantMedia({ ...record, active_media: pendingReference }, mobileWorkspace.round) : null;
  return { record, project, demo, demoOpen, setDemoOpen, busy, pending, draft, setDraft, error: error || connectionError, storageError,
    send, confirmDemo, adoptDemo, startConversation, prepareConversation, activateConversation, archiveWiring, mediaReference,
    reportError: (cause: unknown) => setError(String(cause)), acceptExternal: accept,
    mobileContext: { conversation_id: projectId, title: state.design?.title ?? "Tinkro",
      ...mobileWorkspace, context: { ...mobileWorkspace.context, assistant_context_epoch: project?.context_epoch ?? 0 } },
    restoreChecklist: () => perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${demoId}/restore-checklist`, {})),
    clear: () => perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${id}/reset`, { mode: "clear" })),
    older: async () => {
      if (record?.before === null || record?.before === undefined) return;
      try {
        const previous = await makerRequest<AssistantConversation>(`assistant/conversations/${id}?before=${record.before}`);
        const merge = (value: AssistantConversation | null) => value?.id === id ? { ...value, before: previous.before,
          messages: [...new Map([...previous.messages, ...value.messages].map(m => [m.id, m])).values()] } : value;
        (demoOpen ? setDemo : setProject)(merge);
      } catch (cause) { setError(String(cause)); }
    },
    retryImage: (job: AssistantJob) => perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${id}/jobs/${job.id}/retry-image`,
      { request_id: requestId(`image:${id}:${job.id}`) })),
  };
}
export type AssistantController = ReturnType<typeof useAssistant>;
