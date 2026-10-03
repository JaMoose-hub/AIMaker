import { useEffect, useRef, useState } from "react";
import type { MobileSession } from "../lib/mobile";
import type { ActiveGuideTarget } from "../lib/componentWiringGuides";
import type { Pin } from "../lib/types";
import { computeLetterbox, toDisplay, useElementSize } from "../lib/geometry";
import { mobileRecognitionLease, phoneRecognitionForDisplay } from "../lib/mobileRecognition";
import { pointBounds, placeWiringLabelPair } from "../lib/wiringLabelLayout";
import { PinOverlay } from "./PinOverlay";
import { ComponentPinOverlay } from "./ComponentPinOverlay";
import { GuideConnectionOverlay } from "./GuideConnectionOverlay";
import { ObjectRecognitionOverlay } from "./ObjectRecognitionOverlay";
import type { BodyRecognition } from "../lib/realtimeFrame";

const NO_PINS: ReadonlyMap<string, Pin> = new Map();
const OFFSET = { x: 0, y: 0 };
const NO_SELECTION = () => {};

export interface PhoneOverlayOptions {
  pinsById?: ReadonlyMap<string, Pin>;
  guideTarget?: ActiveGuideTarget | null;
}

/** Reuse webcam renderers, but only with this phone's observations. No camera
 * opening, websocket subscriptions for detections, mirroring or calibration. */
export function MobileRecognitionOverlay({ session, videoSize, pinsById = NO_PINS, guideTarget = null }: {
  session: MobileSession; videoSize: [number, number];
} & PhoneOverlayOptions) {
  const host = useRef<HTMLDivElement>(null);
  const size = useElementSize(host);
  const [clock, setClock] = useState(() => performance.now());
  const lease = useRef({ key: "", deadline: 0 });
  const now = Math.max(clock, performance.now());
  lease.current = mobileRecognitionLease(session, now, lease.current);
  const { key, deadline } = lease.current;
  useEffect(() => {
    if (!deadline || now >= deadline) return;
    const timer = setTimeout(() => setClock(performance.now()), Math.max(1, deadline - performance.now()));
    return () => clearTimeout(timer);
  }, [key, deadline, clock]);
  const packet = phoneRecognitionForDisplay(session, videoSize, now, lease.current);
  const letterbox = computeLetterbox(videoSize, size.width, size.height);
  const board = packet?.detection ?? null;
  const components = packet?.components ?? [];
  const peer = components.find(p => p.component_id === guideTarget?.componentId) ?? null;
  const boardPinId = guideTarget?.boardPinId ?? null;
  const componentPinId = guideTarget?.componentPinId ?? null;
  const bodies: BodyRecognition[] = packet ? [packet.detection, ...components].flatMap(pose => {
    const located = pose.tracking !== "searching" && pose.pins.some(p => p.v);
    const box = pose.body?.box;
    const outline = pose.outline ?? (box?.length === 4 && box.every(Number.isFinite)
      ? [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]] as [number, number][] : null);
    return outline ? [{ id: "component_id" in pose ? pose.component_id : pose.board_id,
      outline, pinsLocated: located, drawOutline: !pose.outline?.length }] : [];
  }) : [];
  const anchor = (pose: typeof board | typeof peer, pinId: string | null) => {
    const pins = pose?.tracking !== "searching" ? pose?.pins.filter(p => p.v) ?? [] : [];
    const pin = pins.find(p => p.id === pinId);
    const points = [...pins.map(p => toDisplay(letterbox, p.x, p.y)),
      ...(pose?.tracking !== "searching" ? pose?.outline ?? [] : []).map(([x, y]) => toDisplay(letterbox, x, y))];
    return { target: pin ? toDisplay(letterbox, pin.x, pin.y) : null, bounds: pointBounds(points) };
  };
  const labels = guideTarget ? placeWiringLabelPair(anchor(board, boardPinId), anchor(peer, componentPinId), size.width, size.height) : null;
  return <div ref={host} className="mobile-recognition-layer" data-recognition-source="phone" data-recognition-frame={packet?.frame_seq}>
    {packet && size.width > 0 && size.height > 0 ? <>
      <ObjectRecognitionOverlay items={bodies} letterbox={letterbox} width={size.width} height={size.height} />
      {guideTarget?.connectionKind === "direct" ? <GuideConnectionOverlay detection={board} componentPose={peer}
        letterbox={letterbox} width={size.width} height={size.height} boardPinId={boardPinId} componentPinId={componentPinId} boardDisplayOffsetPx={OFFSET} /> : null}
      {components.map(pose => <ComponentPinOverlay key={pose.component_id} pose={pose} letterbox={letterbox}
        width={size.width} height={size.height} targetPinId={pose === peer ? componentPinId : null}
        guideLabel={pose === peer ? labels?.component : undefined} />)}
      <PinOverlay detection={board} letterbox={letterbox} width={size.width} height={size.height} pinsById={pinsById}
        highlightIds={null} selectedPinId={null} onSelectPin={NO_SELECTION} interactive={false} lockSeq={0}
        tracking={board?.tracking ?? "searching"} displayOffsetPx={OFFSET} guidePinId={boardPinId} localGuidanceOnly
        guidePeerPose={peer} guidePeerPinId={componentPinId} guideLabel={labels?.board} />
    </> : null}
  </div>;
}
