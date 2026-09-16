import { useEffect, useMemo, useRef, useState } from "react";
import { postCalibrate } from "../lib/api";
import { toDisplay, toSource, type DisplayPoint, type Letterbox } from "../lib/geometry";
import { useI18n } from "../lib/i18n";
import type { DetectionMessage } from "../lib/types";

/**
 * "新增/校正板型" (Add/Calibrate board type) — admin/onboarding action that
 * (re)registers the canonical reference image for the currently-loaded board
 * model (api-contract.md §6).
 *
 * Two ways the guide's four corners get decided:
 *  - "tracked": the board is already locked/stale-tracked (its own real,
 *    possibly-rotated `outline` is available from live detection) - the
 *    guide IS that outline, drawn as a polygon that follows the board's
 *    actual position/rotation. No manual alignment needed; the operator
 *    just holds the board steady. Corners come straight from
 *    `detection.outline` (already in source-px, already in the
 *    TL,TR,BR,BL order api-contract.md §6 requires) - no round trip
 *    through display space needed for submission, only for drawing.
 *  - "manual": no live outline (e.g. registering a genuinely new,
 *    not-yet-recognized board type) - falls back to the original fixed,
 *    axis-aligned centered rectangle that the operator aligns the
 *    physical board to by eye.
 * Added 2026-07-28 after live testing showed a fixed axis-aligned guide
 * can never look "neatly aligned" against a board that's sitting at an
 * angle in frame, which a real rotated board very often is.
 */

type Phase = "idle" | "capturing" | "success" | "error";

/**
 * Keep a small margin around the guide, but do not let the default guide
 * become smaller than the physical pin-resolution gate. At 720p, the old
 * fixed 0.45 factor produced roughly 6 px/mm and allowed unusable references
 * to be captured; the guide now grows to the recommended scale when the
 * source frame has enough room.
 */
const GUIDE_FIT_FACTOR = 0.45;
const GUIDE_MAX_FIT_FACTOR = 0.86;
const MIN_PIN_PITCH_PX = 18;
const MIN_PX_PER_MM = 8;
const RECOMMENDED_PX_PER_MM = 9;
const SUCCESS_AUTOCLOSE_MS = 3000;

type GuideSource = "tracked" | "manual";
type GuideScaleStatus = "ok" | "below_recommended" | "reject";

interface Guide {
  source: GuideSource;
  /** Display-space corners, order TL, TR, BR, BL (must match board-mm (0,0),(W,0),(W,H),(0,H)). */
  displayCorners: readonly [DisplayPoint, DisplayPoint, DisplayPoint, DisplayPoint];
  /** Source-video-px corners, same order - what actually gets POSTed. */
  sourceCorners: readonly [
    [number, number],
    [number, number],
    [number, number],
    [number, number],
  ];
  /** Conservative source-video scale estimate used before POST /api/calibrate. */
  pxPerMm: number;
  pinPitchPx: number;
  scaleStatus: GuideScaleStatus;
}

function scaleStatus(pxPerMm: number): GuideScaleStatus {
  if (pxPerMm < MIN_PX_PER_MM || pxPerMm * 2.54 < MIN_PIN_PITCH_PX) return "reject";
  if (pxPerMm < RECOMMENDED_PX_PER_MM) return "below_recommended";
  return "ok";
}

function guideScaleFields(pxPerMm: number): Pick<Guide, "pxPerMm" | "pinPitchPx" | "scaleStatus"> {
  const safePxPerMm = Number.isFinite(pxPerMm) && pxPerMm > 0 ? pxPerMm : 0;
  return {
    pxPerMm: safePxPerMm,
    pinPitchPx: safePxPerMm * 2.54,
    scaleStatus: scaleStatus(safePxPerMm),
  };
}

function estimateQuadScale(
  sourceCorners: readonly [[number, number], [number, number], [number, number], [number, number]],
  outlineMm: readonly [number, number],
): number {
  const [boardW, boardH] = outlineMm;
  const edge = (a: readonly [number, number], b: readonly [number, number]) =>
    Math.hypot(b[0] - a[0], b[1] - a[1]);
  const scales = [
    edge(sourceCorners[0], sourceCorners[1]) / boardW,
    edge(sourceCorners[3], sourceCorners[2]) / boardW,
    edge(sourceCorners[0], sourceCorners[3]) / boardH,
    edge(sourceCorners[1], sourceCorners[2]) / boardH,
  ].filter((value) => Number.isFinite(value) && value > 0);
  return scales.length ? Math.min(...scales) : 0;
}

