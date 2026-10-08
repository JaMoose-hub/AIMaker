import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { applyDesign, designRequest, initialMaker, makerRequest, validDesign, type MakerState, type MakerStage, type ProjectDesign } from "./maker";
import { useI18n } from "./i18n";
import { MAKER_STORAGE } from "./makerMigration";
import { prepareProjectWiringEdit } from "./wiringEdit";
import type { DebugConversation } from "./debugSessions";
import type { DebugSession } from "./debugSessions";
import type { DebugContext } from "./debug";
import type { WiringReviewAction } from "./wiringReview";
import type { WiringChatFlow, WiringChatActionOp } from "./wiringChat";
import { wiringReceiptSignature, type WiringActionOutbox, type WiringGuideReceipt } from "./wiringReceipt";
import { assistantWiringAnalysis, type AssistantWiringAnalysis } from './assistantAnalysis';
import { componentTestKey } from "./componentTests";
import { currentWire } from "./maker";
import type { ComponentTestHelpContext, TestHelpInvitation } from "./componentTestHelp";

export interface AssistantTestHelpOffer {
  offer_id: string; message_id: string;
  state: 'pending' | 'started' | 'dismissed' | 'stale'; can_act: boolean; can_dismiss: boolean;
  component_id: string; reusable_review: boolean; review_id?: string;
  project_id: string; project_revision: number; guide_run: number; context_epoch: number; guide_key: string;
  test_id: string | null; reason: string | null; mode: 'wiring' | 'setup';
}
export interface AssistantTestHelpResult {
  offer: AssistantTestHelpOffer; debug_session_id?: string; debug_session?: DebugSession; conversation?: AssistantConversation;
}
export interface AssistantWiringFlowResult {
  conversation: AssistantConversation; debug_session_id: string; debug_session: DebugSession;
  request_id?: string; guide_receipt?: WiringGuideReceipt | null; outbox?: WiringActionOutbox;
}
export interface AssistantWiringStartResult extends AssistantWiringFlowResult {
  request_id: string; resumed: boolean;
}

