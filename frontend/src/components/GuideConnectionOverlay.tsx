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
  // Display-only clearance: leave the real Pin centres unobstructed. Never
  // change the detected coordinates or feed this shortened line to checking.
  const dx = geometry.to.x - geometry.from.x;
  const dy = geometry.to.y - geometry.from.y;
  const distance = Math.hypot(dx, dy);
  const inset = Math.min(8, distance / 3) / (distance || 1);
  const lineFrom = { x: geometry.from.x + dx * inset, y: geometry.from.y + dy * inset };
  const lineTo = { x: geometry.to.x - dx * inset, y: geometry.to.y - dy * inset };

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
      <line
        className="guide-connection-glow"
        x1={lineFrom.x}
        y1={lineFrom.y}
        x2={lineTo.x}
        y2={lineTo.y}
      />
      <line
        className="guide-connection-line"
        x1={lineFrom.x}
        y1={lineFrom.y}
        x2={lineTo.x}
        y2={lineTo.y}
        markerEnd="url(#guide-connection-arrowhead)"
      />
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
