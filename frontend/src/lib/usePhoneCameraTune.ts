import { useEffect, useRef, useState } from "react";
import type { BrowserRtcStats } from "./mobileBrowserRtc";
import { restorePhoneTune, samplePhoneFrames, tunePhoneCamera, type PhoneTuneIO, type PhoneTuneResult, type PhoneTuneUndo } from "./phoneCameraTuning";

export function usePhoneCameraTune(input: {
  stream: MediaStream | null; scope: string; busy: boolean; blocked?: () => boolean; stats: BrowserRtcStats;
  readBitrate: (stream: MediaStream) => number | null;
  adjustBitrate: (stream: MediaStream, value: number, signal?: AbortSignal) => Promise<number>;
}) {
  const latest = useRef(input); latest.current = input;
  const [phase, setPhase] = useState<"idle" | "checking" | "cancelling" | "restoring">("idle");
  const [result, setResult] = useState<{ stream: MediaStream; scope: string; value: PhoneTuneResult } | null>(null);
  const [error, setError] = useState("");
  const [undo, setUndo] = useState<PhoneTuneUndo | null>(null);
  const savedUndo = useRef(undo), flight = useRef(false), controller = useRef<AbortController | null>(null), mounted = useRef(true);
  function saveUndo(value: PhoneTuneUndo | null) { savedUndo.current = value; if (mounted.current) setUndo(value); }
  function io(stream: MediaStream, scope: string, video?: HTMLVideoElement): PhoneTuneIO {
    return { stream, current: () => latest.current.stream === stream && latest.current.scope === scope && stream.getVideoTracks()[0]?.readyState === "live",
      sourceCurrent: () => latest.current.stream === stream && stream.getVideoTracks()[0]?.readyState === "live",
      sample: (signal, observe) => samplePhoneFrames(video!, stream, signal, observe),
      stats: () => latest.current.stats, readBitrate: () => latest.current.readBitrate(stream),
      adjustBitrate: (value, signal) => latest.current.adjustBitrate(stream, value, signal), saveUndo };
  }
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; controller.current?.abort(); };
  }, []);
  useEffect(() => {
    controller.current?.abort(); setError("");
    if (savedUndo.current?.stream !== input.stream) saveUndo(null);
  }, [input.stream, input.scope]);
  useEffect(() => { if (input.busy) controller.current?.abort(); }, [input.busy]);
  useEffect(() => {
    const cancelHidden = () => { if (document.visibilityState === "hidden") controller.current?.abort(); };
    document.addEventListener("visibilitychange", cancelHidden);
    return () => document.removeEventListener("visibilitychange", cancelHidden);
  }, []);
  async function start(video: HTMLVideoElement | null) {
    const snapshot = latest.current;
    if (flight.current || snapshot.busy || snapshot.blocked?.() || !snapshot.stream || !video || document.visibilityState === "hidden") return;
    const operation = io(snapshot.stream, snapshot.scope, video), abort = new AbortController();
    flight.current = true; controller.current = abort; setPhase("checking"); setError(""); setResult(null);
    try {
      const value = await tunePhoneCamera(operation, abort.signal);
      if (mounted.current && operation.current()) setResult({ stream: snapshot.stream, scope: snapshot.scope, value });
    } catch (cause) {
      if (mounted.current && operation.current()) setError(cause instanceof Error && cause.name === "AbortError" ? "cancelled" : cause instanceof Error ? cause.message : "phone_tune_failed");
    } finally {
      flight.current = false; if (controller.current === abort) controller.current = null;
      if (mounted.current) setPhase("idle");
    }
  }
  function cancel() { if (controller.current) { setPhase("cancelling"); controller.current.abort(); } }
  async function restore() {
    const snapshot = latest.current, previous = savedUndo.current;
    if (flight.current || snapshot.busy || snapshot.blocked?.() || !previous || previous.stream !== snapshot.stream) return;
    flight.current = true; setPhase("restoring"); setError("");
    const operation = io(previous.stream, snapshot.scope);
    try { await restorePhoneTune(operation, previous); if (mounted.current && operation.current()) { setResult(null); setError("restored"); } }
    catch (cause) { if (mounted.current && operation.current()) setError(cause instanceof Error ? cause.message : "phone_tune_restore_failed"); }
    finally { flight.current = false; if (mounted.current) setPhase("idle"); }
  }
  return { phase, busy: phase !== "idle", result: result?.stream === input.stream && result.scope === input.scope ? result.value : null,
    error, canRestore: undo?.stream === input.stream && Boolean(undo), isRunning: () => flight.current, start, cancel, restore };
}
