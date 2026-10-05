import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CameraPicker } from "./components/CameraPicker";
import { GlassesControls } from "./components/GlassesControls";
import { useGlassesStream } from "./lib/useGlassesStream";
import { CapabilityCard } from "./components/CapabilityCard";
import { PiDeployPanel } from "./components/PiDeployPanel";
import { DebugPage } from "./components/DebugPage";
import { AiDebugPanel } from "./components/AiDebugPanel";
import { PiConnectionControl } from "./components/PiConnectionControl";
import { WiringGuidePanel } from "./components/WiringGuidePanel";
import { RuntimeToolbar } from "./components/RuntimeToolbar";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import { WorkflowResetControl } from "./components/WorkflowResetControl";
import { DeviceConnectionGroups } from "./components/DeviceConnectionGroups";
import { HeaderPanelProvider } from "./lib/headerPanels";
import { StatusBar } from "./components/StatusBar";
import { VideoView, type LegendInfo } from "./components/VideoView";
import {
  fetchBoardProfile,
  fetchConfig,
  fetchControllers,
  postSelectController,
} from "./lib/api";
import {
  FILTER_COLOR_VAR,
  pinDisplayNameWithNumber,
  pinIdsForFilter,
  type FilterId,
} from "./lib/capabilities";
import {
  isDisplayOnlyMode,
  isOpticalHudMode,
  type DisplayMode,
} from "./lib/displayMode";
import { useI18n } from "./lib/i18n";
import { piHeaderGuideText } from "./lib/piHeaderGuide";
import type { OpticalHudCalibration } from "./lib/opticalHud";
import type {
  AppConfig,
  BoardProfile,
  ControllerSummary,
  Locale,
  Pin,
} from "./lib/types";
import type { ActiveGuideTarget } from "./lib/componentWiringGuides";
import { wsClient } from "./lib/wsClient";
import { DesignStudio } from "./components/DesignStudio";
import { BlueprintPage } from "./components/BlueprintPage";
import { UnifiedAssistant, DemoWorkspace } from "./components/UnifiedAssistant";
import { AssistantWorkspace } from "./components/AssistantWorkspace";
import { useAssistant, type AssistantMessage, type AssistantWiringFlowResult } from "./lib/assistant";
import { MakerModelMenu } from "./components/MakerModelMenu";
import { useMakerAI } from "./lib/useMakerAI";
import { useDebugSession } from "./lib/debugSessions";
import { ProjectGuidePanel } from "./components/ProjectGuidePanel";
import { GuidePaneLayout } from "./components/GuidePaneLayout";
import { WiringWorkspace } from "./components/WiringWorkspace";
import { StepDiagramView } from "./components/StepDiagramView";
import { ImageViewControls } from './components/ImageViewControls';
import './floatingGuide.css';
import { DiagramInspectionView } from "./components/DiagramInspectionView";
import { GpioPhotoWorkspace } from "./components/GpioPhotoWorkspace";
import { GpioCaptureAction } from "./components/GpioCaptureAction";
import { useGpioPhotoCapture } from "./lib/useGpioPhotoCapture";
import { photoGuidanceTarget, photoRecordMismatch, type GpioPhotoRecord, type GpioView } from "./lib/gpioPhotoWorkspace";
import type { MobileCapture, MobileContext, MobileSession } from "./lib/mobile";
import { useLiveCamera } from "./lib/useLiveCamera";
import { createDiagramInspection, inspectDiagramInMaker, type DiagramInspection } from "./lib/debugEvidence";
import { confirmConcept, currentWire, enterDebug, makerRequest, reviewProjectWire, wireSignature, type MakerStage, type ProjectGuideState } from "./lib/maker";
import type { DebugSession } from "./lib/debugSessions";
import { prepareProjectWiringEdit } from "./lib/wiringEdit";
import { componentTestHelpInvitation, componentTestHelpRequest, currentTestHelpInvitation, testHelpSourceIdentity, type ComponentTestHelpEvidence, type TestHelpInvitation } from "./lib/componentTestHelp";
import { componentTestKey } from "./lib/componentTests";
import { componentTestStore } from "./lib/componentTestStore";
import type { DebugContext } from "./lib/debug";
import type { WiringReviewAction } from "./lib/wiringReview";
import { confirmReviewedWire, unconfirmReviewedWire, invalidateReviewedComponent, contextWithReviewGuide } from "./lib/wiringReviewGuide";
import { guideFromWiringReceipt } from './lib/wiringReceipt';
import { useMaker, useMakerText } from "./lib/useMaker";
import "./maker.css";

const REST_RETRY_MS = 3000;
const FULLSCREEN_REQUEST_TIMEOUT_MS = 1000;
const GUIDE_VISIBILITY_STORAGE_KEY = "boardvision.wiring-guide-visible.v1";
const NO_TEST_HELP_STORE = { subscribe: (_listener: () => void) => () => {}, getSnapshot: () => null };

