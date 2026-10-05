import type { BrowserRtcStats } from "./mobileBrowserRtc";

export type PhoneQualityIssue = "dark" | "glare" | "detail" | "motion";
export interface PhoneFrameQuality {
  level: number; highlights: number; shadows: number; detail: number; motion: number;
  issues: PhoneQualityIssue[];
}
export const PHONE_AUTO_MODES = ["focusMode", "exposureMode", "whiteBalanceMode"] as const;
type AutoMode = typeof PHONE_AUTO_MODES[number];
type CameraModes = Partial<Record<AutoMode, string>>;
export interface PhoneTuneUndo { stream: MediaStream; modes: CameraModes; bitrate: number | null }
export interface PhoneTuneResult {
  quality: PhoneFrameQuality; camera: "unsupported" | "unchanged" | "improved";
  bitrate: number | null; bitrateChanged: boolean; resolution: "720p" | null;
}
export interface PhoneTuneIO {
  stream: MediaStream; current: () => boolean;
  sourceCurrent?: () => boolean;
  sample: (signal: AbortSignal, observe: () => void) => Promise<PhoneFrameQuality>;
  stats: () => BrowserRtcStats; readBitrate: () => number | null;
  adjustBitrate: (value: number, signal?: AbortSignal) => Promise<number>;
  saveUndo: (undo: PhoneTuneUndo | null) => void;
}
const aborted = () => new DOMException("Cancelled", "AbortError");
function check(io: Pick<PhoneTuneIO, "current">, signal?: AbortSignal) {
  if (signal?.aborted) throw aborted();
  if (!io.current()) throw Error("phone_tune_source_changed");
}
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = (error?: unknown) => { clearTimeout(timer); signal.removeEventListener("abort", cancel); error ? reject(error) : resolve(); };
    const cancel = () => finish(aborted());
    const timer = setTimeout(() => finish(), ms);
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) cancel();
  });
}

/** Downsample only a diagnostic copy. Never alter the published frame or colors. */
export function phoneFrameQuality(data: Uint8ClampedArray, width: number, height: number, previous?: Uint8Array) {
  if (width < 3 || height < 3 || data.length !== width * height * 4) throw Error("phone_tune_frame_unavailable");
  const gray = new Uint8Array(width * height), histogram = new Uint32Array(256);
  let bright = 0, dark = 0, difference = 0, edges = 0, count = 0;
  for (let i = 0; i < gray.length; i++) {
    const p = i * 4, value = Math.round(data[p] * .299 + data[p + 1] * .587 + data[p + 2] * .114);
    gray[i] = value; histogram[value]++;
    if (value >= 248) bright++; if (value <= 20) dark++;
    if (previous?.length === gray.length) difference += Math.abs(value - previous[i]);
  }
  for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) {
    const p = y * width + x;
    const edge = gray[p - 1] + gray[p + 1] + gray[p - width] + gray[p + width] - gray[p] * 4;
    edges += edge * edge; count++;
  }
  let level = 0, total = 0;
  for (; level < 255; level++) { total += histogram[level]; if (total >= gray.length * .75) break; }
  const highlights = bright / gray.length, shadows = dark / gray.length, detail = edges / count;
  const motion = previous?.length === gray.length ? difference / gray.length : 0;
  const issues: PhoneQualityIssue[] = [];
  if (level < 45 && shadows > .45) issues.push("dark");
  if (highlights > .14) issues.push("glare");
  // Texture-poor scenes can also score low. This is a hint, never a focus verdict.
  if (detail < 35) issues.push("detail");
  if (motion > 16) issues.push("motion");
  return { gray, quality: { level, highlights, shadows, detail, motion, issues } };
}

async function freshFrame(video: HTMLVideoElement, signal: AbortSignal, current: () => boolean) {
  return new Promise<void>((resolve, reject) => {
    let frame: number | null = null, poll: ReturnType<typeof setTimeout> | null = null, done = false;
    const finish = (error?: unknown) => {
      if (done) return; done = true; clearTimeout(deadline); if (poll) clearTimeout(poll);
      if (frame !== null) video.cancelVideoFrameCallback?.(frame);
      signal.removeEventListener("abort", cancel); error ? reject(error) : resolve();
    };
    const cancel = () => finish(aborted());
    const deadline = setTimeout(() => finish(Error("phone_tune_frame_unavailable")), 1800);
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) { cancel(); return; }
    const ready = () => current() && !video.paused && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
    if (!ready()) { finish(Error("phone_tune_frame_unavailable")); return; }
    if (typeof video.requestVideoFrameCallback === "function") {
      frame = video.requestVideoFrameCallback(() => finish(ready() ? undefined : Error("phone_tune_source_changed")));
    } else {
      const before = video.currentTime;
      const inspect = () => {
        if (!ready()) { finish(Error("phone_tune_source_changed")); return; }
        if (video.currentTime !== before) finish(); else poll = setTimeout(inspect, 80);
      };
      inspect();
    }
  });
}

