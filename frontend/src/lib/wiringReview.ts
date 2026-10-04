/** Photo observations are advisory; only an explicit human action confirms wiring. */
export type WiringPhotoRole = "pi_side_a" | "pi_side_b" | "component_header";
export type WiringCrop = [number, number, number, number];
export type WiringHumanDecision = "confirmed" | "unsure" | "needs_change";
export interface WiringReviewAction {
  op: "start" | "capture" | "accept_photo" | "crop" | "analyse" | "review" | "changed";
  review_id?: string;
  revision?: number;
  component_id?: string;
  role?: WiringPhotoRole;
  capture_id?: string;
  sha256?: string;
  crop?: WiringCrop | null;
  wire_id?: string;
  decision?: WiringHumanDecision;
  note?: string;
}
export interface WiringPhotoSlot {
  role: WiringPhotoRole;
  capture_id: string;
  image_url: string;
  size: [number, number];
  sha256: string;
  crop: WiringCrop | null;
  crop_source: "manual" | "none" | "auto";
  suggested_crop?: WiringCrop | null;
  available?: boolean;
  /** Selecting a photo does not confirm its pins or any physical connection. */
  photo_acceptance?: { capture_id: string; sha256: string; round: number; accepted_at: number | string; source: "human" } | null;
}
export interface WiringEndpoint {
  id: string;
  capture_id: string;
  role?: WiringPhotoRole;
  pin_id?: string | null;
  physical_pin: number | null;
  pin_label: string | null;
  color: string | null;
  evidence: string;
  color_visibility?: "clear" | "partial" | "not_visible";
  position?: string;
  contact?: "covers_pin" | "breadboard_link" | "detached" | "uncertain";
  box?: WiringCrop | null;
  pin_contact?: [number, number] | null;
  wire_exit?: [number, number] | null;
}
export interface WiringReviewResult {
  wire_id: string;
  component_id?: string;
  expected: { physical_pin: number | null; bcm: number | null; board_pin?: string; component_pin: string; connection_kind?: string };
  pi_candidates: WiringEndpoint[];
  component_candidates: WiringEndpoint[];
  comparison: "similar" | "different" | "ambiguous" | "unknown";
  same_wire?: "consistent" | "different" | "uncertain";
  evidence?: string;
  next_step: string;
  authority?: "visual_advisory";
}
export interface WiringReviewState {
  id: string;
  revision: number;
  round: number;
  component_id: string;
  status: "collecting" | "analysing" | "ready" | "needs_human" | "stale" | "error";
  slots: Record<WiringPhotoRole, WiringPhotoSlot | null>;
  observations: WiringEndpoint[];
  results: WiringReviewResult[];
  reviews: Record<string, { decision: WiringHumanDecision; source: "human"; at: number | string; review_revision: number | null; evidence_stale?: boolean; note?: string }>;
  missing_roles: WiringPhotoRole[];
  no_progress_count: number;
  analysis_revision?: number | null;
  photo_flow_version?: number;
  error?: string | null;
}
export const wiringPhotoRoles: WiringPhotoRole[] = ["pi_side_a", "pi_side_b", "component_header"];

export function validWiringCrop(value: unknown): value is WiringCrop {
  return Array.isArray(value) && value.length === 4 && value.every(n => typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1)
    && value[2] > value[0] && value[3] > value[1];
}

export function cropFromPoints(start: [number, number], end: [number, number]): WiringCrop | null {
  if (![...start, ...end].every(Number.isFinite)) return null;
  const clamp = (value: number) => Math.min(1, Math.max(0, value));
  const crop: WiringCrop = [clamp(Math.min(start[0], end[0])), clamp(Math.min(start[1], end[1])),
    clamp(Math.max(start[0], end[0])), clamp(Math.max(start[1], end[1]))];
  return validWiringCrop(crop) ? crop : null;
}

/** object-fit: contain can letterbox both portrait and landscape images. */
export function containedImageRect(box: { left: number; top: number; width: number; height: number }, size: [number, number]) {
  if (![box.left, box.top, box.width, box.height, ...size].every(Number.isFinite) || box.width <= 0 || box.height <= 0 || size.some(n => n <= 0)) return null;
  const scale = Math.min(box.width / size[0], box.height / size[1]);
  const width = size[0] * scale;
  const height = size[1] * scale;
  return { left: box.left + (box.width - width) / 2, top: box.top + (box.height - height) / 2, width, height };
}

export function imagePointFromClient(x: number, y: number, box: { left: number; top: number; width: number; height: number }, size: [number, number], clamp = false): [number, number] | null {
  const image = containedImageRect(box, size);
  if (!image || !Number.isFinite(x) || !Number.isFinite(y)) return null;
  const nx = (x - image.left) / image.width;
  const ny = (y - image.top) / image.height;
  if (!clamp && (nx < 0 || nx > 1 || ny < 0 || ny > 1)) return null;
  return [Math.max(0, Math.min(1, nx)), Math.max(0, Math.min(1, ny))];
}

/** Bind every change to the exact revision the user is looking at. */
export function boundWiringAction(review: WiringReviewState, action: Omit<WiringReviewAction, "review_id" | "revision">): WiringReviewAction {
  return { ...action, review_id: review.id, revision: review.revision };
}

export function canAnalyseWiring(review: WiringReviewState | null | undefined, busy = false, stale = false) {
  return Boolean(review && !busy && !stale && !["analysing", "stale"].includes(review.status)
    && review.no_progress_count < 2
    && !["ready", "needs_human"].includes(review.status)
    && wiringPhotoRoles.every(role => {
      const slot = review.slots[role], accepted = slot?.photo_acceptance;
      return slot?.available !== false && slot?.capture_id && ((review.photo_flow_version ?? 1) < 2 ||
        (accepted?.source === "human" && accepted.round === review.round && accepted.capture_id === slot.capture_id && accepted.sha256 === slot.sha256));
    }));
}