function initialGuideVisibility(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(GUIDE_VISIBILITY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export default function App() {
  const { t, tx, setLocale, applyDefaultLocale, locale } = useI18n();
  const { state: maker, setState: setMaker, saved: makerSaved } = useMaker();
  const makerAI = useMakerAI(maker, setMaker);
  const tr = useMakerText();
  const videoStageRef = useRef<HTMLDivElement | null>(null);
  const fullscreenRequestPendingRef = useRef(false);
  const fullscreenEnteredRef = useRef(false);
  const fullscreenAttemptIdRef = useRef(0);
  const fullscreenFallbackTimerRef = useRef<number | null>(null);

  const [config, setConfig] = useState<AppConfig | null>(null);
  const liveCamera = useLiveCamera(config, setConfig);
  const [profile, setProfile] = useState<BoardProfile | null>(null);
  const [controllers, setControllers] = useState<ControllerSummary[]>([]);
  const [controllerSwitching, setControllerSwitching] = useState(false);
  const [controllerError, setControllerError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [filter, setFilter] = useState<FilterId>("all");
  const [selectedPinId, setSelectedPinId] = useState<string | null>(null);
  const [guideTarget, setGuideTarget] = useState<ActiveGuideTarget | null>(null);
  const guidePinId = guideTarget?.boardPinId ?? null;
  const [guideVisible, setGuideVisible] = useState(initialGuideVisibility);
  const guideToggleRef = useRef<HTMLButtonElement>(null);
  const guideToggleFocusPending = useRef(false);
  useEffect(() => {
    if (!guideToggleFocusPending.current) return;
    guideToggleRef.current?.focus({ preventScroll: true });
    guideToggleFocusPending.current = false;
  }, [guideVisible]);
  const [calibrateOpen, setCalibrateOpen] = useState(false);
  const [cameraPickerOpen, setCameraPickerOpen] = useState(false);
  const [diagramCaptureOverride, setDiagramCaptureOverride] = useState<string | null>(null);
  const [evidenceDiagram, setEvidenceDiagram] = useState<(DiagramInspection & { requestId: number }) | null>(null);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("standard");
  const glasses = useGlassesStream();
  // Subscribe only to runtime identity, not each camera/detection frame. Webcam
  // changes also advance the runtime; the Eye status alone may remain behind.
  const liveRuntime = useSyncExternalStore(wsClient.subscribe, () => wsClient.getSnapshot().runtime);
  const [glassesDisplayFps, setGlassesDisplayFps] = useState<number | null>(0);
  const glassesSessionRef = useRef(false);
  const [opticalHudCalibration, setOpticalHudCalibration] =
    useState<OpticalHudCalibration | null>(null);
  const [fullscreenFallback, setFullscreenFallback] = useState(false);
  const [imageView, setImageView] = useState<GpioView>('webcam');
  const [gpioPhotos, setGpioPhotos] = useState<GpioPhotoRecord[]>([]);
  const [selectedPhoto, setSelectedPhoto] = useState('');
  const displayModeActive = isDisplayOnlyMode(displayMode);
  const opticalHudActive = isOpticalHudMode(displayMode);
  const displayModeDisabled = backendDown || config === null;
  const opticalHudDisabled = displayModeDisabled || profile === null;
  const makerEnabled = config?.board_id === "raspberry-pi-5";
  const makerStage = displayModeActive ? "guide" : makerEnabled ? maker.stage : "guide";
  const assistantIntent = maker.debug?.intent ?? (makerStage === "deploy" ? "debug" : "wiring");
  const aiDebug = useDebugSession(maker.design?.id ?? null, makerEnabled && Boolean(maker.design));
  const assistant = useAssistant(maker, setMaker, aiDebug.conversation, aiDebug.record, makerAI.aiOptions.selectedModel?.id);
  const wiringFlowFlight = useRef(false);
  const [testHelpOffer, setTestHelpOffer] = useState<{ conversationId: string; invitation: TestHelpInvitation; sourceIdentity: string; code: string } | null>(null);
  const [testHelpMessageTarget, setTestHelpMessageTarget] = useState<{ invitationId: string; element: HTMLDivElement } | null>(null);
  const [testHelpActionId, setTestHelpActionId] = useState<string | null>(null);
  // Share the existing test store only while an invitation is pending; no second polling pipeline.
  const helpTestStore = testHelpOffer && maker.design?.id === testHelpOffer.invitation.projectId
    ? componentTestStore(maker.design.id) : NO_TEST_HELP_STORE;
  const helpTestSnapshot = useSyncExternalStore(helpTestStore.subscribe, helpTestStore.getSnapshot, helpTestStore.getSnapshot);
  const testHelpScope = useRef({ maker, conversationId: assistant.mobileContext.conversation_id, epoch: assistant.project?.context_epoch ?? 0 });
  testHelpScope.current = { maker, conversationId: assistant.mobileContext.conversation_id, epoch: assistant.project?.context_epoch ?? 0 };
  const sharedWiringPrompt = [...(assistant.project?.messages ?? [])].reverse().find(message => message.role === 'assistant'
    && message.wiring_flow?.current && !message.archived && message.epoch === assistant.project?.context_epoch);
  // A phone may have started this same flow. Restore its trusted server link without starting another check.
  useEffect(() => {
    const sid = sharedWiringPrompt?.session_id, flow = sharedWiringPrompt?.wiring_flow;
    if (!sid || !flow || assistant.demoOpen || aiDebug.pending || aiDebug.record?.id === sid || !maker.design) return;
    const snapshot = testHelpScope.current, controller = new AbortController();
    void makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(sid)}`, undefined, controller.signal).then(next => {
      const latest = testHelpScope.current;
      if (!controller.signal.aborted && latest.conversationId === snapshot.conversationId && latest.epoch === snapshot.epoch
        && latest.maker.design === snapshot.maker.design && latest.maker.code === snapshot.maker.code
        && latest.maker.guide === snapshot.maker.guide && next.wiring_review?.id === flow.review_id
        && next.wiring_review.round === flow.round) aiDebug.adoptReview(next);
    }).catch(() => {});
    return () => controller.abort();
  }, [sharedWiringPrompt?.session_id, sharedWiringPrompt?.wiring_flow?.flow_id, assistant.project?.context_epoch,
    assistant.demoOpen, aiDebug.record?.id, aiDebug.pending, maker.design, maker.code, maker.guide]);
  useEffect(() => {
    if (assistant.wiringReceiptPending && !assistant.pending && !aiDebug.pending) void recoverWiringDecision(false);
  }, [assistant.wiringReceiptRequestId, assistant.wiringReceiptPending, assistant.pending, aiDebug.pending]);
  const sharedTestHelp = assistant.project?.messages.find(message => message.id === testHelpOffer?.invitation.messageId)?.test_help_offer;
  const testHelpOfferCurrent = Boolean(testHelpOffer && testHelpOffer.conversationId === assistant.mobileContext.conversation_id
    && sharedTestHelp?.offer_id === testHelpOffer.invitation.id
    && (sharedTestHelp.state === "pending" || testHelpActionId === testHelpOffer.invitation.id && ["started", "dismissed"].includes(sharedTestHelp.state))
    && currentTestHelpInvitation(testHelpOffer.invitation, maker.design, maker.guide, assistant.project?.context_epoch ?? 0)
    && testHelpOffer.code === maker.code && maker.design && helpTestSnapshot && testHelpOffer.sourceIdentity
      === testHelpSourceIdentity(helpTestSnapshot, maker.design, maker.guide, testHelpOffer.invitation.componentId));
  const testHelpInvitation = testHelpOfferCurrent && !helpTestSnapshot?.pending && !assistant.demoOpen
    && (sharedTestHelp?.can_act || sharedTestHelp?.can_dismiss || testHelpOffer?.invitation.mode === "setup" || testHelpActionId === testHelpOffer?.invitation.id)
    && makerStage !== "design" && !displayModeActive ? testHelpOffer && {
      ...testHelpOffer.invitation, canAct: sharedTestHelp?.can_act, canDismiss: sharedTestHelp?.can_dismiss,
    } : undefined;
  useEffect(() => {
    if (testHelpOffer && !testHelpOfferCurrent && !helpTestSnapshot?.pending) {
      setTestHelpOffer(previous => previous?.invitation.id === testHelpOffer.invitation.id ? null : previous);
      setTestHelpActionId(previous => previous === testHelpOffer.invitation.id ? null : previous);
    }
  }, [testHelpOffer, testHelpOfferCurrent, helpTestSnapshot?.pending]);
  const [aiOpen, setAiOpen] = useState(true);
  const [aiOpenRequest, setAiOpenRequest] = useState(0);
  const [mobileTriggerHost, setMobileTriggerHost] = useState<HTMLDivElement | null>(null);
  const [mobileControlsHost, setMobileControlsHost] = useState<HTMLDivElement | null>(null);
  const [cameraSettingsHost, setCameraSettingsHost] = useState<HTMLDivElement | null>(null);
  const [deploymentPreviewHost, setDeploymentPreviewHost] = useState<HTMLDivElement | null>(null);
  const [workflowResetPending, setWorkflowResetPending] = useState(false);
  const [workflowResetError, setWorkflowResetError] = useState("");
  const workflowResetFlight = useRef(false);
  const phoneSourceSelected = config?.camera_source === 'phone' && imageView === 'phone'
    && (makerStage === 'guide' || makerStage === 'deploy') && !displayModeActive && !assistant.demoOpen;
  const phoneMainActive = imageView === 'phone' && makerStage === "guide" && !displayModeActive && !assistant.demoOpen;
  const photoMainActive = imageView === 'photo' && makerStage === "guide" && !displayModeActive && !assistant.demoOpen;
  const lastLiveView = useRef<'webcam' | 'phone'>('webcam');
  const changeImageView = useCallback((view: GpioView) => {
    setImageView(view);
    if (view !== 'photo') lastLiveView.current = view;
    setEvidenceDiagram(null); setDiagramCaptureOverride(null);
    setMaker(s => s.guide.mode === "camera" ? s : ({...s, guide: {...s.guide, mode: "camera"}}));
  }, [setMaker]);
  const liveViewIntent = useRef(0);
  const selectLiveView = useCallback(async (view: 'phone' | 'webcam', session?: MobileSession | null, isCurrent: () => boolean = () => true): Promise<boolean> => {
    if (!canShowPhoto.current) return false;
    const intent = ++liveViewIntent.current;
    if (!isCurrent() || !await liveCamera.select(view, session) || intent !== liveViewIntent.current || !isCurrent()) return false;
    changeImageView(view);
    return true;
  }, [liveCamera.select, changeImageView]);
  const changePhonePreview = useCallback((show: boolean, session?: MobileSession | null, isCurrent?: () => boolean): Promise<boolean> => {
    return selectLiveView(show ? 'phone' : 'webcam', session, isCurrent);
  }, [selectLiveView]);
  useEffect(() => {
    const view = config?.camera_source === 'phone' ? 'phone' : 'webcam';
    lastLiveView.current = view;
    setImageView(current => current === 'photo' ? current : view);
  }, [config?.camera_source, assistant.mobileContext?.conversation_id, assistant.demoOpen]);
  const openAssistant = () => { setAiOpen(true); setAiOpenRequest(value => value + 1); };
  const debugCaptureSession = makerStage === "guide" && aiDebug.record?.status === "awaiting_capture" &&
    !["awaiting_user", "context_changed", "camera_changed", "backend_restarted"].includes(aiDebug.record.phase) &&
    aiDebug.record.current_target !== false && aiDebug.record.camera_current !== false ? aiDebug.record : null;
  const eyeActive = Boolean(glasses.status?.active || config?.camera_source === "xreal" ||
    ["restoring", "stopping", "switching"].includes(glasses.status?.state ?? ""));
  const phoneReady = config?.camera_source === 'phone' && liveCamera.status?.kind === 'phone' && liveCamera.status.ready && !liveCamera.status.error;
  const project = makerEnabled && !maker.standalone ? maker.design : null;
  const activeGpioPhoto = gpioPhotos.find(p => `${p.source}:${p.capture.capture_id}` === selectedPhoto) ?? null;
  const photoMismatch = activeGpioPhoto ? photoRecordMismatch(activeGpioPhoto, project, maker.guide.run ?? 0) : null;
  const cameraAvailable = !calibrateOpen && !debugCaptureSession && !aiDebug.record?.model_busy && !eyeActive && !liveCamera.pending && !cameraPickerOpen;
  const canShowPhoto = useRef(false);
  const keepGpioPhoto = useCallback((record: GpioPhotoRecord, show: boolean) => {
    const key = `${record.source}:${record.capture.capture_id}`;
    setGpioPhotos(previous => [...previous.filter(p => `${p.source}:${p.capture.capture_id}` !== key), record].slice(-20));
    if (show) { setSelectedPhoto(key); changeImageView('photo'); }
    else setSelectedPhoto(previous => previous || key);
  }, [changeImageView]);
  const receiveMobilePhoto = useCallback((capture: MobileCapture, show: boolean, context: MobileContext | null) => {
    const saved = context?.context;
    keepGpioPhoto({ source: 'phone', capture, projectId: saved?.workspace_project_id ?? '',
      revision: saved?.project_version ?? 0, round: context?.round ?? -1 }, show && canShowPhoto.current);
  }, [keepGpioPhoto]);
  const captureSource = config?.camera_source === 'phone' ? 'phone' : 'webcam';
  const captureDisabledReason = !project ? tr('先確認作品，再擷取接線照片', 'Confirm a project before capturing')
    : backendDown ? tr('相機服務未連線', 'Camera service is offline')
    : !cameraAvailable ? tr('請先完成目前相機操作', 'Finish the current camera operation')
    : !liveCamera.status?.ready || liveCamera.status.error || liveCamera.status.kind !== captureSource
      || liveCamera.status.runtime_revision !== config?.runtime_revision ? tr('等待即時影像', 'Waiting for live video') : '';
  const gpioCapture = useGpioPhotoCapture({ project, round: maker.guide.run ?? 0,
    source: { kind: captureSource, runtimeRevision: config?.runtime_revision ?? -1 },
    active: makerStage === 'guide' && !displayModeActive && !assistant.demoOpen,
    allowed: !captureDisabledReason }, keepGpioPhoto);
  const photoOperationBusy = gpioCapture.busy || gpioCapture.needsResume;
  const workflowOperationBusy = makerAI.busy || assistant.busy || photoOperationBusy || liveCamera.pending || aiDebug.pending
    || Boolean(testHelpActionId) || calibrateOpen || cameraPickerOpen || controllerSwitching || glasses.pending
    || Boolean(assistant.project?.jobs.some(job => job.status === "running") || assistant.demo?.jobs.some(job => job.status === "running"));
  const canChangeImage = cameraAvailable && !photoOperationBusy;
  canShowPhoto.current = canChangeImage;
  const debugWebcamReady = (config?.camera_source === 'device' || phoneReady) && !eyeActive && !backendDown
    && !photoMainActive && !liveCamera.pending && !photoOperationBusy;
  const gpioCaptureAction = <GpioCaptureAction source={captureSource} busy={gpioCapture.busy} needsResume={gpioCapture.needsResume}
    error={gpioCapture.error} disabledReason={captureDisabledReason} retake={photoMainActive && !!activeGpioPhoto}
    onCapture={() => void gpioCapture.capture()} onResume={() => void gpioCapture.resume()} />;
  // A fresh Maker project is not the legacy standalone board workspace.
  const emptyProjectGuide = makerEnabled && !maker.standalone && !project && makerStage === "guide" && !displayModeActive;
  const fullWidthWiring = (Boolean(project) || emptyProjectGuide) && makerStage === "guide";
  // A requested photo temporarily reveals the shared camera without changing
  // the user's 2D guide preference or confirmation progress.
  const projectWire = project ? currentWire(project, maker.guide) : undefined;
  const diagramInspection = evidenceDiagram && project && evidenceDiagram.snapshot.project_id === project.id ? evidenceDiagram : null;
  const diagramCaptureKey = debugCaptureSession ? `${debugCaptureSession.id}:${debugCaptureSession.capture_task?.id ??
    `${debugCaptureSession.phase}:${debugCaptureSession.capture_task?.target}:${debugCaptureSession.capture_task?.attempt ?? debugCaptureSession.capture_task?.attempts ?? 0}:${debugCaptureSession.evidence?.at(-1)?.id ?? ""}`}` : null;
  const showWiringDiagram = Boolean(projectWire || diagramInspection) && makerStage === "guide" && maker.guide.mode === "2d" && !displayModeActive &&
    !calibrateOpen && (!debugCaptureSession || diagramCaptureOverride === diagramCaptureKey);
  const navigateMaker = (stage: MakerStage) => {
    setGuideTarget(null);
    setMaker(s => ({ ...s, stage, standalone: false }));
    if (stage === "guide") setGuideVisible(true);
  };
  const openDebug = (componentId?: string, runId?: string, symptom?: string) => {
    openAssistant();
    setGuideTarget(null);
    setGuideVisible(true);
    setMaker(s => ({ ...enterDebug(s, componentId, runId, symptom), stage: s.stage === "deploy" ? "deploy" : "guide" }));
  };
  async function askComponentTestAI(componentId?: string, runId?: string, symptom?: string, evidence?: ComponentTestHelpEvidence) {
    // A failed preflight may have neither a run ID nor a classified reason.
    // An explicit help request still replaces the previous issue's binding.
    const helpComponent = evidence?.componentId ?? componentId;
    const helpRun = evidence ? evidence.run?.id : runId;
    const helpSymptom = evidence ? evidence.reason ?? symptom ?? "test_failed" : symptom;
    openDebug(helpComponent, helpRun, helpSymptom);
    if (!evidence || !maker.design) return true;
    if (assistant.busy) {
      assistant.reportError(tr("對話正在處理其他訊息，請稍後再按「請 AI 幫忙」。", "The conversation is handling another message. Retry Ask AI for help shortly."));
      return false;
    }
    try {
      const snapshot = enterDebug(maker, helpComponent, helpRun, helpSymptom);
      const request = componentTestHelpRequest(maker.design, evidence, tr("zh-TW", "en"));
      const sourceStore = componentTestStore(maker.design.id);
      const sourceIdentity = testHelpSourceIdentity(sourceStore.getSnapshot(), maker.design, snapshot.guide, evidence.componentId);
      const conversationId = assistant.mobileContext.conversation_id;
      const invitation = componentTestHelpInvitation(maker.design, evidence, tr("zh-TW", "en"), {
        id: crypto.randomUUID(), guideKey: componentTestKey(maker.design, snapshot.guide, evidence.componentId),
        guideRun: snapshot.guide.run ?? 0, contextEpoch: assistant.project?.context_epoch ?? 0,
      });
      const accepted = await assistant.offerTestHelp(snapshot, invitation, request.context);
      const latest = testHelpScope.current;
      const latestDesign = latest.maker.design;
      if (accepted && latestDesign && latest.conversationId === conversationId && latestDesign === snapshot.design
        && latest.maker.code === snapshot.code && currentTestHelpInvitation(invitation, latest.maker.design, latest.maker.guide, latest.epoch)
        && !sourceStore.getSnapshot().pending
        && sourceIdentity === testHelpSourceIdentity(sourceStore.getSnapshot(), latestDesign, latest.maker.guide, evidence.componentId)) {
        setTestHelpOffer({ conversationId, invitation: { ...invitation, messageId: accepted }, sourceIdentity, code: snapshot.code });
      }
      return Boolean(accepted);
    } catch (cause) { assistant.reportError(cause); return false; }
  }
  async function handleSharedTestHelp(invitation: TestHelpInvitation, op: "start" | "later") {
    if (!testHelpOfferCurrent || testHelpOffer?.invitation.id !== invitation.id || testHelpActionId) return false;
    setTestHelpActionId(invitation.id);
    try {
      const result = await assistant.testHelpAction(invitation, op);
      const latest = testHelpScope.current;
      if (!result || !currentTestHelpInvitation(invitation, latest.maker.design, latest.maker.guide, latest.epoch)
        || latest.maker.code !== testHelpOffer.code || latest.conversationId !== testHelpOffer.conversationId)
        throw new Error(tr("目前邀請已更新，請查看最新提醒後再試。", "The invitation changed. Review the latest reminder and retry."));
      if (op === "later") return true;
      const next = result.debug_session;
      if (!next || next.wiring_review?.component_id !== invitation.componentId || !aiDebug.adoptReview(next))
        throw new Error(tr("尚未取得目前的照片核對，請再試一次。", "The current photo review is not ready. Retry."));
      return next;
    } catch (cause) {
      setTestHelpActionId(previous => previous === invitation.id ? null : previous);
      throw cause;
    }
  }
  async function handleWiringFlowAction(message: AssistantMessage, action: WiringReviewAction): Promise<boolean> {
    const flow = message.wiring_flow;
    const original = maker;
    const session = aiDebug.record;
    if (wiringFlowFlight.current || assistant.wiringReceiptPending || aiDebug.pending || assistant.busy || !original.design || !session
      || session.model_busy || !flow?.current || !flow.can_act || session.wiring_review?.id !== flow.review_id
      || session.wiring_review.revision !== flow.revision || session.wiring_review.round !== flow.round) return false;
    const unchanged = () => testHelpScope.current.maker.design === original.design
      && testHelpScope.current.maker.code === original.code && testHelpScope.current.maker.guide === original.guide;
    wiringFlowFlight.current = true;
    try {
      let guide = original.guide;
      let context: DebugContext = {
        project: original.design, code: original.code, locale, entry: original.debug ?? {},
        guide_confirmations: guide.confirmed, guide_run: guide.run ?? 0,
        test_keys: Object.fromEntries(original.design.component_ids.map(cid => [cid, componentTestKey(original.design!, guide, cid)])),
        wiring_target: session.wiring_target ?? null,
      };
      const retracting = action.op === 'review' && action.decision !== 'confirmed'
        && Boolean(action.wire_id && guide.confirmed[action.wire_id]);
      if (action.op === 'changed' || retracting || (action.op === 'review' && action.decision === 'needs_change')) {
        const prepared = await aiDebug.action('prepare_wiring', context, undefined, session.response_mode, undefined, session.id);
        if (!prepared?.wiring_edit_ready || !unchanged()) throw new Error(tr('目前尚不能調整接線，請先確認 Pi 工作已停止。', 'Check that Pi work has stopped before changing wiring.'));
      }
      if (action.op === 'changed') guide = invalidateReviewedComponent(original.design, guide, action.component_id);
      else if (action.op === 'review' && action.wire_id) guide = action.decision === 'confirmed'
        ? confirmReviewedWire(original.design, guide, action.wire_id) : unconfirmReviewedWire(original.design, guide, action.wire_id);
      context = contextWithReviewGuide(context, original.design, guide);
      if (!unchanged()) return false;
      const result = await assistant.wiringFlowAction(message, action, context);
      if (!result || !unchanged()) return false;
      if (result.outbox) return applyWiringDecision(result);
      if (!aiDebug.adoptReview(result.debug_session)) throw new Error(tr('照片核對已更新，請查看最新聊天訊息。', 'The photo review changed. Check the latest chat message.'));
      return true;
    } catch (cause) { if (unchanged()) assistant.reportError(cause); return false; }
    finally { wiringFlowFlight.current = false; }
  }
  function applyWiringDecision(result: AssistantWiringFlowResult): boolean {
    const latest = testHelpScope.current;
    if (!result.outbox) return false;
    const guide = guideFromWiringReceipt(latest.maker, result.outbox, result.guide_receipt, result.debug_session, latest.conversationId, latest.epoch);
    if (!guide || !aiDebug.adoptReview(result.debug_session)) return false;
    setMaker(current => {
      const recovered = guideFromWiringReceipt(current, result.outbox!, result.guide_receipt, result.debug_session, latest.conversationId, latest.epoch);
      return recovered ? { ...current, guide: recovered } : current;
    });
    assistant.acknowledgeWiringFlow(result.outbox.request_id);
    return true;
  }
  async function recoverWiringDecision(retryMissing = true): Promise<boolean> {
    const result = await assistant.recoverWiringFlow(retryMissing);
    return Boolean(result && applyWiringDecision(result));
  }
  const inspectWiring = (cid:string, pin?:string, revealGuide = true) => {
    setEvidenceDiagram(null);
    if (revealGuide) setGuideVisible(true);
    setMaker(s => s.design ? ({...s,stage:"guide",guide:reviewProjectWire(s.design,s.guide,cid,pin,s.debug?.panelOpen?"debug":"guide"),
      debug:{...s.debug,panelOpen:false,wireId:s.design.wiring.find(w=>w.componentId===cid&&(!pin||w.componentPin===pin))?.id}}) : s);
  };
  const inspectDiagram = (inspection: DiagramInspection) => {
    if (calibrateOpen || displayModeActive || !createDiagramInspection(inspection.snapshot, inspection.wireId, project)) return;
    setGuideVisible(true);
    setEvidenceDiagram(previous => ({ ...inspection, requestId: (previous?.requestId ?? 0) + 1 }));
    setDiagramCaptureOverride(diagramCaptureKey);
    setMaker(s => inspectDiagramInMaker(s, inspection));
  };
  async function prepareWiringEdit() {
    if (!maker.design) return false;
    return prepareProjectWiringEdit(maker.design.id);
  }
  async function restartWiringConversation(guide: ProjectGuideState) {
    const projectId = maker.design?.id;
    if (!projectId || !await aiDebug.restartConversation()) return false;
    if (!await assistant.archiveWiring(guide.run ?? 0)) return false;
    setEvidenceDiagram(null);
    setDiagramCaptureOverride(null);
    setMaker(s => s.design === maker.design ? ({ ...s, guide, debug: { panelOpen: s.debug?.panelOpen, intent: "wiring" } }) : s);
    return true;
  }
  const adoptDesign = (replaceManual = false) => {
    setGuideTarget(null);
    setMaker(s => confirmConcept(s.design && s.candidate?.source === "demo" ? { ...s,
      candidate: { ...s.candidate, id: s.design.id, revision: s.design.revision + 1 } } : s, replaceManual));
  };
  const startNewProject = async () => {
    if (workflowResetFlight.current) return false;
    if (workflowOperationBusy || wiringFlowFlight.current) {
      setWorkflowResetError(tr("請先完成目前操作，再重新開始；目前工作已保留。", "Finish the current operation before restarting. Your work is kept."));
      return false;
    }
    workflowResetFlight.current = true;
    setWorkflowResetPending(true); setWorkflowResetError("");
    try {
      const nextConversation = await assistant.prepareConversation();
      if (typeof nextConversation?.id !== "string" || !nextConversation.id.trim()) throw new Error("invalid_conversation");
      if (!await makerAI.newProject(nextConversation.id)) return false;
      assistant.activateConversation(nextConversation);
      assistant.setDemoOpen(false);
      setGuideTarget(null); setSelectedPinId(null); setFilter("all");
      setEvidenceDiagram(null); setDiagramCaptureOverride(null);
      setGpioPhotos([]); setSelectedPhoto("");
      // Clear this round's references, not the capture archive or live source.
      setImageView(config?.camera_source === "phone" ? "phone" : "webcam");
      setTestHelpOffer(null); setTestHelpMessageTarget(null); setTestHelpActionId(null);
      return true;
    } catch (error) {
      setWorkflowResetError(tr("無法建立新工作流程，目前工作已保留；請確認後端連線後重試。", "Could not create a new workflow. Your work is kept; check the backend and retry."));
      assistant.reportError(error); return false;
    } finally { workflowResetFlight.current = false; setWorkflowResetPending(false); }
  };

  const handleLocaleChange = useCallback(
    (next: Locale) => {
      setLocale(next);
    },
    [setLocale],
  );

  const handleGuideVisibilityChange = useCallback((visible: boolean) => {
    // The control moves between the panel header and its collapsed entry.
    // Restore focus after the destination control has mounted.
    guideToggleFocusPending.current = document.activeElement === guideToggleRef.current
      || (!visible && Boolean(document.getElementById('maker-floating-guide')?.contains(document.activeElement)));
    setGuideVisible(visible);
    try {
      window.localStorage.setItem(GUIDE_VISIBILITY_STORAGE_KEY, String(visible));
    } catch {
      // Visibility still changes for this session if storage is unavailable.
    }
  }, []);

  const clearFullscreenFallbackTimer = useCallback(() => {
    if (fullscreenFallbackTimerRef.current === null) return;
    window.clearTimeout(fullscreenFallbackTimerRef.current);
    fullscreenFallbackTimerRef.current = null;
  }, []);

  const exitDisplayMode = useCallback(() => {
    if (glassesSessionRef.current) {
      glassesSessionRef.current = false;
      glasses.stop();
    }
    clearFullscreenFallbackTimer();
    fullscreenAttemptIdRef.current += 1;
    fullscreenRequestPendingRef.current = false;
    fullscreenEnteredRef.current = false;
    setDisplayMode("standard");
    setOpticalHudCalibration(null);
    setFullscreenFallback(false);

    const stage = videoStageRef.current;
    if (stage && document.fullscreenElement === stage) {
      void document.exitFullscreen().catch(() => undefined);
    }
  }, [clearFullscreenFallbackTimer, glasses.stop]);

  const enterDisplayMode = useCallback((nextMode: Exclude<DisplayMode, "standard">) => {
    const stage = videoStageRef.current;
    if (!stage || displayModeDisabled) return;

    setCameraPickerOpen(false);
    setCalibrateOpen(false);
    if (nextMode === "optical-hud-calibration") setOpticalHudCalibration(null);
    setDisplayMode(nextMode);
    const windowOnly = nextMode === "smart-glasses-demo";
    setFullscreenFallback(windowOnly);

    const attemptId = fullscreenAttemptIdRef.current + 1;
    fullscreenAttemptIdRef.current = attemptId;
    fullscreenRequestPendingRef.current = !windowOnly;
    fullscreenEnteredRef.current = false;
    clearFullscreenFallbackTimer();

    // Eye stays in the page-sized CSS presentation when the browser or host
    // changes native fullscreen. Its stream ends only through our Exit/Esc.
    if (windowOnly) return;

    if (typeof stage.requestFullscreen !== "function") {
      fullscreenRequestPendingRef.current = false;
      setFullscreenFallback(true);
      return;
    }

    try {
      fullscreenFallbackTimerRef.current = window.setTimeout(() => {
        fullscreenFallbackTimerRef.current = null;
        if (
          fullscreenAttemptIdRef.current === attemptId &&
          document.fullscreenElement !== stage
        ) {
          fullscreenRequestPendingRef.current = false;
          setFullscreenFallback(true);
        }
      }, FULLSCREEN_REQUEST_TIMEOUT_MS);
      void stage
        .requestFullscreen()
        .then(() => {
          clearFullscreenFallbackTimer();
          if (fullscreenAttemptIdRef.current !== attemptId) {
            if (document.fullscreenElement === stage) {
              void document.exitFullscreen().catch(() => undefined);
            }
            return;
          }
          fullscreenRequestPendingRef.current = false;
          // Some embedded Chromium shells resolve the request without exposing
          // a fullscreen element. Treat that as the CSS fallback as well.
          setFullscreenFallback(document.fullscreenElement !== stage);
        })
        .catch(() => {
          clearFullscreenFallbackTimer();
          if (fullscreenAttemptIdRef.current !== attemptId) return;
          fullscreenRequestPendingRef.current = false;
          setFullscreenFallback(true);
        });
    } catch {
      clearFullscreenFallbackTimer();
      fullscreenRequestPendingRef.current = false;
      setFullscreenFallback(true);
    }
  }, [clearFullscreenFallbackTimer, displayModeDisabled]);

  const enterSmartGlassesDemo = useCallback(() => {
    if (displayModeDisabled || glasses.pending) return;
    glassesSessionRef.current = true;
    setGlassesDisplayFps(0);
    enterDisplayMode("smart-glasses-demo");
    glasses.start();
  }, [enterDisplayMode, displayModeDisabled, glasses.pending, glasses.start]);

  // Camera restarts create a new runtime revision; refresh the current pin profile.
  useEffect(() => {
    const revision = Math.max(glasses.status?.runtime_revision ?? 0, liveRuntime?.runtime_revision ?? 0);
    if (!revision || revision === config?.runtime_revision) return;
    let disposed = false;
    let retry = 0;
    async function refresh() {
      try {
        const next = await fetchConfig();
        const nextProfile = await fetchBoardProfile(next.board_id);
        if (disposed) return;
        wsClient.prepareRuntime(next.board_id, next.runtime_revision);
        setConfig(next);
        setProfile(nextProfile);
      } catch {
        if (!disposed) retry = window.setTimeout(refresh, 1000);
      }
    }
    void refresh();
    return () => { disposed = true; window.clearTimeout(retry); };
  }, [glasses.status?.runtime_revision, liveRuntime?.runtime_revision, config?.runtime_revision]);

  const enterOpticalHud = useCallback(() => {
    enterDisplayMode("optical-hud-calibration");
  }, [enterDisplayMode]);

  const handleOpticalHudCalibrationComplete = useCallback(
    (calibration: OpticalHudCalibration) => {
      setOpticalHudCalibration(calibration);
      setDisplayMode("optical-hud-demo");
    },
    [],
  );

  const recalibrateOpticalHud = useCallback(() => {
    setOpticalHudCalibration(null);
    setDisplayMode("optical-hud-calibration");
  }, []);

  useEffect(() => () => clearFullscreenFallbackTimer(), [clearFullscreenFallbackTimer]);

  // Bootstrap: config -> board profile. Retries while the backend is down.
  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const load = async () => {
      try {
        const configPromise = fetchConfig();
        const controllersPromise = fetchControllers();
        const loadedConfig = await configPromise;
        if (cancelled) return;
        const [loadedProfile, loadedControllers] = await Promise.all([
          fetchBoardProfile(loadedConfig.board_id),
          controllersPromise,
        ]);
        if (cancelled) return;
        setConfig(loadedConfig);
        setProfile(loadedProfile);
        setControllers(loadedControllers.controllers);
        setBackendDown(false);
        applyDefaultLocale(loadedConfig.default_locale);
      } catch {
        if (cancelled) return;
        setBackendDown(true);
        timer = window.setTimeout(() => {
          void load();
        }, REST_RETRY_MS);
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [applyDefaultLocale]);

  // Native fullscreen exits still restore HUD presentations. Eye deliberately
  // uses CSS fullscreen, independently of browser/host fullscreen changes.
  useEffect(() => {
    const onFullscreenChange = () => {
      if (!displayModeActive || displayMode === "smart-glasses-demo") return;
      if (document.fullscreenElement === videoStageRef.current) {
        clearFullscreenFallbackTimer();
        fullscreenRequestPendingRef.current = false;
        fullscreenEnteredRef.current = true;
        setFullscreenFallback(false);
        return;
      }
      if (fullscreenEnteredRef.current) {
        exitDisplayMode();
        return;
      }
      if (!fullscreenRequestPendingRef.current && !fullscreenFallback) {
        exitDisplayMode();
      }
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [
    clearFullscreenFallbackTimer,
    exitDisplayMode,
    fullscreenFallback,
    displayModeActive,
    displayMode,
  ]);

  // Esc leaves the display-only mode first, then closes whichever admin panel
  // is open (calibrate takes precedence
  // over the camera picker — they're never both open at once in practice,
  // but this keeps the precedence explicit), otherwise deselects the pin.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (displayModeActive) {
        event.preventDefault();
        exitDisplayMode();
      } else if (calibrateOpen) {
        setCalibrateOpen(false);
      } else if (cameraPickerOpen) {
        setCameraPickerOpen(false);
      } else if (guideVisible) {
        handleGuideVisibilityChange(false);
      } else {
        setSelectedPinId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    calibrateOpen,
    cameraPickerOpen,
    exitDisplayMode,
    guideVisible,
    handleGuideVisibilityChange,
    displayModeActive,
  ]);

  const pinsById = useMemo(() => {
    const map = new Map<string, Pin>();
    for (const pin of profile?.pins ?? []) map.set(pin.id, pin);
    return map;
  }, [profile]);

  const availablePinIds = useMemo(
    () => new Set(pinsById.keys()),
    [pinsById],
  );

  const selectedPin = useMemo(
    () => (selectedPinId ? (pinsById.get(selectedPinId) ?? null) : null),
    [pinsById, selectedPinId],
  );

  const guidePinLabel = guidePinId
    ? (piHeaderGuideText(pinsById.get(guidePinId), t)?.title ?? (pinDisplayNameWithNumber(pinsById.get(guidePinId)) || guidePinId))
    : null;

  const filterSet = useMemo(
    () => (profile && filter !== "all" ? pinIdsForFilter(profile, filter) : null),
    [profile, filter],
  );

  const guideSet = useMemo(() => (guidePinId ? new Set([guidePinId]) : null), [guidePinId]);

  // A guided wiring step must leave exactly one target bright.
  const highlightIds = guideSet ?? filterSet;

  const legend: LegendInfo | null =
    guidePinLabel
      ? { colorVar: "--ok", label: t("photoGuide.videoTarget", { pin: guidePinLabel }), count: 1 }
      : filter !== "all" && filterSet
        ? { colorVar: FILTER_COLOR_VAR[filter], label: t(`filter.${filter}`), count: filterSet.size }
        : null;

  const handleSelectPin = useCallback((pinId: string | null) => {
    setSelectedPinId(pinId);
  }, []);

  const handleOpenCalibrate = useCallback(() => {
    setCalibrateOpen(true);
  }, []);

  const handleCloseCalibrate = useCallback(() => {
    setCalibrateOpen(false);
  }, []);

  const refreshAccuracy = useCallback(async () => {
    try {
      const refreshed = await fetchConfig();
      setConfig((current) =>
        current ? { ...current, accuracy: refreshed.accuracy } : refreshed,
      );
    } catch {
      // The calibration itself already succeeded; leave the last visible
      // quality state in place if the follow-up read is temporarily lost.
    }
  }, []);

  const handleOpenCameraPicker = useCallback(() => {
    setCameraPickerOpen(true);
  }, []);

  const handleCloseCameraPicker = useCallback(() => {
    setCameraPickerOpen(false);
  }, []);

  const handleControllerChange = useCallback(async (boardId: string) => {
    if (!config || boardId === config.board_id || controllerSwitching) return;
    if (guidePinId && !window.confirm(t("runtime.switchConfirm"))) return;
    setControllerSwitching(true);
    setControllerError(null);
    try {
      const result = await postSelectController(boardId);
      if (!result.ok) {
        setControllerError(t(`runtime.error.${result.error_code}`, result.params));
        return;
      }
      wsClient.prepareRuntime(result.board_id, result.runtime_revision);
      setGuideTarget(null);
      setSelectedPinId(null);
      setFilter("all");
      const [nextConfig, nextProfile, nextControllers] = await Promise.all([
        fetchConfig(),
        fetchBoardProfile(result.board_id),
        fetchControllers(),
      ]);
      setConfig(nextConfig);
      setProfile(nextProfile);
      setControllers(nextControllers.controllers);
    } catch {
      setControllerError(t("runtime.error.network"));
    } finally {
      setControllerSwitching(false);
    }
  }, [config, controllerSwitching, guidePinId, t]);

  const assistantPanel = project && !displayModeActive ? <div className="unified-debug-tools" hidden={assistant.demoOpen || makerStage === "design"}><DebugPage key={aiDebug.resetVersion} state={maker} variant="wiring"
    embedded={Boolean(project)} assistantOpen={project ? true : maker.debug?.panelOpen ?? false}
    onAssistantOpenChange={panelOpen=>setMaker(s=>({...s,debug:{...s.debug,panelOpen}}))}
    assistantIntent={assistantIntent}
    onAssistantIntentChange={intent=>setMaker(s=>({...s,debug:{...s.debug,intent}}))}
    wiringTarget={project && assistantIntent === "wiring" && currentWire(project,maker.guide) ? {component_id:currentWire(project,maker.guide)!.componentId,wire_id:currentWire(project,maker.guide)!.id} : undefined}
    sessionRecord={aiDebug.record}
    onSessionAnalyse={context=>aiDebug.action("analyse",context)}
    onCase={caseId=>setMaker(s=>({...s,debug:{...s.debug,caseId}}))}
    onCode={(code,expected)=>setMaker(s=>s.code===expected?({...s,code}):s)} onWiring={inspectWiring} onDeploy={()=>navigateMaker("deploy")}
    onSelect={selectedComponentId=>setMaker(s=>({...s,debug:{...s.debug,selectedComponentId}}))}
    assistant={({context,codeHash,repairCaseId,repairAppliedHash,repairCandidateReady,onRetest,onTrial,onReviewRepair,onManual,operationCard,headerControls})=><AiDebugPanel actionsOnly chatGuidance state={maker} context={context} currentCodeHash={codeHash}
      variant={assistantIntent} wiringTarget={context.wiring_target} onOpenDebug={()=>openDebug()}
      operationCard={operationCard} headerControls={headerControls}
      testHelpInvitation={testHelpInvitation} onTestHelpAction={handleSharedTestHelp} onTestHelpHandled={id => {
        setTestHelpOffer(current => current?.invitation.id === id ? null : current);
        setTestHelpActionId(current => current === id ? null : current);
      }}
      testHelpActionTarget={testHelpMessageTarget?.invitationId === testHelpInvitation?.id ? testHelpMessageTarget?.element : null}
      onReviewGuideChange={(guide, expected) => setMaker(current =>
        current.design === expected.design && current.code === expected.code && current.guide === expected.guide
          ? { ...current, guide } : current)}
      repairCaseId={repairCaseId} repairAppliedHash={repairAppliedHash} repairCandidateReady={repairCandidateReady} session={aiDebug}
      webcamReady={debugWebcamReady} cameraStatusInView={makerStage === 'guide' && !assistant.demoOpen}
      eyeActive={eyeActive} cameraSource={config?.camera_source ?? null} cameraRuntimeRevision={config?.runtime_revision ?? null} onReturnWebcam={glasses.stop}
      onCase={caseId=>setMaker(s=>s.debug?.caseId===caseId?s:({...s,debug:{...s.debug,caseId}}))}
      onRetest={onRetest} onTrial={onTrial} onReviewRepair={onReviewRepair} onManual={onManual} onWiring={inspectWiring} onDiagram={inspectDiagram} />} /></div> : null;

  const renderCameraTools = (videoControls?: ReactNode) => <StatusBar compact embedded={makerEnabled} videoControls={videoControls} active={(!makerEnabled || makerStage !== "design") && !displayModeActive}
    webcamTuningVisible={displayMode === "standard" && config?.camera_source === "device" && !phoneMainActive}
    onOpenCalibrate={handleOpenCalibrate} calibrateDisabled={!profile || backendDown || phoneMainActive || photoOperationBusy}
    onOpenCameraPicker={handleOpenCameraPicker} cameraPickerVisible={config?.camera_source === "device"} cameraPickerDisabled={backendDown || phoneMainActive || photoOperationBusy}
    onEnterSmartGlassesDemo={enterSmartGlassesDemo}
    smartGlassesDemoDisabled={displayModeDisabled || photoOperationBusy || glasses.pending || glasses.status?.state === "restoring"}
    onEnterOpticalHud={enterOpticalHud} opticalHudDisabled={opticalHudDisabled || photoOperationBusy}
    accuracy={config?.accuracy ?? null} pinsById={pinsById}
    boardId={config?.board_id ?? null} runtimeRevision={config?.runtime_revision ?? null} />;

  const brand = <div className="brand">
    <div className="brand-text">
      <h1 className="brand-title"><img className="brand-logo" src="/brand/tinkro-dark.png" alt={t("app.title")} width={128} height={40} /></h1>
      <div className="brand-subtitle">Vibe Maker Studio</div>
    </div>
  </div>;
  const runtimeControls = <>
    <RuntimeToolbar
      collapsible={makerEnabled && !displayModeActive}
      controllers={controllers}
      activeBoardId={config?.board_id ?? null}
      busy={controllerSwitching}
      disabled={backendDown}
      error={controllerError}
      cameraToolsRef={makerEnabled && !displayModeActive ? setCameraSettingsHost : undefined}
      onControllerChange={(boardId) => void handleControllerChange(boardId)}
      onLocaleChange={handleLocaleChange}
    />
    {!displayModeActive && glasses.restoreError && <div className="glasses-restore-error" role="alert">
      <span className="runtime-error">{t("glasses.restoreFailed")} {glasses.restoreError}</span>
      <button type="button" className="camera-trigger" onClick={glasses.stop}>{t("glasses.retryRestore")}</button>
    </div>}
  </>;

  const floatingGuide = makerEnabled && !maker.standalone && !displayModeActive && Boolean(project || emptyProjectGuide);
  const guideVisibilityControl = <button ref={guideToggleRef} type="button"
    className={`guide-visibility-toggle${guideVisible ? " active" : ""}${floatingGuide && guideVisible ? " guide-icon-action" : ""}`}
    aria-expanded={guideVisible} aria-controls={floatingGuide ? 'maker-floating-guide' : undefined}
    aria-label={guideVisible ? tr("收合接線引導", "Hide wiring guide") : tr("展開接線引導", "Show wiring guide")}
    title={guideVisible ? tr("收合接線引導", "Hide wiring guide") : tr("展開接線引導", "Show wiring guide")}
    disabled={!config || !profile} onClick={() => handleGuideVisibilityChange(!guideVisible)}>
    <svg aria-hidden="true" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={floatingGuide && guideVisible ? "m5 7.5 5 5 5-5" : "M7 3H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h3M10 5h6M10 10h6M10 15h6"} />
    </svg>
    {floatingGuide && guideVisible ? null : project || emptyProjectGuide ? guideVisible ? tr("收合接線引導", "Hide wiring guide") : tr("展開接線引導", "Show wiring guide") : t(guideVisible ? "photoGuide.hide" : "photoGuide.show")}
    {floatingGuide && !guideVisible ? <span className="floating-guide-chevron" aria-hidden="true">⌃</span> : null}
  </button>;

  // One shared selector; each view hosts it in its existing header/dock.
  const imageViewControls = makerStage === "guide" && makerEnabled && !displayModeActive ? <ImageViewControls
    view={photoMainActive ? 'photo' : showWiringDiagram ? 'diagram' : 'live'}
    disabled={calibrateOpen || liveCamera.pending || photoOperationBusy}
    photoDisabled={!canChangeImage}
    diagramAvailable={Boolean(project && (projectWire || diagramInspection))}
    onChange={view => {
      if (view === 'diagram') {
        setImageView(lastLiveView.current);
        if (projectWire) setEvidenceDiagram(null);
        setDiagramCaptureOverride(diagramCaptureKey);
        setMaker(s => ({ ...s, guide: { ...s.guide, mode: '2d' } }));
      } else changeImageView(view === 'photo' ? 'photo' : lastLiveView.current);
    }} /> : null;

  const completedStages = {
    design: Boolean(project),
    guide: Boolean(project?.wiring.length && project.wiring.every(wire => maker.guide.confirmed[wire.id]?.signature === wireSignature(wire))),
    deploy: false,
  };

  return (
    <HeaderPanelProvider>
    <div className={`app tinkro-theme${makerEnabled ? ` pi-deploy-layout maker-layout maker-stage-${makerStage}` : ""}${fullWidthWiring ? " maker-wiring-full-width" : ""}${displayModeActive ? ` display-mode-active ${displayMode}` : ""}`}>
      <main className="main">
        {makerEnabled ? <WorkspaceHeader brand={brand}
          saveStatus={makerSaved ? null : <small className="maker-save-status maker-warning" role="alert">
            {tr("儲存失敗，請勿關閉頁面", "Storage failed; keep this page open")}
          </small>}
          navigation={<nav className="maker-nav" aria-label={tr("作品工作流程", "Maker workflow")}>
              {(["design", "guide", "deploy"] as const).map(stage => <button key={stage} type="button" className={makerStage === stage ? "active" : ""}
                aria-current={makerStage === stage ? "step" : undefined} onClick={() => navigateMaker(stage)}>
                {makerStage !== stage && completedStages[stage] ? <svg className="maker-stage-complete" aria-hidden="true" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m4 10 4 4 8-8" /></svg> : null}
                {stage === "design" ? tr("設計與藍圖", "Design & blueprint") : stage === "guide" ? tr("接線與除錯", "Wiring & debug") : tr("部署與執行", "Deploy & run")}
              </button>)}
          </nav>}>
          {displayModeActive ? <MakerModelMenu state={maker} setState={setMaker} assistant={makerAI} /> : null}
          {!displayModeActive ? <WorkflowResetControl onReset={startNewProject}
            busy={workflowResetPending || workflowOperationBusy}
            error={workflowResetError || makerAI.error} /> : null}
          {!displayModeActive ? <DeviceConnectionGroups
            phoneLabel={tr("手機連線", "Phone connection")} piLabel={tr("Pi 執行", "Pi runtime")}
            phoneName={tr("手機", "Phone")} piName="Pi"
            phone={<div className="mobile-toolbar-slot mobile-header-slot" ref={setMobileTriggerHost} />}
            pi={<PiConnectionControl />} /> : <div className="maker-connection-controls"><PiConnectionControl /></div>}
          {runtimeControls}
        </WorkspaceHeader> : <header className="header">
          {brand}
          <div className="workspace-toolbar">
            {runtimeControls}
          </div>
        </header>}
        <AssistantWorkspace active={makerEnabled && !displayModeActive} aiOpen={aiOpen} onAiOpen={setAiOpen}
          openRequest={aiOpenRequest} latestReply={assistant.record?.messages.filter(message => message.role === "assistant").at(-1)?.id ?? ""}
          assistant={<UnifiedAssistant state={maker} setState={setMaker} controller={assistant} legacy={makerAI} debugTools={assistantPanel} onNewProject={startNewProject} testHelpFocus={testHelpInvitation?.id} testHelpText={testHelpInvitation?.text}
            wiringReview={aiDebug.record?.wiring_review} onWiringFlowAction={handleWiringFlowAction} onWiringReceiptRetry={recoverWiringDecision}
            testHelpMessageId={testHelpInvitation?.messageId} onTestHelpActionTargetChange={setTestHelpMessageTarget}
            mobileWorkspace={{ trigger: !displayModeActive ? mobileTriggerHost : null,
              controls: (makerStage === "guide" || makerStage === "deploy") && !assistant.demoOpen && !displayModeActive ? mobileControlsHost : null,
              preview: null, showing: phoneMainActive, phoneSourceSelected,
              source: config?.camera_source === 'phone' ? 'phone' : 'webcam',
              selectedPhoneSource: liveCamera.status?.kind === 'phone' && liveCamera.status.session_id && liveCamera.status.generation !== null
                ? { session_id: liveCamera.status.session_id, generation: liveCamera.status.generation } : null,
              pinsById, guideTarget,
              canShow: canChangeImage, onShow: changePhonePreview,
              onPhoto: receiveMobilePhoto }} />}>
        {assistant.demoOpen && makerEnabled && !displayModeActive ? <DemoWorkspace controller={assistant} /> : null}
        <div className="assistant-project-workspace" hidden={assistant.demoOpen && !displayModeActive}>
        {makerEnabled && makerStage === "design" ? <div className="maker-design-stage">
          {maker.designView === "blueprint" && maker.design ? <BlueprintPage key={`${maker.design.id}:${maker.design.revision}`}
            design={maker.design} onGuide={() => navigateMaker("guide")}
            onEdit={() => setMaker(s => ({ ...s, designView: "concept" }))}
            onViewChange={view => setMaker(s => ({ ...s, designView: view }))}
            hasCandidate={Boolean(maker.candidate)} generating={Boolean(maker.aiJobId)} /> :
              <DesignStudio state={maker} setState={setMaker} onAdopt={adoptDesign} generationPhase={makerAI.phase} busy={makerAI.busy || assistant.busy}
                onViewChange={view => setMaker(s => ({ ...s, designView: view }))} />
            }
        </div> : null}
        <GuidePaneLayout stageRef={videoStageRef}
          className={`video-guide-stage assistant-wiring-stage${floatingGuide ? " guide-floating" : ""}${showWiringDiagram ? " maker-2d" : ""}`}
          visible={makerStage === "guide"}
          stacked={makerEnabled && !maker.standalone && !displayModeActive}
          resizable={makerEnabled && Boolean(project) && guideVisible && !displayModeActive && !floatingGuide}>
          <VideoView
            livePreviewHost={makerEnabled && makerStage === 'deploy' && !displayModeActive ? deploymentPreviewHost : null}
            livePreviewControls={makerStage === 'deploy' ? <div className="image-source-host" ref={setMobileControlsHost} /> : null}
            viewNavigation={imageViewControls}
            viewControl={videoControls => <>{!floatingGuide ? <div className="assistant-guide-tools">{guideVisibilityControl}</div> : null}
              {makerEnabled ? cameraSettingsHost ? createPortal(renderCameraTools(videoControls), cameraSettingsHost) : null : renderCameraTools(videoControls)}
              </>}
            alternateView={photoMainActive ? <GpioPhotoWorkspace key={selectedPhoto || 'empty'} record={activeGpioPhoto}
              viewControls={imageViewControls}
              historical={!!photoMismatch} historicalReason={photoMismatch} target={photoGuidanceTarget(project, maker.guide)}
              records={gpioPhotos} onRecord={record => setSelectedPhoto(`${record.source}:${record.capture.capture_id}`)}
              captureAction={gpioCaptureAction} busy={photoOperationBusy}
              showReturn={!makerEnabled || displayModeActive}
              onReturn={() => changeImageView(lastLiveView.current)} /> : project && showWiringDiagram ? diagramInspection ? <DiagramInspectionView key={diagramInspection.requestId}
              viewControls={imageViewControls}
              inspection={diagramInspection} currentDesign={project} capturePending={Boolean(debugCaptureSession)} onReturn={() => setEvidenceDiagram(null)} />
              : projectWire ? <StepDiagramView viewControls={imageViewControls} design={project} wire={projectWire} capturePending={Boolean(debugCaptureSession)} /> : null : null}
            displayMode={displayMode}
            glassesStatus={glasses.status}
            onGlassesDisplayFps={setGlassesDisplayFps}
            config={config}
            sourceControl={makerStage === 'guide' && makerEnabled && !displayModeActive
              ? <><div className="image-source-host" ref={setMobileControlsHost} />{gpioCaptureAction}</> : null}
            sourceError={liveCamera.error}
            sourceChanging={liveCamera.pending}
            sourceUnavailable={config?.camera_source === 'phone' && !phoneReady}
            onRetrySource={() => { if (!photoOperationBusy) void liveCamera.reconnect(); }}
            pinsById={pinsById}
            highlightIds={highlightIds}
            selectedPinId={selectedPinId}
            onSelectPin={handleSelectPin}
            backendDown={backendDown}
            legend={legend}
            outlineMm={profile?.board.outline_mm ?? null}
            boardName={profile ? tx(profile.board.name) : ""}
            calibrateOpen={calibrateOpen}
            onCloseCalibrate={handleCloseCalibrate}
            onCalibrationSuccess={() => void refreshAccuracy()}
            guideTarget={guideTarget}
            overlayOverview={Boolean(project) && !displayModeActive && (!guideVisible || makerStage !== "guide" || maker.guide.phase !== "active")}
            overlayComponentId={project && makerStage === "guide" && !displayModeActive ? project.component_ids[maker.guide.componentIndex] ?? null : null}
            opticalHudCalibration={opticalHudCalibration}
            onOpticalHudCalibrationComplete={handleOpticalHudCalibrationComplete}
            debugView={false}
            debugCaptureTask={debugCaptureSession?.capture_task}
            debugEvidence={debugCaptureSession?.evidence?.at(-1)}
            debugFramingFeedback={debugCaptureSession?.framing_feedback}
          />
          {floatingGuide && !guideVisible ? <div className="floating-guide-dock">{guideVisibilityControl}</div> : null}
          {project && makerStage === "guide" ? <WiringWorkspace guideOnly design={project} guide={maker.guide} visible={guideVisible && !displayModeActive}
            panelId={floatingGuide ? 'maker-floating-guide' : undefined}
            assistantOpen={maker.debug?.panelOpen ?? false}
            onAssistantOpenChange={panelOpen=>setMaker(s=>({...s,debug:{...s.debug,panelOpen}}))}
            onClose={()=>handleGuideVisibilityChange(false)} assistant={null} busy={Boolean(aiDebug.record?.model_busy)}
            replyId={(aiDebug.conversation?.messages ?? aiDebug.record?.messages)?.filter(message=>message.role==="assistant").at(-1)?.id}>
            <ProjectGuidePanel design={project} session={maker.guide} visible embedded floating={floatingGuide} disabled={backendDown}
            visibilityControl={floatingGuide && guideVisible ? guideVisibilityControl : undefined}
            onInspectComponent={photoMainActive ? cid => inspectWiring(cid) : undefined}
            pinsById={pinsById}
            onChange={guide => setMaker(s => ({ ...s, guide }))}
            onBeforeEdit={prepareWiringEdit}
            onRestart={restartWiringConversation}
            onTargetChange={setGuideTarget} onVisibleChange={handleGuideVisibilityChange} onDebug={askComponentTestAI} onDeploy={() => navigateMaker("deploy")} />
          </WiringWorkspace> : null}
          {emptyProjectGuide ? <section id={floatingGuide ? 'maker-floating-guide' : undefined} className="photo-guide component-guide compact-guide maker-guide-empty"
            hidden={!guideVisible} aria-labelledby="empty-project-guide-title">
            <header className="guide-panel-header"><div>
              <span className="guide-panel-eyebrow">{tr("02 · 接線引導", "02 · Wiring guide")}</span>
              <h2 id="empty-project-guide-title">{tr("尚未確認作品", "No confirmed project yet")}</h2>
            </div>{floatingGuide && guideVisible ? guideVisibilityControl : null}</header>
            <div className="guide-panel-body">
              <p>{tr("請先到 01 建立並確認作品，再依照作品接線。相機仍可使用。", "Create and confirm a project in 01 before following its wiring guide. The camera is still available.")}</p>
              <button type="button" className="guide-primary-action" onClick={() => navigateMaker("design")}>
                {tr("前往 01 建立作品", "Go to 01 · Create a project")}
              </button>
            </div>
          </section> : null}
          {!project && !emptyProjectGuide && makerStage === "guide" && config && profile ? (
            <WiringGuidePanel
              key={`${config.board_id}:${config.runtime_revision}`}
              boardId={config.board_id}
              boardName={tx(profile.board.name)}
              availablePinIds={availablePinIds}
              pinsById={pinsById}
              disabled={!profile || backendDown}
              visible={guideVisible}
              onVisibleChange={handleGuideVisibilityChange}
              onTargetChange={setGuideTarget}
            />
          ) : null}
          {displayModeActive && (
            <>
              {displayMode === "smart-glasses-demo" && <GlassesControls
                status={glasses.status} pending={glasses.pending} error={glasses.error}
                displayFps={glassesDisplayFps} onApply={glasses.apply} />}
              {fullscreenFallback && displayMode !== "smart-glasses-demo" && (
                <div className="smart-glasses-fallback" role="status">
                  {t("smartGlasses.fullscreenFallback")}
                </div>
              )}
              <div className="display-mode-controls">
                {displayMode === "optical-hud-demo" && (
                  <button
                    type="button"
                    className="optical-hud-recalibrate"
                    onClick={recalibrateOpticalHud}
                    title={t("opticalHud.recalibrateTooltip")}
                  >
                    {t("opticalHud.recalibrate")}
                  </button>
                )}
                <button
                  type="button"
                  className="smart-glasses-exit"
                  onClick={exitDisplayMode}
                  title={t(opticalHudActive ? "opticalHud.exitTooltip" : "smartGlasses.exitTooltip")}
                  aria-label={t(opticalHudActive ? "opticalHud.exitTooltip" : "smartGlasses.exitTooltip")}
                >
                  {t(opticalHudActive ? "opticalHud.exit" : "smartGlasses.exit")}
                  <kbd aria-hidden="true">Esc</kbd>
                </button>
              </div>
            </>
          )}
        </GuidePaneLayout>
        {makerEnabled && makerStage === "deploy" ? <div className="maker-deploy-main"><PiDeployPanel project={project ?? undefined} draft={maker.code}
          livePreview={<div className="deployment-live-host" ref={setDeploymentPreviewHost} />}
          onDebug={deployment=>{openAssistant();setGuideTarget(null);setMaker(s=>({...s,debug:{...s.debug,panelOpen:true,intent:"debug",source:"deploy",deployment,componentId:undefined,selectedComponentId:undefined,runId:undefined,symptom:undefined}}));}} onDraftChange={code => setMaker(s => ({ ...s, code, hardware: {} }))} /></div> : null}
        </div>
        </AssistantWorkspace>
      </main>
      {makerStage === "guide" && !fullWidthWiring ? <aside className="side">
        <CapabilityCard profile={profile} pin={selectedPin} backendDown={backendDown} />
      </aside> : null}
      <CameraPicker open={cameraPickerOpen} onClose={handleCloseCameraPicker} />
    </div>
    </HeaderPanelProvider>
  );
}
