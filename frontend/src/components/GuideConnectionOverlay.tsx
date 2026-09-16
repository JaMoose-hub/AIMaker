import { useMemo, type CSSProperties } from "react";
import { toDisplay, type Letterbox } from "../lib/geometry";
import { useSmoothedDetection } from "../lib/useSmoothedDetection";
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

const CONNECTION_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff9a56",
  GND: "#b4becd",
  AO: "#5ee0b2",
};

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

    return {
      from: toDisplay(
        letterbox,
        boardPin.x + boardDisplayOffsetPx.x,
        boardPin.y + boardDisplayOffsetPx.y,
      ),
      to: toDisplay(letterbox, componentPin.x, componentPin.y),
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

  const color = CONNECTION_COLORS[componentPinId ?? ""] ?? "#66dfff";
  const style = { "--guide-connection-color": color } as CSSProperties;

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
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path className="guide-connection-arrowhead" d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      <line
        className="guide-connection-glow"
        x1={geometry.from.x}
        y1={geometry.from.y}
        x2={geometry.to.x}
        y2={geometry.to.y}
      />
      <line
        className="guide-connection-line"
        x1={geometry.from.x}
        y1={geometry.from.y}
        x2={geometry.to.x}
        y2={geometry.to.y}
        markerEnd="url(#guide-connection-arrowhead)"
      />
      <circle
        className="guide-connection-origin"
        cx={geometry.from.x}
        cy={geometry.from.y}
        r="7"
      />
      <circle
        className="guide-connection-target"
        cx={geometry.to.x}
        cy={geometry.to.y}
        r="9"
      />
    </svg>
  );
}
