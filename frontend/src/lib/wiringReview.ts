/** Photo observations are advisory; only an explicit human action confirms wiring. */
export type WiringPhotoRole = "pi_side_a" | "pi_side_b" | "component_header";
export type WiringCapturePlan = "pi_rows_v1" | null;
export type WiringTargetRow = "inner" | "outer";
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
  /** Requested view only; this does not certify which row is visible. */
  target_row?: WiringTargetRow | null;
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
/** Actual cloud inputs; crop coordinates are pixels in the original photograph. */
export interface WiringImageInput {
  role: WiringPhotoRole;
  requested_row?: WiringTargetRow | null;
  image_id?: string;
  view: "overview" | "detail";
  capture_id: string;
  source_size: [number, number];
  source_sha256: string;
  crop: [number, number, number, number] | null;
  size: [number, number];
  original_pixels?: boolean;
  resized?: boolean;
  encoding?: "jpeg" | "png";
  jpeg_quality?: number | null;
  supplied_bytes?: number;
  supplied_sha256?: string;
}
export interface WiringModelReceipt {
  capture_plan?: WiringCapturePlan;
  review_id?: string;
  wiring_round?: number;
  capture_ids?: string[];
  capture_hashes?: (string | null)[];
  image_inputs?: WiringImageInput[];
  reused_roles?: WiringPhotoRole[];
  model?: string;
  effort?: string;
  completed_at?: number | string;
  elapsed_ms?: number;
  stages?: { stage: string; cached?: boolean; image_inputs?: WiringImageInput[]; model_receipt?: WiringModelReceipt }[];
}
export interface WiringEndpoint {
  requested_row?: WiringTargetRow | null;
  id: string;
  capture_id: string;
  role?: WiringPhotoRole;
  pin_id?: string | null;
  /** Read module label/position; this does not confirm the plug's physical contact. */
  module_pin_id?: string | null;
  module_pin_evidence?: string | null;
  /** Source-bound photo position, distinct from proof of end-to-end continuity. */
  pin_seat?: {
    image_id: "pi_side_a" | "pi_side_b";
    row: WiringTargetRow;
    column: number | null;
    base_box: WiringCrop;
    orientation_anchor: string;
    count_evidence: string;
    capture_id: string | null;
    source_sha256: string | null;
    source_size: [number, number] | null;
  } | null;
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
  wire_exit_px?: [number, number];
  source_sha256?: string;
  source_size?: [number, number];
  semantic_color?: string;
  local_color?: { name: string; rgb: [number, number, number]; support: number; method: "local_hsv_vote"; warning: string };
  color_agreement?: "similar" | "different" | "unknown";
}
export interface WiringReviewResult {
  wire_id: string;
  component_id?: string;
  expected: { physical_pin: number | null; bcm: number | null; board_pin?: string; component_pin: string; connection_kind?: string };
  pi_candidates: WiringEndpoint[];
  component_candidates: WiringEndpoint[];
  comparison: "similar" | "different" | "ambiguous" | "unknown";
  same_wire?: "consistent" | "different" | "uncertain";
  wire_colors?: {
    component?: { name: string; visibility: "clear" | "partial" | "not_visible"; evidence?: string };
    board?: { name: string; visibility: "clear" | "partial" | "not_visible"; evidence?: string };
    comparison?: "similar" | "different" | "uncertain";
    evidence?: string;
  };
  evidence?: string;
  next_step: string;
  authority?: "visual_advisory";
  diagnosis?: {
    status: "suspected" | "uncertain" | "no_issue_seen";
    /** Reciprocal colour correspondence is advice, not verified wire continuity. */
    kind?: "reciprocal_endpoint_swap" | "unconnected_terminal" | "row_position_check";
    expected_row?: WiringTargetRow;
    candidate_row?: WiringTargetRow;
    row_candidate_ids?: string[];
    terminal_observation?: {
      pin_id: string;
      state: string;
      evidence: string;
      box: WiringCrop;
      capture_id: string;
      source_sha256: string;
      source_size: [number, number];
      role: "component_header";
    };
    partner_wire_id?: string;
    partner_component_pin?: string;
    candidate_board_pin?: string | null;
    candidate_physical_pin?: number | null;
    module_identity_known?: boolean;
    module_attachment_uncertain?: boolean;
    module_attachment_confirmed?: boolean;
    observed_board_pin: string | null;
    observed_physical_pin: number | null;
    observed_component_pin: string | null;
    board_connector_id: string | null;
    component_connector_id: string | null;
    evidence: string;
    retake_roles: WiringPhotoRole[];
  };
}

