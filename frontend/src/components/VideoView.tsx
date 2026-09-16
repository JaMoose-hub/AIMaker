import { useEffect, useMemo, useRef, useState } from "react";
import { computeLetterbox, toDisplay, useElementSize } from "../lib/geometry";
import { pointBounds, placeWiringLabelPair } from "../lib/wiringLabelLayout";
import {
  isDisplayOnlyMode,
  isOpticalHudMode,
  type DisplayMode,
} from "../lib/displayMode";
import { useI18n } from "../lib/i18n";
import {
  createOpticalHudTransform,
  type OpticalHudCalibration,
  type Quad,
} from "../lib/opticalHud";
import type { ActiveGuideTarget } from "../lib/componentWiringGuides";
import { useGuidedPose } from "../lib/useGuidedPose";
import { useDetections } from "../lib/wsClient";
import { useRealtimeTracking } from "../lib/useRealtimeTracking";
import { currentBodyRecognitions, trackingNotices } from "../lib/realtimeFrame";
import type { AppConfig, Pin, TrackingState } from "../lib/types";
import { CalibratePanel } from "./CalibratePanel";
import { ComponentPinOverlay } from "./ComponentPinOverlay";
import { GuideConnectionOverlay } from "./GuideConnectionOverlay";
import { OpticalHudCalibrationOverlay } from "./OpticalHudCalibration";
import { PinOverlay } from "./PinOverlay";
import { ObjectRecognitionOverlay } from "./ObjectRecognitionOverlay";
import { glassesVideoReady, type GlassesStatus } from "../lib/glasses";

const VIDEO_RETRY_MS = 3000;
const MJPEG_STARTUP_TIMEOUT_MS = 1500;
const SNAPSHOT_FRAME_INTERVAL_MS = 40;
const FALLBACK_VIDEO_SIZE: readonly [number, number] = [1280, 720];
const MIRROR_STORAGE_KEY = "boardvision.camera-mirror.v2";
const LEGACY_MIRROR_X_STORAGE_KEY = "boardvision.camera-mirror-x.v1";
// v3 deliberately resets stored display nudges after Pi 5 gained backend J8
// socket snapping.  Old v2 offsets were compensating a different geometry and
// can make the corrected GPIO lattice look wrong again.
const PIN_CALIBRATION_STORAGE_PREFIX = "boardvision.gpio-pin-calibration.v3";
const LEGACY_PIN_CALIBRATION_STORAGE_KEY = "boardvision.gpio-pin-calibration.v1";
const PIN_CALIBRATION_LIMIT_PX = 30;

interface MirrorSettings {
  x: boolean;
  y: boolean;
}

interface PinCalibrationOffset {
  x: number;
  y: number;
}

function initialMirrorSettings(): MirrorSettings {
  if (typeof window === "undefined") return { x: true, y: false };
  try {
    const stored = window.localStorage.getItem(MIRROR_STORAGE_KEY);
    if (stored !== null) {
      const parsed = JSON.parse(stored) as Partial<MirrorSettings>;
      if (typeof parsed.x === "boolean" && typeof parsed.y === "boolean") {
        return { x: parsed.x, y: parsed.y };
      }
    }
    const legacyX = window.localStorage.getItem(LEGACY_MIRROR_X_STORAGE_KEY);
    return { x: legacyX === null ? true : legacyX === "true", y: false };
  } catch {
    return { x: true, y: false };
  }
}

function pinCalibrationStorageKey(boardId: string): string {
  return `${PIN_CALIBRATION_STORAGE_PREFIX}:${boardId}`;
}

