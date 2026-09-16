import type { ProjectDesign, ProjectWire } from "./maker";

export interface CloudAISelection { model: string; effort: string; available: boolean; busy: boolean; supportsImages: boolean }
export interface CloudWireColor {
  name: "red" | "orange" | "yellow" | "green" | "blue" | "purple" | "pink" | "brown" | "black" | "white" | "gray" | "multicolor" | "other" | "unknown";
  visibility: "clear" | "partial" | "not_visible";
  evidence: string;
}
export interface CloudHeaderObservation {
  connectors: { id: string; position: string; contact: "covers_pin" | "breadboard_link" | "detached" | "uncertain"; wire_color: CloudWireColor; evidence: string;
    breadboard?: { pin_hole: {row: number; column: string; insertion_visible: boolean}; wire_hole: {row: number; column: string; insertion_visible: boolean};
      same_board_and_numbering_confirmed: boolean; topology: string; evidence: string } | null }[];
  target_identity: "identified" | "uncertain";
  target_pin_tip: "bare" | "covered" | "not_visible";
  target_connector_id: string | null;
  evidence: string;
}
export interface CloudPinContact {
  position: string; pin_id: string | null;
  appearance: "bare_tip" | "housing" | "breadboard" | "hidden" | "uncertain";
  connector_id: string | null;
}
export function cloudPinContactLabel(appearance: CloudPinContact["appearance"], locale: string) {
  const labels = {bare_tip: ["裸針", "Bare pin"], housing: ["接頭覆蓋", "Housing covers pin"],
    breadboard: ["經麵包板連接", "Via breadboard"], hidden: ["被遮住", "Hidden"], uncertain: ["待確認", "Uncertain"]};
  return labels[appearance][locale === "zh-TW" ? 0 : 1];
}
export function cloudWireColorLabel(color: CloudWireColor | undefined, locale: string) {
  const zh = locale === "zh-TW";
  if (!color || color.visibility === "not_visible") return zh ? "未看清" : "Not visible";
  const labels: Record<CloudWireColor["name"], string> = {
    red: "紅色", orange: "橘色", yellow: "黃色", green: "綠色", blue: "藍色", purple: "紫色", pink: "粉紅色",
    brown: "棕色", black: "黑色", white: "白色", gray: "灰色", multicolor: "多色", other: "其他顏色", unknown: "顏色不確定",
  };
  const name = zh ? labels[color.name] : color.name === "unknown" ? "Color uncertain" : color.name;
  return `${name}${color.visibility === "partial" ? (zh ? "（局部可見）" : " (partly visible)") : ""}`;
}
export function cloudWiringRequest(design: ProjectDesign, wire: ProjectWire, ai: CloudAISelection, locale: string) {
  return {
    project_id: design.id, project_revision: design.revision, catalog_version: design.catalog_version,
    profile_versions: design.profile_versions ?? {}, wire_id: wire.id, component_id: wire.componentId,
    board_pin: wire.boardPin, component_pin: wire.componentPin, connection_kind: wire.connectionKind,
    model: ai.model, effort: ai.effort, locale,
  };
}
export interface CloudWiringJob {
  id: string; status: "capturing" | "checking" | "completed" | "failed"; model: string;
  error: string | null; stale: boolean;
  completed_at?: string | null;
  inspection?: {phase: string; effort: string; max_calls: number; stages: {stage: string; elapsed_s: number; image_names: string[]}[]};
  capture: { captured_at: string; same_frame: boolean; capture_skew_ms: number; mode?: "pin_crops" | "overview" | "context_crops" } | null;
  images: { name: string; url: string }[];
  result: null | {
    authority: "visual_advisory"; electrical_verified: false;
    verdict: "looks_matched" | "suspected_issue" | "uncertain" | "needs_review";
    summary: string; limitations: string;
    board_endpoint: { state: string; observed_pin: string | null; evidence: string };
    component_endpoint: { state: string; observed_pin: string | null; evidence: string };
    // Optional while an already-running backend/job still uses the previous contract.
    wire_colors?: { board: CloudWireColor; component: CloudWireColor; comparison: "similar" | "different" | "uncertain"; evidence: string };
    wire_path?: { visibility: "traceable" | "partially_visible" | "not_visible"; evidence: string };
    same_wire: string;
    visual_observations?: { board: CloudHeaderObservation; component: CloudHeaderObservation };
    consistency_issues?: string[];
    pin_contacts?: {board?: CloudPinContact[]; component?: CloudPinContact[]};
  };
}
export function cloudPhotoExpired(job: CloudWiringJob | undefined, now: number, lostPose: boolean) {
  if (!job?.capture) return false;
  if ((lostPose && !["overview", "context_crops"].includes(job.capture.mode ?? "")) || job.stale) return true;
  // A pending cloud call must not consume the result's reading window.
  if (job.status === "capturing" || job.status === "checking") return false;
  const completedAt = Date.parse(job.completed_at ?? "");
  const reference = Number.isFinite(completedAt) ? completedAt : Date.parse(job.capture.captured_at);
  return !Number.isFinite(reference) || now - reference > 30000;
}