/** Never upgrade legacy colour-only findings to either a fault or a match. */
export function wiringFindingStatus(row: WiringReviewResult) {
  return row.diagnosis?.status ?? "uncertain";
}

/** A review cursor is not a finding. Only explicit evidence selects a priority wire. */
export function wiringHasConnectionClue(row: WiringReviewResult) {
  const status = wiringFindingStatus(row);
  return status === 'suspected' || status === 'uncertain'
    && (row.diagnosis?.kind === 'row_position_check' || row.comparison === 'different');
}

export function wiringFindingLabel(row: WiringReviewResult, tr: (zh: string, en: string) => string) {
  const status = wiringFindingStatus(row);
  return status === 'suspected' ? row.diagnosis?.kind === 'unconnected_terminal' ? tr('疑似漏接', 'Possibly unconnected') : tr('疑似接錯', 'Possible wrong pin')
    : status === 'no_issue_seen' ? tr('未見明顯錯接', 'No obvious mismatch seen')
      : row.diagnosis?.kind === 'row_position_check' ? tr('優先核對', 'Check first')
      : row.comparison === 'different' ? tr('線色不同・待核對', 'Different colours · check wire') : tr('無法確認', 'Uncertain');
}

/** Render the server's diagnosis without deriving a swap from colours locally. */
export function wiringSuspectedConnectionText(row: WiringReviewResult, tr: (zh: string, en: string) => string) {
  const finding = row.diagnosis;
  if (finding?.status !== 'suspected') return null;
  if (finding.kind === 'unconnected_terminal') return tr(`${row.expected.component_pin} 這個腳位疑似漏接。`, `${row.expected.component_pin} may be unconnected.`)
    + (finding.evidence ? ` ${finding.evidence}` : '');
  if (finding.kind === 'reciprocal_endpoint_swap') {
    const expected = row.expected.physical_pin != null ? `Pi Pin ${row.expected.physical_pin}` : row.expected.board_pin;
    const candidate = finding.candidate_physical_pin != null ? `Pi Pin ${finding.candidate_physical_pin}` : finding.candidate_board_pin;
    if (finding.partner_component_pin && candidate && expected) return tr(
      `${row.expected.component_pin} 與 ${finding.partner_component_pin} 疑似接反；${row.expected.component_pin} 線色對應 ${candidate}（應接 ${expected}），需沿線確認。`,
      `${row.expected.component_pin} and ${finding.partner_component_pin} may be swapped: the colour for ${row.expected.component_pin} matches ${candidate} (expected ${expected}). Trace the wire to confirm.`);
    return finding.evidence || tr('疑似接反，請沿線核對兩端。', 'Possible swapped connections. Trace both wire endpoints.');
  }
  const pin = finding.observed_physical_pin != null ? `Pi Pin ${finding.observed_physical_pin}` : finding.observed_board_pin;
  return finding.observed_component_pin && pin ? tr(`照片疑似：${finding.observed_component_pin} → ${pin}`, `Photo suggests: ${finding.observed_component_pin} → ${pin}`)
    : finding.evidence || tr('照片顯示可能接錯，請核對兩端。', 'The photo suggests a possible mismatch. Check both endpoints.');
}