/**
 * Fits a board_outline_mm-aspect rectangle inside the actual source-video
 * dimensions. The resulting source-space scale is at least the recommended
 * 9 px/mm whenever the frame can fit it, then converted through the existing
 * letterbox transform for display.
 */
function computeManualGuide(
  videoSize: readonly [number, number],
  letterbox: Letterbox,
  outlineMm: readonly [number, number],
): Guide | null {
  const [vw, vh] = videoSize;
  const [boardW, boardH] = outlineMm;
  if (vw <= 0 || vh <= 0 || boardW <= 0 || boardH <= 0) return null;

  const fitPxPerMm = Math.min(vw / boardW, vh / boardH);
  if (fitPxPerMm <= 0 || letterbox.scale <= 0) return null;

  const sourcePxPerMm = Math.min(
    fitPxPerMm * GUIDE_MAX_FIT_FACTOR,
    Math.max(fitPxPerMm * GUIDE_FIT_FACTOR, RECOMMENDED_PX_PER_MM),
  );
  const sourceWidth = boardW * sourcePxPerMm;
  const sourceHeight = boardH * sourcePxPerMm;
  const width = sourceWidth * letterbox.scale;
  const height = sourceHeight * letterbox.scale;
  const innerW = vw * letterbox.scale;
  const innerH = vh * letterbox.scale;

  const left = letterbox.offx + (innerW - width) / 2;
  const top = letterbox.offy + (innerH - height) / 2;

  const displayCorners = [
    { x: left, y: top }, // TL
    { x: left + width, y: top }, // TR
    { x: left + width, y: top + height }, // BR
    { x: left, y: top + height }, // BL
  ] as const;

  return {
    source: "manual",
    displayCorners,
    sourceCorners: displayCorners.map((p) => {
      const s = toSource(letterbox, p.x, p.y);
      return [s.x, s.y] as [number, number];
    }) as unknown as Guide["sourceCorners"],
    ...guideScaleFields(sourcePxPerMm),
  };
}

/**
 * The board's own live-tracked outline (already source-px, already
 * TL,TR,BR,BL) as the guide - no alignment needed, it already IS where the
 * board is. `null` when the board isn't currently tracked (searching), or
 * the profile hasn't published an outline this frame.
 */
function computeTrackedGuide(
  detection: DetectionMessage | null,
  letterbox: Letterbox,
  outlineMm: readonly [number, number],
): Guide | null {
  if (!detection || detection.tracking === "searching" || !detection.outline) return null;
  if (detection.outline.length !== 4) return null;
  const sourceCorners = detection.outline as unknown as Guide["sourceCorners"];
  const displayCorners = detection.outline.map(([x, y]) => toDisplay(letterbox, x, y)) as unknown as Guide["displayCorners"];
  return {
    source: "tracked",
    displayCorners,
    sourceCorners,
    ...guideScaleFields(estimateQuadScale(sourceCorners, outlineMm)),
  };
}

interface CalibratePanelProps {
  open: boolean;
  onClose: () => void;
  onCalibrationSuccess: () => void;
  videoSize: readonly [number, number];
  letterbox: Letterbox;
  containerWidth: number;
  containerHeight: number;
  /** `profile.board.outline_mm`; null while the profile hasn't loaded yet. */
  outlineMm: readonly [number, number] | null;
  /** Latest detection, used to snap the guide to the board's real tracked outline when available. */
  detection: DetectionMessage | null;
}