function initialPinCalibrationOffset(boardId: string | null): PinCalibrationOffset {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  try {
    if (!boardId) return { x: 0, y: 0 };
    // The v1 value was calibrated for the UNO Q. Never apply that historical
    // nudge to a Pi profile; it was a major source of cross-board drift.
    const stored =
      window.localStorage.getItem(pinCalibrationStorageKey(boardId)) ??
      (boardId === "arduino-uno-q"
        ? window.localStorage.getItem(LEGACY_PIN_CALIBRATION_STORAGE_KEY)
        : null);
    if (stored !== null) {
      const parsed = JSON.parse(stored) as Partial<PinCalibrationOffset>;
      if (typeof parsed.x === "number" && typeof parsed.y === "number") {
        return {
          x: Math.max(-PIN_CALIBRATION_LIMIT_PX, Math.min(PIN_CALIBRATION_LIMIT_PX, parsed.x)),
          y: Math.max(-PIN_CALIBRATION_LIMIT_PX, Math.min(PIN_CALIBRATION_LIMIT_PX, parsed.y)),
        };
      }
    }
  } catch {
    // Use the neutral offset when browser storage is unavailable or invalid.
  }
  return { x: 0, y: 0 };
}

export interface LegendInfo {
  colorVar: string;
  label: string;
  count: number;
}

interface VideoViewProps {
  displayMode: DisplayMode;
  glassesStatus: GlassesStatus | null;
  onGlassesDisplayFps: (fps: number | null) => void;
  config: AppConfig | null;
  pinsById: ReadonlyMap<string, Pin>;
  highlightIds: ReadonlySet<string> | null;
  selectedPinId: string | null;
  onSelectPin: (pinId: string | null) => void;
  backendDown: boolean;
  legend: LegendInfo | null;
  /** `profile.board.outline_mm`; null while the profile hasn't loaded yet. */
  outlineMm: readonly [number, number] | null;
  /** `tx(profile.board.name)`; "" while the profile hasn't loaded yet. */
  boardName: string;
  calibrateOpen: boolean;
  onCloseCalibrate: () => void;
  onCalibrationSuccess: () => void;
  guideTarget: ActiveGuideTarget | null;
  opticalHudCalibration: OpticalHudCalibration | null;
  onOpticalHudCalibrationComplete: (calibration: OpticalHudCalibration) => void;
}

