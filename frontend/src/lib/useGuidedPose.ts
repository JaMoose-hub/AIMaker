import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  guidePoseReady,
  guidePoseVisible,
  type ActiveGuideTarget,
} from "./componentWiringGuides";
import type { ComponentPoseMessage, DetectionMessage } from "./types";
import { useDetections, type WsSnapshot } from "./wsClient";
import { getMotionDisplay, subscribeMotionDisplay } from "./motionDisplayStore";

const POSE_FRESH_MS = 1500;
const LOCK_LOSS_GRACE_MS = 900;
const LAST_POSE_HOLD_MS = 3500;

interface HeldGuidePose {
  targetKey: string;
  detection: DetectionMessage;
  pose: ComponentPoseMessage;
  receivedAtMs: number;
  wasLocked: boolean;
}

function targetKey(target: ActiveGuideTarget | null): string | null {
  if (!target) return null;
  return [target.componentId, target.boardPinId ?? "", target.componentPinId ?? ""].join(":");
}

/**
 * Keep the lesson visually stable across short component-model dropouts.
 *
 * `ready` has a short loss-only grace period so buttons and copy do not flash
 * between states. `visual*` can remain available longer, but only from the
 * last matching pose and is explicitly marked held; it never becomes new
 * verification evidence.
 */
export function useGuidedPose(target: ActiveGuideTarget | null, displaySnapshot?: WsSnapshot) {
  const originalSnapshot = useDetections();
  const sharedFrame = useSyncExternalStore(subscribeMotionDisplay, getMotionDisplay, getMotionDisplay);
  const sharedSnapshot = sharedFrame !== undefined ? {
    ...originalSnapshot,
    detection: sharedFrame?.detection ?? null,
    componentPoses: sharedFrame?.components ?? [],
    detectionReceivedAtMs: sharedFrame?.receivedAt ?? 0,
    componentReceivedAtMs: Object.fromEntries((sharedFrame?.components ?? []).map((pose) => [pose.component_id, sharedFrame!.receivedAt])),
  } : undefined;
  const snapshot = displaySnapshot ?? sharedSnapshot ?? originalSnapshot;
  const sameFrameMode = displaySnapshot !== undefined || sharedFrame !== undefined;
  const heldRef = useRef<HeldGuidePose | null>(null);
  const [, tick] = useState(0);
  const enabled = target !== null;
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => tick((value) => value + 1), 250);
    return () => window.clearInterval(timer);
  }, [enabled]);

  const pose = snapshot.componentPoses.find((item) => item.component_id === target?.componentId) ?? null;
  const now = Date.now();
  const componentReceivedAtMs = snapshot.componentReceivedAtMs[target?.componentId ?? ""] ?? 0;
  const fresh = snapshot.connected && now - snapshot.detectionReceivedAtMs < POSE_FRESH_MS
    && now - componentReceivedAtMs < POSE_FRESH_MS;
  const strictReady = guidePoseReady(snapshot.detection, pose, target, fresh);
  const currentVisible = guidePoseVisible(snapshot.detection, pose, target, fresh);
  const key = targetKey(target);
  const receivedAtMs = Math.min(snapshot.detectionReceivedAtMs, componentReceivedAtMs);
  const currentLocked = key && snapshot.detection && pose && strictReady
    ? {
      targetKey: key,
      detection: snapshot.detection,
      pose,
      receivedAtMs,
      wasLocked: true,
    } satisfies HeldGuidePose
    : null;

  useEffect(() => {
    if (!key) {
      heldRef.current = null;
      return;
    }
    if (currentLocked) {
      heldRef.current = currentLocked;
      return;
    }
    if (heldRef.current?.targetKey === key) return;
    // A page can open while the backend is already publishing an occlusion
    // hold. It may be shown as held, but it must not inherit ready status.
    heldRef.current = currentVisible && snapshot.detection && pose
      ? {
        targetKey: key,
        detection: snapshot.detection,
        pose,
        receivedAtMs,
        wasLocked: false,
      }
      : null;
  }, [currentLocked, currentVisible, key, pose, receivedAtMs, snapshot.detection]);

  const held = currentLocked ?? (heldRef.current?.targetKey === key ? heldRef.current : null);
  const heldAgeMs = held ? now - held.receivedAtMs : Number.POSITIVE_INFINITY;
  const ready = strictReady || (!sameFrameMode && Boolean(
    snapshot.connected
      && held?.wasLocked
      && heldAgeMs <= LOCK_LOSS_GRACE_MS,
  ));
  // A moving camera frame must never use a historical held guide pose.
  const visualReady = sameFrameMode ? strictReady : Boolean(held && heldAgeMs <= LAST_POSE_HOLD_MS);

  return {
    ...snapshot,
    pose,
    ready,
    strictReady,
    visualReady,
    visualHeld: visualReady && !ready,
    visualDetection: visualReady ? held!.detection : null,
    visualPose: visualReady ? held!.pose : null,
  };
}
