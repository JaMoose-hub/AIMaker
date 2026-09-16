import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { IDENTITY_LETTERBOX } from "../lib/geometry";
import { useI18n } from "../lib/i18n";
import {
  createOpticalHudTransform,
  type OpticalHudCalibration,
  type PointTuple,
  type Quad,
} from "../lib/opticalHud";

interface OpticalHudCalibrationProps {
  width: number;
  height: number;
  /** Latest locked board outline in canonical TL,TR,BR,BL source-pixel order. */
  sourceCorners: Quad | null;
  onComplete: (calibration: OpticalHudCalibration) => void;
}

const CORNER_KEYS = [
  "opticalHud.corner.topLeft",
  "opticalHud.corner.topRight",
  "opticalHud.corner.bottomRight",
  "opticalHud.corner.bottomLeft",
] as const;

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function copyQuad(points: Quad): Quad {
  return points.map(([x, y]) => [x, y] as PointTuple) as unknown as Quad;
}

export function OpticalHudCalibrationOverlay({
  width,
  height,
  sourceCorners,
  onComplete,
}: OpticalHudCalibrationProps) {
  const { t } = useI18n();
  const canvasRef = useRef<SVGSVGElement>(null);
  const sourceSnapshotRef = useRef<Quad | null>(null);
  const [targetCorners, setTargetCorners] = useState<PointTuple[]>([]);
  const [cursor, setCursor] = useState<PointTuple>([0.5, 0.5]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    canvasRef.current?.focus();
  }, []);

  const ready = sourceSnapshotRef.current !== null || sourceCorners !== null;
  const currentCornerIndex = Math.min(targetCorners.length, 3);
  const currentStep = Math.min(targetCorners.length + 1, 4);
  const currentCorner = t(CORNER_KEYS[currentCornerIndex]);
  const safeWidth = Math.max(1, width);
  const safeHeight = Math.max(1, height);

  const commitPoint = (point: PointTuple) => {
    const frozenSource = sourceSnapshotRef.current ?? sourceCorners;
    if (!frozenSource || targetCorners.length >= 4) return;
    const normalizedPoint: PointTuple = [clamp01(point[0]), clamp01(point[1])];
    const nextTargets = [...targetCorners, normalizedPoint];
    setError(null);

    if (nextTargets.length < 4) {
      sourceSnapshotRef.current = copyQuad(frozenSource);
      setTargetCorners(nextTargets);
      return;
    }

    const calibration: OpticalHudCalibration = {
      sourceCorners: copyQuad(frozenSource),
      targetCornersNormalized: nextTargets as unknown as Quad,
    };
    if (!createOpticalHudTransform(IDENTITY_LETTERBOX, calibration, safeWidth, safeHeight)) {
      setError(t("opticalHud.calibrationInvalid"));
      return;
    }
    sourceSnapshotRef.current = copyQuad(frozenSource);
    setTargetCorners(nextTargets);
    onComplete(calibration);
  };

  const undo = () => {
    setError(null);
    setTargetCorners((current) => {
      const next = current.slice(0, -1);
      if (next.length === 0) sourceSnapshotRef.current = null;
      return next;
    });
    canvasRef.current?.focus();
  };

  const reset = () => {
    sourceSnapshotRef.current = null;
    setTargetCorners([]);
    setCursor([0.5, 0.5]);
    setError(null);
    canvasRef.current?.focus();
  };

  const pointFromPointer = (event: PointerEvent<SVGSVGElement>): PointTuple => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      clamp01((event.clientX - bounds.left) / Math.max(1, bounds.width)),
      clamp01((event.clientY - bounds.top) / Math.max(1, bounds.height)),
    ];
  };

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    setCursor(pointFromPointer(event));
  };

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    const point = pointFromPointer(event);
    setCursor(point);
    commitPoint(point);
  };

  const handleKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const stepX = (event.shiftKey ? 10 : 1) / safeWidth;
    const stepY = (event.shiftKey ? 10 : 1) / safeHeight;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setCursor(([x, y]) => [clamp01(x + (event.key === "ArrowLeft" ? -stepX : stepX)), y]);
      return;
    }
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      setCursor(([x, y]) => [x, clamp01(y + (event.key === "ArrowUp" ? -stepY : stepY))]);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commitPoint(cursor);
      return;
    }
    if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault();
      undo();
      return;
    }
    if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      reset();
    }
  };

  const displayTargets = targetCorners.map(([x, y]) => ({ x: x * safeWidth, y: y * safeHeight }));
  const cursorX = cursor[0] * safeWidth;
  const cursorY = cursor[1] * safeHeight;

  return (
    <div className="optical-hud-calibration-overlay">
      <div className="optical-hud-calibration-copy" role="status">
        <span className="optical-hud-kicker">{t("opticalHud.calibrationKicker")}</span>
        <strong>{t("opticalHud.calibrationTitle")}</strong>
        <span>{t("opticalHud.calibrationInstruction")}</span>
        <span className={`optical-hud-tracking${ready ? " ready" : ""}`}>
          {t(ready ? "opticalHud.boardLocked" : "opticalHud.waitingForBoard")}
        </span>
        <span className="optical-hud-step">
          {t("opticalHud.calibrationStep", {
            step: currentStep,
            corner: currentCorner,
          })}
        </span>
      </div>
      <svg
        ref={canvasRef}
        className={`optical-hud-calibration-canvas${ready ? " ready" : ""}`}
        width={safeWidth}
        height={safeHeight}
        viewBox={`0 0 ${safeWidth} ${safeHeight}`}
        role="application"
        aria-label={t("opticalHud.calibrationCanvasLabel")}
        tabIndex={0}
        onPointerMove={handlePointerMove}
        onPointerDown={handlePointerDown}
        onKeyDown={handleKeyDown}
      >
        {displayTargets.length > 1 && (
          <polyline
            className="optical-hud-calibration-path"
            points={displayTargets.map((point) => `${point.x},${point.y}`).join(" ")}
          />
        )}
        {displayTargets.map((point, index) => (
          <g key={CORNER_KEYS[index]} transform={`translate(${point.x} ${point.y})`}>
            <circle className="optical-hud-calibration-point-glow" r="15" />
            <circle className="optical-hud-calibration-point" r="5" />
            <text className="optical-hud-calibration-point-label" x="11" y="-11">
              {index + 1}
            </text>
          </g>
        ))}
        <g
          className={`optical-hud-crosshair${ready ? " ready" : ""}`}
          transform={`translate(${cursorX} ${cursorY})`}
        >
          <circle r="18" />
          <line x1="-28" y1="0" x2="28" y2="0" />
          <line x1="0" y1="-28" x2="0" y2="28" />
          <text x="25" y="-22">{currentStep}</text>
        </g>
      </svg>
      <div className="optical-hud-calibration-footer">
        <span>{t("opticalHud.calibrationKeyboardHint")}</span>
        {error && <span className="optical-hud-calibration-error" role="alert">{error}</span>}
        <div className="optical-hud-calibration-actions">
          <button type="button" disabled={targetCorners.length === 0} onClick={undo}>
            {t("opticalHud.undo")}
          </button>
          <button type="button" onClick={reset}>{t("opticalHud.reset")}</button>
        </div>
      </div>
    </div>
  );
}
