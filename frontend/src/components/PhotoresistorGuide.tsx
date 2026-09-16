import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  deleteGuidanceStep,
  fetchGuidanceState,
  postGuidanceColorSample,
  postGuidanceElectricalCheck,
  postGuidanceStep,
} from "../lib/api";
import type {
  GuidanceColorCheckResponse,
  GuidanceColorEndpoint,
  GuidanceColorEndpointName,
} from "../lib/api";
import type { VerificationUpdateMessage } from "../lib/types";
import { useI18n } from "../lib/i18n";
import {
  builtinWiringGuideProfile,
  parseWiringGuideProfile,
  WiringGuideProfileError,
  type GuideComponentPinId,
  type WiringGuideProfile,
} from "../lib/wiringGuideProfiles";
import { clearGuidanceSnapshot, useVerification } from "../lib/wsClient";

interface PhotoresistorGuideProps {
  boardId: string;
  boardName: string;
  availablePinIds: ReadonlySet<string>;
  disabled: boolean;
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
  onTargetPinChange: (pinId: string | null) => void;
  onTargetSensorPinChange: (pinId: GuideComponentPinId | null) => void;
}

type GuideMode = "idle" | "active" | "complete";
type ColorSamples = Partial<Record<GuidanceColorEndpointName, GuidanceColorEndpoint>>;
type GuideProfileSource = "builtin" | "imported";

const IMPORTED_PROFILE_STORAGE_PREFIX = "boardvision.wiring-guide-profile.v1";
const PROFILE_SOURCE_STORAGE_PREFIX = "boardvision.wiring-guide-source.v1";
const MAX_IMPORTED_PROFILE_BYTES = 256 * 1024;

function importedProfileStorageKey(boardId: string): string {
  return `${IMPORTED_PROFILE_STORAGE_PREFIX}:${boardId}`;
}

function profileSourceStorageKey(boardId: string): string {
  return `${PROFILE_SOURCE_STORAGE_PREFIX}:${boardId}`;
}

function loadImportedProfile(
  boardId: string,
  availablePinIds: ReadonlySet<string>,
): WiringGuideProfile | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(importedProfileStorageKey(boardId));
    return raw ? parseWiringGuideProfile(JSON.parse(raw), boardId, availablePinIds) : null;
  } catch {
    return null;
  }
}

function loadInitialProfileSource(
  boardId: string,
  importedProfile: WiringGuideProfile | null,
): GuideProfileSource {
  if (!importedProfile || typeof window === "undefined") return "builtin";
  try {
    return window.localStorage.getItem(profileSourceStorageKey(boardId)) === "imported"
      ? "imported"
      : "builtin";
  } catch {
    return "builtin";
  }
}

// Lightness changes easily when the user moves from an UNO close-up to a
// Sensor close-up. Compare Lab chroma (a/b) so the same brown lead does not
// become a false mismatch merely because one end is brighter.
const LAB_CHROMA_MATCH_THRESHOLD = 18;

function labChromaDelta(
  left: GuidanceColorEndpoint | undefined,
  right: GuidanceColorEndpoint | undefined,
): number | undefined {
  if (!left?.lab || !right?.lab) return undefined;
  return Math.hypot(left.lab[1] - right.lab[1], left.lab[2] - right.lab[2]);
}