export interface AssistantMessage {
  id: string; role: "user" | "assistant"; text: string; source: string; created_at: number | null;
  import_key?: string;
  test_help_offer?: AssistantTestHelpOffer;
  wiring_flow?: WiringChatFlow;
  stage: MakerStage; capability: string; epoch: number; round: number; archived?: boolean;
  session_id?: string; evidence_ids?: string[];
  attachments?: { asset_id: string; id?: string; image_url: string; url?: string; thumbnail_url?: string; capture_id?: string;
    filename?: string; width?: number; height?: number; source?: string; type?: "image" | "video"; duration?: number; size?: number }[];
  capture_id?: string;
}
export interface AssistantJob {
  id: string; status: "running" | "completed" | "failed" | "unknown"; request_id: string;
  stage: MakerStage; capability: string; phase?: string; result?: ProjectDesign | null; error?: string;
  epoch?: number;
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
  wiring_analysis?: AssistantWiringAnalysis | null;
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
const REMOVED_MEDIA_KEY = `${KEY}.removed-media.v1`;
function mediaScope(record: AssistantConversation | null, media: AssistantActiveMedia | null): string | null {
  return record && media ? JSON.stringify([record.id, media.epoch, media.round, media.capture_id ?? null, media.asset_ids]) : null;
}
function savedRemovedMedia(): string | null {
  try { return localStorage.getItem(REMOVED_MEDIA_KEY); } catch { return null; }
}
const DEMO_KEY = "boardvision.assistant-demo.v1";
const WIRING_OUTBOX_KEY = `${KEY}.wiring-outbox`;
function savedWiringOutbox(): WiringActionOutbox | null {
  try { const value = JSON.parse(localStorage.getItem(WIRING_OUTBOX_KEY) || 'null');
    return value?.request_id && value?.action && value?.context && typeof value.before_signature === 'string' ? value : null;
  } catch { return null; }
}
export const newConversationId = () => crypto.randomUUID();
async function sha256(text: string) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
/** Match Python fingerprint's ensure_ascii=False and default array separators. */
export function testHelpImportKey(sourceId: string, text: string) {
  return sha256(`[${[sourceId, 'test-help-invitation', 'assistant', text].map(value => JSON.stringify(value)).join(', ')}]`);
}
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
  debugSession?: DebugSession | null, target: "auto" | "answer" | "design" | "wiring" | "debug" = "auto", prompt = snapshot.prompt) {
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
  const [wiringOutbox, setWiringOutbox] = useState<WiringActionOutbox | null>(savedWiringOutbox);
  const [wiringReceiptError, setWiringReceiptError] = useState('');
  const [removedMediaScope, setRemovedMediaScope] = useState(savedRemovedMedia);
  const removedMedia = useRef(removedMediaScope); removedMedia.current = removedMediaScope;
  const wiringOutboxRef = useRef(wiringOutbox); wiringOutboxRef.current = wiringOutbox;
  const recoveryFlight = useRef(false);
  const latest = useRef(state); latest.current = state;
  const activeId = useRef(projectId); activeId.current = projectId;
  const flight = useRef(false);
  const delivered = useRef(rememberedJobs());
  const retry = useRef<{ key: string; id: string; reference?: AssistantActiveMedia | null } | null>((() => {
    try { return JSON.parse(localStorage.getItem(`${KEY}.outbox`) || "null"); } catch { return null; }
  })());
  const importKey = useRef("");
  const debugImportKey = useRef("");
  const wiringStartRetry = useRef<{ key: string; id: string } | null>(null);
  const record = demoOpen ? demo : project;
  const id = demoOpen ? demoId : projectId;
  const wiringAnalysis = assistantWiringAnalysis(record);
  const busy = pending || Boolean(record?.jobs.some(job => job.status === "running")) || Boolean(wiringAnalysis);
  const helpScope = useRef({ projectId, epoch: project?.context_epoch ?? 0, busy, demoOpen, project });
  helpScope.current = { projectId, epoch: project?.context_epoch ?? 0, busy, demoOpen, project };
  const draft = demoOpen ? demoDraft : state.prompt;
  const setDraft = (text: string) => demoOpen ? setDemoDraft(text) : setState(previous => ({ ...previous, prompt: text }));

  useEffect(() => {
    try {
      localStorage.setItem(KEY, projectId); localStorage.setItem(DEMO_KEY, demoId);
      localStorage.setItem(`${DEMO_KEY}.open`, String(demoOpen)); localStorage.setItem(`${DEMO_KEY}.draft`, demoDraft);
      setStorageError(false);
    } catch { setStorageError(true); }
  }, [projectId, demoId, demoOpen, demoDraft]);

  const accept = useCallback((next: AssistantConversation, recoveredHistory = false) => {
    if (next.kind === "demo") { setDemo(previous => mergeConversation(previous, next)); return; }
    if (next.id !== activeId.current) return;
    setProject(previous => {
      if (recoveredHistory && previous?.id === next.id && previous.context_epoch !== next.context_epoch) return previous;
      const base = recoveredHistory && previous?.id === next.id && (next.before ?? 0) < (previous.before ?? 0)
        ? { ...previous, messages: [...new Map([...next.messages, ...previous.messages].map(message => [message.id, message])).values()] }
        : previous;
      return mergeConversation(base, next);
    });
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
    // Guidance is imported by the server through its trusted event link, never by a second client import.
    const messages = debugConversation.messages.filter(message => !message.wiring_flow);
    if (!messages.length) return;
    const key = JSON.stringify([projectId, debugConversation.id, messages]);
    if (debugImportKey.current === key) return;
    debugImportKey.current = key;
    void makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/import`, {
      source_id: `debug:${debugConversation.id}`, kind: "legacy-debug",
      messages: messages.map(message => ({ ...message, round: state.guide.run ?? 0 })),
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
    const request_id = requestId(key, composerMedia(record, workspace.round));
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
  /** Explicit, read-only hardware comparison; never consumes the existing draft. */
  async function sendPartsCheck(snapshot: MakerState, text: string, includePhoto = false) {
    if (!text.trim() || busy || flight.current || demoOpen || latest.current.aiJobId || !project ||
      snapshot.stage !== 'design' || !snapshot.design || snapshot.design !== latest.current.design || activeId.current !== projectId) return false;
    const reference = includePhoto ? composerMedia(project, snapshot.guide.run ?? 0) : null;
    if (includePhoto && (!reference || !reference.attachments.length || reference.attachments.some(asset => asset.type !== 'image'))) return false;
    const base = assistantWorkspacePayload(snapshot, locale, selectedModel, null, 'answer', text);
    const workspace = { ...base, context: { ...base.context, parts_check: { scope: 'demo-three-hardware' } } };
    const key = JSON.stringify([projectId, text, workspace, project.context_epoch, reference]);
    const request_id = requestId(key, reference);
    const accepted = await perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/messages`, {
      request_id, text, ...workspace, inherit_media: false, asset_ids: reference ? [...reference.asset_ids] : [],
      capture_id: reference?.capture_id ?? null,
    }));
    if (accepted) {
      retry.current = null;
      try { localStorage.removeItem(`${KEY}.outbox`); } catch { setStorageError(true); }
    }
    return accepted;
  }
  /** Explicit test-help action uses the project chat and leaves the composer untouched. */
  async function sendTestHelp(snapshot: MakerState, text: string, evidence?: ComponentTestHelpContext) {
    if (!text.trim() || busy || flight.current || demoOpen || latest.current.aiJobId ||
      !snapshot.design || snapshot.design !== latest.current.design || snapshot.code !== latest.current.code ||
      (snapshot.guide.run ?? 0) !== (latest.current.guide.run ?? 0)) return false;
    if (evidence && (evidence.project_id !== snapshot.design.id || evidence.project_revision !== snapshot.design.revision ||
      evidence.component_id !== snapshot.debug?.componentId || evidence.test_id !== (snapshot.debug?.runId ?? null))) return false;
    // Keep this request independent of another debug session and older photos.
    const base = assistantWorkspacePayload(snapshot, locale, selectedModel, null, "debug", text);
    const workspace = { ...base, context: { ...base.context,
      ...(evidence ? { component_test_help: structuredClone(evidence) } : {}) } };
    const key = JSON.stringify([projectId, text, workspace, project?.context_epoch]);
    const request_id = requestId(key, null);
    const accepted = await perform(() => makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/messages`, {
      request_id, text, ...workspace, inherit_media: false, asset_ids: [], capture_id: null,
    }));
    if (accepted) {
      retry.current = null;
      try { localStorage.removeItem(`${KEY}.outbox`); } catch { setStorageError(true); }
    }
    return accepted;
  }
  /** Known test symptoms need a short invitation, rather than another model diagnosis. */
  async function offerTestHelp(snapshot: MakerState, invitation: TestHelpInvitation, evidence: ComponentTestHelpContext): Promise<string | false> {
    const validBinding = () => !helpScope.current.demoOpen && !helpScope.current.project?.jobs.some(job => job.status === 'running')
      && helpScope.current.projectId === projectId && activeId.current === projectId && !latest.current.aiJobId && Boolean(snapshot.design
      && snapshot.design === latest.current.design && snapshot.code === latest.current.code
      && (snapshot.guide.run ?? 0) === (latest.current.guide.run ?? 0)
      && invitation.projectId === snapshot.design.id && invitation.revision === snapshot.design.revision
      && snapshot.design.component_ids.some(cid => cid === invitation.componentId)
      && invitation.guideKey === componentTestKey(snapshot.design, latest.current.guide, invitation.componentId)
      && invitation.guideRun === (snapshot.guide.run ?? 0) && invitation.contextEpoch === helpScope.current.epoch
      && invitation.componentId === snapshot.debug?.componentId && evidence.component_id === invitation.componentId
      && evidence.project_id === invitation.projectId && evidence.project_revision === invitation.revision
      && evidence.test_id === (snapshot.debug?.runId ?? null));
    const canBegin = () => !helpScope.current.busy && !flight.current && validBinding();
    if (!canBegin()) return false;
    const issue = JSON.stringify([projectId, invitation.contextEpoch, invitation.projectId, invitation.revision,
      invitation.componentId, invitation.guideKey, invitation.guideRun, evidence.test_id, evidence.reason]);
    const source_id = `test-help:${await sha256(issue)}`;
    const importKey = await testHelpImportKey(source_id, invitation.text);
    const codeHash = await sha256(snapshot.code);
    if (!canBegin()) return false;
    flight.current = true; setPending(true); setError('');
    try {
      let next = await makerRequest<AssistantConversation>(`assistant/conversations/${projectId}/import`, {
        source_id, kind: 'legacy-debug', messages: [{ id: 'test-help-invitation', role: 'assistant',
          text: invitation.text, stage: snapshot.stage, round: invitation.guideRun, created_at: Date.now() / 1000 }],
        test_help: { offer_id: invitation.id, project_id: invitation.projectId, project_revision: invitation.revision,
          component_id: invitation.componentId, guide_key: invitation.guideKey, guide_run: invitation.guideRun,
          context_epoch: invitation.contextEpoch, test_id: evidence.test_id ?? null, reason: evidence.reason ?? null, mode: invitation.mode,
          code_hash: codeHash },
      });
      const validPage = (page: AssistantConversation) => page.id === projectId && page.kind === 'project'
        && page.context_epoch === invitation.contextEpoch && page.round <= invitation.guideRun
        && !page.jobs.some(job => job.status === 'running');
      const findReceipt = (page: AssistantConversation | null) => page?.messages.find(message => message.import_key === importKey
        && message.role === 'assistant' && message.source === 'legacy-debug' && message.text === invitation.text
        && message.epoch === invitation.contextEpoch && message.round === invitation.guideRun && !message.archived && Boolean(message.id));
      if (!validBinding() || !validPage(next)) return false;
      const cached = helpScope.current.project;
      let receipt = findReceipt(next) ?? (cached && validPage(cached) ? findReceipt(cached) : undefined);
      if (receipt && !findReceipt(next)) next = mergeConversation(cached, next);
      while (!receipt && next.before !== null && next.before > 0) {
        const before = next.before;
        const previous = await makerRequest<AssistantConversation>(`assistant/conversations/${projectId}?before=${before}&limit=100`);
        if (!validBinding() || !validPage(previous)) return false;
        // A decreasing cursor bounds recovery; an unknown receipt cannot loop forever.
        if (previous.before !== null && previous.before >= before) break;
        next = { ...next, before: previous.before,
          messages: [...new Map([...previous.messages, ...next.messages].map(message => [message.id, message])).values()] };
        receipt = findReceipt(next);
      }
      if (!receipt) throw new Error(locale === 'en' ? 'The photo-check invitation could not be retrieved. Retry Ask AI for help.'
        : '尚未取得拍照檢查邀請，請再按一次「請 AI 幫忙」。');
      if (!validBinding()) return false;
      accept(next, true);
      return receipt.id;
    } catch (cause) { if (validBinding()) setError(String(cause)); return false; }
    finally { flight.current = false; setPending(false); }
  }
  async function testHelpAction(invitation: TestHelpInvitation, op: 'start' | 'later'): Promise<AssistantTestHelpResult | false> {
    const originalProject = latest.current.design;
    const originalCode = latest.current.code;
    const currentOffer = () => helpScope.current.project?.messages.find(item => item.id === invitation.messageId)?.test_help_offer;
    const valid = () => !helpScope.current.demoOpen && activeId.current === projectId
      && latest.current.design === originalProject && latest.current.code === originalCode && originalProject?.id === invitation.projectId
      && originalProject.revision === invitation.revision && helpScope.current.epoch === invitation.contextEpoch
      && (latest.current.guide.run ?? 0) === invitation.guideRun
      && componentTestKey(originalProject, latest.current.guide, invitation.componentId) === invitation.guideKey
      && currentOffer()?.offer_id === invitation.id && currentOffer()?.state !== 'stale'
      && (op === 'later' || currentOffer()?.state !== 'dismissed');
    const message = helpScope.current.project?.messages.find(item => item.id === invitation.messageId);
    const offer = message?.test_help_offer;
    if (!valid() || flight.current || op === 'start' && helpScope.current.busy
      || !(op === 'start' ? offer?.can_act : offer?.can_dismiss)
      || message?.role !== 'assistant' || message.source !== 'legacy-debug' || message.archived
      || message.epoch !== invitation.contextEpoch || message.round !== invitation.guideRun
      || !offer || offer.mode !== 'wiring' || !['pending', 'started'].includes(offer.state)
      || offer.offer_id !== invitation.id || offer.message_id !== invitation.messageId) return false;
    flight.current = true; setPending(true); setError('');
    try {
      const result = await makerRequest<AssistantTestHelpResult>(`assistant/conversations/${projectId}/test-help`, {
        op, offer_id: invitation.id, message_id: invitation.messageId,
      });
      if (!valid() || result.offer?.offer_id !== invitation.id || result.offer.message_id !== invitation.messageId
        || result.offer.state !== (op === 'later' ? 'dismissed' : 'started')) return false;
      setProject(current => current?.id === projectId && current.context_epoch === invitation.contextEpoch
        ? { ...current, messages: current.messages.map(item => item.id === invitation.messageId
          ? { ...item, test_help_offer: result.offer } : item) } : current);
      if (result.conversation?.id === projectId && result.conversation.context_epoch === invitation.contextEpoch) accept(result.conversation, true);
      return result;
    } catch (cause) { if (valid()) setError(String(cause)); return false; }
    finally { flight.current = false; setPending(false); }
  }
  /** Explicit entry to photo collection; no model or hardware work is submitted. */
  async function startWiringReview(componentId: string): Promise<AssistantWiringStartResult | false> {
    const snapshot = latest.current;
    const epoch = helpScope.current.epoch;
    const outbox = wiringOutboxRef.current;
    const receiptPending = outbox && outbox.conversation_id === projectId && outbox.context_epoch === epoch
      && outbox.before_signature === wiringReceiptSignature(snapshot);
    if (flight.current || helpScope.current.busy || helpScope.current.demoOpen || snapshot.aiJobId || !project
      || snapshot.stage !== 'guide' || !snapshot.design?.component_ids.some(id => id === componentId)
      || receiptPending || activeId.current !== projectId) return false;
    const valid = () => activeId.current === projectId && !helpScope.current.demoOpen && helpScope.current.epoch === epoch
      && latest.current.design === snapshot.design && latest.current.code === snapshot.code && latest.current.guide === snapshot.guide;
    const targetWire = snapshot.design.wiring.find(wire => wire.componentId === componentId);
    const context: DebugContext = { project: snapshot.design, code: snapshot.code, locale,
      guide_run: snapshot.guide.run ?? 0, guide_confirmations: snapshot.guide.confirmed,
      test_keys: Object.fromEntries(snapshot.design.component_ids.map(cid => [cid, componentTestKey(snapshot.design!, snapshot.guide, cid)])),
      entry: snapshot.debug ?? {}, wiring_target: targetWire ? { component_id: componentId, wire_id: targetWire.id } : null };
    const body = { context_epoch: epoch, context, component_id: componentId, model: selectedModel || snapshot.aiModel || null,
      effort: snapshot.aiEffort || null, response_mode: 'fast' };
    const key = JSON.stringify([projectId, body]);
    if (wiringStartRetry.current?.key !== key) wiringStartRetry.current = { key, id: newConversationId() };
    const request_id = wiringStartRetry.current.id;
    flight.current = true; setPending(true); setError('');
    try {
      const result = await makerRequest<AssistantWiringStartResult>(`assistant/conversations/${projectId}/wiring-review/start`, { ...body, request_id });
      if (!valid()) return false;
      if (result.conversation?.id !== projectId || result.conversation.context_epoch !== epoch
        || result.debug_session?.id !== result.debug_session_id
        || result.debug_session?.wiring_review?.component_id !== componentId || result.request_id !== request_id)
        throw new Error(locale === 'en' ? 'The wiring review changed. Retry from the current project.' : '接線核對已更新，請從目前作品重試。');
      accept(result.conversation, true);
      wiringStartRetry.current = null;
      return result;
    } catch (cause) {
      if (valid()) {
        const status = (cause as { status?: number })?.status;
        const errors: Record<string, [string, string]> = {
          wiring_review_session_active: ['仍有其他接線檢查進行中，請先按「停止本次檢查」再開始。', 'Stop the current wiring check before starting another one.'],
          wiring_review_context_changed: ['作品資料正在同步，請稍後再按「拍照檢查接線」。', 'The project context is syncing. Retry Check wiring with photos shortly.'],
          wiring_review_start_expired: ['上一輪檢查已結束，請再按一次開始新檢查。', 'The previous check ended. Click again to start a new check.'],
          wiring_review_chat_busy: ['AI 正在處理訊息，完成後即可開始拍照。', 'Wait for the current AI reply before starting photos.'],
          pi_busy_for_wiring: ['Pi 仍有工作執行中，請先在「執行管理」停止工作，再拍攝接線。', 'Stop the active Pi work in Execution manager before photographing the wiring.'],
        };
        const raw = String(cause);
        const translated = Object.entries(errors).find(([code]) => raw.includes(code));
        if (raw.includes('wiring_review_start_expired')) wiringStartRetry.current = null;
        setError(status === 404 || status === 405 ? (locale === 'en'
          ? 'Restart Board Vision to load the photo review entry, then retry.' : '請重啟 Board Vision 載入接線照片入口後重試。')
          : translated ? translated[1][locale === 'en' ? 1 : 0] : raw);
      }
      return false;
    } finally { flight.current = false; setPending(false); }
  }
  /** A message-bound action shares the existing chat and never consumes the draft. */
  async function wiringFlowAction(message: AssistantMessage, action: WiringReviewAction, context?: DebugContext): Promise<AssistantWiringFlowResult | false> {
    const snapshot = latest.current;
    const epoch = helpScope.current.epoch;
    const flow = message.wiring_flow;
    const currentMessage = () => helpScope.current.project?.messages.find(item => item.id === message.id);
    const validScope = () => !helpScope.current.demoOpen && activeId.current === projectId
      && helpScope.current.epoch === epoch && latest.current.design === snapshot.design
      && latest.current.code === snapshot.code && latest.current.guide === snapshot.guide;
    const current = currentMessage();
    const reference = current?.wiring_flow;
    if (!validScope() || !snapshot.design || flight.current || helpScope.current.busy
      || message.role !== 'assistant' || message.archived || message.epoch !== epoch
      || message.round !== (snapshot.guide.run ?? 0) || !flow || !reference?.current || !reference.can_act
      || reference.flow_id !== flow.flow_id || reference.review_id !== flow.review_id
      || reference.revision !== flow.revision || reference.round !== flow.round
      || !reference.actions.includes(action.op as WiringChatActionOp)
      || action.review_id !== reference.review_id || action.revision !== reference.revision
      || action.component_id !== reference.component_id) return false;
    const previousOutbox = wiringOutboxRef.current;
    const sameOutbox = previousOutbox?.conversation_id === projectId && previousOutbox.context_epoch === epoch
      && previousOutbox.message_id === message.id && previousOutbox.flow_id === flow.flow_id
      && previousOutbox.before_signature === wiringReceiptSignature(snapshot)
      && JSON.stringify(previousOutbox.action) === JSON.stringify(action);
    if (previousOutbox && !sameOutbox && previousOutbox.conversation_id === projectId && previousOutbox.context_epoch === epoch
      && previousOutbox.before_signature === wiringReceiptSignature(snapshot)) return false;
    const frozenContext = sameOutbox ? previousOutbox!.context : context;
    const key = JSON.stringify(['wiring-flow', projectId, epoch, message.id, flow.flow_id, action, frozenContext]);
    const request_id = sameOutbox ? previousOutbox!.request_id : requestId(key);
    const outbox: WiringActionOutbox | null = ['review', 'changed'].includes(action.op) && frozenContext ? {
      request_id, conversation_id: projectId, context_epoch: epoch, message_id: message.id, flow_id: flow.flow_id,
      action, context: frozenContext, before_signature: wiringReceiptSignature(snapshot),
      ...(sameOutbox ? { before_binding: previousOutbox!.before_binding } : debugSession?.binding ? { before_binding: structuredClone(debugSession.binding) } : {}),
    } : null;
    if (outbox) {
      // Freeze the explicit decision before transmission; a retry retains its original timestamp and identity.
      try { localStorage.setItem(WIRING_OUTBOX_KEY, JSON.stringify(outbox)); }
      catch { setError('無法保存這次決定，請確認瀏覽器儲存空間後重試。'); return false; }
      wiringOutboxRef.current = outbox; setWiringOutbox(outbox); setWiringReceiptError('');
    }
    flight.current = true; setPending(true); setError('');
    try {
      const result = await makerRequest<AssistantWiringFlowResult>(`assistant/conversations/${projectId}/wiring-flow`, {
        request_id, message_id: message.id, flow_id: flow.flow_id, action, ...(frozenContext ? { context: frozenContext } : {}),
      });
      if (!validScope() || result.conversation.id !== projectId || result.conversation.context_epoch !== epoch
        || result.debug_session.id !== result.debug_session_id) return false;
      accept(result.conversation, true);
      return { ...result, ...(outbox ? { outbox } : {}) };
    } catch (cause) { if (validScope()) {
      if (outbox) setWiringReceiptError('尚未確認剛才的決定是否送達，請重試取得確認結果。');
      else setError(String(cause));
    } return false; }
    finally { flight.current = false; setPending(false); }
  }
  function acknowledgeWiringFlow(request_id: string) {
    if (wiringOutboxRef.current?.request_id !== request_id) return;
    wiringOutboxRef.current = null; setWiringOutbox(null); setWiringReceiptError('');
    try { localStorage.removeItem(WIRING_OUTBOX_KEY); } catch { setStorageError(true); }
  }
  async function recoverWiringFlow(retryMissing = false): Promise<AssistantWiringFlowResult | false> {
    const outbox = wiringOutboxRef.current;
    const valid = () => outbox && activeId.current === outbox.conversation_id && !helpScope.current.demoOpen
      && helpScope.current.epoch === outbox.context_epoch && wiringReceiptSignature(latest.current) === outbox.before_signature;
    if (!outbox || flight.current || recoveryFlight.current || !valid()) return false;
    recoveryFlight.current = true;
    try {
      let response = await makerRequest<AssistantWiringFlowResult & { receipt_state: 'done' | 'pending' | 'missing' }>(
        `assistant/conversations/${outbox.conversation_id}/wiring-flow/receipts/${outbox.request_id}`);
      if (!valid() || response.conversation.id !== outbox.conversation_id || response.conversation.context_epoch !== outbox.context_epoch) return false;
      accept(response.conversation, true);
      if (response.receipt_state === 'missing' && retryMissing) {
        const prompt = response.conversation.messages.find(item => item.id === outbox.message_id)?.wiring_flow;
        if (!prompt?.current || !prompt.can_act || prompt.flow_id !== outbox.flow_id || prompt.revision !== outbox.action.revision) return false;
        response = { ...await makerRequest<AssistantWiringFlowResult>(`assistant/conversations/${outbox.conversation_id}/wiring-flow`, {
          request_id: outbox.request_id, message_id: outbox.message_id, flow_id: outbox.flow_id, action: outbox.action, context: outbox.context,
        }), receipt_state: 'done' };
      }
      if (!valid() || response.receipt_state !== 'done' || !response.guide_receipt || !response.debug_session) {
        setWiringReceiptError('尚未取得確認結果，請按「重試取得確認結果」。'); return false;
      }
      accept(response.conversation, true);
      return { ...response, outbox };
    } catch { if (valid()) setWiringReceiptError('確認結果暫時無法取得，請再試一次。'); return false; }
    finally { recoveryFlight.current = false; }
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
  const mediaReference = pendingReference === undefined ? composerMedia(record, mobileWorkspace.round)
    : pendingReference && record ? currentAssistantMedia({ ...record, active_media: pendingReference }, mobileWorkspace.round) : null;
  function composerMedia(conversation: AssistantConversation | null, round: number) {
    const media = currentAssistantMedia(conversation, round);
    return mediaScope(conversation, media) === removedMedia.current ? null : media;
  }
  /** Remove only the next-message reference, never the shared photos/history. */
  function removeMediaReference() {
    if (!mediaReference || busy || flight.current || demoOpen) return false;
    const scope = mediaScope(record, currentAssistantMedia(record, mobileWorkspace.round));
    removedMedia.current = scope; setRemovedMediaScope(scope);
    // An explicit removal is a new user intent, not a retry of the frozen photo payload.
    retry.current = null;
    try {
      if (scope) localStorage.setItem(REMOVED_MEDIA_KEY, scope);
      else localStorage.removeItem(REMOVED_MEDIA_KEY);
      localStorage.removeItem(`${KEY}.outbox`);
    } catch { setStorageError(true); }
    return true;
  }
  return { record, project, demo, demoOpen, setDemoOpen, busy, pending, wiringAnalysis, draft, setDraft, error: error || connectionError, storageError,
    send, sendPartsCheck, sendTestHelp, offerTestHelp, testHelpAction, startWiringReview, wiringFlowAction, recoverWiringFlow, acknowledgeWiringFlow, confirmDemo, adoptDemo, startConversation, prepareConversation, activateConversation, archiveWiring, mediaReference, removeMediaReference,
    wiringReceiptPending: Boolean(wiringOutbox && wiringOutbox.conversation_id === projectId && wiringOutbox.context_epoch === (project?.context_epoch ?? 0)
      && wiringOutbox.before_signature === wiringReceiptSignature(state)),
    wiringReceiptMessageId: wiringOutbox?.message_id, wiringReceiptRequestId: wiringOutbox?.request_id, wiringReceiptError,
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
