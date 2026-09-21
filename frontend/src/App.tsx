import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CameraPicker } from "./components/CameraPicker";
import { GlassesControls } from "./components/GlassesControls";
import { useGlassesStream } from "./lib/useGlassesStream";
import { CapabilityCard } from "./components/CapabilityCard";
import { PiDeployPanel } from "./components/PiDeployPanel";
import { WiringGuidePanel } from "./components/WiringGuidePanel";
import { QueryBox } from "./components/QueryBox";
import { RuntimeToolbar } from "./components/RuntimeToolbar";
import { StatusBar } from "./components/StatusBar";
import { VideoView, type LegendInfo } from "./components/VideoView";
import {
  fetchBoardProfile,
  fetchCameras,
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
  QueryResponse,
} from "./lib/types";
import type { ActiveGuideTarget } from "./lib/componentWiringGuides";
import { wsClient } from "./lib/wsClient";
import { DesignStudio } from "./components/DesignStudio";
import { BlueprintPage } from "./components/BlueprintPage";
import { MakerAssistant } from "./components/MakerAssistant";
import { MakerModelMenu } from "./components/MakerModelMenu";
import { MakerSplitLayout } from "./components/MakerSplitLayout";
import { useMakerAI } from "./lib/useMakerAI";
import { ProjectGuidePanel } from "./components/ProjectGuidePanel";
import { CircuitDiagram } from "./components/CircuitDiagram";
import { confirmConcept, currentWire, type MakerStage } from "./lib/maker";
import { useMaker, useMakerText } from "./lib/useMaker";
import "./maker.css";

const REST_RETRY_MS = 3000;
const FULLSCREEN_REQUEST_TIMEOUT_MS = 1000;
const GUIDE_VISIBILITY_STORAGE_KEY = "boardvision.wiring-guide-visible.v1";