function compareColorSamples(samples: ColorSamples): GuidanceColorCheckResponse | null {
  const board = samples.board;
  const component = samples.component;
  if (!board && !component) return null;

  const boardColor = board?.color;
  const componentColor = component?.color;
  const bothSaved = Boolean(board && component);
  const labDeltaE = labChromaDelta(board, component);
  let status: GuidanceColorCheckResponse["status"];
  let reason: string;
  if (!bothSaved) {
    status = "partial";
    reason = "awaiting_other_endpoint";
  } else if (board?.ambiguous || component?.ambiguous) {
    status = "ambiguous";
    reason = "multiple_pin_exit_candidates";
  } else if (boardColor && componentColor) {
    const labSupportsMatch = labDeltaE !== undefined && labDeltaE <= LAB_CHROMA_MATCH_THRESHOLD;
    status = boardColor === componentColor || labSupportsMatch ? "match" : "mismatch";
    reason = status === "match"
      ? labSupportsMatch && boardColor !== componentColor
        ? "lab_chroma_matches"
        : "colors_match"
      : "colors_differ";
  } else if (boardColor || componentColor) {
    status = "partial";
    reason = "one_endpoint_color_visible";
  } else {
    status = "unknown";
    reason = "no_color_evidence";
  }

  return {
    ok: true,
    status,
    reason,
    confidence: bothSaved
      ? Math.min(board?.confidence ?? 0, component?.confidence ?? 0)
      : board?.confidence ?? component?.confidence ?? 0,
    connection_proximity: bothSaved
      ? Math.min(board?.pin_proximity ?? 0, component?.pin_proximity ?? 0)
      : undefined,
    lab_delta_e: labDeltaE === undefined ? undefined : Number(labDeltaE.toFixed(1)),
    board,
    component,
    advisory: true,
  };
}