export function CalibratePanel({
  open,
  onClose,
  onCalibrationSuccess,
  videoSize,
  letterbox,
  containerWidth,
  containerHeight,
  outlineMm,
  detection,
}: CalibratePanelProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const closeTimerRef = useRef<number | null>(null);
  // Bumped on every open + every capture; async callbacks check it's still
  // "their" attempt before touching state (guards stale responses without
  // needing to fully unmount the panel).
  const requestIdRef = useRef(0);

  // (Re)opening always starts from a clean slate and invalidates anything
  // still in flight from a previous session.
  useEffect(() => {
    if (open) {
      setPhase("idle");
      setMessage(null);
      requestIdRef.current += 1;
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
    }
  }, [open]);

  useEffect(
    () => () => {
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    },
    [],
  );

  // Prefer the board's real tracked outline (already exactly where the
  // board is, at whatever angle it's actually sitting) over the generic
  // fixed rectangle - only fall back to "manual" when nothing is tracked.
  const guide = useMemo(() => {
    const tracked = outlineMm ? computeTrackedGuide(detection, letterbox, outlineMm) : null;
    if (tracked) return tracked;
    return outlineMm ? computeManualGuide(videoSize, letterbox, outlineMm) : null;
  }, [detection, letterbox, videoSize, outlineMm]);

  if (!open) return null;

  const handleCapture = () => {
    if (!guide || phase === "capturing") return;
    const cornersPx = guide.sourceCorners.map((p) => [p[0], p[1]] as [number, number]);

    const myRequestId = ++requestIdRef.current;
    setPhase("capturing");
    setMessage(null);

    postCalibrate(cornersPx)
      .then((result) => {
        if (requestIdRef.current !== myRequestId) return; // superseded/stale
        if (result.ok) {
          onCalibrationSuccess();
          setPhase("success");
          setMessage(t("calibrate.successFallback"));
          closeTimerRef.current = window.setTimeout(() => {
            onClose();
          }, SUCCESS_AUTOCLOSE_MS);
        } else {
          setPhase("error");
          const errorCode = result.error_code ?? result.error ?? "unknown";
          const scaleDetails =
            errorCode === "insufficient_scale" && result.pitch_px != null && result.px_per_mm != null
              ? ` ${t("calibrate.scaleDiagnostics", {
                  pitch: result.pitch_px.toFixed(1),
                  pxPerMm: result.px_per_mm.toFixed(1),
                })}`
              : "";
          setMessage(`${t(`calibrate.error.${errorCode}`)}${scaleDetails}`);
        }
      })
      .catch(() => {
        if (requestIdRef.current !== myRequestId) return;
        setPhase("error");
        setMessage(t("calibrate.networkError"));
      });
  };

  const busy = phase === "capturing";

  return (
    <div className="calibrate-overlay" role="dialog" aria-modal="true" aria-label={t("calibrate.title")}>
      {guide && (
        <svg
          className={`calibrate-guide-svg${guide.source === "tracked" ? " tracked" : " manual"}`}
          width={Math.max(1, containerWidth)}
          height={Math.max(1, containerHeight)}
          role="presentation"
          aria-hidden="true"
        >
          <polygon
            className="calibrate-guide-polygon"
            points={guide.displayCorners.map((p) => `${p.x},${p.y}`).join(" ")}
          />
        </svg>
      )}
      <div className="calibrate-panel-card">
        <h3 className="calibrate-title">{t("calibrate.title")}</h3>

        {phase !== "success" && (
          <>
            <p className="calibrate-instruction">
              {guide?.source === "tracked" ? t("calibrate.instructionTracked") : t("calibrate.instruction")}
            </p>
            <p className="calibrate-hint">{t("calibrate.hint")}</p>
            {guide && (
              <p className={`calibrate-hint${guide.scaleStatus === "reject" ? " error" : ""}`}>
                {guide.scaleStatus === "reject"
                  ? t("calibrate.scaleTooSmall", {
                      pitch: guide.pinPitchPx.toFixed(1),
                      pxPerMm: guide.pxPerMm.toFixed(1),
                    })
                  : t("calibrate.scaleEstimate", {
                      pitch: guide.pinPitchPx.toFixed(1),
                      pxPerMm: guide.pxPerMm.toFixed(1),
                    })}
              </p>
            )}
          </>
        )}

        {phase === "error" && message && <div className="calibrate-message error">{message}</div>}
        {phase === "success" && message && (
          <div className="calibrate-message success">{message}</div>
        )}

        {phase !== "success" && (
          <div className="calibrate-actions">
            <button
              type="button"
              className="calibrate-btn primary"
              disabled={busy || !guide || guide.scaleStatus === "reject"}
              onClick={handleCapture}
            >
              {busy && <span className="calibrate-spinner" aria-hidden="true" />}
              {busy
                ? t("calibrate.capturing")
                : phase === "error"
                  ? t("calibrate.retry")
                  : t("calibrate.capture")}
            </button>
            <button type="button" className="calibrate-btn secondary" disabled={busy} onClick={onClose}>
              {t("calibrate.cancel")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
