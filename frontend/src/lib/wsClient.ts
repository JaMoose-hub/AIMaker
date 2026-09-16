import { useSyncExternalStore } from "react";
import type {
  ComponentPoseMessage,
  ComponentSegmentMessage,
  DetectionMessage,
  GuidanceCheckMessage,
  HelloMessage,
  RuntimeChangedMessage,
  VerificationUpdateMessage,
  WireTraceMessage,
} from "./types";

/**
 * WebSocket client for /ws/detections (api-contract.md §2).
 *
 * - Auto-reconnects with exponential backoff (0.5s -> 5s cap).
 * - Keeps only the latest detection (the backend sends latest-state, no queue).
 * - Re-renders are coalesced to animation frames: messages mutate internal
 *   state and a single requestAnimationFrame flush publishes an immutable
 *   snapshot to React via useSyncExternalStore.
 * - Unknown message `type` values are ignored (forward compatibility).
 */

export interface WsSnapshot {
  detectionReceivedAtMs: number;
  componentReceivedAtMs: Readonly<Record<string, number>>;
  detection: DetectionMessage | null;
  componentPoses: ComponentPoseMessage[];
  componentPose: ComponentPoseMessage | null;
  componentSegments: ComponentSegmentMessage | null;
  hello: HelloMessage | null;
  /** Latest wire_trace message, or null before the first one arrives (wire-recognition-design.md §4 — its own throttled cadence, not tied to detectionsPerSec). */
  wireTrace: WireTraceMessage | null;
  guidance: GuidanceCheckMessage | null;
  verification: VerificationUpdateMessage | null;
  connected: boolean;
  /** Detection messages received during the last full second. */
  detectionsPerSec: number;
}

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 5000;
const WS_PATH = "/ws/detections";

type Listener = () => void;

class WsClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private started = false;

  private detection: DetectionMessage | null = null;
  private detectionReceivedAtMs = 0;
  private componentReceivedAtMs: Record<string, number> = {};
  private componentPoses = new Map<string, ComponentPoseMessage>();
  private componentPose: ComponentPoseMessage | null = null;
  private componentSegments: ComponentSegmentMessage | null = null;
  private hello: HelloMessage | null = null;
  private wireTrace: WireTraceMessage | null = null;
  private guidance: GuidanceCheckMessage | null = null;
  private verification: VerificationUpdateMessage | null = null;
  private connected = false;
  private detectionsPerSec = 0;

  private snapshot: WsSnapshot = {
    detectionReceivedAtMs: 0,
    componentReceivedAtMs: {},
    detection: null,
    componentPoses: [],
    componentPose: null,
    componentSegments: null,
    hello: null,
    wireTrace: null,
    guidance: null,
    verification: null,
    connected: false,
    detectionsPerSec: 0,
  };

  private rafId: number | null = null;
  private backstopId: number | null = null;
  private backoffMs = INITIAL_BACKOFF_MS;
  private reconnectTimer: number | null = null;
  private messageCount = 0;
  private runtimeRevision = 0;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    this.start();
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): WsSnapshot => this.snapshot;

  clearGuidance = (): void => {
    if (this.guidance === null && this.verification === null) return;
    this.guidance = null;
    this.verification = null;
    this.flush();
  };

  prepareRuntime = (boardId: string, runtimeRevision: number): void => {
    const revision = Number(runtimeRevision) || 0;
    if (revision < this.runtimeRevision) return;
    this.runtimeRevision = revision;
    this.detection = null;
    this.detectionReceivedAtMs = 0;
    this.componentReceivedAtMs = {};
    this.componentPoses.clear();
    this.componentPose = null;
    this.componentSegments = null;
    this.wireTrace = null;
    this.guidance = null;
    this.verification = null;
    this.messageCount = 0;
    if (this.hello?.board_id !== boardId || this.hello.runtime_revision !== revision) {
      this.hello = null;
    }
    this.flush();
  };

  private start(): void {
    if (this.started) return;
    this.started = true;
    this.connect();
    window.setInterval(() => {
      if (this.detectionsPerSec !== this.messageCount) {
        this.detectionsPerSec = this.messageCount;
        this.scheduleFlush();
      }
      this.messageCount = 0;
    }, 1000);
  }

  private connect(): void {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}${WS_PATH}`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.backoffMs = INITIAL_BACKOFF_MS;
      this.connected = true;
      this.flush();
    };
    ws.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.detectionReceivedAtMs = 0;
      this.componentReceivedAtMs = {};
      if (this.connected) {
        this.connected = false;
        this.flush();
      }
      this.scheduleReconnect();
    };
    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
  }

  private handleMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(event.data);
    } catch {
      return;
    }
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as { type?: unknown }).type !== "string"
    ) {
      return;
    }
    const message = parsed as { type: string };
    if (message.type === "hello") {
      const hello = message as HelloMessage;
      this.prepareRuntime(hello.board_id, hello.runtime_revision);
      this.hello = hello;
      this.scheduleFlush();
    } else if (message.type === "runtime_changed") {
      const changed = message as RuntimeChangedMessage;
      this.prepareRuntime(changed.board_id, changed.runtime_revision);
    } else if (message.type === "detection") {
      const detection = message as DetectionMessage;
      if (detection.runtime_revision < this.runtimeRevision) return;
      if (detection.runtime_revision > this.runtimeRevision) {
        this.prepareRuntime(detection.board_id, detection.runtime_revision);
      }
      this.detection = detection;
      this.detectionReceivedAtMs = Date.now();
      this.messageCount += 1;
      this.scheduleFlush();
    } else if (message.type === "component_pose") {
      const componentPose = message as ComponentPoseMessage;
      this.componentPoses.set(componentPose.component_id, componentPose);
      this.componentReceivedAtMs[componentPose.component_id] = Date.now();
      if (
        componentPose.component_id === "photoresistor-module" ||
        this.componentPose === null ||
        this.componentPose.component_id === componentPose.component_id
      ) {
        this.componentPose = componentPose;
      }
      this.scheduleFlush();
    } else if (message.type === "component_segments") {
      this.componentSegments = message as ComponentSegmentMessage;
      this.scheduleFlush();
    } else if (message.type === "wire_trace") {
      // Own throttled cadence (design doc §4/§5) - deliberately NOT counted
      // into messageCount/detectionsPerSec, which reports pose-detection rate.
      this.wireTrace = message as WireTraceMessage;
      this.scheduleFlush();
    } else if (message.type === "guidance_check") {
      this.guidance = message as GuidanceCheckMessage;
      this.scheduleFlush();
    } else if (message.type === "verification_update") {
      this.verification = message as VerificationUpdateMessage;
      this.scheduleFlush();
    }
    // Any other `type` (wiring_check, telemetry, ...) is intentionally ignored.
  }

  /**
   * Coalesce bursts of messages into one React notification per frame.
   * requestAnimationFrame is suspended in hidden tabs, so a timeout backstop
   * keeps the snapshot fresh (at a low rate) when the page is not visible.
   */
  private scheduleFlush(): void {
    if (this.rafId !== null) return;
    this.rafId = window.requestAnimationFrame(() => {
      this.clearScheduled();
      this.flush();
    });
    this.backstopId = window.setTimeout(() => {
      this.clearScheduled();
      this.flush();
    }, 250);
  }

  private clearScheduled(): void {
    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.backstopId !== null) {
      window.clearTimeout(this.backstopId);
      this.backstopId = null;
    }
  }

  private flush(): void {
    this.snapshot = {
      detectionReceivedAtMs: this.detectionReceivedAtMs,
      componentReceivedAtMs: { ...this.componentReceivedAtMs },
      detection: this.detection,
      componentPoses: Array.from(this.componentPoses.values()),
      componentPose: this.componentPose,
      componentSegments: this.componentSegments,
      hello: this.hello,
      wireTrace: this.wireTrace,
      guidance: this.guidance,
      verification: this.verification,
      connected: this.connected,
      detectionsPerSec: this.detectionsPerSec,
    };
    for (const listener of this.listeners) listener();
  }
}

export const wsClient = new WsClient();

/** Latest detection state, throttled to animation frames. */
export function useDetections(): WsSnapshot {
  return useSyncExternalStore(wsClient.subscribe, wsClient.getSnapshot);
}

/** Latest wire_trace message, throttled to animation frames (same store as useDetections). */
export function useWireTrace(): WireTraceMessage | null {
  return useSyncExternalStore(wsClient.subscribe, wsClient.getSnapshot).wireTrace;
}

/** Latest authoritative guidance verdict, when a step is active. */
export function useGuidance(): GuidanceCheckMessage | null {
  return useSyncExternalStore(wsClient.subscribe, wsClient.getSnapshot).guidance;
}

/** Latest fused geometry + visual + electrical result for the active step. */
export function useVerification(): VerificationUpdateMessage | null {
  return useSyncExternalStore(wsClient.subscribe, wsClient.getSnapshot).verification;
}

/** Clear a verdict that belongs to a step the REST API just replaced/removed. */
export function clearGuidanceSnapshot(): void {
  wsClient.clearGuidance();
}
