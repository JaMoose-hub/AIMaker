export interface GlassesSettings {
  width: number;
  height: number;
  fps: number;
  denoise: "original" | "clean" | "strong";
}

export interface GlassesStatus {
  active: boolean;
  state: string;
  error: string | null;
  requested: GlassesSettings;
  actual: { width: number | null; height: number | null };
  capture_fps: number;
  processing_fps: number;
  denoise_backend?: "cuda" | "cpu" | "none" | "pending" | null;
  denoise_fallback_reason?: string | null;
  inference?: {
    processing_fps: number;
    processing_ms: number;
    models: Array<{
      id: string;
      actual_backend: string;
      preprocessing_backend: string;
      available: boolean;
      fallback_reason: string | null;
    }>;
  } | null;
  runtime_revision: number;
  modes: {
    resolutions: Array<{ width: number; height: number }>;
    fps: number[];
    denoise: GlassesSettings["denoise"][];
  };
}

export const DEFAULT_GLASSES_SETTINGS: GlassesSettings = {
  width: 1920, height: 1080, fps: 30, denoise: "clean",
};

export function glassesInferenceSummary(inference: GlassesStatus["inference"]) {
  if (!inference) return null;
  const total = inference.models.length;
  const ready = inference.models.filter(model => model.available);
  const cuda = ready.filter(model => model.actual_backend === "cuda").length;
  const cpu = ready.filter(model => ["cpu", "opencv"].includes(model.actual_backend)).length;
  const kind = !total || ready.length < total ? "notReady" : cuda === total ? "cuda"
    : cpu === total ? "cpu" : cuda || cpu ? "mixed" : "other";
  return { total, ready: ready.length, cuda, kind };
}

/** Remember only working Eye settings for this page session, independently of the webcam. */
export function createGlassesSessionSettings() {
  let confirmed: GlassesSettings | null = null;
  return {
    observe(status: GlassesStatus) {
      if (status.active && status.state === "running" && !status.error) confirmed = { ...status.requested };
    },
    forStart(): GlassesSettings {
      return { ...(confirmed ?? DEFAULT_GLASSES_SETTINGS) };
    },
  };
}

export function sameGlassesCamera(left: GlassesSettings, right: GlassesSettings) {
  return left.width === right.width && left.height === right.height && left.fps === right.fps;
}

/** Noise changes apply now without submitting unapplied camera-format edits. */
export function denoiseUpdate(draft: GlassesSettings, applied: GlassesSettings | undefined, denoise: GlassesSettings["denoise"]) {
  return { draft: { ...draft, denoise }, request: { ...(applied ?? DEFAULT_GLASSES_SETTINGS), denoise } };
}

export function glassesRestoreError(stopping: boolean, pending: boolean, status: GlassesStatus | null, requestError: string | null) {
  return stopping && !pending ? requestError || (status?.state === "error" ? status.error : null) : null;
}

export async function requestGlassesStream(method: "GET" | "PUT" | "DELETE", settings?: GlassesSettings): Promise<GlassesStatus> {
  const response = await fetch("/api/glasses/stream", {
    method, cache: "no-store", headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...(settings ? { body: JSON.stringify(settings) } : {}),
  });
  if (!response.ok) throw new Error(`Eye ${method}: HTTP ${response.status}`);
  return await response.json() as GlassesStatus;
}

/** Preserve enter/apply/exit order even if a user presses Esc during a slow PUT. */
export function createGlassesMutationQueue() {
  let tail: Promise<unknown> = Promise.resolve();
  return (method: "PUT" | "DELETE", settings?: GlassesSettings) => {
    const operation = tail.catch(() => undefined).then(() => requestGlassesStream(method, settings));
    tail = operation;
    return operation;
  };
}

export function glassesVideoReady(status: GlassesStatus | null) {
  return status?.active === true && status.state === "running";
}
