import { useMemo, type CSSProperties } from "react";
import { toDisplay, type Letterbox } from "../lib/geometry";
import { useSmoothedDetection } from "../lib/useSmoothedDetection";
import { guideConnectionColor, guideConnectionPath } from "../lib/recognitionStyle";
import { componentHeaderAtTop } from "../lib/componentHeaderGuide";
import type { ComponentPoseMessage, DetectionMessage } from "../lib/types";

interface GuideConnectionOverlayProps {
  detection: DetectionMessage | null;
  componentPose: ComponentPoseMessage | null;
  letterbox: Letterbox;
  width: number;
  height: number;
  boardPinId: string | null;
  componentPinId: string | null;
  boardDisplayOffsetPx: { x: number; y: number };
  held?: boolean;
}

/**
 * Visual-only link for the active wiring lesson. It connects the two live
 * projected Pin centres; it is not wire tracing and never contributes to a
 * verification score.
 */
export function GuideConnectionOverlay({
  detection,
  componentPose,
  letterbox,
  width,
  height,
  boardPinId,
  componentPinId,
  boardDisplayOffsetPx,
  held = false,
}: GuideConnectionOverlayProps) {
  const visualDetection = useSmoothedDetection(detection);
  const geometry = useMemo(() => {
    if (
      !boardPinId
      || !componentPinId
      || !visualDetection
      || visualDetection.tracking === "searching"
      || !componentPose
      || componentPose.tracking === "searching"
    ) {
      return null;
    }
    const boardPin = visualDetection.pins.find(
      (pin) => pin.id === boardPinId && pin.v,
    );
    const componentPin = componentPose.pins.find(
      (pin) => pin.id === componentPinId && pin.v,
    );
    if (!boardPin || !componentPin) return null;

    const headerAtTop = componentHeaderAtTop(componentPose.component_id);
    return {
      from: toDisplay(
        letterbox,
        boardPin.x + boardDisplayOffsetPx.x,
        boardPin.y + boardDisplayOffsetPx.y,
      ),
      to: toDisplay(letterbox, componentPin.x, componentPin.y),
      target: headerAtTop !== null && componentPose.outline ? {
        headerAtTop,
        outline: componentPose.outline.map(([x, y]) => toDisplay(letterbox, x, y)),
      } : undefined,
      stale:
        held
        || visualDetection.tracking === "stale"
        || componentPose.tracking === "stale",
    };
  }, [
    boardDisplayOffsetPx.x,
    boardDisplayOffsetPx.y,
    boardPinId,
    componentPinId,
    componentPose,
    held,
    letterbox,
    visualDetection,
  ]);

  if (!geometry) return null;

  const color = guideConnectionColor(componentPinId ?? "");
  const style = { "--guide-connection-color": color } as CSSProperties;
  const path = guideConnectionPath(geometry.from, geometry.to, 8, geometry.target);

  return (
    <svg
      className={`guide-connection-overlay${geometry.stale ? " stale" : ""}${held ? " guidance-held" : ""}`}
      width={Math.max(1, width)}
      height={Math.max(1, height)}
      style={style}
      aria-hidden="true"
      data-guide-connection={`${boardPinId}:${componentPinId}`}
    >
      <defs>
        <marker
          id="guide-connection-arrowhead"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerUnits="userSpaceOnUse"
          markerWidth="9"
          markerHeight="9"
          orient="auto"
        >
          <path className="guide-connection-arrowhead" d="M 1 1 L 9 5 L 1 9" />
        </marker>
      </defs>
      <path
        className="guide-connection-contrast"
        d={path}
      />
      <path
        className="guide-connection-glow"
        d={path}
      />
      <path
        className="guide-connection-line"
        d={path}
        markerEnd="url(#guide-connection-arrowhead)"
      />
      <path className="guide-connection-spark" d={path} />
      <circle
        className="guide-connection-origin"
        cx={geometry.from.x}
        cy={geometry.from.y}
        r="5"
      />
      <circle
        className="guide-connection-target"
        cx={geometry.to.x}
        cy={geometry.to.y}
        r="6"
      />
    </svg>
  );
}
