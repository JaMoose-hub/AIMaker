import { useEffect, useState } from "react";
import { acceptTrackingFrame, trackingCursor, trackingDisplayFrame, type TrackingFrame } from "./realtimeFrame";
import { openMotionDisplay } from "./motionDisplayStore";

/** One in-flight request/decode, then atomically expose that JPEG and poses. */
export function useRealtimeTracking(enabled: boolean, boardId: string | null, revision: number, targetHz = 30, sourceKey = "standard") {
  const [frame, setFrame] = useState<(TrackingFrame & { sourceKey: string }) | null>(null);
  const [fps, setFps] = useState(0);
  useEffect(() => {
    setFrame(null);
    setFps(0);
    if (!enabled) return;
    const display = openMotionDisplay();
    let disposed = false;
    let after = -1;
    let count = 0;
    let windowStart = performance.now();
    let lastFrameAt = Date.now();
    let timer = 0;
    let abort: AbortController | null = null;
    const freshTimer = window.setInterval(() => {
      setFrame((current) => current && Date.now() - current.receivedAt > 600 ? null : current);
      if (Date.now() - lastFrameAt > 600) { after = trackingCursor(after, lastFrameAt, Date.now()); setFps(0); display.update(null); }
    }, 200);
    async function poll() {
      const started = performance.now();
      abort = new AbortController();
      const timeout = window.setTimeout(() => abort?.abort(), 1000);
      let retryMs = 0;
      try {
        const response = await fetch(`/api/tracking/frame?after=${after}`, {
          signal: abort.signal, cache: "no-store",
        });
        if (response.status === 204) return;
        if (!response.ok) throw new Error(`tracking ${response.status}`);
        const next = await response.json() as TrackingFrame;
        if (!acceptTrackingFrame(next, boardId, revision, after)) return;
        // Decoding before setting state prevents a previous JPEG from being
        // displayed underneath the next pose during a network/decode delay.
        const image = new Image();
        image.src = next.image;
        await image.decode();
        if (disposed || abort.signal.aborted) return;
        after = next.seq;
        lastFrameAt = Date.now();
        const decodedFrame = { ...next, receivedAt: Date.now(), sourceKey };
        setFrame(decodedFrame);
        display.update(decodedFrame);
        count++;
        if (performance.now() - windowStart >= 1000) {
          setFps(Math.round(count * 1000 / (performance.now() - windowStart)));
          count = 0;
          windowStart = performance.now();
        }
      } catch {
        if (!disposed) { setFrame(null); setFps(0); display.update(null); }
        retryMs = 500;
        // A restarted backend resets its frame sequence.
        after = -1;
      } finally {
        window.clearTimeout(timeout);
        if (!disposed) timer = window.setTimeout(poll, Math.max(retryMs, 1000 / targetHz - (performance.now() - started)));
      }
    }
    void poll();
    return () => {
      disposed = true;
      display.close();
      abort?.abort();
      window.clearTimeout(timer);
      window.clearInterval(freshTimer);
    };
  }, [enabled, boardId, revision, targetHz, sourceKey]);
  const currentFrame = trackingDisplayFrame(frame, enabled, sourceKey, boardId, revision);
  return {
    frame: currentFrame,
    fps: currentFrame ? fps : 0,
  };
}