export function VideoView({
  displayMode,
  glassesStatus,
  onGlassesDisplayFps,
  config,
  pinsById,
  highlightIds,
  selectedPinId,
  onSelectPin,
  backendDown,
  legend,
  outlineMm,
  boardName,
  calibrateOpen,
  onCloseCalibrate,
  onCalibrationSuccess,
  guideTarget,
  opticalHudCalibration,
  onOpticalHudCalibrationComplete,
}: VideoViewProps) {
  const { t } = useI18n();
  const original = useDetections();
  const glassesMode = displayMode === "smart-glasses-demo";
  const glassesReady = glassesVideoReady(glassesStatus);
  // Exit changes the UI before DELETE finishes. Wait for the original source
  // and its config revision rather than fetching Eye again in standard mode.
  const glassesLeaving = !glassesMode && (glassesStatus?.active === true || config?.camera_source === "xreal"
    || ["restoring", "stopping"].includes(glassesStatus?.state ?? ""));
  const [realtimeEnabled, setRealtimeEnabled] = useState(true);
  const realtimeActive = glassesMode || (realtimeEnabled && Boolean(config?.realtime_tracking) && config?.board_id === "raspberry-pi-5" && !calibrateOpen
    && !isOpticalHudMode(displayMode));
  const realtime = useRealtimeTracking(realtimeActive && !glassesLeaving && (!glassesMode || glassesReady),
    config?.board_id ?? null,
    glassesMode ? glassesStatus?.runtime_revision ?? -1 : original.hello?.runtime_revision ?? config?.runtime_revision ?? 1,
    glassesMode ? glassesStatus?.requested.fps ?? 30 : 30, glassesMode ? "eye" : "standard");
  useEffect(() => { onGlassesDisplayFps(glassesMode && glassesReady ? realtimeActive ? realtime.fps : null : 0); }, [glassesMode, glassesReady, realtimeActive, realtime.fps, onGlassesDisplayFps]);
  const motionNotices = realtimeActive ? trackingNotices(realtime.frame) : [];
  // Body-only labels belong to Eye. Webcam keeps its original GPIO/Pin
  // overlays and search hint, even when the shared packet carries body data.
  const bodyRecognitions = glassesMode && realtimeActive ? currentBodyRecognitions(realtime.frame, true) : [];
  const motionNames: Record<string, string> = { "raspberry-pi-5": "Pi 5", "hc-sr04": "HC-SR04", "mrd-tf240-8p-cs": "TFT" };
  const displaySnapshot = realtimeActive || glassesLeaving ? {
    ...original,
    detection: realtime.frame?.detection ?? null,
    componentPoses: realtime.frame?.components ?? [],
    detectionReceivedAtMs: realtime.frame?.receivedAt ?? 0,
    componentReceivedAtMs: Object.fromEntries((realtime.frame?.components ?? [])
      .map((pose) => [pose.component_id, realtime.frame!.receivedAt])),
  } : undefined;
  const {
    detection,
    pose: componentPose,
    componentPoses,
    hello,
    connected,
    visualReady: poseVisualReady,
    visualHeld: poseVisualHeld,
    visualDetection: heldGuideDetection,
    visualPose: heldGuidePose,
  } = useGuidedPose(guideTarget, displaySnapshot);
  // New manual lessons use the held visual pose below; the legacy
  // snapshot/colour workflow keeps its original endpoint behaviour.
  const guideVisible = guideTarget?.manualOnly ? poseVisualReady : guideTarget !== null;
  const guidePinId = guideVisible ? guideTarget?.boardPinId ?? null : null;
  const guideSensorPinId = guideVisible ? guideTarget?.componentPinId ?? null : null;
  const guideDetection = guideTarget?.manualOnly && guideVisible ? heldGuideDetection : detection;
  const guideComponentPose = guideTarget?.manualOnly && guideVisible ? heldGuidePose : componentPose;
  const displayedComponentPoses = useMemo(() => {
    if (!guideTarget?.manualOnly || !guideVisible || !heldGuidePose) return componentPoses;
    const hasTarget = componentPoses.some((pose) => pose.component_id === guideTarget.componentId);
    return hasTarget
      ? componentPoses.map((pose) => pose.component_id === guideTarget.componentId ? heldGuidePose : pose)
      : [...componentPoses, heldGuidePose];
  }, [componentPoses, guideTarget, guideVisible, heldGuidePose]);
  const displayOnlyMode = isDisplayOnlyMode(displayMode);
  const opticalHudMode = isOpticalHudMode(displayMode);
  const opticalCalibrationMode = displayMode === "optical-hud-calibration";
  const opticalDemoMode = displayMode === "optical-hud-demo";

  const containerRef = useRef<HTMLDivElement>(null);
  const size = useElementSize(containerRef);
  const boardId = config?.board_id ?? null;
  const [mirror, setMirror] = useState(initialMirrorSettings);
  const [pinCalibrationOpen, setPinCalibrationOpen] = useState(false);
  const [pinCalibrationOffset, setPinCalibrationOffset] = useState(() =>
    initialPinCalibrationOffset(boardId),
  );

  useEffect(() => {
    setPinCalibrationOffset(initialPinCalibrationOffset(boardId));
  }, [boardId]);

  const videoSize: readonly [number, number] =
    detection?.video_size ?? hello?.video_size ?? config?.video_size ?? FALLBACK_VIDEO_SIZE;
  const videoWidth = videoSize[0];
  const videoHeight = videoSize[1];
  // Calibration always uses canonical source orientation. Normal guidance
  // can mirror without changing any backend pixel coordinates.
  const displayedMirrorX = mirror.x && !calibrateOpen && !opticalHudMode && !glassesMode;
  const displayedMirrorY = mirror.y && !calibrateOpen && !opticalHudMode && !glassesMode;
  const displayedPinOffset = glassesMode ? { x: 0, y: 0 } : pinCalibrationOffset;
  const baseLetterbox = useMemo(
    () => computeLetterbox(
      [videoWidth, videoHeight],
      size.width,
      size.height,
      displayedMirrorX,
      displayedMirrorY,
    ),
    [displayedMirrorX, displayedMirrorY, size.height, size.width, videoHeight, videoWidth],
  );
  const opticalTransform = useMemo(
    () => createOpticalHudTransform(
      baseLetterbox,
      opticalHudCalibration,
      size.width,
      size.height,
    ),
    [baseLetterbox, opticalHudCalibration, size.height, size.width],
  );
  const letterbox = opticalDemoMode && opticalTransform ? opticalTransform : baseLetterbox;
  const wiringLabels = useMemo(() => {
    if (boardId !== "raspberry-pi-5" || !guideTarget) return undefined;
    const boardPins = guideDetection?.tracking !== "searching" ? (guideDetection?.pins ?? []).filter(p => p.v) : [];
    const modulePins = guideComponentPose?.tracking !== "searching" ? (guideComponentPose?.pins ?? []).filter(p => p.v) : [];
    const boardPin = boardPins.find(p => p.id === guidePinId);
    const modulePin = modulePins.find(p => p.id === guideSensorPinId);
    const boardPoint = (p: { x: number; y: number }) => toDisplay(letterbox, p.x + displayedPinOffset.x, p.y + displayedPinOffset.y);
    const boardPoints = boardPins.map(boardPoint);
    const modulePoints = modulePins.map(p => toDisplay(letterbox, p.x, p.y));
    if (guideDetection?.tracking !== "searching") boardPoints.push(...(guideDetection?.outline ?? []).map(([x, y]) => toDisplay(letterbox, x, y)));
    if (guideComponentPose?.tracking !== "searching") modulePoints.push(...(guideComponentPose?.outline ?? []).map(([x, y]) => toDisplay(letterbox, x, y)));
    return placeWiringLabelPair(
      { target: boardPin ? boardPoint(boardPin) : null, bounds: pointBounds(boardPoints) },
      { target: modulePin ? toDisplay(letterbox, modulePin.x, modulePin.y) : null, bounds: pointBounds(modulePoints) },
      size.width, size.height,
    );
  }, [boardId, guideTarget, guideDetection, guideComponentPose, guidePinId, guideSensorPinId, letterbox, displayedPinOffset.x, displayedPinOffset.y, size.width, size.height]);
  const tracking: TrackingState = detection?.tracking ?? "searching";
  const opticalCalibrationSource = useMemo<Quad | null>(() => {
    if (detection?.tracking !== "locked" || detection.outline?.length !== 4) return null;
    return detection.outline.map(([x, y]) => [x, y] as const) as unknown as Quad;
  }, [detection]);

  const toggleMirror = (axis: keyof MirrorSettings) => {
    setMirror((current) => {
      const next = { ...current, [axis]: !current[axis] };
      try {
        window.localStorage.setItem(MIRROR_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // The toggle still works for this session when storage is unavailable.
      }
      return next;
    });
  };

  const adjustPinCalibration = (dx: number, dy: number) => {
    setPinCalibrationOffset((current) => {
      const next = {
        x: Math.max(-PIN_CALIBRATION_LIMIT_PX, Math.min(PIN_CALIBRATION_LIMIT_PX, current.x + dx)),
        y: Math.max(-PIN_CALIBRATION_LIMIT_PX, Math.min(PIN_CALIBRATION_LIMIT_PX, current.y + dy)),
      };
      try {
        if (boardId) {
          window.localStorage.setItem(pinCalibrationStorageKey(boardId), JSON.stringify(next));
        }
      } catch {
        // The calibration still applies for this session when storage is unavailable.
      }
      return next;
    });
  };

  const resetPinCalibration = () => {
    setPinCalibrationOffset({ x: 0, y: 0 });
    try {
      if (boardId) window.localStorage.removeItem(pinCalibrationStorageKey(boardId));
      if (boardId === "arduino-uno-q") {
        window.localStorage.removeItem(LEGACY_PIN_CALIBRATION_STORAGE_KEY);
      }
    } catch {
      // Keep the neutral calibration for this session.
    }
  };

  // Arrow buttons describe movement on the displayed (possibly mirrored)
  // video. Convert that intent back to canonical source-pixel coordinates.
  const adjustDisplayedPinCalibration = (dx: number, dy: number) => {
    adjustPinCalibration(displayedMirrorX ? -dx : dx, displayedMirrorY ? -dy : dy);
  };

  // Staggered marker entrance replays only on searching -> locked transitions.
  const previousTrackingRef = useRef<TrackingState>("searching");
  const [lockSeq, setLockSeq] = useState(0);
  useEffect(() => {
    if (previousTrackingRef.current === "searching" && tracking === "locked") {
      setLockSeq((seq) => seq + 1);
    }
    previousTrackingRef.current = tracking;
  }, [tracking]);

  // Prefer the low-overhead MJPEG stream. Some embedded Chromium builds keep
  // that infinite response pending without painting its first frame, so fall
  // back to finite JPEG snapshots when no load event arrives promptly.
  const [videoTransport, setVideoTransport] = useState<"mjpeg" | "snapshot">("mjpeg");
  const [snapshotNonce, setSnapshotNonce] = useState(0);
  const mjpegStartupTimerRef = useRef<number | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (videoTransport !== "mjpeg" || realtimeActive) return;
    mjpegStartupTimerRef.current = window.setTimeout(() => {
      mjpegStartupTimerRef.current = null;
      setVideoTransport("snapshot");
    }, MJPEG_STARTUP_TIMEOUT_MS);
    return () => {
      if (mjpegStartupTimerRef.current !== null) {
        window.clearTimeout(mjpegStartupTimerRef.current);
        mjpegStartupTimerRef.current = null;
      }
    };
  }, [videoTransport, realtimeActive]);
  useEffect(() => () => {
      if (mjpegStartupTimerRef.current !== null) window.clearTimeout(mjpegStartupTimerRef.current);
      if (retryTimerRef.current !== null) window.clearTimeout(retryTimerRef.current);
    }, []);

  const scheduleSnapshot = (delayMs = SNAPSHOT_FRAME_INTERVAL_MS) => {
    if (retryTimerRef.current !== null) return;
    retryTimerRef.current = window.setTimeout(() => {
      retryTimerRef.current = null;
      setSnapshotNonce((nonce) => nonce + 1);
    }, delayMs);
  };

  const handleVideoLoad = () => {
    if (realtimeActive) return;
    if (videoTransport === "mjpeg") {
      if (mjpegStartupTimerRef.current !== null) {
        window.clearTimeout(mjpegStartupTimerRef.current);
        mjpegStartupTimerRef.current = null;
      }
      return;
    }
    scheduleSnapshot();
  };

  const handleVideoError = () => {
    if (realtimeActive) return;
    if (videoTransport === "mjpeg") {
      setVideoTransport("snapshot");
      return;
    }
    scheduleSnapshot(VIDEO_RETRY_MS);
  };

  const offline = backendDown || (!connected && !detection);
  const searching = !offline && tracking === "searching";
  const componentDetected = Boolean(
    componentPoses.some(
      (pose) => pose.tracking !== "searching" || pose.diagnostic?.detected,
    ),
  );
  const showBoardSearchHint = !glassesLeaving && searching && !componentDetected && bodyRecognitions.length === 0 && (!glassesMode || glassesReady);
  const showArOverlays = !glassesLeaving && (!realtimeActive || realtime.frame !== null)
    && !opticalCalibrationMode && (!opticalDemoMode || opticalTransform !== null)
    && (!glassesMode || glassesReady);

  return (
    <div
      ref={containerRef}
      className={`video-shell${realtimeActive ? " realtime-tracking" : ""}${showBoardSearchHint ? " searching" : ""}${displayOnlyMode ? " display-mode-active" : ""}${opticalHudMode ? " optical-hud" : ""}`}
    >
      <img
        key={glassesMode ? `eye-${glassesStatus?.runtime_revision}` : "standard-video"}
        className={`video-img${opticalHudMode || glassesLeaving || (glassesMode && (!glassesReady || (realtimeActive && !realtime.frame))) ? " hidden" : ""}${displayedMirrorX ? " mirrored-x" : ""}${displayedMirrorY ? " mirrored-y" : ""}`}
        src={glassesLeaving || (glassesMode && !glassesReady) ? undefined : realtimeActive && realtime.frame ? realtime.frame.image
          : videoTransport === "mjpeg" ? "/video" : `/frame.jpg?v=${snapshotNonce}`}
        data-tracking-frame={realtimeActive ? realtime.frame?.frame_id : undefined}
        alt=""
        draggable={false}
        onError={handleVideoError}
        onLoad={handleVideoLoad}
      />
      {glassesMode && (!glassesReady || (realtimeActive && !realtime.frame)) && <div className="video-hint"><span className="hint-pill">
        {t(glassesStatus?.state === "error" ? "glasses.noCamera" : "glasses.waiting")}
      </span></div>}
      {!displayOnlyMode && (
        <>
          <div className="mirror-controls" role="group" aria-label={t("camera.mirrorControlsLabel")}>
            {config?.board_id === "raspberry-pi-5" && config.realtime_tracking && <button
              type="button"
              className={`mirror-toggle realtime-toggle${realtimeEnabled ? " active" : ""}`}
              aria-pressed={realtimeEnabled}
              title={t("camera.realtimeTooltip")}
              onClick={() => setRealtimeEnabled((value) => !value)}
            >
              {t("camera.realtime")}{realtimeActive ? ` · ${realtime.frame ? `${realtime.fps} fps` : t("camera.realtimeWaiting")}` : ""}
            </button>}
            <button
              type="button"
              className={`mirror-toggle${mirror.x ? " active" : ""}`}
              aria-pressed={mirror.x}
              title={t("camera.mirrorHorizontalTooltip")}
              disabled={calibrateOpen}
              onClick={() => toggleMirror("x")}
            >
              <span aria-hidden="true">↔</span>
              {t("camera.mirrorHorizontalLabel")}
            </button>
            <button
              type="button"
              className={`mirror-toggle${mirror.y ? " active" : ""}`}
              aria-pressed={mirror.y}
              title={t("camera.mirrorVerticalTooltip")}
              disabled={calibrateOpen}
              onClick={() => toggleMirror("y")}
            >
              <span aria-hidden="true">↕</span>
              {t("camera.mirrorVerticalLabel")}
            </button>
          </div>
          <div className="pin-calibration-controls">
            <button
              type="button"
              className={`pin-calibration-toggle${pinCalibrationOpen ? " active" : ""}`}
              aria-expanded={pinCalibrationOpen}
              title={t("camera.pinCalibrationTooltip")}
              disabled={calibrateOpen}
              onClick={() => setPinCalibrationOpen((open) => !open)}
            >
              {t("camera.pinCalibrationLabel")}
            </button>
            {pinCalibrationOpen && (
              <div className="pin-calibration-panel" role="group" aria-label={t("camera.pinCalibrationControlsLabel")}>
                <small>{t("camera.pinCalibrationHint")}</small>
                <div className="pin-calibration-grid">
                  <span />
                  <button type="button" title={t("camera.pinCalibrationUp")} onClick={() => adjustDisplayedPinCalibration(0, -1)}>↑</button>
                  <span />
                  <button type="button" title={t("camera.pinCalibrationLeft")} onClick={() => adjustDisplayedPinCalibration(-1, 0)}>←</button>
                  <button type="button" title={t("camera.pinCalibrationReset")} onClick={resetPinCalibration}>·</button>
                  <button type="button" title={t("camera.pinCalibrationRight")} onClick={() => adjustDisplayedPinCalibration(1, 0)}>→</button>
                  <span />
                  <button type="button" title={t("camera.pinCalibrationDown")} onClick={() => adjustDisplayedPinCalibration(0, 1)}>↓</button>
                  <span />
                </div>
                <small className="pin-calibration-value">X {pinCalibrationOffset.x} · Y {pinCalibrationOffset.y}</small>
              </div>
            )}
          </div>
        </>
      )}
      {showArOverlays && (
        <>
          {glassesMode && <ObjectRecognitionOverlay items={bodyRecognitions} letterbox={letterbox} width={size.width} height={size.height} />}
          {motionNotices.length > 0 && <div className="tracking-notice" role="status">
            {motionNotices.map(({ id, key }) => <span key={id}>{motionNames[id] ?? id} · {t(key)}</span>)}
          </div>}
          {guideVisible && guideTarget?.connectionKind === "direct" ? <GuideConnectionOverlay
            detection={guideDetection}
            componentPose={guideComponentPose}
            letterbox={letterbox}
            width={size.width}
            height={size.height}
            boardPinId={guidePinId}
            componentPinId={guideSensorPinId}
            boardDisplayOffsetPx={displayedPinOffset}
            held={poseVisualHeld}
          /> : null}
          {displayedComponentPoses.map((pose) => (
            <ComponentPinOverlay
              key={pose.component_id}
              pose={pose}
              letterbox={letterbox}
              width={size.width}
              height={size.height}
              targetPinId={
                pose.component_id === guideTarget?.componentId ? guideSensorPinId : null
              }
              dimmed={Boolean(guideTarget && pose.component_id !== guideTarget.componentId)}
              guidanceSuspended={Boolean(guideTarget?.componentId === pose.component_id && !guideVisible && !realtimeActive)}
              held={Boolean(poseVisualHeld && guideTarget?.componentId === pose.component_id)}
              guideLabel={pose.component_id === guideTarget?.componentId ? wiringLabels?.component : undefined}
            />
          ))}
          {!guideTarget || guideVisible || realtimeActive ? <PinOverlay
            detection={guideDetection}
            letterbox={letterbox}
            width={size.width}
            height={size.height}
            pinsById={pinsById}
            highlightIds={highlightIds}
            selectedPinId={selectedPinId}
            onSelectPin={onSelectPin}
            interactive={!displayOnlyMode}
            lockSeq={lockSeq}
            tracking={poseVisualHeld ? "stale" : guideDetection?.tracking ?? tracking}
            displayOffsetPx={displayedPinOffset}
            guidePinId={guidePinId}
            localGuidanceOnly={guideTarget?.manualOnly ?? false}
            guidanceHeld={poseVisualHeld}
            guidePeerPose={guideComponentPose ? { tracking: guideComponentPose.tracking, outline: guideComponentPose.outline, pins: guideComponentPose.pins } : null}
            guidePeerPinId={guideSensorPinId}
            guideLabel={wiringLabels?.board}
          /> : null}
          {guideTarget && (!guideVisible || poseVisualHeld || guideTarget.connectionKind === "divider") ? (
            <div className={`wiring-hud-note${poseVisualHeld ? " held" : ""}`} role="status">
              {t(!guideVisible ? guideTarget.manualOnly ? "wiring.manualUnlocated" : "wiring.paused" : poseVisualHeld ? guideTarget.manualOnly ? "wiring.manualUnlocated" : "wiring.trackingHold" : "wiring.dividerHud")}
            </div>
          ) : null}
        </>
      )}
      {legend && !opticalCalibrationMode && (
        <div className="video-legend">
          <span className="legend-dot" style={{ background: `var(${legend.colorVar})` }} />
          <span className="legend-label">{legend.label}</span>
          <span className="legend-count">{t("legend.count", { count: legend.count })}</span>
        </div>
      )}
      {offline && !glassesMode && (
        <div className="video-hint">
          <span className="hint-pill offline">
            {t("backend.down")} · {t("backend.retrying")}
          </span>
        </div>
      )}
      {glassesMode && showBoardSearchHint && (
        <div className="video-hint">
          <span className="hint-pill">
            {boardName ? t("hint.placeBoard", { board: boardName }) : t("hint.placeBoardGeneric")}
          </span>
        </div>
      )}
      {!displayOnlyMode && (
        <CalibratePanel
          open={calibrateOpen}
          onClose={onCloseCalibrate}
          onCalibrationSuccess={onCalibrationSuccess}
          videoSize={videoSize}
          letterbox={letterbox}
          containerWidth={size.width}
          containerHeight={size.height}
          outlineMm={outlineMm}
          detection={detection}
        />
      )}
      {opticalCalibrationMode && (
        <OpticalHudCalibrationOverlay
          width={size.width}
          height={size.height}
          sourceCorners={opticalCalibrationSource}
          onComplete={onOpticalHudCalibrationComplete}
        />
      )}
      {opticalDemoMode && opticalTransform && (
        <div className="optical-hud-fixed-head" role="status">
          <span aria-hidden="true" />
          {t("opticalHud.fixedHead")}
        </div>
      )}
    </div>
  );
}
