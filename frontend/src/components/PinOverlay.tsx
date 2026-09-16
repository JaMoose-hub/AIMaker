import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { toDisplay, type DisplayPoint, type Letterbox } from "../lib/geometry";
import { guidanceCalloutGeometry, guidancePointerGeometry } from "../lib/guidanceCallout";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import { pointBounds, placeWiringLabel, type LabelRect, type WiringLabel } from "../lib/wiringLabelLayout";
import {
  capColorVar,
  capLabel,
  orderedCapabilityTypes,
  pinColorVar,
  pinOverlayLabel,
  pinDisplayNameWithNumber,
} from "../lib/capabilities";
import { useI18n } from "../lib/i18n";
import { useSmoothedDetection } from "../lib/useSmoothedDetection";
import { useGuidance } from "../lib/wsClient";
import type { ComponentPoseMessage, DetectionMessage, DetectionPin, Pin, TrackingState } from "../lib/types";

/** Hover/click hit radius in CSS px (contract §3 requires >= 24px). */
const HIT_RADIUS_PX = 24;
// 4px: at demo distance the UNO Q's pin pitch is ~10px on screen - a 7px
// radius made adjacent markers overlap into a blob (user feedback 2026-07-29).
const MARKER_RADIUS_PX = 3;
const MARKER_RADIUS_MM = 0.86;
const MIN_MARKER_RADIUS_PX = 1.65;
const MAX_MARKER_RADIUS_PX = 4.6;
const LABEL_OFFSET_PX = 18;
// Forty GPIO markers used to take ~0.85 s before the final marker appeared
// (39 * 15 ms stagger + 260 ms animation).  Keep a subtle entrance cue while
// making the whole lattice visible in under 0.3 s.
const STAGGER_MS = 3;
const TOOLTIP_WIDTH = 210;
const TOOLTIP_HEIGHT = 88;
const TOOLTIP_OFFSET = 16;

const HEADER_GUIDE_LABELS: Readonly<
  Record<string, { headerKey: string; countFromKey: string }>
> = {
  JANALOG: {
    headerKey: "boardGuide.header.analog",
    countFromKey: "boardGuide.countFromBoot",
  },
  JDIGITAL: {
    headerKey: "boardGuide.header.digital",
    countFromKey: "boardGuide.countFromScl",
  },
};

interface DisplayPin {
  det: DetectionPin;
  pin: Pin | undefined;
  x: number;
  y: number;
  index: number;
}

interface LabelPlacement {
  x: number;
  y: number;
  textAnchor: "start" | "middle" | "end";
}

