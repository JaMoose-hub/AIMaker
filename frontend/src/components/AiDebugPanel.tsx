import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMakerText } from "../lib/useMaker";
import { systemText } from "../lib/systemText";
import { makerCatalog, type MakerState, type ProjectGuideState } from "../lib/maker";
import type { DebugContext } from "../lib/debug";
import type { DebugMessage, DebugResponseMode, DebugSession, DebugSessionAction, useDebugSession } from "../lib/debugSessions";
import { sameDebugTestKeys } from "../lib/debugSessions";
import { componentComplete, componentTestKey } from "../lib/componentTests";
import type { TestHelpInvitation } from "../lib/componentTestHelp";
import { PhotoEvidenceCard } from "./PhotoEvidenceCard";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { DiagramEvidenceCard } from "./DiagramEvidenceCard";
import { debugEvidenceUrl, evidenceSessionId, type DiagramInspection } from "../lib/debugEvidence";
import { useCaptureCountdown } from "../lib/useCaptureCountdown";
import { CaptureCountdown } from "./CaptureCountdown";
import { useChatScroll } from "../lib/useChatScroll";
import { WiringReviewCard } from "./WiringReviewCard";
import { WiringReviewEntry } from "./WiringReviewEntry";
import { recommendWiringReview } from "../lib/wiringReviewEntry";
import { boundWiringAction, type WiringReviewAction, type WiringHumanDecision } from "../lib/wiringReview";
import { confirmReviewedWire, unconfirmReviewedWire, invalidateReviewedComponent, contextWithReviewGuide } from "../lib/wiringReviewGuide";

type SessionControl = ReturnType<typeof useDebugSession>;
const isTerminal = (status?: string) => status === "complete" || status === "stopped" || status === "error";
const epochTime = (value: string | number, locale: string) => new Date(typeof value === "string" ? value : value < 1e12 ? value * 1000 : value).toLocaleTimeString(locale);

