import { useMemo, type CSSProperties } from "react";
import { toDisplay, type Letterbox } from "../lib/geometry";
import { guidanceCalloutGeometry } from "../lib/guidanceCallout";
import { componentHeaderGuideText } from "../lib/componentHeaderGuide";
import { pointBounds, placeWiringLabel, type WiringLabel } from "../lib/wiringLabelLayout";
import { useI18n } from "../lib/i18n";
import type { ComponentPoseMessage } from "../lib/types";

interface ComponentPinOverlayProps {
  pose: ComponentPoseMessage | null;
  letterbox: Letterbox;
  width: number;
  height: number;
  targetPinId: string | null;
  dimmed?: boolean;
  guidanceSuspended?: boolean;
  held?: boolean;
  guideLabel?: WiringLabel | null;
}

const PIN_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff7777",
  GND: "#aab4c4",
  AO: "#65d6a0",
  TRIG: "#ffb45f",
  ECHO: "#c891ff",
  SCL: "#6fb9ff",
  SDA: "#65d6a0",
  XDA: "#8fe3bd",
  XCL: "#8fc8ff",
  AD0: "#ffd166",
  INT: "#c891ff",
  RES: "#ff9d66",
  DC: "#f4c95d",
  CS: "#c891ff",
  BLK: "#8f9bad",
};

const COMPACT_LABELS: Readonly<Record<string, string>> = {
  VCC: "V",
  TRIG: "T",
  ECHO: "E",
  GND: "G",
  SCL: "C",
  SDA: "D",
  XDA: "XD",
  XCL: "XC",
  AD0: "A0",
  INT: "I",
  RES: "R",
  DC: "DC",
  CS: "CS",
  BLK: "B",
};

// Physical header order when counting from the AO edge is AO, DO, GND, VCC.
// DO is not used by this analog-only guide, but it still occupies pin 2.
const PIN_ORDINALS: Readonly<Record<string, number>> = {
  AO: 1,
  GND: 3,
  VCC: 4,
};