export interface CloudCheckViewState {
  job?: CloudWiringJob; error?: string | null; stale: boolean; busy?: boolean; readAgain?: boolean;
}
/** Presentation only: never changes the model's verdict or manual wiring records. */
export function cloudWiringCopy({ job, error, stale, busy, readAgain }: CloudCheckViewState, locale: string) {
  const tr = (zh: string, en: string) => locale === "zh-TW" ? zh : en;
  const copy = (title: string, next: string, tone: "success" | "warning" | "issue" | "neutral", symbol: string) => ({ title, next, tone, symbol });
  if (busy) {
    const phase = job?.inspection?.phase;
    const extra = job?.inspection?.max_calls === 4 ? 1 : 0;
    const step = (n: number) => `${n + extra}/${3 + extra} · `;
    const title = phase === "localization" ? tr("1/4 · 尋找端點、準備特寫", "1/4 · Locating endpoints for close-ups")
      : phase === "component" ? step(1) + tr("檢查零件接頭", "Inspecting module contacts")
      : phase === "board" ? step(2) + tr("檢查 Pi 接頭", "Inspecting Pi contacts")
        : phase === "route" ? step(3) + tr("核對線路", "Checking wire route")
          : tr("正在檢查這一步", "Checking this connection");
    return copy(title, tr("請稍候，不必重複送出。", "Please wait; no need to send again."), "neutral", "…");
  }
  if (error || job?.status === "failed") return copy(tr("檢查未完成", "Check not completed"), readAgain
    ? tr("請按「再讀結果」，不會重新送出照片。", "Read the result again; no new photo will be sent.")
    : tr("請查看錯誤說明，排除後再試一次。", "Review the error details, then try again."), "warning", "!");
  if (stale || job?.stale) return copy(tr("先前照片，請重新檢查", "Earlier photo — check again"),
    tr("請重新拍攝目前接線。", "Take a new photo of the current wiring."), "neutral", "↻");
  const result = job?.result;
  if (!result) return copy(tr("拍照檢查這一步", "Check this connection"),
    tr("接好後按「AI 檢查本步」。", "Connect the wire, then select AI check step."), "neutral", "◎");
  if (result.verdict === "looks_matched") return copy(tr("照片外觀符合", "Photo looks matched"),
    tr("請自行確認後，繼續手動接線引導。", "Confirm for yourself, then continue the manual guide."), "success", "✓");
  if (result.verdict === "needs_review") return copy(tr("分壓接線仍需確認", "Divider still needs review"),
    tr("請對照分壓圖，核對電阻與兩段接線。", "Compare the divider diagram, resistors and both wire sections."), "warning", "!");
  const piWrong = ["other", "empty"].includes(result.board_endpoint.state);
  const moduleWrong = ["other", "empty"].includes(result.component_endpoint.state);
  if (result.verdict === "suspected_issue") return copy(tr("疑似接錯，請核對", "Possible wiring issue"),
    piWrong && moduleWrong ? tr("請核對兩端目標腳位，再重新檢查。", "Check both target pins, then take another photo.")
      : piWrong ? tr("請核對 Pi 端目標腳位，再重新檢查。", "Check the target pin on the Pi, then take another photo.")
        : moduleWrong ? tr("請核對零件端目標腳位，再重新檢查。", "Check the target pin on the module, then take another photo.")
          : tr("請把兩端之間的線路分開擺，重新檢查。", "Separate the wire routes between both ends, then check again."), "issue", "!");
  const piUnclear = ["uncertain", "occluded"].includes(result.board_endpoint.state);
  const moduleUnclear = ["uncertain", "occluded"].includes(result.component_endpoint.state);
  const visiblePiPlug = result.visual_observations?.board.connectors.some(c => ["covers_pin", "breadboard_link"].includes(c.contact));
  const visibleModulePlug = result.visual_observations?.component.connectors.some(c => ["covers_pin", "breadboard_link"].includes(c.contact));
  if ((piUnclear && visiblePiPlug) || (moduleUnclear && visibleModulePlug)) return copy(
    piUnclear && moduleUnclear ? tr("已看見接頭，兩端腳位待確認", "Connectors visible — pin identities unclear")
      : piUnclear ? tr("已看見接線，Pi 腳位待確認", "Wire visible — Pi pin needs confirmation")
        : tr("已看見接線，零件腳位待確認", "Wire visible — module pin needs confirmation"),
    piUnclear ? tr("請補拍 Pi 排針近照，包含 Pin 1 端與接頭位置。", "Take a Pi header close-up including the Pin 1 end and the connector.")
      : tr("請補拍零件排針近照，包含腳位標示與接頭。", "Take a module close-up including the pin labels and connector."), "warning", "?");
  return copy(tr("這一步還看不清楚", "This connection is still unclear"),
    piUnclear && moduleUnclear ? tr("請露出兩端插孔，對焦後重新檢查。", "Expose both connectors and focus, then check again.")
      : piUnclear ? tr("請露出 Pi 端插孔，對焦後重新檢查。", "Expose and focus on the Pi connector, then check again.")
        : moduleUnclear ? tr("請露出零件端插孔，對焦後重新檢查。", "Expose and focus on the module connector, then check again.")
          : tr("請把線路分開擺，露出中段後重新檢查。", "Separate the wires and expose the middle section, then check again."), "warning", "?");
}

