import { useI18n } from "../lib/i18n";
import { useDetections } from "../lib/wsClient";
import { getMotionDisplay, subscribeMotionDisplay } from "../lib/motionDisplayStore";
import {
  advanceBoardStatus, currentPitchSample, distanceScaleAdvice, hasCurrentBoardBody,
  type PitchSample,
} from "../lib/boardDistance";
import { pinDisplayNameWithNumber } from "../lib/capabilities";
import type { AccuracySummary, Pin } from "../lib/types";
import { CameraAutoTune } from "./CameraAutoTune";
import { cameraToolsPlacement } from "../lib/cameraTools";
import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

interface StatusBarProps {
  /** A toolbar trigger with an out-of-flow panel instead of a footer row. */
  compact?: boolean;
  /** Inline disclosure inside Settings, rather than a floating toolbar panel. */
  embedded?: boolean;
  active?: boolean;
  webcamTuningVisible?: boolean;
  /** Controlled by the original VideoView; closing tools never resets them. */
  videoControls?: ReactNode;
  /** Opens the "新增/校正板型" admin panel. */
  onOpenCalibrate: () => void;
  /** True while there's no loaded board profile to calibrate against (or the backend is down). */
  calibrateDisabled: boolean;
  /** Opens the "切換鏡頭" camera picker panel. */
  onOpenCameraPicker: () => void;
  /** Present in device mode even when no camera is connected yet. */
  cameraPickerVisible: boolean;
  /** True while the backend is unreachable (trigger stays visible but greyed out, like calibrateDisabled). */
  cameraPickerDisabled: boolean;
  /** Enters the display-only smart-glasses presentation mode. */
  onEnterSmartGlassesDemo: () => void;
  /** Disabled until a camera configuration is loaded or while the backend is unreachable. */
  smartGlassesDemoDisabled: boolean;
  /** Starts the through-the-lens four-point calibration for the black optical HUD. */
  onEnterOpticalHud: () => void;
  /** Disabled until a board profile and camera configuration are available. */
  opticalHudDisabled: boolean;
  /** Read-only profile/camera quality gate reported by GET /api/config. */
  accuracy: AccuracySummary | null;
  pinsById: ReadonlyMap<string, Pin>;
  boardId?: string | null;
  runtimeRevision?: number | null;
}