interface MarkerPerspective {
  rx: number;
  ry: number;
  angleDeg: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

interface PinOverlayProps {
  detection: DetectionMessage | null;
  letterbox: Letterbox;
  width: number;
  height: number;
  pinsById: ReadonlyMap<string, Pin>;
  /** null = no filter/query active (everything full opacity). */
  highlightIds: ReadonlySet<string> | null;
  selectedPinId: string | null;
  onSelectPin: (pinId: string | null) => void;
  /** False in presentation modes where the overlay is display-only. */
  interactive: boolean;
  /** Increments on each searching -> locked transition (replays entrance). */
  lockSeq: number;
  tracking: TrackingState;
  /** Display-only source-pixel nudge for manual GPIO-hole alignment. */
  displayOffsetPx: { x: number; y: number };
  /** Local guided-wiring target; available immediately after the user starts a step. */
  guidePinId: string | null;
  localGuidanceOnly?: boolean;
  guidanceHeld?: boolean;
  guidePeerPose?: Pick<ComponentPoseMessage, "tracking" | "outline" | "pins"> | null;
  guidePeerPinId?: string | null;
  /** undefined: standalone/legacy placement; null: joint layout has no room. */
  guideLabel?: WiringLabel | null;
}

interface HoverState {
  id: string;
  x: number;
  y: number;
}

export function PinOverlay({
  detection,
  letterbox,
  width,
  height,
  pinsById,
  highlightIds,
  selectedPinId,
  onSelectPin,
  interactive,
  lockSeq,
  tracking,
  displayOffsetPx,
  guidePinId,
  localGuidanceOnly = false,
  guidanceHeld = false,
  guidePeerPose = null,
  guidePeerPinId = null,
  guideLabel,
}: PinOverlayProps) {
  const { t } = useI18n();
  const [hover, setHover] = useState<HoverState | null>(null);
  const remoteGuidance = useGuidance();
  const guidance = localGuidanceOnly ? null : remoteGuidance;
  const visualDetection = useSmoothedDetection(detection);
  // The local target is set as soon as the user presses "接線引導". The
  // WebSocket verdict arrives later, so use it only as a fallback; otherwise
  // the Arduino marker/callout would wait for the first backend check.
  const activeGuidePinId = guidePinId ?? guidance?.expected_pin_id ?? null;

  useEffect(() => {
    if (!interactive) setHover(null);
  }, [interactive]);

  const pinStates = useMemo(() => {
    const states = new Map<string, "connected" | "uncertain" | "wrong">();
    if (guidance?.status === "wrong_pin" && guidance.actual_pin_id) {
      states.set(guidance.actual_pin_id, "wrong");
    }
    return states;
  }, [guidance]);

  const displayPins = useMemo<DisplayPin[]>(() => {
    if (!visualDetection || visualDetection.tracking === "searching") return [];
    return visualDetection.pins
      .filter((pin) => pin.v)
      .map((pin, index) => {
        const point = toDisplay(
          letterbox,
          pin.x + displayOffsetPx.x,
          pin.y + displayOffsetPx.y,
        );
        return { det: pin, pin: pinsById.get(pin.id), x: point.x, y: point.y, index };
      });
  }, [displayOffsetPx, letterbox, pinsById, visualDetection]);

  const displayOutline = useMemo<DisplayPoint[] | null>(() => {
    if (!visualDetection?.outline || visualDetection.tracking === "searching") return null;
    return visualDetection.outline.map(([x, y]) => toDisplay(letterbox, x, y));
  }, [letterbox, visualDetection]);

  const outlinePoints = useMemo(
    () => displayOutline?.map((point) => `${point.x},${point.y}`).join(" ") ?? null,
    [displayOutline],
  );

  // Estimate the local board-plane basis from neighbouring profile pins.
  // At an oblique camera angle one header axis is foreshortened, so a round
  // pin opening projects to a rotated ellipse. This is visual-only geometry;
  // the marker centre remains the backend's height-aware 3-D projection.
  const markerPerspectives = useMemo(() => {
    const result = new Map<string, MarkerPerspective>();
    const fallback: MarkerPerspective = {
      rx: MARKER_RADIUS_PX,
      ry: MARKER_RADIUS_PX,
      angleDeg: 0,
    };
    const localBasis = (
      origin: DisplayPin,
      axis: 0 | 1,
    ): { x: number; y: number } | null => {
      if (!origin.pin) return null;
      const crossAxis: 0 | 1 = axis === 0 ? 1 : 0;
      let best: { x: number; y: number; distance: number } | null = null;
      for (const candidate of displayPins) {
        if (
          candidate.det.id === origin.det.id ||
          !candidate.pin ||
          candidate.pin.header !== origin.pin.header
        ) {
          continue;
        }
        const axisDelta = candidate.pin.pos_mm[axis] - origin.pin.pos_mm[axis];
        const crossDelta = candidate.pin.pos_mm[crossAxis] - origin.pin.pos_mm[crossAxis];
        if (Math.abs(axisDelta) < 0.5 || Math.abs(crossDelta) > 0.4) continue;
        const distance = Math.abs(axisDelta);
        if (!best || distance < best.distance) {
          best = {
            x: (candidate.x - origin.x) / axisDelta,
            y: (candidate.y - origin.y) / axisDelta,
            distance,
          };
        }
      }
      return best ? { x: best.x, y: best.y } : null;
    };

    for (const pin of displayPins) {
      const basisX = localBasis(pin, 0);
      const basisY = localBasis(pin, 1);
      if (!basisX && !basisY) {
        result.set(pin.det.id, fallback);
        continue;
      }
      const scaleX = basisX ? Math.hypot(basisX.x, basisX.y) : null;
      const scaleY = basisY ? Math.hypot(basisY.x, basisY.y) : null;
      const sharedScale = scaleX ?? scaleY ?? MARKER_RADIUS_PX / MARKER_RADIUS_MM;
      const rx = clamp(
        (scaleX ?? sharedScale) * MARKER_RADIUS_MM,
        MIN_MARKER_RADIUS_PX,
        MAX_MARKER_RADIUS_PX,
      );
      const ry = clamp(
        (scaleY ?? sharedScale) * MARKER_RADIUS_MM,
        MIN_MARKER_RADIUS_PX,
        MAX_MARKER_RADIUS_PX,
      );
      const angleDeg = basisX
        ? (Math.atan2(basisX.y, basisX.x) * 180) / Math.PI
        : basisY
          ? (Math.atan2(basisY.y, basisY.x) * 180) / Math.PI - 90
          : 0;
      result.set(pin.det.id, { rx, ry, angleDeg });
    }
    return result;
  }, [displayPins]);

  // Derive label direction from profile geometry instead of screen Y. A Pi
  // J8 header has two rows, so each row is labelled away from the other row;
  // a one-row Arduino header is labelled away from the board centre. The
  // vectors rotate and mirror with the detected board, keeping rows separated
  // at every orientation without rotating/reversing the text itself.
  const labelPlacements = useMemo(() => {
    const placements = new Map<string, LabelPlacement>();
    if (!displayPins.length) return placements;
    const fallbackCenter = {
      x: displayPins.reduce((sum, pin) => sum + pin.x, 0) / displayPins.length,
      y: displayPins.reduce((sum, pin) => sum + pin.y, 0) / displayPins.length,
    };
    const boardCenter = displayOutline?.length
      ? {
          x: displayOutline.reduce((sum, point) => sum + point.x, 0) / displayOutline.length,
          y: displayOutline.reduce((sum, point) => sum + point.y, 0) / displayOutline.length,
        }
      : fallbackCenter;
    const byHeader = new Map<string, DisplayPin[]>();
    for (const displayPin of displayPins) {
      const header = displayPin.pin?.header ?? displayPin.det.id;
      const group = byHeader.get(header) ?? [];
      group.push(displayPin);
      byHeader.set(header, group);
    }

    for (const headerPins of byHeader.values()) {
      const withProfile = headerPins.filter((pin) => pin.pin);
      if (!withProfile.length) continue;
      const profileXs = withProfile.map((pin) => pin.pin!.pos_mm[0]);
      const profileYs = withProfile.map((pin) => pin.pin!.pos_mm[1]);
      const rangeX = Math.max(...profileXs) - Math.min(...profileXs);
      const rangeY = Math.max(...profileYs) - Math.min(...profileYs);
      const rowAxis: 0 | 1 = rangeX <= rangeY ? 0 : 1;
      const sorted = [...withProfile].sort(
        (a, b) => a.pin!.pos_mm[rowAxis] - b.pin!.pos_mm[rowAxis],
      );
      const rows: DisplayPin[][] = [];
      for (const pin of sorted) {
        const coordinate = pin.pin!.pos_mm[rowAxis];
        const row = rows.at(-1);
        const rowCoordinate = row?.[0].pin?.pos_mm[rowAxis];
        if (!row || rowCoordinate === undefined || Math.abs(coordinate - rowCoordinate) > 0.5) {
          rows.push([pin]);
        } else {
          row.push(pin);
        }
      }
      const rowCentres = rows.map((row) => ({
        x: row.reduce((sum, pin) => sum + pin.x, 0) / row.length,
        y: row.reduce((sum, pin) => sum + pin.y, 0) / row.length,
      }));
      const headerCenter = {
        x: rowCentres.reduce((sum, point) => sum + point.x, 0) / rowCentres.length,
        y: rowCentres.reduce((sum, point) => sum + point.y, 0) / rowCentres.length,
      };

      rows.forEach((row, rowIndex) => {
        const origin = rowCentres.length > 1 ? headerCenter : boardCenter;
        let dx = rowCentres[rowIndex].x - origin.x;
        let dy = rowCentres[rowIndex].y - origin.y;
        const length = Math.hypot(dx, dy);
        if (length < 0.001) {
          dx = 0;
          dy = -1;
        } else {
          dx /= length;
          dy /= length;
        }
        const placement: LabelPlacement = {
          x: dx * LABEL_OFFSET_PX,
          y: dy * LABEL_OFFSET_PX,
          textAnchor: dx > 0.35 ? "start" : dx < -0.35 ? "end" : "middle",
        };
        for (const pin of row) placements.set(pin.det.id, placement);
      });
    }
    return placements;
  }, [displayOutline, displayPins]);

  /** Overlapping hit areas resolve to the nearest marker center. */
  const nearestPin = (px: number, py: number): DisplayPin | null => {
    let best: DisplayPin | null = null;
    let bestDistance = HIT_RADIUS_PX;
    for (const dp of displayPins) {
      const distance = Math.hypot(dp.x - px, dp.y - py);
      if (distance <= bestDistance) {
        bestDistance = distance;
        best = dp;
      }
    }
    return best;
  };

  const localPoint = (event: { clientX: number; clientY: number; currentTarget: Element }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const point = localPoint(event);
    const hit = nearestPin(point.x, point.y);
    setHover(hit ? { id: hit.det.id, x: point.x, y: point.y } : null);
  };

  const handleClick = (event: ReactMouseEvent<SVGSVGElement>) => {
    const point = localPoint(event);
    const hit = nearestPin(point.x, point.y);
    onSelectPin(hit ? hit.det.id : null); // empty video click deselects
  };

  const hoveredPin = interactive && hover
    ? (displayPins.find((dp) => dp.det.id === hover.id) ?? null)
    : null;

  const guidanceCallout = useMemo(() => {
    const targetPinId = activeGuidePinId;
    if (!targetPinId) return null;
    const target = displayPins.find((dp) => dp.det.id === targetPinId);
    if (!target?.pin) return null;
    const pin = target.pin;
    const labels = HEADER_GUIDE_LABELS[pin.header];
    const pi = piHeaderGuideText(pin, t);
    const ordinal = pi?.number ?? pin.index + 1;
    const peerPin = guidePeerPose?.tracking !== "searching"
      ? guidePeerPose?.pins.find(p => p.id === guidePeerPinId && p.v) : null;
    const peer = peerPin ? toDisplay(letterbox, peerPin.x, peerPin.y) : null;
    const obstacles: LabelRect[] = [];
    if (peer) {
      const peerBounds = pointBounds((guidePeerPose?.outline ?? []).map(([x, y]) => toDisplay(letterbox, x, y)));
      if (peerBounds) obstacles.push(peerBounds);
      const callout = guidanceCalloutGeometry(peer.x, peer.y, width, height);
      obstacles.push({ x: callout.boxX, y: callout.boxY, width: callout.boxWidth, height: callout.boxHeight });
    }
    const label = pi ? guideLabel !== undefined ? guideLabel : placeWiringLabel(target, peer, pointBounds([...(displayOutline ?? []), ...displayPins]), obstacles, width, height) : null;
    return {
      target,
      pin,
      pi,
      label,
      ordinal,
      headerLabel: labels ? t(labels.headerKey) : pin.header,
      countFromLabel: labels ? t(labels.countFromKey) : t("boardGuide.countFromFirst"),
      ...guidanceCalloutGeometry(target.x, target.y, width, height),
      ...(pi ? guidancePointerGeometry(target.x, target.y, width, height) : {}),
      ...(label ? { startX: label.startX, startY: label.startY, endX: label.endX, endY: label.endY } : {}),
    };
  }, [activeGuidePinId, displayPins, displayOutline, guidePeerPose, guidePeerPinId, guideLabel, letterbox, height, t, width]);

  return (
    <>
      <svg
        className={`overlay-svg${tracking === "stale" ? " stale" : ""}${guidanceHeld ? " guidance-held" : ""}`}
        width={Math.max(1, width)}
        height={Math.max(1, height)}
        onPointerMove={interactive ? handlePointerMove : undefined}
        onPointerLeave={interactive ? () => setHover(null) : undefined}
        onClick={interactive ? handleClick : undefined}
        style={{
          cursor: hoveredPin ? "pointer" : "default",
          pointerEvents: interactive ? "auto" : "none",
        }}
        role="presentation"
      >
        <defs>
          <marker
            id="board-guidance-arrowhead"
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
        {outlinePoints && <polygon className="board-outline" points={outlinePoints} strokeDasharray={visualDetection?.pose_quality?.stability === 'motion_prediction' ? '6 5' : undefined} />}
        {outlinePoints && visualDetection?.pose_quality?.stability === 'motion_prediction' && <text x={displayOutline?.[0].x} y={(displayOutline?.[0].y ?? 0) - 10} fill="#64cfff" fontSize="13">預測補位 · 非辨識</text>}
        <g key={lockSeq}>
          {displayPins.map((dp) => {
            const isHovered = hover?.id === dp.det.id;
            const isSelected = selectedPinId === dp.det.id;
            const isHighlighted = highlightIds ? highlightIds.has(dp.det.id) : true;
            const isGuidanceTarget = activeGuidePinId === dp.det.id;
            const labelPlacement = labelPlacements.get(dp.det.id) ?? {
              x: 0,
              y: -LABEL_OFFSET_PX,
              textAnchor: "middle" as const,
            };
            const color = dp.pin ? pinColorVar(dp.pin) : "var(--cap-other)";
            const pinState = pinStates.get(dp.det.id);
            const markerPerspective = markerPerspectives.get(dp.det.id) ?? {
              rx: MARKER_RADIUS_PX,
              ry: MARKER_RADIUS_PX,
              angleDeg: 0,
            };
            const markerRotation = `rotate(${markerPerspective.angleDeg})`;
            const markerClass = [
              "pin-marker",
              isHovered ? "hovered" : "",
              highlightIds && isHighlighted ? "boost" : "",
              pinState ?? "",
              isGuidanceTarget ? "guidance-target" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <g
                key={dp.det.id}
                transform={`translate(${dp.x} ${dp.y})`}
                className={`pin-group${isHighlighted ? "" : " dim"}${isGuidanceTarget ? " guidance-active" : ""}`}
                style={{ "--mk": color } as CSSProperties}
              >
                <title>
                  {pinDisplayNameWithNumber(dp.pin) || dp.det.id}
                  {pinState ? ` · ${pinState}` : ""}
                </title>
                {isSelected && (
                  <ellipse
                    className="select-ring"
                    rx={markerPerspective.rx + 4}
                    ry={markerPerspective.ry + 4}
                    transform={markerRotation}
                  />
                )}
                <g className={markerClass} style={{ animationDelay: `${dp.index * STAGGER_MS}ms` }}>
                  {isGuidanceTarget && (
                    <>
                      <ellipse
                        className="guidance-halo guidance-halo-outer"
                        rx={markerPerspective.rx + 10}
                        ry={markerPerspective.ry + 10}
                        transform={markerRotation}
                      />
                      <ellipse
                        className="guidance-halo guidance-halo-inner"
                        rx={markerPerspective.rx + 6}
                        ry={markerPerspective.ry + 6}
                        transform={markerRotation}
                      />
                    </>
                  )}
                  <ellipse
                    className="pin-dot"
                    rx={markerPerspective.rx}
                    ry={markerPerspective.ry}
                    transform={markerRotation}
                  />
                </g>
                <text
                  className="pin-label pin-label-always"
                  x={labelPlacement.x}
                  y={labelPlacement.y}
                  textAnchor={labelPlacement.textAnchor}
                  dominantBaseline="middle"
                >
                  {pinOverlayLabel(dp.pin) || dp.det.id}
                </text>
                {/* Invisible enlarged hit circle (actual hits use nearest-center). */}
                <circle className="pin-hit" r={HIT_RADIUS_PX / 2} />
              </g>
            );
          })}
        </g>
        {guidanceCallout && (
          <g className={`component-pin-callout board-pin-callout${guidanceCallout.pi ? " pi-guidance-pointer" : ""}`}
            role={guidanceCallout.pi ? "img" : undefined} aria-label={guidanceCallout.pi?.title}>
            <line
              className="component-pin-callout-arrow"
              x1={guidanceCallout.startX}
              y1={guidanceCallout.startY}
              x2={guidanceCallout.endX}
              y2={guidanceCallout.endY}
              markerEnd="url(#board-guidance-arrowhead)"
            />
            {guidanceCallout.pi && guidanceCallout.label ? <>
              <rect className="component-pin-callout-box pi-row-label-box" x={guidanceCallout.label.x} y={guidanceCallout.label.y}
                width={guidanceCallout.label.width} height={guidanceCallout.label.height} rx="8" />
              <text className="pi-row-label-text" x={guidanceCallout.label.x + 10} y={guidanceCallout.label.y + 21}>
                {guidanceCallout.pi.title}
              </text>
            </> : null}
            {!guidanceCallout.pi ? <><rect
              className="component-pin-callout-box"
              x={guidanceCallout.boxX}
              y={guidanceCallout.boxY}
              width={guidanceCallout.boxWidth}
              height={guidanceCallout.boxHeight}
              rx="9"
            />
            <text
              className="component-pin-callout-title"
              x={guidanceCallout.boxX + 10}
              y={guidanceCallout.boxY + 18}
            >
              {t("boardGuide.pinOrdinal", {
                header: guidanceCallout.headerLabel,
                number: guidanceCallout.ordinal,
                pin: pinDisplayNameWithNumber(guidanceCallout.pin),
              })}
            </text>
            <text
              className="component-pin-callout-hint"
              x={guidanceCallout.boxX + 10}
              y={guidanceCallout.boxY + 35}
            >
              {guidanceCallout.countFromLabel}
            </text>
            </> : null}
          </g>
        )}
      </svg>
      {hoveredPin && hover && (
        <div className="pin-tooltip" style={tooltipStyle(hover.x, hover.y, width, height)}>
          <div className="tt-title">
            {pinDisplayNameWithNumber(hoveredPin.pin) || hoveredPin.det.id}
          </div>
          {hoveredPin.pin && (
            <div className="tt-chips">
              {orderedCapabilityTypes(hoveredPin.pin).map((type) => (
                <span
                  key={type}
                  className="chip"
                  style={{ "--c": capColorVar(type, hoveredPin.pin) } as CSSProperties}
                >
                  {capLabel(t, type)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function tooltipStyle(x: number, y: number, width: number, height: number): CSSProperties {
  const left =
    x + TOOLTIP_OFFSET + TOOLTIP_WIDTH > width ? x - TOOLTIP_OFFSET - TOOLTIP_WIDTH : x + TOOLTIP_OFFSET;
  const top =
    y + TOOLTIP_OFFSET + TOOLTIP_HEIGHT > height ? y - TOOLTIP_OFFSET - TOOLTIP_HEIGHT : y + TOOLTIP_OFFSET;
  return { left: Math.max(4, left), top: Math.max(4, top) };
}
