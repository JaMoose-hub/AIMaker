import { useEffect, useRef, useState } from "react";
import { requestCameraTuning, tuningMessage, type CameraTuningStatus } from "../lib/cameraTuning";
import { useI18n } from "../lib/i18n";

export function CameraAutoTune({ disabled, onBusyChange }: {
  disabled: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const { t } = useI18n();
  const [status, setStatus] = useState<CameraTuningStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const busy = pending || Boolean(status?.busy);
  useEffect(() => {
    onBusyChange(busy);
    return () => onBusyChange(false);
  }, [busy, onBusyChange]);

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

  async function change(action: "start" | "cancel" | "restore") {
    if (inFlight.current) return;
    inFlight.current = true;
    epoch.current += 1;
    setPending(true);
    setError(null);
    try {
      await requestCameraTuning(action === "cancel" ? "DELETE" : "POST", action === "restore");
      const next = await requestCameraTuning("GET");
      if (mounted.current) setStatus(next);
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "network");
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }

  const message = tuningMessage(status, error);
  return <div className="camera-auto-tune" aria-busy={busy}>
    <button type="button" className="camera-auto-trigger" onClick={() => void change("start")}
      disabled={disabled || busy || !status?.available} title={t("cameraTune.tooltip")}>
      <span aria-hidden="true">{busy ? "◌" : "✦"}</span>
      {t(busy ? "cameraTune.running" : "cameraTune.button")}
      {status?.busy ? ` ${Math.min(100, Math.max(0, status.progress))}%` : ""}
    </button>
    {status?.busy ? <button type="button" className="camera-trigger" disabled={disabled || pending}
      onClick={() => void change("cancel")}>{t("cameraTune.cancel")}</button> : null}
    {!busy && status?.can_restore ? <button type="button" className="camera-trigger" disabled={disabled}
      onClick={() => void change("restore")}>{t("cameraTune.restore")}</button> : null}
    <span className={`camera-auto-message ${message === "improved" ? "success" : ""}`} role="status" aria-live="polite">
      {t(`cameraTune.${message}`)}
    </span>
  </div>;
}