export function AiDebugPanel({ state, context, currentCodeHash, repairCaseId, repairAppliedHash, repairCandidateReady, session, webcamReady, eyeActive, cameraSource, cameraRuntimeRevision, onReturnWebcam,
  onCase, onRetest, onTrial, onReviewRepair, onManual, onWiring, onDiagram, onReviewGuideChange, testHelpInvitation, testHelpActionTarget, onTestHelpHandled, onTestHelpAction, variant = "debug", wiringTarget, onOpenDebug, operationCard, headerControls, actionsOnly = false, chatGuidance = false, phonePreview = false, cameraStatusInView = false }: {
  state: MakerState; context: DebugContext; currentCodeHash: string; session: SessionControl; webcamReady: boolean; eyeActive: boolean;
  repairCaseId: string | null; repairAppliedHash: string | null; repairCandidateReady: boolean;
  cameraSource: string | null; cameraRuntimeRevision: number | null;
  onReturnWebcam: () => void; onCase: (id: string) => void; onRetest: (id: string, runId?: string) => void;
  onTrial: (trialId?: string) => void; onReviewRepair: () => void; onManual: () => void; onWiring: (id: string, pin?: string) => void;
  onDiagram?: (inspection: DiagramInspection) => void;
  onReviewGuideChange?: (guide: ProjectGuideState, expected: MakerState) => void;
  testHelpInvitation?: TestHelpInvitation | null;
  testHelpActionTarget?: HTMLElement | null;
  onTestHelpHandled?: (id: string) => void;
  onTestHelpAction?: (invitation: TestHelpInvitation, op: "start" | "later") => Promise<DebugSession | boolean>;
  variant?: "debug" | "wiring"; wiringTarget?: DebugContext["wiring_target"]; onOpenDebug?: () => void; operationCard?: React.ReactNode; headerControls?: React.ReactNode;
  actionsOnly?: boolean; chatGuidance?: boolean; phonePreview?: boolean; cameraStatusInView?: boolean;
}) {
  const tr = useMakerText();
  const statusText = (text: string) => systemText(text, tr("zh-TW", "en"));
  const initialSymptom = state.debug?.symptom ?? "";
  const [entry, setEntry] = useState(/^[a-z]+(?:_[a-z]+)+$/.test(initialSymptom) ? "" : initialSymptom);
  const [kind, setKind] = useState("custom");
  const [responseMode, setResponseMode] = useState<DebugResponseMode>(session.record?.response_mode ?? "fast");
  const [now, setNow] = useState(Date.now());
  const [recordsOpen, setRecordsOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [reviewToolbar, setReviewToolbar] = useState<HTMLDivElement | null>(null);
  const [reviewExpanded, setReviewExpanded] = useState(false);
  const [reviewReveal, setReviewReveal] = useState<{ token: string; reviewId: string; componentId: string } | null>(null);
  const [invitationWorking, setInvitationWorking] = useState(false);
  const invitationFlight = useRef(false);
  const invitationMounted = useRef(true);
  const toolsTrigger = useRef<HTMLButtonElement>(null);
  const recordsTrigger = useRef<HTMLButtonElement>(null);
  const recordsHeading = useRef<HTMLHeadingElement>(null);
  const recordsWasOpen = useRef(false);
  const panelRef = useRef<HTMLElement>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const composing = useRef(false);
  const staleNotified = useRef<string | null>(null);
  const targetNotified = useRef<string | null>(null);
  const reviewFlight = useRef(false);
  const reviewLatest = useRef(state);
  reviewLatest.current = state;
  const [reviewError, setReviewError] = useState("");
  const [reviewWorking, setReviewWorking] = useState(false);
  const record = session.record;
  const wiringMode = variant === "wiring";
  const actionContext = wiringTarget ? { ...context, wiring_target: wiringTarget } : context;
  const active = Boolean(record && !isTerminal(record.status));
  const missingWiring = state.design?.component_ids.find(id => !componentComplete(state.design!, state.guide, id));
  const latestObservation = record?.observations?.at(-1);
  const latestVisualObservation = [...(record?.observations ?? [])].reverse().find(item => item.observation_kind !== "conversation" && item.capture_ids.length > 0);
  const currentInstruction = statusText(record?.instruction || record?.report?.next_step || tr("正在整理本次證據。", "Collecting this session's evidence."));
  const sameInstruction = (left?: string, right?: string) => Boolean(left && right &&
    left.replace(/[\s\p{P}]+/gu, "").toLowerCase() === right.replace(/[\s\p{P}]+/gu, "").toLowerCase());
  const awaitingReply = record?.phase === "awaiting_user";
  const captureHint = record?.status === "awaiting_capture" && !awaitingReply && !record.model_busy && record.capture_task?.instruction &&
    !sameInstruction(record.capture_task.instruction, currentInstruction) &&
    !sameInstruction(record.capture_task.instruction, latestObservation?.next_step)
    ? statusText(record.capture_task.instruction) : null;
  const legacyMessages: DebugMessage[] = record?.messages?.length ? record.messages : record ? [
    { id: "initial", role: "user", text: record.symptom, created_at: record.observations?.[0]?.created_at ?? record.updated_at },
    ...(record.observations ?? []).map(observation => ({
      id: observation.id, role: "assistant" as const,
      text: [observation.seen, observation.explanation, observation.next_step]
        .filter((text, index, values): text is string => Boolean(text && !values.slice(0, index).some(value => sameInstruction(value, text))))
        .join("\n\n"),
      created_at: observation.created_at, capture_ids: observation.capture_ids, model: observation.model,
    })),
  ] : [];
  const sameMessageProject = !record?.binding?.project_id || record.binding.project_id === state.design?.id;
  const messages = [...new Map([...(session.conversation?.messages ?? []), ...(sameMessageProject ? legacyMessages : [])].map(message => [message.id, message])).values()]
    .sort((left, right) => left.created_at - right.created_at);
  const allEvidence = [...(session.conversation?.evidence ?? []), ...(record?.evidence ?? []).map(item => ({ ...item, session_id: item.session_id ?? record?.id }))];
  const diagrams = [...(session.conversation?.diagrams ?? []), ...(record?.diagrams ?? [])];
  const lastMessage = messages.at(-1);
  const chat = useChatScroll(lastMessage ? `${lastMessage.id}:${lastMessage.text}` : "", !recordsOpen);
  const normalize = (value: string) => value.replace(/[\s\p{P}]+/gu, "").toLowerCase();
  const instructionAlreadyShown = lastMessage?.role === "assistant" &&
    normalize(lastMessage.text).includes(normalize(currentInstruction));
  const elapsedSeconds = record?.model_started_at ? Math.max(0, Math.floor((now - record.model_started_at * 1000) / 1000)) : null;
  const binding = record?.binding;
  const sameProject = !binding?.project_id || binding.project_id === state.design?.id;
  const sameCode = !binding?.code_hash || !currentCodeHash || binding.code_hash === currentCodeHash;
  const sameWiring = !binding?.test_keys || sameDebugTestKeys(binding.test_keys, context.test_keys);
  // A newly created session can know the new camera revision before the
  // browser's config request catches up. Only trust that lag when the server
  // confirms this session still uses the current camera.
  const sameCamera = record?.wiring_photos_current === true || !record?.camera || cameraSource === null || cameraRuntimeRevision === null ||
    (record.camera.source === cameraSource && (record.camera.runtime_revision === cameraRuntimeRevision ||
      (record.camera_current === true && record.camera.runtime_revision > cameraRuntimeRevision)));
  const current = record?.current_target !== false && (record?.camera_current !== false || record?.wiring_photos_current === true)
    && sameProject && sameCode && sameWiring && sameCamera;
  const wiringRecommendation = recommendWiringReview(record, actionContext, current);
  const invitation = testHelpInvitation;
  const invitationCurrent = Boolean(invitation && state.design && !phonePreview && onReviewGuideChange && onTestHelpHandled
    && invitation.mode === "wiring" && invitation.projectId === state.design.id && invitation.revision === state.design.revision
    && state.design.component_ids.some(id => id === invitation.componentId)
    && invitation.guideRun === (state.guide.run ?? 0)
    && invitation.guideKey === componentTestKey(state.design, state.guide, invitation.componentId)
    && context.test_keys[invitation.componentId] === invitation.guideKey);
  const existingReview = record?.wiring_review;
  const reusableReview = invitationCurrent && active && current && record?.phase !== "backend_restarted"
    && existingReview && existingReview.component_id === invitation?.componentId
    && !["stale", "error"].includes(existingReview.status) ? existingReview : null;
  const invitationLatest = useRef({ invitation, current: invitationCurrent, reusableReview, onTestHelpHandled, onTestHelpAction,
    busy: session.pending || Boolean(record?.model_busy), state, start: wiringReviewAction });
  invitationLatest.current = { invitation, current: invitationCurrent, reusableReview, onTestHelpHandled, onTestHelpAction,
    busy: session.pending || Boolean(record?.model_busy), state, start: wiringReviewAction };
  const recommendedModule = makerCatalog.modules.find(module => module.id === wiringRecommendation?.component_id);
  const canStart = Boolean(state.design && !phonePreview && (wiringMode ? ["device", "phone"].includes(cameraSource ?? '') && !eyeActive : webcamReady) && !session.pending);
  const canAct = Boolean(active && record?.phase !== "backend_restarted" && current && webcamReady && !session.pending && (!binding?.code_hash || currentCodeHash));
  const approvedRepairCode = record?.status === "awaiting_repair" && sameProject && sameWiring && sameCamera &&
    record.current_target !== false && record.camera_current !== false && !sameCode &&
    Boolean(repairAppliedHash && repairAppliedHash === currentCodeHash && repairCaseId === record?.diagnosis?.case_id);
  const canResumeRepair = Boolean(approvedRepairCode && !session.pending && webcamReady);
  const canMessage = Boolean(active && record?.phase !== "backend_restarted" && current && !session.pending && !record?.model_busy && (!binding?.code_hash || currentCodeHash));
  const targetWire = state.design?.wiring?.find(wire => wire.id === actionContext.wiring_target?.wire_id);
  const targetModule = makerCatalog.modules.find(module => module.id === targetWire?.componentId);
  const targetModuleName = targetModule ? tr(targetModule.name["zh-TW"], targetModule.name.en) : targetWire?.componentId;
  const wiringPresets = wiringMode && targetWire && targetWire.componentId === actionContext.wiring_target?.component_id ? [
    { label: tr("這一步怎麼接？", "How do I connect this?"), text: tr(
      `${targetModuleName} 的 ${targetWire.componentPin} → Pi ${targetWire.boardLabel}，這一步怎麼接？請簡短說明，接線時保持斷電。`,
      `How do I connect ${targetModuleName} ${targetWire.componentPin} to Pi ${targetWire.boardLabel}? Please explain briefly, keeping power disconnected while wiring.`) },
    { label: tr("Pi 腳位在哪？", "Where is the Pi pin?"), text: tr(
      `這一步要接到 Pi ${targetWire.boardLabel}。請說明它在接腳排上的位置，以及從哪個方向數腳。`,
      `This step connects to Pi ${targetWire.boardLabel}. Where is it on the header, and which direction do I count the pins from?`) },
    { label: tr("怎麼檢查接線？", "How do I check the wiring?"), text: tr(
      `${targetModuleName} 的 ${targetWire.componentPin} → Pi ${targetWire.boardLabel} 接好後，怎麼在斷電時檢查接線？請先說明方法，不要自動執行測試。`,
      `After connecting ${targetModuleName} ${targetWire.componentPin} to Pi ${targetWire.boardLabel}, how do I check the wiring with power disconnected? Explain the method first; do not automatically run a test.`) },
  ] : [];
  const canCaptureWiring = Boolean(webcamReady && targetWire && !session.pending && !record?.model_busy &&
    (!active || (canAct && !["model_limit", "backend_restarted"].includes(record?.phase ?? ""))));
  const captureScope = JSON.stringify([state.design?.id, state.design?.revision, context.test_keys, currentCodeHash,
    cameraSource, cameraRuntimeRevision, wiringMode, wiringTarget, record?.id, record?.phase, session.resetVersion]);
  const countdown = useCaptureCountdown(captureScope,
    Boolean(state.design && webcamReady && !eyeActive && !recordsOpen && !session.pending && !record?.model_busy && (!active || current)), panelRef);
  const counting = countdown.remaining !== null;
  const expectedModules = state.design?.component_ids.filter(id => id === "hc-sr04" || id === "mrd-tf240-8p-cs") ?? [];
  const testOutcomes = expectedModules.map(id => [...(record?.test_results ?? [])].reverse().find(run => run.component_id === id && !run.invalidated)?.outcome);
  const componentOutcome = !current ? tr("紀錄已過期", "Record is stale")
    : expectedModules.length > 0 && testOutcomes.every(value => value === "passed") ? tr("功能通過", "Function passed")
    : testOutcomes.some(value => value === "awaiting_confirmation") ? tr("等待實體確認", "Waiting for physical confirmation")
    : testOutcomes.some(value => value === "failed" || value === "inconclusive") ? tr("未通過／不確定", "Failed or uncertain")
    : testOutcomes.some(value => value === "running") ? tr("測試中", "Testing")
    : tr("尚未通過", "Not yet passed");
  const wholeOutcome = !current ? tr("紀錄已過期", "Record is stale")
    : record?.trial_result?.outcome === "passed" ? tr("試跑通過", "Trial passed")
    : record?.trial_result?.outcome === "awaiting_confirmation" ? tr("等待目視確認", "Waiting for visual confirmation")
    : record?.trial_result?.outcome === "failed" || record?.trial_result?.outcome === "inconclusive" ? tr("未通過／不確定", "Failed or uncertain")
    : record?.trial_result?.outcome === "running" ? tr("試跑中", "Trial running")
    : tr("尚未通過", "Not yet passed");

  useEffect(() => {
    if (active && record?.diagnosis?.case_id && record.diagnosis.case_id !== state.debug?.caseId) onCase(record.diagnosis.case_id);
  }, [active, record?.diagnosis?.case_id, state.debug?.caseId, onCase]);
  useEffect(() => { invitationMounted.current = true; return () => { invitationMounted.current = false; }; }, []);
  useEffect(() => { if (record?.id) setEntry(""); }, [record?.id]);
  useLayoutEffect(() => {
    if (recordsOpen) recordsHeading.current?.focus({preventScroll:true});
    else if (recordsWasOpen.current) recordsTrigger.current?.focus({preventScroll:true});
    recordsWasOpen.current = recordsOpen;
  }, [recordsOpen]);
  useLayoutEffect(() => {
    const input = composerRef.current;
    if (!input) return;
    const resize = () => {
      input.style.height = "0px";
      input.style.height = `${input.scrollHeight}px`;
    };
    resize();
    let width = input.clientWidth;
    const observer = new ResizeObserver(() => {
      if (input.clientWidth === width) return;
      width = input.clientWidth;
      resize();
    });
    observer.observe(input);
    return () => observer.disconnect();
  }, [entry]);
  useEffect(() => { if (record?.response_mode) setResponseMode(record.response_mode); }, [record?.id, record?.response_mode]);
  useEffect(() => {
    if (!record?.model_busy) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [record?.model_busy, record?.model_started_at]);
  useEffect(() => {
    // A server-committed human decision may precede its local ACK. Never retract it with the old guide table.
    if (chatGuidance && sameProject && sameCode && sameCamera || !record || !active || record.phase === "backend_restarted" || current || approvedRepairCode || !sameProject || record.current_target === false || !currentCodeHash || cameraSource === null || cameraRuntimeRevision === null) return;
    const changedKey = JSON.stringify([record.id, currentCodeHash, cameraSource, cameraRuntimeRevision, context.test_keys]);
    if (staleNotified.current === changedKey) return;
    // Another rapid confirmation may arrive while the prior refresh is in
    // flight. Only an adopted reply acknowledges this exact context.
    void session.contextChanged(actionContext).then(result => { if (result) staleNotified.current = changedKey; });
  }, [chatGuidance, record?.id, active, current, approvedRepairCode, sameProject, sameCode, sameCamera, currentCodeHash, cameraSource, cameraRuntimeRevision, context, session]);
  useEffect(() => {
    const target = actionContext.wiring_target;
    if (chatGuidance || !record || !active || !wiringMode || !target || !current || record.model_busy || session.pending || record.phase === "backend_restarted") return;
    if (record.wiring_target?.wire_id === target.wire_id && record.wiring_target.component_id === target.component_id) return;
    const key = `${record.id}:${target.component_id}:${target.wire_id}`;
    if (targetNotified.current === key) return;
    void session.contextChanged(actionContext).then(result => { if (result) targetNotified.current = key; });
  }, [record?.id, active, wiringMode, chatGuidance, actionContext.wiring_target?.component_id, actionContext.wiring_target?.wire_id, record?.wiring_target?.wire_id, record?.model_busy, session.pending, current]);

  const examples: Record<string, [string, string]> = {
    distance: ["HC-SR04+ 測不到距離，請檢查感測器與目標。", "HC-SR04+ has no distance reading. Check the sensor and target."],
    display: ["MRD-TFT240 沒有畫面或顏色不對，請檢查螢幕。", "MRD-TFT240 has no picture or wrong colors. Check the display."],
    program: ["作品執行後沒有反應，請檢查程式、距離與螢幕。", "The project does not respond. Check its code, distance readings, and display."],
  };
  function selectKind(value: string) {
    setKind(value);
    if (examples[value]) setEntry(tr(...examples[value]));
  }
  function fillWiringQuestion(question: string) {
    if (session.pending) return;
    setEntry(previous => !previous.trim() ? question : previous.split(/\r?\n/).includes(question)
      ? previous : `${previous}${previous.endsWith("\n") ? "" : "\n"}${question}`);
    composerRef.current?.focus();
  }
  async function send() {
    const text = entry.trim() || (!active && !wiringMode ? tr("請查看目前 Webcam 畫面，結合 Pi 狀態與作品程式，找出需要確認的異常並引導我完成下一步。", "Inspect the current Webcam image alongside Pi status and the project code, identify what needs checking, and guide my next step.") : "");
    if (!text || session.pending || record?.model_busy || counting) return;
    chat.followNext();
    if (active) {
      if (!canMessage) return;
      const result = await session.action("message", actionContext, text, responseMode);
      if (result) setEntry(value => value.trim() === text ? "" : value);
    } else if (canStart) {
      const create = () => session.create(actionContext, text, state.aiModel, state.aiEffort, responseMode, { purpose: wiringMode ? "wiring_review" : "debug" });
      const result = await (wiringMode ? create() : countdown.run(create));
      if (result) setEntry(value => value.trim() === text ? "" : value);
    }
  }
  function act(actionName: DebugSessionAction) {
    if (actionName === "stop") countdown.cancel();
    else if (counting) return;
    const action = () => session.action(actionName, actionContext, undefined, responseMode);
    const takesPhoto = actionName === "capture" || (actionName === "continue" && record?.purpose !== "wiring_review" &&
      (record?.status === "awaiting_capture" || (record?.status === "paused" && !["test_preflight_blocked", "trial_preflight_blocked", "backend_restarted"].includes(record.phase))));
    chat.followNext();
    void (takesPhoto ? countdown.run(action) : action());
  }
  async function captureStep() {
    if (!canCaptureWiring || counting) return;
    chat.followNext();
    await countdown.run(async () => {
      if (!active) {
        await session.create(actionContext, entry.trim() || tr("請檢查這一步的實際接線，對照既有設計並指出需要調整的地方。", "Review this step's actual wiring against the existing design and explain what needs adjusting."), state.aiModel, state.aiEffort, responseMode, { purpose: "wiring_review", initial_action: "capture" });
      } else if (canAct) {
        if (record?.purpose !== "wiring_review" && !await session.action("prepare_wiring", actionContext, undefined, responseMode)) return;
        await session.action("capture", actionContext, undefined, responseMode);
      }
    });
  }
  async function startDebug() {
    if (!record || session.pending || record.model_busy || counting) return;
    chat.followNext();
    if (await countdown.run(() => session.action("start_debug", actionContext, undefined, responseMode))) onOpenDebug?.();
  }
  async function wiringReviewAction(payload: WiringReviewAction) {
    if (reviewFlight.current || session.pending || record?.model_busy || counting || !state.design || phonePreview) return false;
    reviewFlight.current = true; setReviewWorking(true); setReviewError("");
    const originalState = state;
    const unchanged = () => reviewLatest.current.design === originalState.design
      && reviewLatest.current.guide === originalState.guide && reviewLatest.current.code === originalState.code;
    try {
      let currentRecord = record;
      if (!active || !current || record?.phase === "backend_restarted") {
        if (payload.op !== "start") throw new Error(tr("請先開始新一輪接線檢查。", "Start a new wiring review first."));
        if (active && !await session.action("stop")) return false;
        if (!unchanged()) return false;
        currentRecord = await session.create(actionContext,
          state.debug?.symptom || tr("對照 Pi 排針與零件接頭的腳位和線色，逐條由我確認。", "Compare the Pi header and the component header; I will confirm each wire."),
          state.aiModel, state.aiEffort, responseMode, { purpose: "wiring_review", initial_action: "collect" }) ?? null;
        if (!currentRecord || !unchanged()) return false;
        // A new session has no review yet; discard the old card's CAS token.
        payload = { op: "start", component_id: payload.component_id };
      }
      if (!currentRecord) return false;
      let nextGuide = originalState.guide;
      let nextContext = actionContext;
      const retracting = payload.op === "review" && payload.decision !== "confirmed"
        && Boolean(payload.wire_id && originalState.guide.confirmed[payload.wire_id]);
      if (payload.op === "changed" || retracting || (payload.op === "review" && payload.decision === "needs_change") || (payload.op === "start" && currentRecord.purpose !== "wiring_review")) {
        const prepared = await session.action("prepare_wiring", actionContext, undefined, responseMode, undefined, currentRecord.id);
        if (!prepared?.wiring_edit_ready || !unchanged()) throw new Error(tr("請先停止並核對 Pi 工作，再修改接線或確認紀錄。", "Stop and reconcile Pi work before changing wiring or confirmations."));
        currentRecord = prepared;
      }
      if (payload.op === "changed") {
        nextGuide = invalidateReviewedComponent(originalState.design!, originalState.guide, payload.component_id);
      } else if (payload.op === "review" && payload.wire_id) {
        nextGuide = payload.decision === "confirmed"
          ? confirmReviewedWire(originalState.design!, originalState.guide, payload.wire_id)
          : unconfirmReviewedWire(originalState.design!, originalState.guide, payload.wire_id);
      }
      if (nextGuide !== originalState.guide) {
        if (!onReviewGuideChange) throw new Error(tr("此畫面無法更新人工確認，請回到作品助手。", "Return to the project assistant to update human confirmations."));
        nextContext = contextWithReviewGuide(actionContext, originalState.design!, nextGuide);
      }
      if (!unchanged()) return false;
      const submit = () => session.action("wiring_review", nextContext, undefined, responseMode, payload, currentRecord!.id);
      const next = await (payload.op === "capture" ? countdown.run(submit) : submit());
      if (!next || !unchanged()) return false;
      if (nextGuide !== originalState.guide) onReviewGuideChange?.(nextGuide, originalState);
      chat.followNext();
      return next;
    } catch (cause) {
      setReviewError(cause instanceof Error ? cause.message : tr("接線核對未完成，請重試。", "The wiring review did not complete. Retry."));
      return false;
    } finally { reviewFlight.current = false; setReviewWorking(false); }
  }
  async function reviewWire(wireId: string, decision: WiringHumanDecision) {
    if (!record?.wiring_review) return;
    await wiringReviewAction(boundWiringAction(record.wiring_review, { op: "review", wire_id: wireId, decision }));
  }
  async function startTestHelpPhotos() {
    const request = invitationLatest.current;
    if (!invitationMounted.current || !request.current || !request.invitation || request.invitation.id !== invitation?.id
      || request.invitation.canAct === false || request.busy || counting || invitationFlight.current) return false;
    invitationFlight.current = true; setInvitationWorking(true);
    try {
      const next = request.onTestHelpAction ? await request.onTestHelpAction(request.invitation, "start")
        : request.reusableReview ? null : await request.start({ op: "start", component_id: request.invitation.componentId });
      if (request.onTestHelpAction && !next) return false;
      const review = next && typeof next === "object" ? next.wiring_review : request.reusableReview;
      const latest = invitationLatest.current;
      if (!review || review.component_id !== request.invitation.componentId || !invitationMounted.current
        || !latest.current || latest.invitation?.id !== request.invitation.id
        || latest.state.design !== request.state.design || latest.state.guide !== request.state.guide || latest.state.code !== request.state.code) return false;
      if (!chatGuidance) setReviewReveal({ token: request.invitation.id, reviewId: review.id, componentId: review.component_id });
      latest.onTestHelpHandled?.(request.invitation.id);
      return true;
    } catch (cause) {
      if (invitationMounted.current && invitationLatest.current.invitation?.id === request.invitation.id)
        setReviewError(cause instanceof Error ? cause.message : "connection_lost");
      return false;
    } finally { invitationFlight.current = false; if (invitationMounted.current) setInvitationWorking(false); }
  }
  async function dismissTestHelp() {
    const latest = invitationLatest.current;
    const currentInvitation = latest.invitation;
    if (!invitationMounted.current || !latest.current || !currentInvitation || currentInvitation.canDismiss === false || currentInvitation.id !== invitation?.id || invitationFlight.current) return;
    invitationFlight.current = true; setInvitationWorking(true);
    try {
      if (latest.onTestHelpAction && !await latest.onTestHelpAction(currentInvitation, "later")) return;
      if (invitationMounted.current && invitationLatest.current.current && invitationLatest.current.invitation?.id === currentInvitation.id)
        invitationLatest.current.onTestHelpHandled?.(currentInvitation.id);
    } catch (cause) {
      if (invitationMounted.current && invitationLatest.current.invitation?.id === currentInvitation.id)
        setReviewError(cause instanceof Error ? cause.message : "connection_lost");
    } finally { invitationFlight.current = false; if (invitationMounted.current) setInvitationWorking(false); }
  }
  async function startNewCheck() {
    if (!canStart || session.pending || record?.model_busy || counting) return;
    chat.followNext();
    const create = async () => {
      if (active && !await session.action("stop")) return;
      return session.create(actionContext, entry.trim() || record?.symptom || tr("接續這個作品的檢查，請先整理目前資訊與下一步。", "Continue checking this project and summarize the current evidence and next step."),
        state.aiModel, state.aiEffort, responseMode, { purpose: wiringMode ? "wiring_review" : record?.purpose ?? "debug" });
    };
    const result = await (wiringMode || record?.purpose === "wiring_review" ? create() : countdown.run(create));
    if (result) setEntry("");
  }
  function onComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) {
      event.preventDefault();
      void send();
    }
  }
  const statusName: Record<string, string> = {
    diagnosing: tr("正在檢查", "Checking"), awaiting_capture: tr("等待拍攝", "Waiting for capture"),
    awaiting_ready: tr("等待你擺好目標", "Waiting for your setup"), testing: tr("正在測試", "Testing"),
    awaiting_visual: tr("等待螢幕目視確認", "Waiting for screen confirmation"),
    awaiting_repair: tr("檢查程式修復", "Reviewing code repair"),
    awaiting_trial_visual: tr("等待試跑目視確認", "Waiting for trial confirmation"),
    complete: tr("本次除錯完成", "Debug session complete"), paused: tr("已暫停", "Paused"),
    stopped: tr("已停止", "Stopped"), error: tr("執行出錯", "Error"),
  };
  const frameUrl = debugEvidenceUrl;
  const cameraVerdict = record?.camera_verdict === "read_current_frame" ? tr("鏡頭讀到本次畫面", "Camera read this test's frame")
    : record?.camera_verdict === "display_abnormal" ? tr("鏡頭看到畫面異常", "Camera saw an abnormal display")
    : record?.camera_verdict === "inconclusive" ? tr("鏡頭尚無法判定", "Camera cannot determine the result") : null;
  const readableError = (value: string) => {
    const messages: Record<string, [string, string]> = {
      session_active: ["這台 Pi 已有另一個 AI 除錯工作階段。請先停止該工作階段。", "This Pi already has an active AI debug session. Stop it first."],
      webcam_required: ["請先啟用 Webcam。", "Enable a Webcam first."],
      webcam_restore_required: ["請先從 Eye 恢復 Webcam。", "Restore the Webcam from Eye first."],
      wiring_confirmation_required: ["請回到 02 完成逐腳接線確認。", "Complete the pin confirmations in step 02."],
      wiring_confirmation_changed: ["接線確認已更新，請重新開始本次除錯。", "Wiring confirmations changed. Start a new debug session."],
      pi5_required: ["請切換到 Raspberry Pi 5 工作流程。", "Switch to the Raspberry Pi 5 workflow."],
      stale_debug_context: ["作品或接線已變更，請重新開始除錯。", "The project or wiring changed. Start a new debug session."],
      camera_changed: ["鏡頭已變更，請重新開始除錯。", "The camera changed. Start a new debug session."],
      camera_source_unavailable: ["目前無法取得 Webcam 來源，請確認鏡頭已連接並啟用。", "The Webcam source is unavailable. Check that the camera is connected and enabled."],
      camera_frame_unavailable: ["尚未收到鏡頭畫面。請確認 Webcam 有畫面後再拍照。", "No camera image is available. Wait for the Webcam image, then capture again."],
      camera_frame_not_new: ["還沒有取得新的鏡頭影格。請確認畫面持續更新後再拍照。", "No fresh camera frame arrived. Check that the video is updating, then capture again."],
      camera_frame_invalid: ["這次鏡頭影格無法讀取，請重新拍照。", "This camera frame could not be read. Capture again."],
      camera_encode_failed: ["這次照片無法編碼，請重新拍照。", "This photo could not be encoded. Capture again."],
      camera_frame_too_large: ["這次照片超過大小上限，請降低鏡頭解析度後重試。", "This photo exceeds the size limit. Lower the camera resolution and retry."],
      "Codex request timed out": ["雲端 AI 回應逾時，請按下方按鈕重新拍照分析。", "Cloud AI timed out. Use the button below to capture and analyze again."],
      "AI generation failed": ["雲端 AI 這次未完成分析，請按下方按鈕重新拍照分析。", "Cloud AI could not finish this analysis. Use the button below to capture and analyze again."],
      model_call_limit_reached: ["本次 AI 分析已達上限，請查看現有證據。", "This session reached its AI analysis limit. Review the evidence."],
      model_call_in_progress: ["AI 正在回覆，請等這一輪完成後再傳送。", "AI is replying. Wait for this turn before sending another message."],
      backend_restarted: ["後端已重新啟動。請先核對 Pi 工作狀態並停止舊案件，再以目前作品開始新案件。", "The backend restarted. Check the Pi job state, stop this old session, then start a new one with the current project."],
      restart_requires_new_session: ["重啟後的案件僅供檢視。請停止舊案件，再開始新的 AI 除錯。", "A session from before the restart is read only. Stop it, then start a new AI debug session."],
      restart_requires_stop: ["請先核對 Pi 工作並停止重啟前的案件，再開始新的 AI 除錯。", "Check Pi jobs and stop the session from before the restart before starting a new one."],
      stale_wiring_review: ["照片輪次已更新，請查看目前這一輪再操作。", "The photo round changed. Review the current round before continuing."],
      stale_wiring_review_photo: ["這張照片已被更新，請查看目前的照片再選用。", "This photo was replaced. Review the current photo before selecting it."],
      wiring_review_photos_not_accepted: ["請先逐張選用這輪要求的接線照片，再開始分析。", "Select the wiring photos requested for this round before analysing."],
      wiring_review_photos_incomplete: ["請先完成這輪要求的三張接線照片，再開始分析。", "Capture the three requested wiring photos before analysing."],
      wiring_review_photos_expired: ["這組照片已不適用，請為目前接線重新拍照。", "These photos are no longer current. Capture the present wiring."],
      wiring_review_photo_required: ["這個視角尚無可用照片，請先拍攝。", "Capture this view before selecting a region."],
      wiring_review_crop_too_small: ["框選範圍太小，請包含接頭、插接底部與線色。", "Expand the crop to include the housing, insertion point and wire color."],
      wiring_review_analysis_timeout: ["照片分析逾時，原圖與已完成的觀察會保留，可重新分析。", "Photo analysis timed out. Originals and completed observations are retained; retry the analysis."],
      wiring_review_image_budget_exceeded: ["照片總尺寸超出分析上限，請選用較小尺寸的照片後重試。", "The total photo size exceeds the analysis limit. Select smaller photos and retry."],
      photo_color_profile_invalid: ["無法讀取照片的色彩設定，請轉存為 sRGB 照片後重試。", "The photo color profile could not be read. Save an sRGB copy and retry."],
      human_review_required: ["補查尚未改善證據，請親自沿線核對兩端，再記錄結果。", "Photo checks have not improved the evidence. Trace both ends yourself and record your decision."],
      pi_busy_for_wiring: ["Pi 工作尚未確認停止，請先在執行管理完成停止，再調整接線。", "Pi work has not been confirmed stopped. Stop it in execution management before changing wiring."],
      wiring_review_result_required: ["請先分析這輪照片，再逐條記錄人工核對。", "Analyse this photo round before recording wire reviews."],
    };
    return messages[value] ? tr(...messages[value]) : value.startsWith("HTTP ") ? tr("除錯服務暫時無法回應，請稍後再試。", "The debug service is unavailable. Try again shortly.") : statusText(value);
  };

  const recordsActions = <><button ref={recordsTrigger} type="button" className="workflow-secondary" aria-expanded={recordsOpen} aria-controls="ai-debug-records" title={tr("照片使用與檢查紀錄", "Photo use and inspection records")} onClick={() => setRecordsOpen(value => !value)}>{tr("檢查紀錄", "Check records")}</button><button type="button" className="workflow-secondary" aria-controls="debug-manual-tools" onClick={() => {setRecordsOpen(false);onManual();}}>{tr("手動測試工具", "Manual test tools")}</button></>;
  const captureLabel = !webcamReady && cameraStatusInView ? tr('影像尚未就緒，請到即時畫面確認連線', 'Camera not ready. Check the connection in Live view')
    : wiringMode ? tr("拍攝這一步", "Capture this step")
    : !active ? tr("拍照並開始除錯", "Capture and start debugging")
      : tr("拍目前畫面", "Capture current view");
  const showCompactCapture = wiringMode || !active || (record?.status === "awaiting_capture" && awaitingReply && !record.model_busy);
  const photoReviewInFocus = invitationCurrent || Boolean(reviewExpanded && record?.wiring_review && record.purpose === 'wiring_review'
    && record.status === 'awaiting_capture' && current && !record.error && !record.model_busy);
  const invitationActions = invitationCurrent ? <div className="ai-debug-actions test-help-invitation" role="group" aria-label={tr("接線照片檢查邀請", "Wiring photo review invitation")}>
    <button type="button" className="guide-primary-action" disabled={invitation?.canAct === false || invitationWorking || reviewWorking || session.pending || Boolean(record?.model_busy) || counting}
      onClick={() => void startTestHelpPhotos()}>{reusableReview ? tr("繼續照片核對", "Continue photo review") : tr("拍照檢查", "Check wiring with photos")}</button>
    <button type="button" disabled={invitation?.canDismiss === false || invitationWorking} onClick={() => void dismissTestHelp()}>{tr("稍後", "Later")}</button>
    {reviewError ? <small className="pi-error" role="alert">{readableError(reviewError)}</small> : null}
  </div> : null;
  if (actionsOnly && chatGuidance) {
    const invitationPortal = invitationActions && testHelpActionTarget ? createPortal(invitationActions, testHelpActionTarget) : null;
    const canStop = active && !phonePreview;
    if (!invitationPortal && !canStop) return null;
    return <>{invitationPortal}{canStop ? <div className="assistant-debug-toolbar">
      <button className="assistant-debug-stop" type="button" disabled={session.pending} onClick={() => act("stop")}>{wiringMode ? tr("停止本次檢查", "Stop this check") : tr("停止本次除錯", "Stop this session")}</button>
      {session.error ? <small className="pi-error" role="alert">{readableError(session.error)}</small> : null}
    </div> : null}</>;
  }
  return <section ref={panelRef} className={`ai-debug-panel${wiringMode ? " is-wiring-review" : ""}${actionsOnly ? " is-actions-only" : ""}`} aria-label={wiringMode ? tr("與 AI 一起接線", "Wire with AI") : tr("與 AI 一起除錯", "Debug with AI")}
    onKeyDown={event => {
      if (actionsOnly && toolsOpen && event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault(); event.stopPropagation(); countdown.cancel(); setToolsOpen(false); toolsTrigger.current?.focus();
      }
    }}>
    {actionsOnly ? <>
      <div className="assistant-debug-toolbar">
        <div className="assistant-debug-primary">
          {showCompactCapture && !reviewExpanded ? <button className="assistant-capture" type="button" title={captureLabel} aria-label={captureLabel}
            disabled={recordsOpen || counting || (wiringMode ? !canCaptureWiring : !active ? !canStart : !canAct)}
            onClick={() => wiringMode ? void captureStep() : !active ? void send() : act("capture")}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 5 6 8H4a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-2l-2-3Z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>{tr("拍目前畫面", "Capture current view")}</span>
          </button> : null}
          {state.design && onReviewGuideChange ? <div className="assistant-wiring-entry-slot" ref={setReviewToolbar} /> : null}
          <button ref={toolsTrigger} className="assistant-debug-tools-toggle" type="button" title={tr("工具與設定", "Tools & settings")} aria-label={tr("工具與設定", "Tools & settings")} aria-expanded={toolsOpen} aria-controls="assistant-debug-settings" onClick={() => setToolsOpen(value => !value)}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>
          </button>
        </div>
      </div>
      <div id="assistant-debug-settings" className="assistant-debug-settings" hidden={!toolsOpen}>
        {headerControls ? <div className="assistant-debug-secondary"><span>{tr('對話情境', 'Conversation context')}</span>{headerControls}</div> : null}
        <label><span>{tr("照片分析", "Photo analysis")}</span><select aria-label={tr("照片分析方式", "Photo analysis style")} value={responseMode} disabled={Boolean(counting || record?.model_busy || session.pending)} onChange={event => setResponseMode(event.target.value as DebugResponseMode)}><option value="fast">{tr("快速引導", "Quick guidance")}</option><option value="thorough">{tr("深入分析", "Detailed analysis")}</option></select></label>
        <div className="assistant-debug-secondary">{recordsActions}</div>
      </div>
      {active ? <button className="assistant-debug-stop" type="button" disabled={session.pending} onClick={() => act("stop")}>{wiringMode ? tr("停止本次檢查", "Stop this check") : tr("停止本次除錯", "Stop this session")}</button> : null}
    </> : <div className="ai-debug-head">
      {headerControls}
      <div className="ai-debug-head-actions">{active ? <button type="button" disabled={session.pending} onClick={() => act("stop")}>{wiringMode ? tr("停止本次檢查", "Stop this check") : tr("停止本次除錯", "Stop this session")}</button> : null}{recordsActions}</div>
    </div>}
    <div className="ai-debug-conversation" hidden={recordsOpen}>
    <CaptureCountdown remaining={countdown.remaining} onCancel={countdown.cancel} />
    {!webcamReady && (!cameraStatusInView || eyeActive) ? <div className="guide-caution" role="status">
      <p>{eyeActive ? tr("目前是 Eye 畫面。請先恢復 Webcam，再開始 AI 協作除錯。", "Eye is active. Restore the Webcam before starting AI guided debugging.")
        : tr("請確認目前影像來源持續更新，再拍照；仍可先詢問接法。", "Check that the selected camera is live before capturing. You can still ask about wiring.")}</p>
      {eyeActive ? <button type="button" onClick={onReturnWebcam}>{tr("返回 Webcam", "Restore Webcam")}</button> : null}
    </div> : null}
    {!state.design ? <p className="guide-caution">{tr("先建立作品，系統才能對照目前接線、程式與測試結果。", "Create a project so the system can compare its wiring, code, and tests.")}</p> : null}
    <div className="ai-debug-chat" ref={chat.chatRef} role={actionsOnly ? "region" : "log"} aria-label={actionsOnly ? tr("除錯操作與證據", "Debug actions and evidence") : tr("AI 除錯對話", "AI debugging conversation")} aria-live="polite" aria-relevant="additions" onScroll={chat.onScroll}>
    <div className="ai-debug-chat-content" ref={chat.contentRef}>
      {invitationActions && (testHelpActionTarget ? createPortal(invitationActions, testHelpActionTarget) : !actionsOnly ? invitationActions : null)}
      {state.design && onReviewGuideChange ? <WiringReviewEntry key={state.design.id} review={sameProject ? record?.wiring_review : null}
        toolbarTarget={actionsOnly ? reviewToolbar : null} disabled={recordsOpen}
        onExpandedChange={setReviewExpanded}
        revealRequest={reviewReveal}
        resumable={active && current && record?.phase !== "backend_restarted"}
        recommendation={wiringRecommendation} componentLabel={recommendedModule ? tr(recommendedModule.name["zh-TW"], recommendedModule.name.en) : undefined}>
        {componentId => <WiringReviewCard review={sameProject ? record?.wiring_review : null}
        components={(state.design?.component_ids ?? []).map(id => {
          const module = makerCatalog.modules.find(item => item.id === id);
          return { id, label: module ? tr(module.name["zh-TW"], module.name.en) : id };
        })} componentId={componentId ?? state.debug?.selectedComponentId ?? state.debug?.componentId ?? targetWire?.componentId}
        busy={reviewWorking || session.pending || Boolean(record?.model_busy) || counting}
        captureReady={webcamReady && !eyeActive} stale={Boolean(record && (!active || !current)) || record?.phase === "backend_restarted"}
        error={reviewError || session.error ? readableError(reviewError || session.error) : undefined} onAction={wiringReviewAction} onReview={reviewWire}
        onRetest={id => onRetest(id)} onInspectWire={wireId => {
          const wire = state.design?.wiring.find(item => item.id === wireId);
          if (wire) onWiring(wire.componentId, wire.componentPin);
        }} />}</WiringReviewEntry> : null}
      {!actionsOnly && !record && messages.length === 0 ? <div className="ai-debug-welcome"><span className="ai-debug-avatar">AI</span><h4>{wiringMode ? tr("這一步需要幫忙嗎？", "Need help with this step?") : tr("哪裡沒有照預期運作？", "What isn't working as expected?")}</h4><p>{wiringMode ? tr("直接問接法，或按「拍攝這一步」讓 AI 對照實際接線。Pi 尚未開機也可以先討論。", "Ask about the wiring, or capture this step for AI to inspect it. You can talk before powering on the Pi.") : tr("直接告訴我。我會看目前的鏡頭畫面，對照 Pi 與作品資料，接著一步一步排查。", "Tell me what's happening. I'll inspect the camera image and your project's Pi data, then guide you step by step.")}</p>{missingWiring ? <p className="workflow-muted">{tr("可以先讓 AI 看畫面並引導排查；硬體測試前再完成接線確認。", "AI can inspect the image first; confirm wiring before hardware tests.")}</p> : null}</div> : null}
      {!actionsOnly && messages.map(message => <article key={message.id} className={`ai-debug-message is-${message.role}`} data-message-id={message.id}>
        <div className="ai-debug-message-meta"><strong>{message.role === "user" ? tr("你", "You") : "Tinkro AI"}</strong><time>{epochTime(message.created_at, tr("zh-TW", "en"))}</time>{message.role === "assistant" && message.elapsed_ms != null ? <span>{(message.elapsed_ms / 1000).toFixed(1)} s</span> : null}</div>
        {message.role === 'assistant' ? <AssistantMarkdown text={message.text} /> : <p>{message.text}</p>}
        {message.capture_ids?.length ? <div className="ai-debug-message-photos">{message.capture_ids.map(id => {
          const sourceId = message.session_id ?? message.check_id;
          const photo = [...allEvidence].reverse().find(item => item.id === id && (!sourceId || (item.session_id ?? item.check_id) === sourceId));
          return <PhotoEvidenceCard key={`${sourceId}:${id}`} evidence={photo} sessionId={evidenceSessionId(message, photo, record?.id)} />;
        })}</div> : null}
        {message.diagram_refs?.map((reference, index) => <DiagramEvidenceCard key={`${message.id}:${reference.snapshot_id}:${index}`} reference={reference}
          snapshot={diagrams.find(item => item.id === reference.snapshot_id)} currentDesign={state.design} onDiagram={onDiagram} />)}
        {message.role === "assistant" && message.model ? <small className="ai-debug-message-model">{message.model}</small> : null}
      </article>)}
    {record && !photoReviewInFocus ? <>
      <div className="ai-debug-current">
        <div className="ai-debug-current-title"><span className="workflow-eyebrow">{tr("目前這一步", "Current step")}</span><strong>{record.phase === "backend_restarted" ? tr("重啟後的舊紀錄", "Record after restart") : record.model_busy ? tr("雲端 AI 分析中", "Cloud AI is analyzing") : awaitingReply ? tr("等待你回覆", "Waiting for your reply") : statusName[record.status] ?? record.status}</strong></div>
        {!instructionAlreadyShown && !record.model_busy ? <p>{currentInstruction}</p> : null}
        {record.phase === "backend_restarted" ? <p className="guide-caution" role="status">{tr("此案件僅供檢視，不能接續自動測試。請先在執行管理核對 Pi 工作，停止本次除錯後，使用目前作品重新開始。", "This session is read only and cannot resume automated tests. Check Pi jobs in Execution, stop this session, then start again with the current project.")}</p> : null}
        {record.phase === "wiring_required" && missingWiring ? <button type="button" onClick={() => onWiring(missingWiring)}>{tr("完成 02 接線確認", "Complete wiring confirmation in 02")}</button> : null}
        {record.error && (active || record.status === "error") && record.phase !== "backend_restarted" ? <p className="pi-error" role="alert">{readableError(record.error)}</p> : null}
        {active && ["model_limit", "capture_limit"].includes(record.phase) ? <div className="ai-debug-actions"><span>{tr("本輪已達上限；重新檢查會保留對話與先前證據。", "This check reached its limit. A new check keeps the conversation and earlier evidence.")}</span><button type="button" disabled={!canStart || Boolean(record.model_busy)} onClick={() => void startNewCheck()}>{tr("開始新一輪檢查", "Start a new check")}</button></div> : null}
        {record.model_busy ? <div className="ai-debug-busy" role="status"><p><span className="ai-debug-busy-dot" />{record.model_capture_ids?.length ? tr("正在分析本次拍攝的畫面", "Analyzing the images just captured") : tr("正在閱讀你的訊息與除錯紀錄", "Reviewing your message and debugging history")}{elapsedSeconds != null ? ` · ${elapsedSeconds} ${tr("秒", "s")}` : "…"}</p><small>{elapsedSeconds !== null && elapsedSeconds >= 30 ? tr("這一輪需要較久時間；回覆完成後會直接顯示在對話中。", "This turn is taking longer. The reply will appear here when ready.") : tr("你可以先輸入下一則訊息，等回覆完成後送出。", "You can draft your next message while waiting for the reply.")}</small></div> : null}
        {captureHint ? <p className="ai-debug-capture-hint">{tr("拍攝提示", "Framing tip")}: {captureHint}</p> : null}
        {active && !current ? <p className="guide-caution">{!sameProject ? tr("這台 Pi 正在處理另一個作品的 AI 除錯。請先停止該工作階段，再開始目前作品。", "This Pi has an active AI debug session for another project. Stop that session before starting this project.") : approvedRepairCode ? tr("修復已改變草稿；請在下方確認修改，完成後接回本次試跑。", "The repair changed the draft. Confirm the change below, then resume this trial.") : tr("作品、接線、程式或相機已變更，正在更新檢查內容；先前對話會保留。", "The project, wiring, code, or camera changed. Updating this check while preserving the conversation.")}</p> : null}
        {record.status === "awaiting_capture" && !awaitingReply && !record.model_busy && !wiringMode ? ["guided_observation", "capture_needed"].includes(record.phase)
          ? <div className="ai-debug-actions"><span>{latestObservation ? tr("照上方指示調整後，讓 AI 再看一次。", "Follow the guidance above, then let AI look again.") : tr("依錯誤提示處理後，重新拍照分析。", "Address the error above, then capture and analyze again.")}</span><button type="button" className="guide-primary-action" disabled={!canAct || counting} onClick={() => act("capture")}>{latestObservation ? tr("已調整，讓 AI 再看", "Adjusted, let AI look again") : tr("重新拍照分析", "Capture and analyze again")}</button></div>
          : <div className="ai-debug-actions"><span>{tr("取景到位後會自動拍攝；也可以手動擷取。", "The system captures when framing is ready. You can also capture manually.")}</span><button type="button" disabled={!canAct || counting} onClick={() => act("capture")}>{tr("手動拍照", "Capture now")}</button></div> : null}
        {record.status === "awaiting_ready" ? <button type="button" className="guide-primary-action" disabled={!canAct} onClick={() => act("ready")}>{tr("準備好了，取得新讀值", "Ready, take fresh readings")}</button> : null}
        {operationCard ? <div className="ai-debug-operation">{operationCard}</div> : null}
        {record.status === "awaiting_visual" ? <div className="ai-debug-actions">{!operationCard ? <button type="button" onClick={() => onRetest("mrd-tf240-8p-cs", [...(record.test_results ?? [])].reverse().find(run => run.component_id === "mrd-tf240-8p-cs" && !run.invalidated)?.id)}>{tr("前往螢幕目視確認", "Review the physical screen")}</button> : null}<button type="button" disabled={!canAct} onClick={() => act("continue")}>{tr("完成確認後繼續", "Continue after confirmation")}</button></div> : null}
        {record.status === "awaiting_repair" ? <div className="ai-debug-actions">{!operationCard ? <button type="button" disabled={!record.diagnosis?.case_id || repairCaseId !== record.diagnosis.case_id || record.phase !== "repair_ready"} onClick={onReviewRepair}>{tr("查看診斷與修復提案", "Review diagnosis and repair")}</button> : null}{record.phase === "repair_ready" && !(repairCandidateReady && repairCaseId === record.diagnosis?.case_id) && !approvedRepairCode && (record.budget?.model_calls ?? 0) < (record.budget?.max_model_calls ?? 6) ? <button type="button" disabled={!canAct} onClick={() => act("analyse")}>{tr("請 AI 分析程式邏輯", "Ask AI to review code logic")}</button> : null}{approvedRepairCode ? <button type="button" className="guide-primary-action" disabled={!canResumeRepair} onClick={() => act("continue")}>{tr("修復已確認，接回試跑", "Repair confirmed, resume trial")}</button> : null}</div> : null}
        {record.status === "awaiting_trial_visual" ? <div className="ai-debug-actions">{!operationCard ? <button type="button" onClick={() => onTrial(record.trial_result?.id)}>{tr("前往 60 秒試跑結果", "Review the 60-second trial")}</button> : null}<button type="button" disabled={!canAct} onClick={() => act("continue")}>{tr("完成目視確認後繼續", "Continue after visual confirmation")}</button></div> : null}
        {record.purpose === "wiring_review" && active && !reviewExpanded ? <button type="button" disabled={!canMessage || !webcamReady || counting} onClick={() => void startDebug()}>{tr("開始功能除錯", "Start functional debugging")}</button> : null}
        {record.status === "paused" && !["context_changed", "camera_changed", "backend_restarted"].includes(record.phase) && !(record.phase === "wiring_required" && missingWiring) && current && webcamReady ? <button type="button" disabled={session.pending || counting} onClick={() => act("continue")}>{tr("重新檢查後繼續", "Recheck and continue")}</button> : null}
      </div>
    </> : null}
    </div>
    </div>
    {!actionsOnly && chat.unread ? <button type="button" className="ai-debug-latest" onClick={chat.showLatest}>{tr("查看最新回覆 ↓", "View latest reply ↓")}</button> : null}
    {!actionsOnly ? <div className="ai-debug-entry ai-debug-composer">
      {!active && !wiringMode ? <div className="ai-debug-quick" role="group" aria-label={tr("常見現象", "Common symptoms")}>
        {(["distance", "display", "program"] as const).map(value => <button key={value} type="button" aria-pressed={kind === value} onClick={() => selectKind(value)}>{value === "distance" ? tr("測不到距離", "No distance reading") : value === "display" ? tr("螢幕異常", "Screen issue") : tr("作品沒反應", "Not responding")}</button>)}
      </div> : null}
      <label htmlFor="ai-debug-message">{awaitingReply ? tr("回覆 AI 的問題", "Answer AI's question") : tr("傳訊息給 AI", "Message AI")}</label>
      {wiringMode && targetWire ? <small className="ai-debug-wiring-target">{tr("目前這一步", "Current step")}: {targetWire.componentPin} → {targetWire.boardLabel}</small> : null}
      {wiringPresets.length ? <div className="ai-debug-quick ai-debug-wiring-presets" role="group" aria-label={tr("常見接法問題", "Common wiring questions")}>
        {wiringPresets.map(question => <button key={question.label} type="button" title={question.text} disabled={session.pending} onClick={() => fillWiringQuestion(question.text)}>{question.label}</button>)}
      </div> : null}
      <div className="ai-debug-compose-row">
        <textarea ref={composerRef} id="ai-debug-message" value={entry} onChange={event => setEntry(event.target.value)} onKeyDown={onComposerKeyDown} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} rows={1} placeholder={wiringMode ? tr("問這一步的接法，或說明你看到的情況…", "Ask about this connection, or describe what you see…") : active ? tr("直接回覆，或說明你剛才做了什麼…", "Reply, or describe what you just tried…") : tr("例如：螢幕亮著，但沒有顯示距離", "For example: the screen is on, but no distance appears")} />
        <div className="ai-debug-composer-send"><button type="button" className="guide-primary-action" disabled={Boolean(counting || record?.model_busy || (active ? !canMessage || !entry.trim() : !canStart || (wiringMode && !entry.trim())))} onClick={() => void send()}>{session.pending ? tr("傳送中…", "Sending…") : active || wiringMode ? tr("送出", "Send") : tr("幫我檢查", "Check for me")}</button></div>
      </div>
      <div className="ai-debug-composer-toolbar"><label className="ai-debug-response-mode"><span>{tr("回覆方式", "Response style")}</span><select value={responseMode} disabled={Boolean(counting || record?.model_busy || session.pending)} onChange={event => setResponseMode(event.target.value as DebugResponseMode)}><option value="fast">{tr("快速引導", "Quick guidance")}</option><option value="thorough">{tr("深入分析", "Detailed analysis")}</option></select></label>{wiringMode ? <button type="button" disabled={!canCaptureWiring || counting} onClick={() => void captureStep()}>{tr("拍攝這一步", "Capture this step")}</button> : record?.status === "awaiting_capture" && awaitingReply && !record.model_busy ? <button type="button" disabled={!canAct || counting} onClick={() => act("capture")}>{tr("拍目前畫面", "Capture current view")}</button> : null}</div>
      <small className="ai-debug-composer-hint">{tr("Enter 傳送 · Shift + Enter 換行", "Enter to send · Shift + Enter for a new line")}</small>
      {session.error ? <p className="pi-error" role="alert">{readableError(session.error)}</p> : null}
    </div> : session.error ? <p className="pi-error" role="alert">{readableError(session.error)}</p> : null}
    </div>
    <div id="ai-debug-records" className="debug-tool-view ai-debug-records" hidden={!recordsOpen} role="region" aria-labelledby="ai-debug-records-heading" onKeyDown={event => {if (event.key === "Escape" && !event.defaultPrevented) {event.stopPropagation();setRecordsOpen(false);}}}>
    <div className="debug-tool-heading"><h4 id="ai-debug-records-heading" ref={recordsHeading} tabIndex={-1}>{tr("照片使用與檢查紀錄", "Photo use and inspection records")}</h4><button type="button" className="workflow-secondary" onClick={() => setRecordsOpen(false)}>{tr("返回對話", "Back to chat")}</button></div>
    <p className="ai-debug-disclosure">{tr("開始後，本次選取的 Webcam 照片與遮蔽密碼、金鑰後的診斷資料會送給上方選擇的 Codex 模型分析。文字回覆沿用本次對話；需要新畫面時，才重新拍照。", "After you start, selected Webcam photos and diagnostics with passwords and keys redacted are sent to the Codex model selected above. Text replies use this conversation; a new photo is captured when needed.")}</p>
    {record ? <>
      <div className="ai-debug-evidence-levels" aria-label={tr("證據層級", "Evidence levels")}>
        <span>{tr("AI 看圖", "AI camera view")}: {cameraVerdict ?? (latestVisualObservation?.visibility === "clear" ? tr("畫面可讀", "Readable") : latestVisualObservation ? tr("尚不確定", "Uncertain") : tr("尚未觀察", "Not observed"))}</span>
        <span>{tr("零件功能", "Component function")}: {componentOutcome}</span>
        <span>{tr("整體作品", "Whole project")}: {wholeOutcome}</span>
      </div>
      {cameraVerdict ? <p className="ai-debug-camera-verdict">{cameraVerdict} · {tr("相機觀察仍需正式測試與人工目視確認。", "Camera observations still need fixed tests and human visual confirmation.")}</p> : null}
      {record.report ? <section className="ai-debug-report"><h4>{tr("本次結果", "Session result")}</h4>
        {record.report.confirmed?.length ? <><strong>{tr("已確認", "Confirmed")}</strong><ul>{record.report.confirmed.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
        {record.report.uncertain?.length ? <><strong>{tr("仍不確定", "Still uncertain")}</strong><ul>{record.report.uncertain.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
        {record.report.next_step && !sameInstruction(record.report.next_step, currentInstruction) && !messages.some(message => normalize(message.text).includes(normalize(record.report!.next_step))) ? <p>{record.report.next_step}</p> : null}</section> : null}
      <details className="ai-debug-timeline"><summary>{tr("照片、測試與工作紀錄", "Photos, tests, and activity")} ({(record.evidence?.length ?? 0) + (record.jobs?.length ?? 0)})</summary>
        <ol>{[...(record.evidence ?? [])].reverse().map(item => <li key={item.id}>{item.available === false ? <span>{item.target} · frame {item.frame_id} · {tr("照片已過期", "Photo expired")}</span> : <a href={frameUrl(record.id, item.id)} target="_blank" rel="noreferrer">{item.target} · frame {item.frame_id}</a>} <time>{epochTime(item.captured_at, tr("zh-TW", "en"))}</time> {item.phase ?? ""}</li>)}</ol>
        <ul>{(record.jobs ?? []).map(job => <li key={job.id}>{job.component_id ?? job.kind} · {job.state}{job.error ? ` · ${job.error}` : ""}</li>)}</ul>
        {record.budget ? <small>{tr("AI 呼叫", "AI calls")} {record.budget.model_calls}/{record.budget.max_model_calls} · {tr("照片", "Photos")} {record.budget.captures}/{record.budget.max_captures}</small> : null}
      </details>
    </> : null}
    </div>
  </section>;
}
