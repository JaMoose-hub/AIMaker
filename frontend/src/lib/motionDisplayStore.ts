import type { TrackingFrame } from "./realtimeFrame";

// Display-only feed for wiring cards. Never modifies the authoritative WS
// snapshot or manual records. undefined = original mode; null = waiting/lost.
let value: TrackingFrame | null | undefined;
let owner: symbol | undefined;
const listeners = new Set<() => void>();
export const getMotionDisplay = () => value;
export function subscribeMotionDisplay(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function publish(next: typeof value) {
  if (value === next) return;
  value = next;
  listeners.forEach((listener) => listener());
}
export function openMotionDisplay() {
  const token = Symbol();
  owner = token;
  publish(null);
  return {
    update: (next: TrackingFrame | null) => { if (owner === token) publish(next); },
    close: () => { if (owner === token) { owner = undefined; publish(undefined); } },
  };
}