/** Replace internal view IDs in prose without rewriting the AI's observation. */
export function cloudEvidenceText(text: string, locale: string) {
  const names: Record<string, string> = locale === "zh-TW"
    ? { pi_overview: "全景照片", pi_pins: "Pi 排針特寫", component_overview: "零件全景照片", component_pins: "零件腳位特寫", pi_reading: "Pi 放大閱讀圖", component_reading: "零件旋正閱讀圖" }
    : { pi_overview: "overview photo", pi_pins: "Pi header close-up", component_overview: "module overview", component_pins: "module pin close-up", pi_reading: "Pi enlarged view", component_reading: "module reading view" };
  return text.replace(/\b(?:pi_overview|pi_pins|component_overview|component_pins|pi_reading|component_reading)\b/g, name => names[name]);
}

export function cloudEndpointLabel(endpoint: { state: string; observed_pin: string | null }, locale: string) {
  const tr = (zh: string, en: string) => locale === "zh-TW" ? zh : en;
  switch (endpoint.state) {
    case "target": return tr("目標腳位可見", "Target pin visible");
    case "other": return endpoint.observed_pin ? tr(`疑似插在 ${endpoint.observed_pin}`, `Appears on ${endpoint.observed_pin}`) : tr("疑似其他腳位", "Possibly another pin");
    case "empty": return tr("目標插孔未見接頭", "No connector seen at target");
    case "occluded": return tr("插孔被遮住", "Connector obscured");
    default: return tr("腳位未辨清", "Exact pin unclear");
  }
}

export function cloudContactLabel(contact: string, locale: string) {
  const tr = (zh: string, en: string) => locale === "zh-TW" ? zh : en;
  return contact === "covers_pin" ? tr("接頭覆住針尖", "Housing covers pin tip")
    : contact === "breadboard_link" ? tr("經麵包板同組孔位", "Via breadboard terminal strip")
    : contact === "detached" ? tr("接頭懸空", "Detached connector") : tr("接合處未辨清", "Contact unclear");
}

export function cloudTargetColorLabel(endpoint: {state: string}, color: CloudWireColor | undefined,
  observation: CloudHeaderObservation | undefined, locale: string) {
  const zh = locale === "zh-TW";
  if (endpoint.state === "empty") return zh ? "未見目標接線" : "No target wire seen";
  if ((!color || color.name === "unknown" || color.visibility === "not_visible") && observation?.connectors.length) {
    return zh ? "目標線尚未對應（見下方接頭觀察）" : "Target wire not associated (see connectors below)";
  }
  return cloudWireColorLabel(color, locale);
}

/** Preserve candidate colors without presenting them as the target wire. */
export function cloudEndpointFinding(endpoint: { state: string; observed_pin: string | null }, color: CloudWireColor | undefined,
  observation: CloudHeaderObservation | undefined, locale: string) {
  const zh = locale === "zh-TW";
  const status = cloudEndpointLabel(endpoint, locale);
  if (endpoint.state === "empty") return status;
  if (color && color.name !== "unknown" && color.visibility !== "not_visible") return `${status} · ${cloudWireColorLabel(color, locale)}`;
  const covered = (observation?.connectors ?? []).filter(c => ["covers_pin", "breadboard_link"].includes(c.contact) && c.wire_color.name !== "unknown" && c.wire_color.visibility !== "not_visible");
  if (["uncertain", "occluded"].includes(endpoint.state) && covered.length) {
    const names = [...new Set(covered.map(c => cloudWireColorLabel(c.wire_color, locale)))];
    return `${status} · ${zh ? "已見接頭：" : "Visible connectors: "}${names.join(zh ? "、" : ", ")}`;
  }
  const colors = [...new Set((observation?.connectors ?? []).filter(c => c.wire_color.name !== "unknown" && c.wire_color.visibility !== "not_visible")
    .map(c => cloudWireColorLabel(c.wire_color, locale)))];
  if (colors.length) return `${status} · ${zh ? "候選線：" : "Candidate wires: "}${colors.join(zh ? "、" : ", ")}`;
  return color ? `${status} · ${cloudWireColorLabel(color, locale)}` : status;
}

export function cloudPathLabel(result: NonNullable<CloudWiringJob["result"]>, locale: string) {
  const tr = (zh: string, en: string) => locale === "zh-TW" ? zh : en;
  if (result.same_wire === "different") return tr("疑似不同條線", "Possibly different wires");
  if (result.same_wire === "consistent" && result.wire_path?.visibility === "traceable") return tr("可追蹤為同一條線", "Same wire visually traceable");
  if (result.visual_observations && result.wire_path?.visibility === "traceable") return tr("線路可追蹤，端點對應待確認", "Route traceable; target endpoints unconfirmed");
  return result.wire_path?.visibility === "partially_visible" ? tr("部分路徑未辨清", "Part of the route is unclear") : tr("尚未辨清完整路徑", "Full route not confirmed");
}