/** Requested camera row alone never creates a photo position. */
export function wiringPinSeatText(candidate: WiringEndpoint, tr: (zh: string, en: string) => string) {
  const seat = candidate.pin_seat;
  if (!seat || !['pi_side_a', 'pi_side_b'].includes(candidate.role ?? '') || seat.image_id !== candidate.role
    || !['inner', 'outer'].includes(seat.row)
    || seat.capture_id !== candidate.capture_id) return null;
  if (seat.column === null) return tr(`照片定位：${seat.row === 'inner' ? '內排' : '外排'}，第幾個位置尚未確認`,
    `Photo position: ${seat.row} row; the position within the row is not yet confirmed`);
  if (!Number.isInteger(seat.column) || seat.column < 1 || seat.column > 20) return null;
  return tr(`照片定位：${seat.row === 'inner' ? '內排' : '外排'}第 ${seat.column} 位（從 Pin 1／2 端數）`,
    `Photo position: ${seat.row} row, position ${seat.column} from the Pin 1/2 end`);
}

export function prioritiseWiringResults(rows: WiringReviewResult[]) {
  const rank = (row: WiringReviewResult) => wiringFindingStatus(row) === 'suspected' ? 0
    : row.diagnosis?.kind === 'row_position_check' && wiringFindingStatus(row) === 'uncertain' ? 1
      : wiringFindingStatus(row) === 'uncertain' ? 2 : 3;
  return [...rows].sort((a, b) => rank(a) - rank(b));
}
export interface WiringReviewState {
  id: string;
  /** Missing on historical reviews captured as two unspecified sides. */
  capture_plan?: WiringCapturePlan;
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
  model_receipt?: WiringModelReceipt | null;
  photo_flow_version?: number;
  pipeline_version?: string;
  pipeline_stages?: { stage: "exit_inventory" | "pin_review"; elapsed_ms?: number; cached?: boolean }[];
  error?: string | null;
}
export const wiringPhotoRoles: WiringPhotoRole[] = ["pi_side_a", "pi_side_b", "component_header"];

export function wiringPhotoRow(role: WiringPhotoRole, plan?: WiringCapturePlan): WiringTargetRow | null {
  return plan === 'pi_rows_v1' ? role === 'pi_side_a' ? 'inner' : role === 'pi_side_b' ? 'outer' : null : null;
}

/** Never relabel a historical side photo as a requested pin row. */
export function wiringPhotoRoleLabel(role: WiringPhotoRole, tr: (zh: string, en: string) => string, plan?: WiringCapturePlan) {
  const row = wiringPhotoRow(role, plan);
  return row === 'inner' ? tr('Pi 內排', 'Pi inner row') : row === 'outer' ? tr('Pi 外排', 'Pi outer row')
    : role === 'pi_side_a' ? tr('Pi 第一側', 'Pi first side') : role === 'pi_side_b' ? tr('Pi 另一側', 'Pi other side') : tr('零件接頭', 'Module header');
}

export function wiringPhotoInstruction(role: WiringPhotoRole, tr: (zh: string, en: string) => string, plan?: WiringCapturePlan) {
  const row = wiringPhotoRow(role, plan);
  return row === 'inner' ? tr('拍 Pi 內排（靠板中央）：從板內側斜拍，露出插頭底部、線色與板角。', 'Photograph the Pi inner row (toward the board centre): angle the camera from over the board, showing plug bases, wire colours and a board corner.')
    : row === 'outer' ? tr('拍 Pi 外排（靠板邊緣）：從板邊外側斜拍，露出插頭底部、線色與板角。', 'Photograph the Pi outer row (toward the board edge): angle the camera from outside the edge, showing plug bases, wire colours and a board corner.')
      : role === 'component_header' ? tr('拍零件接頭，讓標字與插頭入鏡。', 'Photograph the module header with labels and plugs visible.')
        : role === 'pi_side_b' ? tr('換到 Pi 另一側，拍出被遮住的接頭。', 'Photograph the other Pi side to show the hidden plugs.')
          : tr('拍 Pi 第一側，保留排針與板角。', 'Photograph the first Pi side with the header and board corner visible.');
}

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
