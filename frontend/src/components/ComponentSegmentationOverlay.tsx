import { useMemo, type CSSProperties } from "react";
import { toDisplay, type Letterbox } from "../lib/geometry";
import type { ComponentSegmentMessage } from "../lib/types";

interface ComponentSegmentationOverlayProps {
  segments: ComponentSegmentMessage | null;
  letterbox: Letterbox;
  width: number;
  height: number;
}

const COLORS = [
  "#ffcc66", "#ff8c66", "#66d9ff", "#d19cff",
  "#70e0a1", "#f48fb1", "#ffd166", "#9be564",
];

export function ComponentSegmentationOverlay({
  segments,
  letterbox,
  width,
  height,
}: ComponentSegmentationOverlayProps) {
  const items = useMemo(() => {
    if (!segments) return [];
    // The generic model detects many board parts, but this screen is a
    // board-aware GPIO mapping view. Keep the other classes available to the
    // backend while showing only the GPIO header region here.
    return segments.detections.filter((item) => item.class_name.toLowerCase() === "gpio").map((item) => {
      const polygon = item.polygon
        .map(([x, y]) => toDisplay(letterbox, x, y))
        .map((point) => `${point.x},${point.y}`)
        .join(" ");
      const topLeft = toDisplay(letterbox, item.box[0], item.box[1]);
      const label = "GPIO header region";
      return {
        ...item,
        polygon,
        label,
        labelX: topLeft.x,
        labelY: Math.max(16, topLeft.y - 5),
      };
    });
  }, [segments, letterbox]);

  if (!segments || items.length === 0) return null;
  return (
    <svg
      className="component-segmentation-overlay-svg"
      width={Math.max(1, width)}
      height={Math.max(1, height)}
      role="presentation"
    >
      {items.map((item) => {
        const color = COLORS[item.class_id % COLORS.length];
        return (
          <g
            key={`${item.class_id}-${item.box.join("-")}`}
            style={{ "--component-seg-color": color } as CSSProperties}
          >
            <polygon className="component-gpio-region" points={item.polygon} />
            <text className="component-gpio-label" x={item.labelX} y={item.labelY}>
              {item.label} {Math.round(item.confidence * 100)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}
