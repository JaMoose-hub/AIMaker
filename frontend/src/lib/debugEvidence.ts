import type { MakerState, ProjectDesign } from "./maker";
import type { DebugEvidence, DebugMessage, DiagramSnapshot } from "./debugSessions";
import type { I18nText } from "./types";

const sameLabel = (left: I18nText, right: I18nText) => typeof left === "string" || typeof right === "string"
  ? left === right : left?.["zh-TW"] === right?.["zh-TW"] && left?.en === right?.en;

export function evidenceSessionId(message: DebugMessage, evidence: DebugEvidence | undefined, currentSessionId?: string) {
  return message.check_id ?? message.session_id ?? evidence?.check_id ?? evidence?.session_id ?? currentSessionId;
}

export function debugEvidenceUrl(sessionId: string, captureId: string, view?: string) {
  const base = `/api/debug/sessions/${encodeURIComponent(sessionId)}/evidence/${encodeURIComponent(captureId)}`;
  return view && view !== "overview" ? `${base}?view=${encodeURIComponent(view)}` : base;
}

export function diagramWires(snapshot: DiagramSnapshot, wireIds: string[]) {
  const allowed = new Set(wireIds);
  return snapshot.design.wiring.filter(wire => allowed.has(wire.id));
}

export interface DiagramInspection { snapshot: DiagramSnapshot; wireId: string }

/** Inspect the archived drawing, never substitute a current wire or pin profile. */
export function createDiagramInspection(snapshot: DiagramSnapshot, wireId: string, current: ProjectDesign | null): DiagramInspection | null {
  if (!current || snapshot.schema_version !== "debug-diagram-v1" || snapshot.project_id !== current.id ||
      snapshot.design.id !== snapshot.project_id || snapshot.design.revision !== snapshot.project_revision) return null;
  const wire = snapshot.design.wiring.find(item => item.id === wireId);
  const modules = snapshot.render_snapshot?.modules;
  if (!wire || !modules?.length || !snapshot.design.component_ids.includes(wire.componentId) ||
      !snapshot.design.component_ids.every(id => modules.some(module => module.id === id && module.pins?.length && module.pin_order?.length)) ||
      !modules.some(module => module.id === wire.componentId && module.pin_order.includes(wire.componentPin))) return null;
  return { snapshot, wireId };
}

/** A view-only action preserves the guide cursor, confirmations, tests and AI context. */
export function inspectDiagramInMaker(state: MakerState, inspection: DiagramInspection): MakerState {
  if (!createDiagramInspection(inspection.snapshot, inspection.wireId, state.design)) return state;
  return { ...state, stage: "guide", guide: { ...state.guide, mode: "2d" }, debug: { ...state.debug, panelOpen: true } };
}

/** A historical illustration can navigate only while its exact design is current. */
export function diagramMatchesCurrent(snapshot: DiagramSnapshot, current: ProjectDesign | null) {
  if (!current || snapshot.project_id !== current.id || snapshot.project_revision !== current.revision ||
      snapshot.design.catalog_version !== current.catalog_version) return false;
  const versions = snapshot.design.profile_versions ?? {};
  const currentVersions = current.profile_versions ?? {};
  if (Object.keys(versions).length !== Object.keys(currentVersions).length ||
      Object.entries(versions).some(([id, profile]) => profile.sha256 !== currentVersions[id]?.sha256)) return false;
  return snapshot.design.wiring.length === current.wiring.length && snapshot.design.wiring.every(wire =>
    current.wiring.some(item => item.id === wire.id && item.componentId === wire.componentId &&
      item.componentPin === wire.componentPin && item.boardPin === wire.boardPin && item.connectionKind === wire.connectionKind &&
      item.boardLabel === wire.boardLabel && sameLabel(item.instruction, wire.instruction) && sameLabel(item.hint, wire.hint)));
}