export function StatusBar({
  compact = false,
  embedded = false,
  active = true,
  webcamTuningVisible = false,
  videoControls = null,
  onOpenCalibrate,
  calibrateDisabled,
  onOpenCameraPicker,
  cameraPickerVisible,
  cameraPickerDisabled,
  onEnterSmartGlassesDemo,
  smartGlassesDemoDisabled,
  onEnterOpticalHud,
  opticalHudDisabled,
  accuracy,
  pinsById,
  boardId = null,
  runtimeRevision = null,
}: StatusBarProps) {
  const { t } = useI18n();
  const [cameraTuningBusy, setCameraTuningBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(Date.now);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [portalHost, setPortalHost] = useState<Element | null>(null);
  const [placement, setPlacement] = useState<ReturnType<typeof cameraToolsPlacement> | null>(null);
  useEffect(() => {
    // Portal past the clipped video stage, but keep the app's theme variables.
    if (compact && !embedded) setPortalHost(triggerRef.current?.closest(".app") ?? null);
  }, [compact, embedded]);
  useEffect(() => { if (!active) setExpanded(false); }, [active]);
  useLayoutEffect(() => {
    if (!compact || embedded || !expanded) return;
    const position = () => {
      const anchor = triggerRef.current?.getBoundingClientRect();
      if (anchor) setPlacement(cameraToolsPlacement(anchor, { width: window.innerWidth, height: window.innerHeight }));
    };
    position();
    panelRef.current?.focus({ preventScroll: true });
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, { capture: true, passive: true });
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [compact, embedded, expanded, portalHost]);
  useEffect(() => {
    if (!compact || !expanded) return;
    const outside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !triggerRef.current?.contains(target) && !panelRef.current?.contains(target)) setExpanded(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setExpanded(false);
      triggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [compact, expanded]);
  const openTool = (action: () => void) => { if (compact) setExpanded(false); action(); };
  useEffect(() => {
    if (!webcamTuningVisible || !expanded) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [webcamTuningVisible, expanded]);
  const ws = useDetections();
  const motion = useSyncExternalStore(subscribeMotionDisplay, getMotionDisplay, getMotionDisplay);
  const expectedBoard = boardId ?? ws.runtime?.board_id ?? ws.detection?.board_id;
  // The live stream revision changes immediately on a camera restart, while
  // GET /api/config can still be loading. Do not discard current frames just
  // because the previous config revision is still rendered.
  const expectedRevision = ws.connected && ws.runtime && ws.runtime.board_id === expectedBoard
    ? ws.runtime.runtime_revision
    : motion && motion.board_id === expectedBoard && now - motion.receivedAt <= 1200
      ? motion.runtime_revision
    : runtimeRevision ?? ws.detection?.runtime_revision;
  const rawDetection = ws.connected && ws.detection && ws.detectionReceivedAtMs > 0
    && now - ws.detectionReceivedAtMs <= 1200 && ws.detection.board_id === expectedBoard
    && ws.detection.runtime_revision === expectedRevision ? ws.detection : null;
  // In realtime mode the video and GPIO overlay use the synchronized motion
  // frame. A raw detector SEARCHING packet must not contradict that image.
  const motionFrame = motion && motion.board_id === expectedBoard && motion.runtime_revision === expectedRevision
    && motion.detection?.frame_id === motion.frame_id && now - motion.receivedAt <= 1200 ? motion : null;
  const detection = motion !== undefined ? motionFrame?.detection ?? null : rawDetection;
  const receivedAtMs = motion !== undefined ? motionFrame?.receivedAt ?? 0 : ws.detectionReceivedAtMs;
  // A synchronized HTTP motion frame is a live video observation even if the
  // independent guidance WebSocket is reconnecting. Keep its status separate
  // from the WS connection indicator and distance/trace availability.
  const streamLive = detection !== null && (motion !== undefined || ws.connected);
  const currentSample = streamLive ? currentPitchSample(detection, receivedAtMs, pinsById, now) : null;
  const lastSample = useRef<PitchSample | null>(null);
  useEffect(() => {
    if (currentSample) lastSample.current = currentSample;
  }, [currentSample?.atMs, currentSample?.pitchPx, currentSample?.boardId, currentSample?.runtimeRevision]);
  const distance = distanceScaleAdvice({
    connected: ws.connected, detection, rawDetection, trace: ws.wireTrace,
    traceReceivedAtMs: ws.wireTraceReceivedAtMs, accuracy,
    currentSample, lastSample: lastSample.current, now,
    boardId: expectedBoard ?? null, runtimeRevision: expectedRevision ?? null,
    videoSize: detection?.video_size ?? rawDetection?.video_size ?? null,
  });

  // Require several consecutive, distinct current-frame locks before saying
  // LOCKED. Loss of a trustworthy pose is immediate; this only stabilizes text.
  const lockRun = useRef({ context: "", frameId: -1, count: 0 });
  const context = `${expectedBoard ?? ""}:${expectedRevision ?? ""}:${motion !== undefined ? "motion" : "raw"}`;
  const boardStatus = advanceBoardStatus(lockRun.current, context, detection, streamLive);
  lockRun.current = boardStatus.run;
  const { statusKey, pillClass } = boardStatus;
  const poseConfidence = detection?.tracking === "locked" && !detection.pose_quality?.outline_only
    && detection.pins?.some((pin) => pin.v) && Number.isFinite(detection.confidence)
    ? detection.confidence : null;
  const bodyConfidence = poseConfidence === null && hasCurrentBoardBody(detection)
    ? detection?.body?.confidence ?? null : null;
  const confidence = poseConfidence ?? bodyConfidence;
  const pitchText = distance.pitchPx !== null
    ? `${distance.sampleFresh ? "" : "≈"}${distance.pitchPx.toFixed(1)}px / ${(distance.pitchPx / 2.54).toFixed(2)} px/mm`
    : "—";
  const poseQuality = detection?.pose_quality;
  const guidancePin = ws.guidance
    ? pinDisplayNameWithNumber(pinsById.get(ws.guidance.expected_pin_id)) || ws.guidance.expected_pin_id
    : null;

  const content = (
      <div id="camera-status-details" ref={panelRef} className={`statusbar-content${compact ? embedded ? " camera-tools-inline" : " camera-tools-popover" : ""}`} hidden={!expanded || !active}
        role={compact ? embedded ? "group" : "dialog" : undefined} aria-label={compact ? t("status.toolsTitle") : undefined}
        tabIndex={compact && !embedded ? -1 : undefined} style={compact && !embedded && placement ? placement : undefined}>
      {compact && !embedded && <div className="camera-tools-heading">
        <strong>{t("status.toolsTitle")}</strong>
        <button type="button" aria-label={t("status.hideTools")} onClick={() => {
          setExpanded(false); triggerRef.current?.focus({ preventScroll: true });
        }}>×</button>
      </div>}
      {videoControls ? <section className="camera-tools-video-controls" aria-label={t("status.videoControls")}>
        <strong>{t("status.videoControls")}</strong>
        {videoControls}
      </section> : null}
      <div className="status-metrics">
      <span className={`pill ${pillClass}`}>
        <span className="pill-dot" aria-hidden="true" />
        {t(statusKey)}
      </span>
        <span className="status-item" title={t(bodyConfidence !== null ? "status.bodyConfidenceTooltip" : "status.poseConfidenceTooltip")}>
          {t("status.confidence")} <strong>{confidence === null ? "—" : `${Math.round(confidence * 100)}%`}</strong>
        </span>
        <span className="status-item" title={t("status.resolutionTooltip")}>
          {t("status.resolution")} <strong>{detection?.video_size ? `${detection.video_size[0]}×${detection.video_size[1]}` : "—"}</strong>
        </span>
      <span className="status-item">
        <span className={`ws-dot${ws.connected ? " on" : ""}`} aria-hidden="true" />
        {t(ws.connected ? "status.connected" : "status.disconnected")}
      </span>
      <span className="status-item">
        {t("status.rate")} <strong>{ws.detectionsPerSec}/s</strong>
      </span>
        <span
          className={`status-item${distance.pitchPx !== null && distance.minimumPx !== null && distance.pitchPx < distance.minimumPx ? " status-warning" : ""}`}
          title={t("status.geometryTooltip")}
        >
          {t("status.pitch")} <strong>{pitchText}</strong>
        </span>
        <span
          className={`status-item${poseQuality?.inlier_board_area_frac != null && poseQuality.inlier_board_area_frac < 0.05 ? " status-warning" : ""}`}
          title={t("status.poseQualityTooltip")}
        >
          {t("status.poseQuality")} <strong>{poseQuality?.inliers != null && poseQuality.reproj_px != null ? `${poseQuality.inliers} / ${poseQuality.reproj_px.toFixed(2)}px` : "—"}</strong>
        </span>
        <span
          className="status-item status-warning"
          title={accuracy?.warnings.join(" | ")}
        >
          {accuracy && accuracy.status !== "ready" ? t("status.accuracyWarning") : "—"}
        </span>
        <span className={`status-item guidance-${ws.guidance?.status ?? "idle"}`}>
          {ws.guidance ? t("status.guidance", { status: ws.guidance.status, pin: guidancePin ?? ws.guidance.expected_pin_id }) : "—"}
        </span>
      </div>
      <div className="status-actions">
      <button
        type="button"
        className="calibrate-trigger"
        onClick={() => openTool(onOpenCalibrate)}
        disabled={calibrateDisabled || cameraTuningBusy}
        title={t("calibrate.triggerTooltip")}
      >
        {t("calibrate.triggerLabel")}
      </button>
      {cameraPickerVisible && (
        <button
          type="button"
          className="camera-trigger"
          onClick={() => openTool(onOpenCameraPicker)}
          disabled={cameraPickerDisabled || cameraTuningBusy}
          title={t("camera.triggerTooltip")}
        >
          {t("camera.triggerLabel")}
        </button>
      )}
      {webcamTuningVisible && <details className="distance-assistant">
        <summary title={t("distanceAssistant.tooltip")}>{t("distanceAssistant.title")}</summary>
        <div className={`distance-assistant-panel ${distance.state}`} role="group" aria-label={t("distanceAssistant.title")}>
          <strong aria-live="polite">{t(`distanceAssistant.${distance.state}`)}</strong>
          {distance.boundaryUnverified && <span>{t("distanceAssistant.boundaryUnverified")}</span>}
          {distance.pitchPx !== null && distance.minimumPx !== null && distance.targetPx !== null && <>
            <span>{t(distance.sampleFresh ? "distanceAssistant.pitch" : "distanceAssistant.lastPitch", { current: distance.pitchPx.toFixed(1), minimum: distance.minimumPx.toFixed(1) })}</span>
            <div className="distance-scale-track" role="meter" aria-label={t("distanceAssistant.meter")} aria-valuemin={0}
              aria-valuemax={Math.ceil(distance.targetPx)} aria-valuenow={Math.min(Math.round(distance.pitchPx), Math.ceil(distance.targetPx))}>
              <span style={{ width: `${Math.min(100, Math.round(distance.pitchPx / distance.targetPx * 20) * 5)}%` }} />
            </div>
            <span>{t("distanceAssistant.target", { target: distance.targetPx.toFixed(1) })}</span>
            {(distance.state === "moveCloser" || distance.state === "addMargin") && distance.factor !== null &&
              <span>{t("distanceAssistant.move", { factor: distance.factor.toFixed(1) })}</span>}
          </>}
          {expectedBoard === "raspberry-pi-5" && <CameraAutoTune
            disabled={cameraPickerDisabled || expectedRevision == null} onBusyChange={setCameraTuningBusy}
            alignment={{ detection, distance, receivedAtMs, now: Math.max(now, receivedAtMs), synchronized: motion !== undefined,
              context: `${expectedBoard}:${expectedRevision ?? ""}` }} />}
          <small>{t("distanceAssistant.limit")}</small>
        </div>
      </details>}
      {webcamTuningVisible && expectedBoard !== "raspberry-pi-5" &&
        <CameraAutoTune disabled={cameraPickerDisabled} onBusyChange={setCameraTuningBusy} />}
      <button
        type="button"
        className="smart-glasses-trigger"
        onClick={() => openTool(onEnterSmartGlassesDemo)}
        disabled={smartGlassesDemoDisabled || cameraTuningBusy}
        title={t("smartGlasses.enterTooltip")}
      >
        {t("smartGlasses.enter")}
      </button>
      <button
        type="button"
        className="optical-hud-trigger"
        onClick={() => openTool(onEnterOpticalHud)}
        disabled={opticalHudDisabled || cameraTuningBusy}
        title={t("opticalHud.enterTooltip")}
      >
        {t("opticalHud.enter")}
      </button>
      </div>
      </div>
  );
  return (
    <div className={`statusbar${compact ? " camera-tools-menu" : ""}${embedded ? " camera-tools-embedded" : ""}${expanded ? " expanded" : ""}`} hidden={!active}>
      <button ref={triggerRef} type="button" className="statusbar-toggle" aria-expanded={expanded} aria-controls="camera-status-details"
        aria-haspopup={compact && !embedded ? "dialog" : undefined}
        onClick={() => { setNow(Date.now()); setExpanded(open => !open); }}>
        <span aria-hidden="true">{compact ? "⚙" : expanded ? "▾" : "▴"}</span>
        {t(compact ? "status.tools" : expanded ? "status.hideTools" : "status.showTools")}
      </button>
      {compact && !embedded && typeof document !== "undefined" ? portalHost ? createPortal(content, portalHost) : null : content}
    </div>
  );
}
