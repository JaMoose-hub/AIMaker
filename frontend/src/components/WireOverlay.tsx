import { type CSSProperties } from "react";
import { computeLetterbox, toDisplay, type DisplayPoint, type Letterbox } from "../lib/geometry";
import { isWireTraceFresh } from "../lib/traceFreshness";
import { useWireTrace } from "../lib/wsClient";
import type { DetectionMessage, WireEndpoint, WireInstance } from "../lib/types";

/**
 * Renders the latest `wire_trace` WS message (docs/wire-recognition-design.md
 * §3/§4) as an informational SVG layer stacked on the same overlay area as
 * `PinOverlay` — same letterbox transform, same source-pixel coordinate
 * space (api-contract.md §3). Purely informational: `pointer-events: none`
 * on the root <svg> so it never intercepts the existing pin hover/click
 * handling in PinOverlay.
 *
 * Renders nothing until the first wire_trace message arrives, and nothing
 * again once board tracking is "searching" (no pins to snap against, so the
 * backend already sends an empty `wires` list - see wire_tracer.trace()).
 */

const PIN_MARKER_RADIUS_PX = 4; // smaller than PinOverlay's own 7px dot - reads as "attached to", not a duplicate pin
const HALO_RADIUS_PX = 9;
const FLOATING_RADIUS_PX = 6;

const WIRE_COLOR_VAR: Record<string, string> = {
  red: "var(--wire-red)",
  orange: "var(--wire-orange)",
  brown: "var(--wire-brown)",
  yellow: "var(--wire-yellow)",
  green: "var(--wire-green)",
  blue: "var(--wire-blue)",
  purple: "var(--wire-purple)",
  black: "var(--wire-black)",
  gray: "var(--wire-gray)",
  white: "var(--wire-white)",
};

function wireStrokeVar(color: string): string {
  return WIRE_COLOR_VAR[color] ?? "var(--wire-other)";
}

interface WireOverlayProps {
  letterbox: Letterbox;
  width: number;
  height: number;
  /** Latest detection message, used to look up a resolved pin's own live screen position. */
  detection: DetectionMessage | null;
}

export function WireOverlay({ letterbox, width, height, detection }: WireOverlayProps) {
  const wireTrace = useWireTrace();
  const freshWireTrace = isWireTraceFresh(wireTrace, detection) ? wireTrace : null;

  if (!freshWireTrace || freshWireTrace.wires.length === 0) return null;

  // A trace is produced on a particular source frame.  During a camera
  // switch, the latest detection may already have a different resolution;
  // use the trace's own source size for its path/floating endpoints instead
  // of briefly stretching old source pixels through the new letterbox.
  const traceLetterbox = freshWireTrace.video_size
    ? computeLetterbox(
        freshWireTrace.video_size,
        width,
        height,
        letterbox.mirrorX,
        letterbox.mirrorY,
      )
    : letterbox;

  /**
   * A "pin" endpoint's marker is drawn at the pin's own current tracked
   * position (so it visually sits exactly on the pin dot and tracks it).
   * Per the WS contract (docs/api-contract.md §2 / wire_worker.py's
   * _endpoint_message), a "pin"-kind endpoint never carries `px` - only
   * "floating"/"ambiguous_tie" do. Because wire-trace updates on its own
   * slower cadence (~0.5-2s, see docs/wire-recognition-design.md §5) than
   * live pin tracking (~30Hz), a pin a wire resolved to at trace time can
   * legitimately have gone off-frame/not-visible by the time this renders
   * (e.g. the board moved closer and a pin near the edge dropped out) -
   * that's a real, expected staleness gap, not a contract violation. There
   * is no safe pixel to fall back to in that case, so this returns null
   * and the caller skips drawing that one marker rather than guessing -
   * same "never fabricate a position" discipline the backend already
   * applies to floating/ambiguous_tie endpoints.
   */
  const resolvePoint = (endpoint: WireEndpoint): DisplayPoint | null => {
    if (endpoint.kind === "pin") {
      if (!endpoint.pin_id) return null;
      const pin = detection?.pins.find((p) => p.id === endpoint.pin_id && p.v);
      if (!pin) return null;
      // Resolved pins are looked up in the newest detection and therefore
      // belong to the newest detection letterbox, not the older wire trace.
      return toDisplay(letterbox, pin.x, pin.y);
    }
    if (!endpoint.px) return null;
    return toDisplay(traceLetterbox, endpoint.px[0], endpoint.px[1]);
  };

  return (
    <svg
      className={`wire-overlay-svg${freshWireTrace.board_tracking === "stale" ? " stale" : ""}`}
      width={Math.max(1, width)}
      height={Math.max(1, height)}
      role="presentation"
      aria-hidden="true"
    >
      {freshWireTrace.wires.map((wire) => (
        <WirePath key={wire.wire_id} wire={wire} letterbox={traceLetterbox} resolvePoint={resolvePoint} />
      ))}
    </svg>
  );
}

interface WirePathProps {
  wire: WireInstance;
  letterbox: Letterbox;
  resolvePoint: (endpoint: WireEndpoint) => DisplayPoint | null;
}

function WirePath({ wire, letterbox, resolvePoint }: WirePathProps) {
  const points = wire.path.map(([x, y]) => {
    const p = toDisplay(letterbox, x, y);
    return `${p.x},${p.y}`;
  });
  const a = resolvePoint(wire.endpoint_a);
  const b = resolvePoint(wire.endpoint_b);

  return (
    <g style={{ "--wc": wireStrokeVar(wire.color) } as CSSProperties}>
      <polyline
        className={`wire-path${wire.ambiguous ? " ambiguous" : ""}${wire.attachment === "unknown" ? " unknown" : ""}${wire.attachment === "resting" ? " resting" : ""}`}
        points={points.join(" ")}
      />
      {a && <EndpointMarker endpoint={wire.endpoint_a} point={a} />}
      {b && <EndpointMarker endpoint={wire.endpoint_b} point={b} />}
    </g>
  );
}

function EndpointMarker({ endpoint, point }: { endpoint: WireEndpoint; point: DisplayPoint }) {
  if (endpoint.kind === "pin") {
    return (
      <g transform={`translate(${point.x} ${point.y})`}>
        <circle className="wire-endpoint-halo" r={HALO_RADIUS_PX} />
        <circle className="wire-endpoint-pin" r={PIN_MARKER_RADIUS_PX} />
      </g>
    );
  }
  // "floating" (nothing near enough) and "ambiguous_tie" (2+ equally-close
  // pins) are both honestly unresolved - never hidden, drawn as an open/
  // dashed marker rather than a solid "connected" dot (design doc §2 Stage D).
  return (
    <g transform={`translate(${point.x} ${point.y})`}>
      <circle
        className={`wire-endpoint-floating${endpoint.kind === "ambiguous_tie" ? " tie" : ""}`}
        r={FLOATING_RADIUS_PX}
      />
    </g>
  );
}
