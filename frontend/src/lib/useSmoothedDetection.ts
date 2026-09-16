import { useCallback, useEffect, useRef, useState } from "react";
import type { DetectionMessage, DetectionPin } from "./types";
import { isSynchronizedPose } from "./realtimeFrame";

// The backend pose stream normally runs at 15-20 Hz.  A short exponential
// interpolation fills the visual gaps at requestAnimationFrame cadence while
// keeping the displayed lattice only about one frame behind the newest pose.
const FOLLOW_TIME_CONSTANT_MS = 28;
const SETTLE_EPSILON_PX = 0.18;
const SNAP_DISTANCE_FRACTION = 0.18;

function sameVideoSpace(left: DetectionMessage, right: DetectionMessage): boolean {
  return (
    left.board_id === right.board_id &&
    left.video_size[0] === right.video_size[0] &&
    left.video_size[1] === right.video_size[1] &&
    left.pins.length === right.pins.length
  );
}

function pinMap(message: DetectionMessage): Map<string, DetectionPin> {
  return new Map(message.pins.map((pin) => [pin.id, pin]));
}

function maxDisplacement(left: DetectionMessage, right: DetectionMessage): number {
  const previous = pinMap(left);
  let maximum = 0;
  for (const pin of right.pins) {
    const old = previous.get(pin.id);
    if (!old) return Number.POSITIVE_INFINITY;
    maximum = Math.max(maximum, Math.hypot(pin.x - old.x, pin.y - old.y));
  }
  return maximum;
}

function shouldSnap(
  current: DetectionMessage | null,
  target: DetectionMessage | null,
): boolean {
  if (!current || !target) return true;
  if (current.tracking === "searching" || target.tracking === "searching") return true;
  if (!sameVideoSpace(current, target)) return true;
  const diagonal = Math.hypot(target.video_size[0], target.video_size[1]);
  return maxDisplacement(current, target) > diagonal * SNAP_DISTANCE_FRACTION;
}

function lerp(a: number, b: number, amount: number): number {
  return a + (b - a) * amount;
}

function interpolateDetection(
  current: DetectionMessage,
  target: DetectionMessage,
  amount: number,
): DetectionMessage {
  const previousPins = pinMap(current);
  const pins = target.pins.map((pin) => {
    const old = previousPins.get(pin.id);
    if (!old || old.v !== pin.v) return pin;
    return {
      ...pin,
      x: lerp(old.x, pin.x, amount),
      y: lerp(old.y, pin.y, amount),
    };
  });
  const outline =
    current.outline && target.outline && current.outline.length === target.outline.length
      ? target.outline.map(([x, y], index) => [
          lerp(current.outline![index][0], x, amount),
          lerp(current.outline![index][1], y, amount),
        ] as [number, number])
      : target.outline;
  return { ...target, pins, outline };
}

/**
 * Visual-only pose interpolation.  Backend confidence, hand-occlusion holds,
 * electrical decisions, and source coordinates remain authoritative; this
 * hook only fills the short gaps between accepted detection messages.
 */
export function useSmoothedDetection(
  detection: DetectionMessage | null,
): DetectionMessage | null {
  const synchronized = isSynchronizedPose(detection);
  const [visual, setVisual] = useState<DetectionMessage | null>(detection);
  const visualRef = useRef<DetectionMessage | null>(detection);
  const targetRef = useRef<DetectionMessage | null>(detection);
  const animationRef = useRef<number | null>(null);
  const lastTimeRef = useRef(0);

  const animate = useCallback((now: number) => {
    const current = visualRef.current;
    const target = targetRef.current;
    if (shouldSnap(current, target)) {
      visualRef.current = target;
      setVisual(target);
      animationRef.current = null;
      return;
    }

    const remaining = maxDisplacement(current!, target!);
    if (remaining <= SETTLE_EPSILON_PX) {
      visualRef.current = target;
      setVisual(target);
      animationRef.current = null;
      return;
    }

    const elapsed = Math.min(50, Math.max(1, now - lastTimeRef.current));
    lastTimeRef.current = now;
    const amount = 1 - Math.exp(-elapsed / FOLLOW_TIME_CONSTANT_MS);
    const next = interpolateDetection(current!, target!, amount);
    visualRef.current = next;
    setVisual(next);
    animationRef.current = window.requestAnimationFrame(animate);
  }, []);

  useEffect(() => {
    targetRef.current = detection;
    if (synchronized || shouldSnap(visualRef.current, detection)) {
      if (animationRef.current !== null) {
        window.cancelAnimationFrame(animationRef.current);
        animationRef.current = null;
      }
      visualRef.current = detection;
      setVisual(detection);
      return;
    }
    if (animationRef.current === null) {
      lastTimeRef.current = performance.now();
      animationRef.current = window.requestAnimationFrame(animate);
    }
  }, [animate, detection, synchronized]);

  useEffect(
    () => () => {
      if (animationRef.current !== null) {
        window.cancelAnimationFrame(animationRef.current);
      }
    },
    [],
  );

  // Bypass state/effect and animation-frame latency for the synchronized
  // JPEG path. Both PinOverlay and GuideConnectionOverlay use this hook.
  return synchronized ? detection : visual;
}