export function ComponentPinOverlay({
  pose,
  letterbox,
  width,
  height,
  targetPinId,
  dimmed = false,
  guidanceSuspended = false,
  held = false,
  guideLabel,
}: ComponentPinOverlayProps) {
  const { t } = useI18n();
  const headerGuide = useMemo(() => componentHeaderGuideText(pose?.component_id ?? "", targetPinId, t), [pose?.component_id, targetPinId, t]);
  const markerId = `component-guidance-arrowhead-${pose?.component_id ?? "unknown"}`;
  const usesPi5Style =
    pose?.component_id === "hc-sr04" ||
    pose?.component_id === "mrd-tf240-8p-cs";
  const points = useMemo(() => {
    if (!pose || pose.tracking === "searching") return [];
    return pose.pins
      .filter((pin) => pin.v && (targetPinId === null || pin.id === targetPinId))
      .map((pin) => ({ ...pin, ...toDisplay(letterbox, pin.x, pin.y) }));
  }, [pose, letterbox, targetPinId]);

  const targetCallout = useMemo(() => {
    if (targetPinId === null) return null;
    const target = points.find((pin) => pin.id === targetPinId);
    const ordinal = pose?.component_id === "photoresistor-module" ? PIN_ORDINALS[targetPinId] : undefined;
    if (!target) return null;
    if (headerGuide) {
      const label = guideLabel !== undefined ? guideLabel : placeWiringLabel(target, null,
        pointBounds((pose?.outline ?? []).map(([x, y]) => toDisplay(letterbox, x, y))), [], width, height);
      if (!label) return null;
      return { target, ordinal, ...label, boxX: label.x, boxY: label.y, boxWidth: label.width, boxHeight: label.height };
    }
    return {
      target,
      ordinal,
      ...guidanceCalloutGeometry(target.x, target.y, width, height),
    };
  }, [points, targetPinId, width, height, pose, headerGuide, guideLabel, letterbox]);

  const markerRadius = useMemo(() => {
    if (!usesPi5Style || points.length < 2) return usesPi5Style ? 3 : 5;
    let minimumSpacing = Number.POSITIVE_INFINITY;
    for (let index = 1; index < points.length; index += 1) {
      minimumSpacing = Math.min(
        minimumSpacing,
        Math.hypot(
          points[index].x - points[index - 1].x,
          points[index].y - points[index - 1].y,
        ),
      );
    }
    return Math.max(1.65, Math.min(3, minimumSpacing * 0.32));
  }, [points, usesPi5Style]);

  const displayOutline = useMemo(() => {
    if (!pose?.outline || pose.tracking === "searching") return null;
    return pose.outline.map(([x, y]) => toDisplay(letterbox, x, y));
  }, [pose, letterbox]);
  const outline = displayOutline?.map((point) => `${point.x},${point.y}`).join(" ") ?? null;

  const labelPlacement = useMemo(() => {
    if (!usesPi5Style || !displayOutline?.length || !points.length) {
      return { x: 0, y: -12, textAnchor: "middle" as const };
    }
    const boardCenter = {
      x: displayOutline.reduce((sum, point) => sum + point.x, 0) / displayOutline.length,
      y: displayOutline.reduce((sum, point) => sum + point.y, 0) / displayOutline.length,
    };
    const headerCenter = {
      x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
      y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    };
    let dx = headerCenter.x - boardCenter.x;
    let dy = headerCenter.y - boardCenter.y;
    const length = Math.hypot(dx, dy);
    if (length < 0.001) {
      dx = 0;
      dy = -1;
    } else {
      dx /= length;
      dy /= length;
    }
    return {
      x: dx * 18,
      y: dy * 18,
      textAnchor: dx > 0.35 ? "start" as const : dx < -0.35 ? "end" as const : "middle" as const,
    };
  }, [displayOutline, points, usesPi5Style]);

  // Do not render the orange diagnostic boxes for partial/invalid component
  // detections. Those boxes are useful for model debugging, but in the live
  // teaching UI they read like another active model and distract from GPIO
  // alignment. Keep models running in the background; only draw trusted pose
  // overlays.
  if (!pose || pose.tracking === "searching" || guidanceSuspended) return null;

  return (
    <svg
      className={`component-overlay-svg${usesPi5Style ? " component-overlay-pi5" : ""}${pose.tracking === "stale" ? " stale" : ""}${held ? " guidance-held" : ""}`}
      style={dimmed ? { opacity: 0.18 } : undefined}
      data-component-id={pose.component_id}
      data-target-pin={targetPinId ?? undefined}
      width={Math.max(1, width)}
      height={Math.max(1, height)}
      role="presentation"
    >
      <defs>
        <marker
          id={markerId}
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path className="component-guidance-arrowhead" d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      {outline && (
        <polygon
          className={usesPi5Style ? "board-outline component-outline-pi5" : "component-outline"}
          points={outline}
          strokeDasharray={pose.pose_quality?.stability === 'motion_prediction' ? '6 5' : undefined}
        />
      )}
      {outline && pose.pose_quality?.stability === 'motion_prediction' && <text x={displayOutline?.[0].x} y={(displayOutline?.[0].y ?? 0) - 10} fill="#64cfff" fontSize="13">預測補位 · 非辨識</text>}
      {points.map((pin) => {
        const active = targetPinId === pin.id;
        const color = PIN_COLORS[pin.id] ?? "#61dafb";
        return (
          <g
            key={pin.id}
            transform={`translate(${pin.x} ${pin.y})`}
            className={`component-pin-group${usesPi5Style ? " pi5-style" : ""}${active ? " guidance-active" : ""}`}
            style={{ "--component-pin": color, "--mk": color } as CSSProperties}
          >
            <title>{pin.id}</title>
            {active && (
              <>
                <circle className="component-guidance-halo outer" r="17" />
                <circle className="component-guidance-halo inner" r="11" />
              </>
            )}
            <circle
              className={usesPi5Style ? "component-pin-dot pin-dot" : "component-pin-dot"}
              r={markerRadius}
            />
            <text
              className={usesPi5Style ? "pin-label pin-label-always" : "component-pin-label"}
              x={labelPlacement.x}
              y={labelPlacement.y}
              textAnchor={labelPlacement.textAnchor}
              dominantBaseline="middle"
            >
              {usesPi5Style && !active ? (COMPACT_LABELS[pin.id] ?? pin.id) : pin.id}
            </text>
          </g>
        );
      })}
      {targetCallout && (
        <g className="component-pin-callout" aria-label={headerGuide?.title}>
          <line
            className="component-pin-callout-arrow"
            x1={targetCallout.startX}
            y1={targetCallout.startY}
            x2={targetCallout.endX}
            y2={targetCallout.endY}
            markerEnd={`url(#${markerId})`}
          />
          <rect
            className="component-pin-callout-box"
            x={targetCallout.boxX}
            y={targetCallout.boxY}
            width={targetCallout.boxWidth}
            height={targetCallout.boxHeight}
            rx="9"
          />
          <text
            className={headerGuide ? "component-row-label-text" : "component-pin-callout-title"}
            x={targetCallout.boxX + 10}
            y={targetCallout.boxY + (headerGuide ? 21 : 18)}
          >
            {headerGuide?.title ?? (targetCallout.ordinal === undefined ? targetCallout.target.id : t("componentGuide.pinOrdinal", {
              number: targetCallout.ordinal,
              pin: targetCallout.target.id,
            }))}
          </text>
          {!headerGuide ? <text
            className="component-pin-callout-hint"
            x={targetCallout.boxX + 10}
            y={targetCallout.boxY + 35}
          >
            {targetCallout.ordinal === undefined ? pose.component_id : t("componentGuide.countFromAo")}
          </text> : null}
        </g>
      )}
    </svg>
  );
}