function initialGuideVisibility(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(GUIDE_VISIBILITY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export default function App() {
  const { locale, t, tx, setLocale, applyDefaultLocale } = useI18n();
  const { state: maker, setState: setMaker, saved: makerSaved } = useMaker();
  const makerAI = useMakerAI(maker, setMaker);
  const tr = useMakerText();
  const videoStageRef = useRef<HTMLDivElement>(null);
  const fullscreenRequestPendingRef = useRef(false);
  const fullscreenEnteredRef = useRef(false);
  const fullscreenAttemptIdRef = useRef(0);
  const fullscreenFallbackTimerRef = useRef<number | null>(null);

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [profile, setProfile] = useState<BoardProfile | null>(null);
  const [controllers, setControllers] = useState<ControllerSummary[]>([]);
  const [controllerSwitching, setControllerSwitching] = useState(false);
  const [controllerError, setControllerError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [filter, setFilter] = useState<FilterId>("all");
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [selectedPinId, setSelectedPinId] = useState<string | null>(null);
  const [guideTarget, setGuideTarget] = useState<ActiveGuideTarget | null>(null);
  const guidePinId = guideTarget?.boardPinId ?? null;
  const [guideVisible, setGuideVisible] = useState(initialGuideVisibility);
  const [calibrateOpen, setCalibrateOpen] = useState(false);
  const [cameraPickerOpen, setCameraPickerOpen] = useState(false);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("standard");
  const glasses = useGlassesStream();
  const [glassesDisplayFps, setGlassesDisplayFps] = useState<number | null>(0);
  const glassesSessionRef = useRef(false);
  const [opticalHudCalibration, setOpticalHudCalibration] =
    useState<OpticalHudCalibration | null>(null);
  const [fullscreenFallback, setFullscreenFallback] = useState(false);
  // Decided once per successful bootstrap: hides the "切換鏡頭" trigger
  // entirely in synthetic-camera mode or when the scan found no devices,
  // rather than opening it into an empty, confusing panel.
  const [camerasAvailable, setCamerasAvailable] = useState(false);
  const displayModeActive = isDisplayOnlyMode(displayMode);
  const opticalHudActive = isOpticalHudMode(displayMode);
  const displayModeDisabled = backendDown || config === null;
  const opticalHudDisabled = displayModeDisabled || profile === null;
  const makerEnabled = config?.board_id === "raspberry-pi-5";
  const makerStage = displayModeActive ? "guide" : makerEnabled ? maker.stage : "guide";
  const project = makerEnabled && !maker.standalone ? maker.design : null;
  const fullWidthWiring = Boolean(project) && makerStage === "guide";
  const projectWire = project && maker.guide.phase === "active" ? currentWire(project, maker.guide) : undefined;
  const navigateMaker = (stage: MakerStage) => {
    setGuideTarget(null);
    setMaker(s => ({ ...s, stage, standalone: false }));
    if (stage === "guide") setGuideVisible(true);
  };
  const adoptDesign = (replaceManual = false) => {
    setGuideTarget(null);
    setMaker(s => confirmConcept(s, replaceManual));
  };

  const handleLocaleChange = useCallback(
    (next: Locale) => {
      setLocale(next);
      setQueryResult(null);
    },
    [setLocale],
  );

  const handleGuideVisibilityChange = useCallback((visible: boolean) => {
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
    const revision = glasses.status?.runtime_revision;
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
  }, [glasses.status?.runtime_revision, config?.runtime_revision]);

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
        // One-shot scan, not retried on its own: synthetic mode never has
        // device cameras, and a scan failure just means the trigger stays
        // hidden (not a reason to keep retrying against a live capture setup).
        if (loadedConfig.camera_source === "device") {
          fetchCameras()
            .then((resp) => {
              if (cancelled) return;
            setCamerasAvailable(resp.cameras.some((camera) => camera.available));
            })
            .catch(() => {
              if (cancelled) return;
              setCamerasAvailable(false);
            });
        } else {
          setCamerasAvailable(false);
        }
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

  useEffect(() => {
    setQueryResult(null);
  }, [locale]);

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

  const querySet = useMemo(
    () =>
      queryResult && queryResult.matched && queryResult.pin_ids.length > 0
        ? new Set(queryResult.pin_ids)
        : null,
    [queryResult],
  );

  const guideSet = useMemo(() => (guidePinId ? new Set([guidePinId]) : null), [guidePinId]);

  // A guided wiring step must leave exactly one target bright. Query results
  // otherwise take precedence over the capability filter.
  const highlightIds = guideSet ?? querySet ?? filterSet;

  const legend: LegendInfo | null =
    guidePinLabel
      ? { colorVar: "--ok", label: t("photoGuide.videoTarget", { pin: guidePinLabel }), count: 1 }
      : filter !== "all" && filterSet && !querySet
        ? { colorVar: FILTER_COLOR_VAR[filter], label: t(`filter.${filter}`), count: filterSet.size }
        : null;

  const handleSelectPin = useCallback((pinId: string | null) => {
    setSelectedPinId(pinId);
  }, []);

  const handleQueryResult = useCallback((result: QueryResponse) => {
    setQueryResult(result);
  }, []);

  const handleQueryClear = useCallback(() => {
    setQueryResult(null);
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
      setQueryResult(null);
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

  return (
    <div className={`app${makerEnabled ? ` pi-deploy-layout maker-layout maker-stage-${makerStage}` : ""}${fullWidthWiring ? " maker-wiring-full-width" : ""}${displayModeActive ? ` display-mode-active ${displayMode}` : ""}`}>
      <main className="main">
        <header className={`header${makerEnabled ? " maker-header" : ""}`}>
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <div className="brand-text">
              <h1 className="brand-title">{t("app.title")}</h1>
              <div className="brand-subtitle">{t("app.subtitle")}</div>
            </div>
          </div>
          {makerEnabled ? <small className={`maker-save-status ${makerSaved ? "maker-muted" : "maker-warning"}`} role={makerSaved ? "status" : "alert"}>
            {tr(makerSaved ? "作品草稿已保存於此瀏覽器" : "儲存失敗，請勿關閉頁面", makerSaved ? "Draft saved in this browser" : "Storage failed; keep this page open")}
          </small> : null}
          <div className={`workspace-toolbar${makerEnabled ? " maker-workflow-toolbar" : ""}`}>
            {makerEnabled ? <nav className="maker-nav" aria-label={tr("作品工作流程", "Maker workflow")}>
              {(["design", "blueprint", "guide", "deploy"] as const).map((stage, i) => <button key={stage} className={makerStage === stage ? "active" : ""}
                disabled={stage === "blueprint" && !maker.design} aria-current={makerStage === stage ? "step" : undefined} onClick={() => navigateMaker(stage)}><span>{String(i + 1).padStart(2, "0")}</span>{stage === "design" ? tr("設計作品", "Design") : stage === "blueprint" ? "Blueprint" : stage === "guide" ? tr("Pin 接線引導", "Pin wiring") : tr("部署與測試", "Deploy & test")}</button>)}
            </nav> : null}
            {makerEnabled ? <MakerModelMenu state={maker} setState={setMaker} assistant={makerAI} /> : null}
            <RuntimeToolbar
              controllers={controllers}
              activeBoardId={config?.board_id ?? null}
              busy={controllerSwitching}
              disabled={backendDown}
              error={controllerError}
              onControllerChange={(boardId) => void handleControllerChange(boardId)}
              onLocaleChange={handleLocaleChange}
            />
            {!displayModeActive && glasses.restoreError && <div className="glasses-restore-error" role="alert">
              <span className="runtime-error">{t("glasses.restoreFailed")} {glasses.restoreError}</span>
              <button type="button" className="camera-trigger" onClick={glasses.stop}>{t("glasses.retryRestore")}</button>
            </div>}
          </div>
        </header>
        {makerEnabled && makerStage === "design" ? <MakerSplitLayout stage="design"
          left={<MakerAssistant state={maker} setState={setMaker} assistant={makerAI} onReview={() => navigateMaker("design")} />}>
          <DesignStudio state={maker} setState={setMaker} onAdopt={adoptDesign} />
        </MakerSplitLayout> : null}
        {makerEnabled && makerStage === "blueprint" && maker.design ? <BlueprintPage key={`${maker.design.id}:${maker.design.revision}`}
          design={maker.design} onGuide={() => navigateMaker("guide")} onEdit={() => navigateMaker("design")}
          hasCandidate={Boolean(maker.candidate)} generating={Boolean(maker.aiJobId)} /> : null}
        <div ref={videoStageRef} className={`video-guide-stage${project && maker.guide.mode === "2d" && !displayModeActive ? " maker-2d" : ""}`} style={makerStage !== "guide" ? { display: "none" } : undefined}>
          <button
            type="button"
            className={`guide-visibility-toggle${guideVisible ? " active" : ""}`}
            aria-expanded={guideVisible}
            disabled={!config || !profile}
            onClick={() => handleGuideVisibilityChange(!guideVisible)}
          >
            <span aria-hidden="true">↯</span>
            {t(guideVisible ? "photoGuide.hide" : "photoGuide.show")}
          </button>
          <VideoView
            displayMode={displayMode}
            glassesStatus={glasses.status}
            onGlassesDisplayFps={setGlassesDisplayFps}
            config={config}
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
            opticalHudCalibration={opticalHudCalibration}
            onOpticalHudCalibrationComplete={handleOpticalHudCalibrationComplete}
          />
          {project && maker.guide.mode === "2d" && !displayModeActive ? <div className="maker-2d-main"><h2>{tr("2D 人工接線引導", "2D manual wiring")}</h2><CircuitDiagram design={project} activeId={projectWire?.id} /></div> : null}
          {project && makerStage === "guide" ? <ProjectGuidePanel design={project} session={maker.guide} visible={guideVisible} disabled={backendDown}
            pinsById={pinsById}
            onChange={guide => setMaker(s => ({ ...s, guide }))}
            onTargetChange={setGuideTarget} onVisibleChange={handleGuideVisibilityChange} onDeploy={() => navigateMaker("deploy")} /> : null}
          {!project && config && profile ? (
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
        </div>
        {makerEnabled && makerStage === "deploy" ? <div className="maker-deploy-main"><PiDeployPanel project={project ?? undefined} draft={project ? maker.code : undefined}
          onDraftChange={project ? code => setMaker(s => ({ ...s, code, hardware: {} })) : undefined} /></div> : null}
        <div hidden={makerStage !== "guide"}><QueryBox result={queryResult} onResult={handleQueryResult} onClear={handleQueryClear} /></div>
        <div hidden={makerEnabled && (makerStage === "design" || makerStage === "blueprint")}><StatusBar
          webcamTuningVisible={displayMode === "standard" && config?.camera_source === "device"}
          onOpenCalibrate={handleOpenCalibrate}
          calibrateDisabled={!profile || backendDown}
          onOpenCameraPicker={handleOpenCameraPicker}
          cameraPickerVisible={camerasAvailable}
          cameraPickerDisabled={backendDown}
          onEnterSmartGlassesDemo={enterSmartGlassesDemo}
          smartGlassesDemoDisabled={displayModeDisabled || glasses.pending || glasses.status?.state === "restoring"}
          onEnterOpticalHud={enterOpticalHud}
          opticalHudDisabled={opticalHudDisabled}
          accuracy={config?.accuracy ?? null}
          pinsById={pinsById}
        /></div>
      </main>
      {makerStage === "guide" && !fullWidthWiring ? <aside className="side">
        {!project && makerEnabled ? <PiDeployPanel /> : null}
        <CapabilityCard profile={profile} pin={selectedPin} backendDown={backendDown} />
      </aside> : null}
      <CameraPicker open={cameraPickerOpen} onClose={handleCloseCameraPicker} />
    </div>
  );
}
