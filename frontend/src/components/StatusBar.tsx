import { useI18n } from "../lib/i18n";
import { useDetections } from "../lib/wsClient";
import { pinDisplayNameWithNumber } from "../lib/capabilities";
import type { AccuracySummary, Pin } from "../lib/types";
import { CameraAutoTune } from "./CameraAutoTune";
import { useState } from "react";

interface StatusBarProps {
  webcamTuningVisible?: boolean;
  /** Opens the "新增/校正板型" admin panel. */
  onOpenCalibrate: () => void;
  /** True while there's no loaded board profile to calibrate against (or the backend is down). */
  calibrateDisabled: boolean;
  /** Opens the "切換鏡頭" camera picker panel. */
  onOpenCameraPicker: () => void;
  /** Whether the trigger renders at all — false in synthetic-camera mode or when no device cameras were found. */
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
}

export function StatusBar({
  webcamTuningVisible = false,
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
}: StatusBarProps) {
  const { t } = useI18n();
  const [cameraTuningBusy, setCameraTuningBusy] = useState(false);
  const { detection, connected, detectionsPerSec, guidance } = useDetections();

  const tracking = detection?.tracking ?? "searching";
  const confidence =
    detection && tracking !== "searching" ? Math.round(detection.confidence * 100) : null;
  const liveGeometry = detection?.geometry;
  const poseQuality = detection?.pose_quality;
  const guidancePin = guidance
    ? pinDisplayNameWithNumber(pinsById.get(guidance.expected_pin_id)) || guidance.expected_pin_id
    : null;

  return (
    <div className="statusbar">
      <div className="status-metrics">
      <span className={`pill ${tracking}`}>
        <span className="pill-dot" aria-hidden="true" />
        {t(`status.${tracking}`)}
      </span>
        <span className="status-item">
          {t("status.confidence")} <strong>{confidence === null ? "—" : `${confidence}%`}</strong>
        </span>
        <span className="status-item" title={t("status.resolutionTooltip")}>
          {t("status.resolution")} <strong>{detection?.video_size ? `${detection.video_size[0]}×${detection.video_size[1]}` : "—"}</strong>
        </span>
      <span className="status-item">
        <span className={`ws-dot${connected ? " on" : ""}`} aria-hidden="true" />
        {t(connected ? "status.connected" : "status.disconnected")}
      </span>
      <span className="status-item">
        {t("status.rate")} <strong>{detectionsPerSec}/s</strong>
      </span>
        <span
          className={`status-item${liveGeometry && liveGeometry.px_per_mm < 8 ? " status-warning" : ""}`}
          title={t("status.geometryTooltip")}
        >
          {t("status.pitch")} <strong>{liveGeometry ? `${liveGeometry.pitch_px.toFixed(1)}px / ${liveGeometry.px_per_mm.toFixed(2)} px/mm` : "—"}</strong>
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
        <span className={`status-item guidance-${guidance?.status ?? "idle"}`}>
          {guidance ? t("status.guidance", { status: guidance.status, pin: guidancePin ?? guidance.expected_pin_id }) : "—"}
        </span>
      </div>
      <div className="status-actions">
      <button
        type="button"
        className="calibrate-trigger"
        onClick={onOpenCalibrate}
        disabled={calibrateDisabled || cameraTuningBusy}
        title={t("calibrate.triggerTooltip")}
      >
        {t("calibrate.triggerLabel")}
      </button>
      {cameraPickerVisible && (
        <button
          type="button"
          className="camera-trigger"
          onClick={onOpenCameraPicker}
          disabled={cameraPickerDisabled || cameraTuningBusy}
          title={t("camera.triggerTooltip")}
        >
          {t("camera.triggerLabel")}
        </button>
      )}
      {webcamTuningVisible ? <CameraAutoTune disabled={cameraPickerDisabled} onBusyChange={setCameraTuningBusy} /> : null}
      <button
        type="button"
        className="smart-glasses-trigger"
        onClick={onEnterSmartGlassesDemo}
        disabled={smartGlassesDemoDisabled || cameraTuningBusy}
        title={t("smartGlasses.enterTooltip")}
      >
        {t("smartGlasses.enter")}
      </button>
      <button
        type="button"
        className="optical-hud-trigger"
        onClick={onEnterOpticalHud}
        disabled={opticalHudDisabled || cameraTuningBusy}
        title={t("opticalHud.enterTooltip")}
      >
        {t("opticalHud.enter")}
      </button>
      </div>
    </div>
  );
}
