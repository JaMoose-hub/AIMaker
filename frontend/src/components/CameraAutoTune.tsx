import { useEffect, useRef, useState } from "react";
import { requestCameraTuning, tuningMessage, type CameraTuningStatus } from "../lib/cameraTuning";
import { advanceAlignment, emptyAlignmentRun, inspectAlignment, postTuneAlignmentIssue, type AlignmentIssue } from "../lib/autoCalibration";
import { useI18n } from "../lib/i18n";
import type { DistanceAdvice } from "../lib/boardDistance";
import type { DetectionMessage } from "../lib/types";

export interface AutoAlignmentInput {
  detection: DetectionMessage | null;
  distance: DistanceAdvice;
  receivedAtMs: number;
  now: number;
  synchronized: boolean;
  context: string;
}

type AlignmentPhase = "idle" | "starting" | "tuning" | "checking" | "aligned" | "needsAction" | "stale" | "error";

export function CameraAutoTune({ disabled, onBusyChange, alignment }: {
  disabled: boolean; onBusyChange: (busy: boolean) => void; alignment?: AutoAlignmentInput;
}) {
  const { t } = useI18n();
  const [status, setStatus] = useState<CameraTuningStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [phase, setPhase] = useState<AlignmentPhase>("idle");
  const [checkStartedAt, setCheckStartedAt] = useState(0);
  const [checkIssue, setCheckIssue] = useState<AlignmentIssue>("waitingFrame");
  const alignmentRun = useRef(emptyAlignmentRun());
  const attemptContext = useRef("");
  const inFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const busy = pending || Boolean(status?.busy) || phase === "starting" || phase === "tuning" || phase === "checking";
  const evidence = alignment ? inspectAlignment(alignment) : null;
  const postTuneIssue = alignment ? postTuneAlignmentIssue(alignment) : null;
  const targetUnavailable = Boolean(alignment && status?.available && !status.target_supported);
  const contextChanged = Boolean(alignment && attemptContext.current && alignment.context !== attemptContext.current);
  const shownPhase = phase === "aligned" && (evidence?.kind !== "supported" || contextChanged || status?.busy) ? "stale" : phase;
  useEffect(() => {
    onBusyChange(busy);
  }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange(false), [onBusyChange]);

  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    let timer = 0;
    async function poll() {
      const version = epoch.current;
      try {
        const next = await requestCameraTuning("GET");
        if (!disposed && version === epoch.current && !inFlight.current) {
          setStatus(next);
          setError(current => current === "network" ? null : current);
        }
      } catch {
        if (!disposed && version === epoch.current && !inFlight.current) setError("network");
      } finally {
        if (!disposed) timer = window.setTimeout(poll, 1000);
      }
    }
    if (!disabled) void poll();
    return () => { disposed = true; mounted.current = false; window.clearTimeout(timer); };
  }, [disabled]);

  useEffect(() => {
    if (!alignment || phase !== "tuning" || !status || status.busy) return;
    if (status.state === "improved" || status.state === "unchanged") {
      alignmentRun.current = emptyAlignmentRun();
      if (postTuneIssue) {
        setCheckIssue(postTuneIssue);
        setPhase("needsAction");
      } else {
        setCheckStartedAt(Date.now());
        setPhase("checking");
      }
    } else if (status.state === "error" || status.state === "cancelled") {
      setPhase("error");
    }
  }, [alignment, phase, postTuneIssue, status]);

  useEffect(() => {
    if (!alignment || (phase !== "checking" && phase !== "aligned" && phase !== "needsAction")) return;
    if (contextChanged || (phase === "aligned" && status?.busy)) { setPhase("stale"); return; }
    if (phase === "aligned") {
      if (evidence?.kind !== "supported") setPhase("stale");
      return;
    }
    if (postTuneIssue) {
      alignmentRun.current = emptyAlignmentRun();
      if (checkIssue !== postTuneIssue) setCheckIssue(postTuneIssue);
      if (phase !== "needsAction") setPhase("needsAction");
      return;
    }
    if (evidence?.kind === "supported" && alignment.receivedAtMs > checkStartedAt) {
      const next = advanceAlignment(alignmentRun.current, evidence);
      alignmentRun.current = next.run;
      if (next.ready) { setPhase("aligned"); return; }
      if (phase === "needsAction") {
        setCheckStartedAt(Date.now());
        setPhase("checking");
      }
    } else if (evidence) {
      alignmentRun.current = emptyAlignmentRun();
      setCheckIssue(evidence.kind === "issue" ? evidence.issue : "poseUnverified");
    }
    if (phase === "checking" && checkStartedAt > 0 && alignment.now - checkStartedAt >= 12000) {
      setCheckIssue(evidence?.kind === "issue" ? evidence.issue : "poseUnverified");
      setPhase("needsAction");
    }
  }, [alignment, checkIssue, checkStartedAt, contextChanged, evidence, phase, postTuneIssue, status?.busy]);

  async function change(action: "start" | "cancel" | "restore") {
    if (inFlight.current) return;
    if (action === "cancel" && phase === "checking") {
      alignmentRun.current = emptyAlignmentRun();
      setPhase("idle");
      return;
    }
    if (alignment && action === "start") {
      if (!status?.target_supported) {
        setError("restart_required");
        setPhase("error");
        return;
      }
    }
    inFlight.current = true;
    epoch.current += 1;
    setPending(true);
    setError(null);
    if (alignment && action === "start") {
      attemptContext.current = alignment.context;
      alignmentRun.current = emptyAlignmentRun();
      setPhase("starting");
    } else if (alignment && action === "restore") {
      setPhase("stale");
    } else if (alignment && action === "cancel") {
      setPhase("idle");
    }
    try {
      const accepted = await requestCameraTuning(action === "cancel" ? "DELETE" : "POST", action === "restore",
        alignment && action === "start" ? "raspberry-pi-5" : undefined);
      if (mounted.current) {
        setStatus(accepted);
        if (alignment && action === "start") setPhase("tuning");
      }
      // A transient status-read failure must not invalidate an accepted tune.
      // The regular poll can recover the authoritative progress/result.
      try {
        const next = await requestCameraTuning("GET");
        if (mounted.current) setStatus(next);
      } catch (reason) {
        if (mounted.current) setError(reason instanceof Error ? reason.message : "network");
      }
    } catch (reason) {
      if (mounted.current) {
        setError(reason instanceof Error ? reason.message : "network");
        if (alignment && action === "start") setPhase("error");
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }

  const message = targetUnavailable ? "restart_required" : tuningMessage(status, error);
  return <div className="camera-auto-tune" aria-busy={busy}>
    <button type="button" className="camera-auto-trigger" onClick={() => void change("start")}
      disabled={disabled || busy || !status?.available || targetUnavailable}
      title={t(targetUnavailable ? "cameraTune.restart_required" : alignment ? "autoCalibration.tooltip" : "cameraTune.tooltip")}>
      <span aria-hidden="true">{busy ? "◌" : "✦"}</span>
      {t(alignment && !busy ? "autoCalibration.button" : busy ? "cameraTune.running" : "cameraTune.button")}
      {status?.busy ? ` ${Math.min(100, Math.max(0, status.progress))}%` : ""}
    </button>
    {status?.busy || phase === "checking" ? <button type="button" className="camera-trigger" disabled={disabled || pending}
      onClick={() => void change("cancel")}>{t("cameraTune.cancel")}</button> : null}
    {!busy && status?.can_restore ? <button type="button" className="camera-trigger" disabled={disabled}
      onClick={() => void change("restore")}>{t("cameraTune.restore")}</button> : null}
    <span className={`camera-auto-message ${message === "improved" ? "success" : ""}`} role="status" aria-live="polite">
      {t(`cameraTune.${message}`)}
    </span>
    {alignment && !targetUnavailable && <span className={`auto-alignment-message ${shownPhase === "aligned" ? "success" : ""}`}
      role="status" aria-live="polite">
      {t(`autoCalibration.${shownPhase === "needsAction" ? checkIssue : shownPhase}`)}
    </span>}
  </div>;
}
