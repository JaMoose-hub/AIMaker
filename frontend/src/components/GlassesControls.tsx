import { useEffect, useState } from "react";
import { DEFAULT_GLASSES_SETTINGS, denoiseUpdate, glassesInferenceSummary, type GlassesSettings, type GlassesStatus } from "../lib/glasses";
import { useI18n } from "../lib/i18n";

interface Props {
  status: GlassesStatus | null;
  pending: boolean;
  error: string | null;
  displayFps: number | null;
  onApply: (settings: GlassesSettings) => void;
}

export function GlassesControls({ status, pending, error, displayFps, onApply }: Props) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<GlassesSettings>(() => ({ ...(status?.requested ?? DEFAULT_GLASSES_SETTINGS) }));
  const requested = status?.requested;
  useEffect(() => {
    if (requested) setDraft(current => ({ ...current, width: requested.width, height: requested.height, fps: requested.fps }));
  }, [requested?.width, requested?.height, requested?.fps]);
  useEffect(() => {
    if (requested) setDraft(current => ({ ...current, denoise: requested.denoise }));
  }, [requested?.denoise]);
  const resolutions = status?.modes.resolutions ?? [{ width: 1920, height: 1080 }];
  const busy = pending || (!error && ["starting", "switching", "restoring", "stopping"].includes(status?.state ?? "starting"));
  // A failed status request leaves the last good settings available for retry,
  // but its cached backend and rate samples no longer describe current activity.
  const diagnostics = error ? null : status;
  const inference = glassesInferenceSummary(diagnostics?.inference);
  const modelDetails = diagnostics?.inference?.models.map(model => `${model.id}: ${model.available ? model.actual_backend.toUpperCase() : t("glasses.inference.notReady")}`
    + ` · ${t("glasses.preprocessing")} ${model.preprocessing_backend || "—"}`
    + (model.fallback_reason ? ` · ${model.fallback_reason}` : "")).join("\n");
  return <section className="glasses-controls" aria-label={t("glasses.controls")}>
    <div className="glasses-controls-heading"><strong>R1 + Eye</strong><span>{t(`glasses.state.${error ? "error" : status?.state ?? "starting"}`)}</span></div>
    <div className="glasses-settings">
      <label>{t("glasses.resolution")}<select value={`${draft.width}x${draft.height}`} disabled={busy} onChange={event => {
        const [width, height] = event.target.value.split("x").map(Number); setDraft({ ...draft, width, height });
      }}>{resolutions.map(mode => <option key={`${mode.width}x${mode.height}`} value={`${mode.width}x${mode.height}`}>{mode.width} × {mode.height}</option>)}</select></label>
      <label>FPS<select value={draft.fps} disabled={busy} onChange={event => setDraft({ ...draft, fps: Number(event.target.value) })}>
        {(status?.modes.fps ?? [30, 60]).map(fps => <option key={fps} value={fps}>{fps}</option>)}
      </select></label>
      <label>{t("glasses.denoise")}<select value={draft.denoise} disabled={busy} onChange={event => {
        const update = denoiseUpdate(draft, requested, event.target.value as GlassesSettings["denoise"]);
        setDraft(update.draft);
        onApply(update.request);
      }}>
        {(status?.modes.denoise ?? ["original", "clean", "strong"]).map(mode => <option key={mode} value={mode}>{t(`glasses.denoise.${mode}`)}</option>)}
      </select></label>
      <button type="button" disabled={busy} onClick={() => onApply(draft)}>{t("glasses.apply")}</button>
    </div>
    <div className="glasses-metrics" role="status">
      <span>{t("glasses.actual")} {status?.actual.width && status.actual.height ? `${status.actual.width} × ${status.actual.height}` : "—"}</span>
      <span>{t("glasses.capture")} {error ? "—" : status?.state === "running" ? status.capture_fps.toFixed(1) : "0"} FPS</span>
      <span>{t("glasses.processing")} {error ? "—" : status?.state === "running" ? status.processing_fps.toFixed(1) : "0"} FPS</span>
      <span>{t("glasses.display")} {displayFps ?? "—"} FPS</span>
    </div>
    {(inference || diagnostics?.denoise_backend) && <div className="glasses-metrics" role="status">
      {inference && <>
        <span title={modelDetails}>YOLO {t(`glasses.inference.${inference.kind}`)} {inference.kind === "cuda" ? inference.cuda : inference.ready}/{inference.total}
          {inference.kind === "mixed" || inference.kind === "notReady" ? ` · CUDA ${inference.cuda}/${inference.total}` : ""}</span>
        <span>{t("glasses.inferenceRate")} {diagnostics?.state === "running" ? diagnostics.inference!.processing_fps.toFixed(1) : "0"} FPS
          {diagnostics?.state === "running" ? ` · ${diagnostics.inference!.processing_ms.toFixed(1)} ms` : ""}</span>
      </>}
      {diagnostics?.denoise_backend && <span title={diagnostics.denoise_fallback_reason ?? undefined}>{t("glasses.denoise")} {diagnostics.denoise_backend === "none" ? t("glasses.denoise.original")
        : diagnostics.denoise_backend === "pending" ? t("glasses.denoise.pending") : diagnostics.denoise_backend.toUpperCase()}</span>}
    </div>}
    {(error || status?.error) && <div className="glasses-error" role="alert">{error || status?.error}</div>}
  </section>;
}