export async function samplePhoneFrames(video: HTMLVideoElement, stream: MediaStream, signal: AbortSignal, observe: () => void) {
  const track = stream.getVideoTracks()[0], sourceSize = [video.videoWidth, video.videoHeight];
  const current = () => video.srcObject === stream && track?.readyState === "live" && document.visibilityState !== "hidden"
    && video.videoWidth === sourceSize[0] && video.videoHeight === sourceSize[1];
  const scale = Math.min(1, 320 / Math.max(...sourceSize));
  if (!current() || !Number.isFinite(scale) || Math.min(...sourceSize) < 3) throw Error("phone_tune_frame_unavailable");
  const canvas = video.ownerDocument.createElement("canvas");
  canvas.width = Math.max(3, Math.round(sourceSize[0] * scale)); canvas.height = Math.max(3, Math.round(sourceSize[1] * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw Error("phone_tune_frame_unavailable");
  const qualities: PhoneFrameQuality[] = []; let previous: Uint8Array | undefined;
  try {
    for (let i = 0; i < 4; i++) {
      if (i) await wait(600, signal);
      await freshFrame(video, signal, current);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const measured = phoneFrameQuality(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height, previous);
      previous = measured.gray; qualities.push(measured.quality); observe();
    }
    const median = (key: Exclude<keyof PhoneFrameQuality, "issues">) => [...qualities.map(q => q[key])].sort((a, b) => a - b)[2];
    return { level: median("level"), highlights: median("highlights"), shadows: median("shadows"), detail: median("detail"), motion: median("motion"),
      issues: [...new Set(qualities.filter(q => q.issues.includes("motion")).length >= 2 ? ["motion" as const] : []) ,
        ...["dark", "glare", "detail"].filter(issue => qualities.filter(q => q.issues.includes(issue as PhoneQualityIssue)).length >= 3) as PhoneQualityIssue[]] };
  } finally { canvas.width = canvas.height = 0; }
}

/** Require two recent, distinct counter-based reports before reducing bitrate. */
export function phoneTransportPlan(reports: BrowserRtcStats[], before: number | null, now = Date.now()) {
  const fresh = [...new Map(reports.filter(r => typeof r.measuredAtMs === "number" && now - r.measuredAtMs >= 0 && now - r.measuredAtMs <= 4000
    && typeof r.sampleIntervalMs === "number" && r.sampleIntervalMs >= 500 && r.sampleIntervalMs <= 2500)
    .map(r => [r.measuredAtMs, r])).values()];
  const slow = fresh.filter(r => typeof r.sendFps === "number" && r.sendFps < 20);
  const bandwidth = slow.filter(r => r.qualityLimitationReason === "bandwidth");
  const cpu = slow.filter(r => r.qualityLimitationReason === "cpu");
  const bitrate = bandwidth.length >= 2 && before !== null ? Math.min(before, bandwidth.every(r => r.sendFps! < 12) ? 3000 : 8000) : before;
  const resolution = cpu.length >= 2 && cpu.every(r => Math.max(r.width ?? 0, r.height ?? 0) > 1280) ? "720p" as const : null;
  return { bitrate, resolution };
}

function settings(track: MediaStreamTrack): CameraModes { return track.getSettings() as MediaTrackSettings & CameraModes; }
export function phoneAutomaticModes(track: MediaStreamTrack): CameraModes {
  try {
    const caps = track.getCapabilities() as MediaTrackCapabilities & Record<AutoMode, string[]>;
    const values = settings(track), modes: CameraModes = {};
    for (const key of PHONE_AUTO_MODES) if (Array.isArray(caps[key]) && caps[key].includes("continuous")
      && typeof values[key] === "string" && caps[key].includes(values[key]!)) modes[key] = values[key];
    return modes;
  } catch { return {}; }
}
function modeConstraints(track: MediaStreamTrack, modes: CameraModes): MediaTrackConstraints {
  // applyConstraints replaces the constraint set. Retain resolution, facing
  // mode and FPS so changing autofocus cannot silently select a new source size.
  const previous = track.getConstraints(), kept = { ...previous } as MediaTrackConstraints & CameraModes;
  for (const key of Object.keys(modes) as AutoMode[]) delete kept[key];
  const advanced = (previous.advanced ?? []).map(value => {
    const copy = { ...value } as MediaTrackConstraintSet & CameraModes;
    for (const key of Object.keys(modes) as AutoMode[]) delete copy[key];
    return copy;
  }).filter(value => Object.keys(value).length);
  return { ...kept, advanced: [...advanced, modes as MediaTrackConstraintSet] };
}
export async function restorePhoneTune(io: PhoneTuneIO, undo: PhoneTuneUndo) {
  if (undo.stream !== io.stream || !io.current()) throw Error("phone_tune_source_changed");
  let failed = false;
  try {
    if (Object.keys(undo.modes).length) {
      const track = io.stream.getVideoTracks()[0]; await track.applyConstraints(modeConstraints(track, undo.modes));
      if (!io.current() || Object.entries(undo.modes).some(([key, value]) => settings(track)[key as AutoMode] !== value)) failed = true;
    }
  } catch { failed = true; }
  try { if (undo.bitrate !== null && io.readBitrate() !== undo.bitrate) await io.adjustBitrate(undo.bitrate); }
  catch { failed = true; }
  if (failed) throw Error("phone_tune_restore_failed");
  io.saveUndo(null);
}

/** One bounded check. No photo upload, camera acquisition, model call or restart. */
export async function tunePhoneCamera(io: PhoneTuneIO, signal: AbortSignal): Promise<PhoneTuneResult> {
  check(io, signal);
  const reports: BrowserRtcStats[] = [], observe = () => { reports.push({ ...io.stats() }); };
  const before = await io.sample(signal, observe); check(io, signal);
  if (before.issues.includes("motion")) return { quality: before, camera: "unchanged", bitrate: io.readBitrate(), bitrateChanged: false, resolution: null };
  const track = io.stream.getVideoTracks()[0], available = phoneAutomaticModes(track);
  const original = Object.fromEntries(Object.entries(available).filter(([, value]) => value !== "continuous")) as CameraModes;
  const undo: PhoneTuneUndo = { stream: io.stream, modes: original, bitrate: io.readBitrate() };
  const plan = phoneTransportPlan(reports, undo.bitrate);
  let quality = before, camera: PhoneTuneResult["camera"] = Object.keys(available).length ? "unchanged" : "unsupported";
  const changing = Object.keys(original).length || plan.bitrate !== undo.bitrate;
  if (!changing) return { quality, camera, bitrate: undo.bitrate, bitrateChanged: false, resolution: plan.resolution };
  io.saveUndo(undo);
  try {
    if (Object.keys(original).length) {
      await track.applyConstraints(modeConstraints(track, Object.fromEntries(Object.keys(original).map(key => [key, "continuous"]))));
      check(io, signal);
      if (Object.keys(original).some(key => settings(track)[key as AutoMode] !== "continuous")) throw Error("phone_tune_unsupported");
      await wait(350, signal); quality = await io.sample(signal, observe); check(io, signal);
      const improved = !quality.issues.includes("motion") && quality.highlights <= before.highlights + .03 && quality.detail >= before.detail * .85
        && (quality.detail > before.detail * 1.15 + 5 || before.highlights - quality.highlights > .04 || before.issues.includes("dark") && quality.level > before.level + 12);
      if (improved) camera = "improved";
      else { await restorePhoneTune(io, { ...undo, bitrate: null }); check(io, signal); undo.modes = {}; quality = before; io.saveUndo(undo); }
    }
    if (plan.bitrate !== null && plan.bitrate !== undo.bitrate) { await io.adjustBitrate(plan.bitrate, signal); check(io, signal); }
    const bitrate = io.readBitrate(), bitrateChanged = bitrate !== undo.bitrate;
    if (!Object.keys(undo.modes).length && !bitrateChanged) io.saveUndo(null);
    return { quality, camera, bitrate, bitrateChanged, resolution: plan.resolution };
  } catch (cause) {
    if ((io.sourceCurrent ?? io.current)()) await restorePhoneTune({ ...io, current: io.sourceCurrent ?? io.current }, undo);
    else io.saveUndo(null);
    throw cause;
  }
}