export function PhotoresistorGuide({
  boardId,
  boardName,
  availablePinIds,
  disabled,
  visible,
  onVisibleChange,
  onTargetPinChange,
  onTargetSensorPinChange,
}: PhotoresistorGuideProps) {
  const { t, tx } = useI18n();
  const verification = useVerification();
  const builtinProfile = builtinWiringGuideProfile(boardId);
  const [importedProfile, setImportedProfile] = useState<WiringGuideProfile | null>(() =>
    loadImportedProfile(boardId, availablePinIds),
  );
  const [profileSource, setProfileSource] = useState<GuideProfileSource>(() =>
    loadInitialProfileSource(boardId, importedProfile),
  );
  const [profileError, setProfileError] = useState<string | null>(null);
  const profileInputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<GuideMode>("idle");
  const [stepIndex, setStepIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [electricalBusy, setElectricalBusy] = useState(false);
  const [electricalRequestedLocally, setElectricalRequestedLocally] = useState(false);
  const [electricalError, setElectricalError] = useState<string | null>(null);
  const [verificationSnapshot, setVerificationSnapshot] = useState<VerificationUpdateMessage | null>(null);
  const [colorBusyEndpoint, setColorBusyEndpoint] = useState<GuidanceColorEndpointName | null>(null);
  const [colorError, setColorError] = useState<string | null>(null);
  const [colorSamples, setColorSamples] = useState<ColorSamples>({});
  const [colorPreview, setColorPreview] = useState<{
    endpoint: GuidanceColorEndpointName;
    version: number;
  } | null>(null);

  const guideProfile = profileSource === "imported" && importedProfile
    ? importedProfile
    : builtinProfile;
  const steps = guideProfile?.steps ?? [];
  const step = steps[stepIndex] ?? null;

  useEffect(() => {
    setVerificationSnapshot(null);
    if (mode !== "active" || !step) return undefined;

    let cancelled = false;
    const sync = () => {
      void fetchGuidanceState()
        .then((state) => {
          if (!cancelled) setVerificationSnapshot(state.verification);
        })
        .catch(() => {
          // Keep any WebSocket update already received; the next poll can recover.
        });
    };
    sync();
    const intervalId = window.setInterval(sync, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [mode, step?.id]);

  const currentVerification = step && verification?.target.step_id === step.id
    ? verification
    : step && verificationSnapshot?.target.step_id === step.id
      ? verificationSnapshot
      : null;
  const electricalEvidence = currentVerification?.evidence.electrical;
  const electricalRequested = Boolean(
    currentVerification?.target.electrical_requested || electricalRequestedLocally,
  );
  const electricalRunning = electricalRequested
    && electricalEvidence?.status === "uncertain"
    && electricalEvidence.reason !== "serial_unavailable";
  const electricalSupported = Boolean(currentVerification?.target.electrical_supported);
  const electricalNotice = electricalError ?? t(
    !currentVerification
      ? "photoGuide.electricalStatusLoading"
      : !electricalSupported
      ? "photoGuide.electricalUnavailable"
      : electricalEvidence?.status === "pass"
        ? "photoGuide.electricalComplete"
        : electricalRunning
          ? "photoGuide.electricalRunningHint"
          : "photoGuide.electricalHint",
  );
  const colorResult = compareColorSamples(colorSamples);
  const colorPairReady = Boolean(colorSamples.board && colorSamples.component);
  const colorName = (color: string | null | undefined) =>
    t(`photoGuide.colorName.${color ?? "unknown"}`);
  const sampledColorName = (endpoint: GuidanceColorEndpoint | undefined) =>
    endpoint ? colorName(endpoint.color) : t("photoGuide.colorNotSampled");
  const pinProximity = (endpoint: GuidanceColorEndpoint | undefined) =>
    Math.round((endpoint?.pin_proximity ?? 0) * 100);
  const formattedPinProximity = (endpoint: GuidanceColorEndpoint | undefined) =>
    endpoint ? `${pinProximity(endpoint)}%` : "–";
  const controllerLabel = guideProfile ? tx(guideProfile.controller_label) : boardName;
  const colorNotice = colorError ?? t(
    colorBusyEndpoint === "board"
      ? "photoGuide.colorCheckingController"
      : colorBusyEndpoint === "component"
        ? "photoGuide.colorCheckingSensor"
        : !colorResult
          ? "photoGuide.colorHint"
          : !colorPairReady
            ? "photoGuide.colorAwaitingOther"
            : colorResult.status === "match"
              ? "photoGuide.colorMatch"
              : colorResult.status === "mismatch"
                ? "photoGuide.colorMismatch"
                : colorResult.status === "partial"
                  ? "photoGuide.colorPartial"
                  : colorResult.status === "ambiguous"
                    ? "photoGuide.colorAmbiguous"
                    : "photoGuide.colorUnknown",
    { controller: controllerLabel },
  );

  const selectProfileSource = useCallback((next: GuideProfileSource) => {
    if (mode === "active" || (next === "imported" && !importedProfile)) return;
    setProfileError(null);
    setProfileSource(next);
    setStepIndex(0);
    setMode("idle");
    onTargetPinChange(null);
    onTargetSensorPinChange(null);
    try {
      window.localStorage.setItem(profileSourceStorageKey(boardId), next);
    } catch {
      // Selection remains valid for this session if storage is unavailable.
    }
  }, [boardId, importedProfile, mode, onTargetPinChange, onTargetSensorPinChange]);

  const handleProfileSourceChange = useCallback((event: ChangeEvent<HTMLSelectElement>) => {
    selectProfileSource(event.currentTarget.value as GuideProfileSource);
  }, [selectProfileSource]);

  const handleProfileImport = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file || mode === "active") return;
    setProfileError(null);
    try {
      if (file.size > MAX_IMPORTED_PROFILE_BYTES) {
        throw new Error(t("photoGuide.profileTooLarge"));
      }
      const parsed = parseWiringGuideProfile(
        JSON.parse(await file.text()),
        boardId,
        availablePinIds,
      );
      setImportedProfile(parsed);
      setProfileSource("imported");
      setStepIndex(0);
      setMode("idle");
      onTargetPinChange(null);
      onTargetSensorPinChange(null);
      try {
        window.localStorage.setItem(importedProfileStorageKey(boardId), JSON.stringify(parsed));
        window.localStorage.setItem(profileSourceStorageKey(boardId), "imported");
      } catch {
        // The imported profile still works for this session.
      }
    } catch (reason) {
      setProfileError(
        reason instanceof WiringGuideProfileError
          ? t(`photoGuide.profileError.${reason.code}`, reason.params)
          : reason instanceof Error && reason.message === t("photoGuide.profileTooLarge")
            ? reason.message
            : t("photoGuide.profileInvalid"),
      );
    }
  }, [availablePinIds, boardId, mode, onTargetPinChange, onTargetSensorPinChange, t]);

  const deleteImportedProfile = useCallback(() => {
    if (mode === "active") return;
    setImportedProfile(null);
    setProfileSource("builtin");
    setProfileError(null);
    setStepIndex(0);
    setMode("idle");
    onTargetPinChange(null);
    onTargetSensorPinChange(null);
    try {
      window.localStorage.removeItem(importedProfileStorageKey(boardId));
      window.localStorage.setItem(profileSourceStorageKey(boardId), "builtin");
    } catch {
      // State has already been cleared for this session.
    }
  }, [boardId, mode, onTargetPinChange, onTargetSensorPinChange]);

  const activateStep = useCallback(
    async (nextIndex: number) => {
      const next = guideProfile?.steps[nextIndex];
      if (!guideProfile || !next) {
        setError(t("photoGuide.profileMissing"));
        return;
      }
      setBusy(true);
      setError(null);
      try {
        const response = await postGuidanceStep({
          expected_pin_id: next.board_pin_id,
          expected_role: next.component_pin_id,
          component_id: guideProfile.component_id,
          hint_color: next.wire_class,
          step_id: next.id,
          advance_mode: "confirm",
        });
        if (!response.ok) {
          const errorCode = response.error_code ?? response.error ?? "unknown";
          setError(t(
            `photoGuide.startError.${errorCode}`,
            response.params as Record<string, string | number> | undefined,
          ));
          return;
        }
        clearGuidanceSnapshot();
        setElectricalBusy(false);
        setElectricalRequestedLocally(false);
        setElectricalError(null);
        setColorBusyEndpoint(null);
        setColorError(null);
        setColorSamples({});
        setColorPreview(null);
        setStepIndex(nextIndex);
        setMode("active");
        onTargetPinChange(next.board_pin_id);
        onTargetSensorPinChange(next.component_pin_id);
      } catch {
        setError(t("photoGuide.error"));
      } finally {
        setBusy(false);
      }
    },
    [guideProfile, onTargetPinChange, onTargetSensorPinChange, t],
  );

  const runElectricalCheck = useCallback(async () => {
    setElectricalBusy(true);
    setElectricalError(null);
    try {
      const response = await postGuidanceElectricalCheck();
      if (!response.ok) {
        const key = `photoGuide.electricalError.${response.error_code ?? response.error ?? "unknown"}`;
        setElectricalError(t(key));
        return;
      }
      setElectricalRequestedLocally(true);
    } catch {
      setElectricalError(t("photoGuide.electricalError.unknown"));
    } finally {
      setElectricalBusy(false);
    }
  }, [t]);

  const runColorCheck = useCallback(async (endpoint: GuidanceColorEndpointName) => {
    setColorBusyEndpoint(endpoint);
    setColorError(null);
    setColorPreview(null);
    try {
      const response = await postGuidanceColorSample(endpoint);
      if (!response.ok || !response.sample) {
        setColorError(t(`photoGuide.colorError.${response.error_code ?? response.error ?? "unknown"}`));
        return;
      }
      setColorSamples((current) => ({ ...current, [endpoint]: response.sample }));
    } catch {
      setColorError(t("photoGuide.colorError.unknown"));
    } finally {
      setColorBusyEndpoint(null);
    }
  }, [t]);

  const finish = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteGuidanceStep();
      clearGuidanceSnapshot();
      setElectricalRequestedLocally(false);
      setColorBusyEndpoint(null);
      setColorError(null);
      setColorSamples({});
      setColorPreview(null);
      setMode("complete");
      onTargetPinChange(null);
      onTargetSensorPinChange(null);
    } catch {
      setError(t("photoGuide.error"));
    } finally {
      setBusy(false);
    }
  }, [onTargetPinChange, onTargetSensorPinChange, t]);

  const reset = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "active") await deleteGuidanceStep();
      clearGuidanceSnapshot();
      setElectricalBusy(false);
      setElectricalRequestedLocally(false);
      setElectricalError(null);
      setColorBusyEndpoint(null);
      setColorError(null);
      setColorSamples({});
      setColorPreview(null);
      setMode("idle");
      setStepIndex(0);
      onTargetPinChange(null);
      onTargetSensorPinChange(null);
    } catch {
      setError(t("photoGuide.error"));
    } finally {
      setBusy(false);
    }
  }, [mode, onTargetPinChange, onTargetSensorPinChange, t]);

  return (
    <section
      className={`photo-guide ${mode}`}
      aria-live="polite"
      aria-label={t("photoGuide.panelLabel")}
      hidden={!visible}
    >
      <div className="photo-guide-head">
        <div className="photo-guide-heading">
          <div className="card-kicker">{t("photoGuide.kicker")}</div>
          <h2>{t("photoGuide.title")}</h2>
        </div>
        <div className="photo-guide-head-actions">
          {mode === "active" && (
            <span className="photo-guide-progress">
              {t("photoGuide.progress", { current: stepIndex + 1, total: steps.length })}
            </span>
          )}
          <button
            type="button"
            className="photo-guide-close"
            aria-label={t("photoGuide.hide")}
            title={t("photoGuide.hide")}
            onClick={() => onVisibleChange(false)}
          >
            ×
          </button>
        </div>
      </div>

      {mode === "idle" && (
        <>
          <div className="photo-guide-profile-controls">
            <label>
              <span>{t("photoGuide.profileLabel")}</span>
              <select
                value={profileSource}
                disabled={busy}
                onChange={handleProfileSourceChange}
              >
                <option value="builtin" disabled={!builtinProfile}>
                  {builtinProfile
                    ? t("photoGuide.profileBuiltin", { name: tx(builtinProfile.name) })
                    : t("photoGuide.profileNoBuiltin")}
                </option>
                {importedProfile ? (
                  <option value="imported">
                    {t("photoGuide.profileImported", { name: tx(importedProfile.name) })}
                  </option>
                ) : null}
              </select>
            </label>
            <input
              ref={profileInputRef}
              className="photo-guide-profile-input"
              type="file"
              accept=".json,application/json"
              tabIndex={-1}
              onChange={(event) => void handleProfileImport(event)}
            />
            <button
              type="button"
              className="photo-guide-profile-button"
              disabled={busy}
              onClick={() => profileInputRef.current?.click()}
            >
              {t("photoGuide.profileImport")}
            </button>
            <a
              className="photo-guide-profile-button"
              href={
                boardId === "raspberry-pi-5"
                  ? "/examples/wiring-guide-profile.pi5.json"
                  : "/examples/wiring-guide-profile.uno-q.json"
              }
              download
            >
              {t("photoGuide.profileExample")}
            </a>
            {importedProfile ? (
              <button
                type="button"
                className="photo-guide-profile-delete"
                disabled={busy}
                onClick={deleteImportedProfile}
              >
                {t("photoGuide.profileDelete")}
              </button>
            ) : null}
          </div>
          <p className="photo-guide-copy">
            {guideProfile ? tx(guideProfile.intro) : t("photoGuide.profileMissing")}
          </p>
          <div className="photo-guide-route" aria-label={t("photoGuide.routeLabel")}>
            {steps.map((routeStep) => (
              <span key={routeStep.id}>
                {routeStep.board_label} → {routeStep.component_pin_id}
              </span>
            ))}
          </div>
          <p className="photo-guide-safety">
            {guideProfile ? tx(guideProfile.safety) : t("photoGuide.profileMissing")}
          </p>
          <button
            type="button"
            className="photo-guide-primary"
            disabled={disabled || busy || !guideProfile || steps.length === 0}
            onClick={() => void activateStep(0)}
          >
            {busy ? t("photoGuide.loading") : t("photoGuide.start")}
          </button>
          {profileError ? (
            <div className="photo-guide-profile-error" role="alert">
              {t("photoGuide.profileInvalid")} · {profileError}
            </div>
          ) : null}
        </>
      )}

      {mode === "active" && step && guideProfile && (
        <>
          <div className="photo-guide-instruction">
            <span className={`photo-guide-step-dot ${step.wire_class}`}>{stepIndex + 1}</span>
            <div>
              <strong>{tx(step.instruction)}</strong>
              <p>{tx(step.hint)}</p>
            </div>
          </div>

          <div className="photo-guide-map">
            <div className="photo-guide-endpoint controller">
              <small>{tx(guideProfile.controller_label)}</small>
              <strong>{step.board_label}</strong>
            </div>
            <div className={`photo-guide-wire ${step.wire_class}`} aria-hidden="true" />
            <div className="photo-guide-sensor">
              <small>{tx(guideProfile.component_label)}</small>
              <div className="sensor-pins">
                {(["VCC", "GND", "AO"] as const).map((pin) => (
                  <span
                    key={pin}
                    className={pin === step.component_pin_id ? `active ${step.wire_class}` : "dim"}
                  >
                    <i aria-hidden="true" />
                    {pin}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="photo-guide-checks">
            {/* VLM connector and final-image checks are intentionally removed
                from the MVP flow. HSV remains advisory; Serial is the final
                functional evidence on the AO step. */}
            <div className="photo-guide-check-row photo-guide-color-check">
              <div className="photo-guide-color-sample-actions">
                <button
                  type="button"
                  className="photo-guide-check-button color"
                  disabled={busy || colorBusyEndpoint !== null}
                  onClick={() => void runColorCheck("board")}
                >
                  {colorBusyEndpoint === "board"
                    ? t("photoGuide.colorCheckingController", { controller: controllerLabel })
                    : t("photoGuide.colorSampleController", { controller: controllerLabel })}
                </button>
                <button
                  type="button"
                  className="photo-guide-check-button color"
                  disabled={busy || colorBusyEndpoint !== null}
                  onClick={() => void runColorCheck("component")}
                >
                  {colorBusyEndpoint === "component"
                    ? t("photoGuide.colorCheckingSensor")
                    : t("photoGuide.colorSampleSensor")}
                </button>
              </div>
              <span className={colorError ? "error" : ""}>{colorNotice}</span>
            </div>
            {colorResult ? (
              <>
                <div className={`photo-guide-color-result ${colorResult.status ?? "unknown"}`}>
                  <span>{t("photoGuide.colorController", {
                    controller: controllerLabel,
                    color: sampledColorName(colorResult.board),
                  })}</span>
                  <span aria-hidden="true">↔</span>
                  <span>{t("photoGuide.colorSensor", { color: sampledColorName(colorResult.component) })}</span>
                  <strong>
                    {colorPairReady
                      ? t(`photoGuide.colorStatus.${colorResult.status ?? "unknown"}`)
                      : t("photoGuide.colorAwaitingOther")}
                    {" · "}{Math.round((colorResult.confidence ?? 0) * 100)}%
                  </strong>
                  <div className="photo-guide-color-proximity">
                    <span>
                      <small>{t("photoGuide.colorProximityController", { controller: controllerLabel })}</small>
                      <b>{formattedPinProximity(colorResult.board)}</b>
                    </span>
                    <span>
                      <small>{t("photoGuide.colorProximitySensor")}</small>
                      <b>{formattedPinProximity(colorResult.component)}</b>
                    </span>
                    <strong>
                      {colorPairReady
                        ? <>{t("photoGuide.colorProximityConnection")}{" · "}{Math.round((colorResult.connection_proximity ?? 0) * 100)}%</>
                        : t("photoGuide.colorAwaitingOther")}
                    </strong>
                  </div>
                  {colorPairReady && colorResult.lab_delta_e !== undefined ? (
                    <small className="photo-guide-color-lab">
                      {t("photoGuide.colorLabDelta", { value: colorResult.lab_delta_e.toFixed(1) })}
                    </small>
                  ) : null}
                </div>
                {colorResult.board?.electrically_equivalent && colorResult.board.pin_id ? (
                  <small className="photo-guide-color-equivalent">
                    {t("photoGuide.colorEquivalentGround", { pin: colorResult.board.pin_id })}
                  </small>
                ) : null}
                <div className="photo-guide-preview-actions">
                  {colorResult.board ? (
                    <button
                      type="button"
                      className="photo-guide-preview-button"
                      onClick={() => setColorPreview((current) => current?.endpoint === "board"
                        ? null
                        : { endpoint: "board", version: Date.now() })}
                    >
                      {t(colorPreview?.endpoint === "board"
                        ? "photoGuide.colorPreviewHide"
                        : "photoGuide.colorPreviewController", { controller: controllerLabel })}
                    </button>
                  ) : null}
                  {colorResult.component ? (
                    <button
                      type="button"
                      className="photo-guide-preview-button"
                      onClick={() => setColorPreview((current) => current?.endpoint === "component"
                        ? null
                        : { endpoint: "component", version: Date.now() })}
                    >
                      {t(colorPreview?.endpoint === "component"
                        ? "photoGuide.colorPreviewHide"
                        : "photoGuide.colorPreviewSensor")}
                    </button>
                  ) : null}
                </div>
                {colorPreview ? (
                  <div className="photo-guide-vlm-preview">
                    <img
                      src={`/api/guidance/color-check/image/${colorPreview.endpoint}?v=${colorPreview.version}`}
                      alt={t(colorPreview.endpoint === "board"
                        ? "photoGuide.colorPreviewControllerAlt"
                        : "photoGuide.colorPreviewSensorAlt", { controller: controllerLabel })}
                    />
                    <small>{t("photoGuide.colorPreviewHint")}</small>
                  </div>
                ) : null}
              </>
            ) : null}
            {/*
            <div className="photo-guide-check-row photo-guide-color-check">
              <button
                type="button"
                className="photo-guide-check-button ai"
                disabled={busy || connectorBusy}
                onClick={() => void runConnectorCheck()}
              >
                {connectorBusy ? t("photoGuide.connectorChecking") : t("photoGuide.connectorCheck")}
              </button>
              <span className={connectorError ? "error" : ""}>{connectorNotice}</span>
            </div>
            {connectorStatus === "complete" ? (
              <>
                <div className={`photo-guide-color-result vlm ${visualEvidence?.status ?? "uncertain"}`}>
                  <span>{t(`verification.reason.${visualEvidence?.reason ?? "vlm_uncertain"}`)}</span>
                </div>
                <button
                  type="button"
                  className="photo-guide-preview-button"
                  onClick={() => setShowConnectorPreview((visible) => !visible)}
                >
                  {t(showConnectorPreview ? "photoGuide.connectorPreviewHide" : "photoGuide.connectorPreview")}
                </button>
                {showConnectorPreview ? (
                  <div className="photo-guide-vlm-preview">
                    <img
                      src={`/api/guidance/visual-check/image?v=${connectorPreviewVersion}`}
                      alt={t("photoGuide.connectorPreviewAlt")}
                    />
                    <small>{t("photoGuide.connectorPreviewHint")}</small>
                  </div>
                ) : null}
              </>
            ) : null}
            {stepIndex === STEPS.length - 1 ? (
              <>
                <div className="photo-guide-check-row">
                  <button
                    type="button"
                    className="photo-guide-check-button ai"
                    disabled={busy || finalBusy}
                    onClick={() => void runFinalCheck()}
                  >
                    {finalBusy
                      ? t("photoGuide.finalChecking")
                      : finalStatus === "complete"
                        ? t("photoGuide.finalRecheck")
                        : t("photoGuide.finalStart")}
                  </button>
                  <span className={finalError ? "error" : ""}>{finalNotice}</span>
                </div>
                {finalResult?.connections ? (
                  <div className="photo-guide-final-results">
                    {finalResult.connections.map((connection) => {
                      const stateKey = connection.state === "inserted_target"
                        ? "photoGuide.finalState.correct"
                        : connection.state === "inserted_adjacent"
                          ? "photoGuide.finalState.adjacent"
                          : connection.state === "empty"
                            ? "photoGuide.finalState.empty"
                            : "photoGuide.finalState.uncertain";
                      return (
                        <div key={`${connection.board_pin}-${connection.component_pin}`}>
                          <span>{connection.board_pin} → {connection.component_pin}</span>
                          <strong>{t(stateKey)} · {Math.round(connection.confidence * 100)}%</strong>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                {finalStatus === "complete" ? (
                  <>
                    <button
                      type="button"
                      className="photo-guide-preview-button"
                      onClick={() => setShowFinalPreview((visible) => !visible)}
                    >
                      {t(
                        showFinalPreview
                          ? "photoGuide.finalPreviewHide"
                          : "photoGuide.finalPreview",
                      )}
                    </button>
                    {showFinalPreview ? (
                      <div className="photo-guide-vlm-preview">
                        <img
                          src={`/api/guidance/final-check/image?v=${finalPreviewVersion}`}
                          alt={t("photoGuide.finalPreviewAlt")}
                        />
                        <small>{t("photoGuide.finalPreviewHint")}</small>
                      </div>
                    ) : null}
                  </>
                ) : null}
              </>
            ) : (
              <div className="photo-guide-check-row">
                <span>{t("photoGuide.finalAfterGuide")}</span>
              </div>
            )}

            */}
            {step.electrical_verification === "serial-a0" ? (
              <>
                <p className="photo-guide-safety">{t("photoGuide.a0Challenge")}</p>
                <div className="photo-guide-check-row">
                  <button
                    type="button"
                    className="photo-guide-check-button electrical"
                    disabled={busy || electricalBusy || electricalRunning || !currentVerification || !electricalSupported}
                    onClick={() => void runElectricalCheck()}
                  >
                    {electricalBusy || electricalRunning
                      ? t("photoGuide.electricalRunning")
                      : electricalEvidence?.status === "pass"
                        ? t("photoGuide.electricalRestart")
                        : t("photoGuide.electricalStart")}
                  </button>
                  <span className={electricalError ? "error" : ""}>{electricalNotice}</span>
                </div>
              </>
            ) : step.component_pin_id === "AO" ? (
              <p className="photo-guide-safety">{t("photoGuide.piDigitalOnly")}</p>
            ) : null}
          </div>

          {/*
          {currentVerification && (
            <details className="photo-guide-details">
              <summary>
                <span>{t("photoGuide.details")}</span>
                <strong>{currentVerification.fusion.overall_confidence}<small>/100</small></strong>
              </summary>
              <VerificationPanel
                verification={currentVerification}
                showElectrical={step.sensorPin === "AO"}
              />
            </details>
          )}
          */}

          <div className="photo-guide-actions">
            <button
              type="button"
              className="photo-guide-secondary"
              disabled={busy}
              onClick={() => (stepIndex === 0 ? void reset() : void activateStep(stepIndex - 1))}
            >
              {stepIndex === 0 ? t("photoGuide.cancel") : t("photoGuide.previous")}
            </button>
            <button
              type="button"
              className="photo-guide-primary"
              disabled={busy}
              onClick={() =>
                stepIndex === steps.length - 1 ? void finish() : void activateStep(stepIndex + 1)
              }
            >
              {busy
                ? t("photoGuide.loading")
                : stepIndex === steps.length - 1
                  ? t("photoGuide.finish")
                  : t("photoGuide.next")}
            </button>
          </div>
        </>
      )}

      {mode === "complete" && (
        <>
          <div className="photo-guide-complete-mark" aria-hidden="true">✓</div>
          <strong className="photo-guide-complete-title">{t("photoGuide.completeTitle")}</strong>
          <p className="photo-guide-copy">
            {guideProfile ? tx(guideProfile.complete_hint) : t("photoGuide.profileMissing")}
          </p>
          <button type="button" className="photo-guide-secondary" disabled={busy} onClick={() => void reset()}>
            {t("photoGuide.restart")}
          </button>
        </>
      )}

      {error && <div className="photo-guide-error">{t("photoGuide.error")} · {error}</div>}
    </section>
  );
}

// Public generic name; the implementation remains backward-compatible with
// the historical file/component import while profiles now drive both boards.
export { PhotoresistorGuide as WiringGuidePanel };
