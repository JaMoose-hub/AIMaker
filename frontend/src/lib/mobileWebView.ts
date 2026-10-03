import { acceptPhotoCapture, acceptPhotoImageSize, locatedPhotoPin, photoOverlayObjects, reliablePhotoPose, type PhotoCapture } from "./photoWiring";

export function mobilePairingCode(search: string): string {
  const code = new URLSearchParams(search).get("code") ?? "";
  return /^\d{6}$/.test(code) ? code : "";
}

export function mobileCaptureSeconds(expiresAt: number | undefined, now: number): number {
  return expiresAt && Number.isFinite(expiresAt) && Number.isFinite(now) ? Math.max(0, Math.ceil((expiresAt * 1000 - now) / 1000)) : 0;
}

export function mobilePhotoLayout(size: readonly number[], width: number, height: number, zoom = 1) {
  if (size.length !== 2 || ![...size, width, height, zoom].every(value => Number.isFinite(value) && value > 0)) return null;
  const scale = Math.min(width / size[0], height / size[1]) * Math.min(6, Math.max(1, zoom));
  return { width: size[0] * scale, height: size[1] * scale, scale };
}

/** Original dimensions are metadata; geometry continues to use the analysis image size. */
export function mobilePhotoSource(capture: PhotoCapture & { original_size?: readonly number[]; analysis_limited?: boolean }) {
  const size = capture.original_size ?? [capture.quality.original_width, capture.quality.original_height];
  const originalSize = size.length === 2 && size.every(value => typeof value === "number" && Number.isFinite(value) && value > 0) ? size as readonly number[] : null;
  return { originalSize, analysisLimited: capture.analysis_limited ?? capture.quality.analysis_limited === true };
}

/** Blob pixels and all drawn geometry must still identify the same frozen source. */
export function mobilePhotoMatches(capture: PhotoCapture, natural: readonly number[] | null): boolean {
  if (!natural || natural.length !== 2 || !Array.isArray(capture.components) || !Array.isArray(capture.wires)) return false;
  return acceptPhotoImageSize(capture, natural[0], natural[1]) && acceptPhotoCapture({ ...capture,
    image_url: `/api/photo-wiring/captures/${encodeURIComponent(capture.capture_id)}/image` }, capture.session_id,
  { catalog_version: "mobile", profile_versions: {}, component_ids: capture.components.map(item => item.component_id), wires: capture.wires });
}

export function mobilePhotoGeometry(capture: PhotoCapture, wireId: string | null, natural: readonly number[] | null) {
  if (!mobilePhotoMatches(capture, natural)) return null;
  const wire = capture.wires.find(item => item.wire_id === wireId) ?? capture.wires[0];
  return { wire, objects: photoOverlayObjects(capture, "corrected"),
    boardPin: wire ? locatedPhotoPin(reliablePhotoPose(capture, "raspberry-pi-5"), wire.board_pin) : null,
    componentPin: wire ? locatedPhotoPin(reliablePhotoPose(capture, wire.component_id), wire.component_pin) : null };
}

export function mobileReadiness(stream: { active?: boolean; state?: string; reason?: string } | undefined, canCapture: boolean, previewFresh = true) {
  if (!stream?.active) return "idle";
  if (!previewFresh) return "finding";
  if (stream.state === "locked") return canCapture ? "locked" : "finding";
  return stream.state === "hold_still" ? "hold_still" : "finding";
}

export function mobileObjectName(id: string) {
  return id === "raspberry-pi-5" ? "Raspberry Pi 5" : id === "hc-sr04" ? "HC-SR04+" : id === "mrd-tf240-8p-cs" ? "MRD-TFT240" : id;
}

export function mobilePhotoReasons(capture: PhotoCapture) {
  return ["raspberry-pi-5", ...capture.components.map(item => item.component_id)].flatMap(id => {
    const item = capture.localization?.find(value => value.object_id === id);
    return item?.status === "located" ? [] : [{ id, reason: item?.reason ?? "localization_not_validated" }];
  });
}
