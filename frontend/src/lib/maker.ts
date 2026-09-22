import catalog from "../../../profiles/component-catalog.json";
import type { ComponentGuideStep, GuidedComponentId } from "./componentWiringGuides";

export type MakerStage = "design" | "blueprint" | "guide" | "debug" | "deploy";
export type GuideMode = "camera" | "2d";
export type DesignMode = "fixed" | "free";
export interface ProjectWire extends ComponentGuideStep { componentId: GuidedComponentId }
export interface Material { id: string; name: string; quantity: number; price: number; purpose: string }
export const structuralParts = {
  wheel: { name: "輪子 / Wheel", price: 30 }, axle: { name: "輪軸 / Axle", price: 20 },
  standoff: { name: "銅柱 / Brass standoff", price: 5 }, "acrylic-panel": { name: "壓克力板 / Acrylic panel", price: 60 },
  bracket: { name: "支架 / Bracket", price: 25 }, screw: { name: "螺絲 / Screw", price: 1 },
};
export interface ProjectDesign {
  id: string; revision: number; source: "ai" | "demo"; prompt: string;
  catalog_version: string; title: string; summary: string; features: string[];
  profile_versions?: Record<string, { version: string; sha256: string }>;
  component_ids: GuidedComponentId[]; parameters: { distance_cm: number; sample_ms: number };
  wiring: ProjectWire[]; bom: Material[]; instructions: string[]; tests: string[];
  code: string; logic: string; unresolved: string[];
  requirements: { imports: string[]; devices: string[] };
  generation?: { model: string; effort: string; design_mode?: DesignMode };
  assembly?: { description: string; parts: { kind: keyof typeof structuralParts; quantity: number; purpose: string }[] } | null;
  image?: { id: string; url: string; width: number; height: number; provider: string; created_at: string; sha256: string };
  image_required?: boolean; image_error?: string; image_job_id?: string;
  preview?: { scene: string; interaction: string; screen_title: string; screen_lines: string[];
    accent: "teal" | "blue" | "amber"; layout: "console" | "tower" | "flat" } | null;
}
export interface Confirmation { signature: string; mode: GuideMode; at: string }
export interface ProjectGuideState {
  componentIndex: number; index: number; phase: "prepare" | "active" | "review";
  mode: GuideMode; checks: string[]; confirmed: Record<string, Confirmation>; restored: boolean;
  run?: number;
  inspection?: boolean;
}
export interface MakerState {
  aiModel: string; aiEffort: string; aiExpectedOutputTokens: number | null;
  aiIntent: "auto" | "design" | "ask"; aiJobId: string | null;
  designMode: DesignMode;
  standalone: boolean;
  stage: MakerStage; prompt: string; selected: GuidedComponentId[];
  design: ProjectDesign | null; candidate: ProjectDesign | null; code: string;
  guide: ProjectGuideState; conversation: { role: "user" | "assistant"; text: string }[];
  hardware: Record<string, string>;
  debug?: { caseId?: string; componentId?: string; selectedComponentId?: string; runId?: string; source?: "guide" | "deploy"; symptom?: string;
    deployment?: {invocation_id?:string;code_hash?:string;run_id?:string;exit_code:number|null;logs?:string[];captured_at?:number} };
}
export const makerCatalog = catalog;
export const emptyGuide = (): ProjectGuideState => ({ componentIndex: 0, index: 0, phase: "prepare", mode: "camera", checks: [], confirmed: {}, restored: false });
export const defaultPrompt = "幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與警告狀態，距離小於 20 公分時顯示警告。";
export const initialMaker = (): MakerState => ({ standalone: false, stage: "design", prompt: "",
  aiModel: "", aiEffort: "low", aiExpectedOutputTokens: null,
  aiIntent: "auto", aiJobId: null, designMode: "free",
  selected: ["hc-sr04", "mrd-tf240-8p-cs"], design: null, candidate: null,
  code: "", guide: emptyGuide(), conversation: [], hardware: {} });
export const wireSignature = (wire: ProjectWire): string => [wire.componentId, wire.componentPin, wire.boardPin, wire.connectionKind].join("|");
export const currentWire = (design: ProjectDesign, guide: ProjectGuideState): ProjectWire | undefined =>
  design.wiring.filter(w => w.componentId === design.component_ids[guide.componentIndex])[guide.index];

/** Exhibition navigation records the user's action; localization is not a prerequisite. */
export const startProjectGuide = (session: ProjectGuideState): ProjectGuideState => ({ ...session, phase: "active", index: 0, checks: [] });
export const restartProjectGuide = (session: ProjectGuideState): ProjectGuideState => ({
  ...emptyGuide(), mode: session.mode, run: (session.run ?? 0) + 1,
});
export function confirmProjectWire(design: ProjectDesign, session: ProjectGuideState): ProjectGuideState {
  const steps = design.wiring.filter(w => w.componentId === design.component_ids[session.componentIndex]);
  const step = steps[session.index];
  if (session.phase !== "active" || !step) return session;
  return { ...session, confirmed: { ...session.confirmed, [step.id]: {
    signature: wireSignature(step), mode: session.mode, at: new Date().toISOString(),
  } }, index: session.index === steps.length - 1 ? session.index : session.index + 1,
  phase: session.index === steps.length - 1 ? "review" : "active" };
}

export const needsDraftConsent = (state: MakerState): boolean => Boolean(state.candidate && state.design
  && state.code !== state.design.code && state.code !== state.candidate.code);
export function confirmConcept(state: MakerState, replaceManual = false): MakerState {
  if (state.candidate && (state.candidate.image_required || state.candidate.source === "ai") && !state.candidate.image) return state;
  if (needsDraftConsent(state) && !replaceManual) return state;
  return state.candidate ? applyDesign(state, state.candidate, "blueprint")
    : state.design ? { ...state, standalone: false, stage: "blueprint" } : state;
}

export function applyDesign(state: MakerState, design: ProjectDesign, stage: MakerStage): MakerState {
  const sameProject = state.design?.id === design.id;
  const confirmed: Record<string, Confirmation> = {};
  if (sameProject) for (const wire of design.wiring) {
    const old = state.guide.confirmed[wire.id];
    if (old?.signature === wireSignature(wire)) confirmed[wire.id] = old;
  }
  const unchangedWiring = sameProject && JSON.stringify(state.design?.wiring.map(wireSignature)) === JSON.stringify(design.wiring.map(wireSignature));
  return { ...state, standalone: false, stage, design, candidate: null, code: design.code, hardware: {},
    guide: { ...(unchangedWiring ? state.guide : emptyGuide()), mode: state.guide.mode, confirmed, restored: state.guide.restored },
    conversation: state.conversation };
}

/** Candidate remains a preview until explicit confirmation, including on follow-up turns. */
export function designRequest(state: MakerState, locale: string, model: string | null) {
  const fresh = state.aiIntent === "design" && state.designMode === "free";
  return { prompt: state.prompt, component_ids: state.selected,
    current: state.aiIntent !== "design" && state.stage !== "design" ? state.design : state.candidate ?? state.design,
    locale, model, effort: state.aiEffort, expected_output_tokens: state.aiExpectedOutputTokens,
    intent: state.aiIntent, design_mode: state.designMode, generate_image: state.aiIntent !== "ask",
    conversation: fresh ? [] : state.conversation.slice(-20).map(m => ({ ...m, text: m.text.slice(0, 4000) })),
    workflow: { stage: state.stage, active_wire: state.design && state.guide.phase === "active" ? currentWire(state.design, state.guide)?.id ?? null : null,
      manual_confirmations: Object.keys(state.guide.confirmed).length,
      code_draft: state.stage === "deploy" || state.stage === "debug" ? state.code.slice(0, 16000) : "" } };
}

/** Conversation is independent of the approved project, draft, and live tests. */
export function clearMakerConversation(state: MakerState): MakerState {
  return state.aiJobId ? state : {...state, conversation: []};
}

/** Demo is a local preview, never a deployment or implicit project replacement. */
export function previewDemo(state: MakerState, demo: ProjectDesign): MakerState {
  if (state.aiJobId || !validDesign(demo) || demo.source !== "demo") return state;
  return {...state, candidate: demo, stage: "design", standalone: false};
}

export function validDesign(value: unknown): value is ProjectDesign {
  if (!value || typeof value !== "object") return false;
  const d = value as ProjectDesign;
  if (d.image && (!/^[0-9a-f]{32}$/.test(d.image.id) || d.image.url !== `/api/design/images/${d.image.id}`
    || !Number.isFinite(d.image.width) || !Number.isFinite(d.image.height))) return false;
  if (d.assembly && (typeof d.assembly.description !== "string" || !Array.isArray(d.assembly.parts) || d.assembly.parts.length > 6
    || !d.assembly.parts.every(p => p && Object.prototype.hasOwnProperty.call(structuralParts, p.kind) && Number.isInteger(p.quantity) && p.quantity > 0 && p.quantity <= 32 && typeof p.purpose === "string"))) return false;
  const preview = d.preview;
  if (preview && (!(typeof preview === "object") || ![preview.scene, preview.interaction, preview.screen_title].every(v => typeof v === "string")
    || !Array.isArray(preview.screen_lines) || preview.screen_lines.length > 3 || !preview.screen_lines.every(v => typeof v === "string")
    || !["teal", "blue", "amber"].includes(preview.accent) || !["console", "tower", "flat"].includes(preview.layout))) return false;
  return typeof d.id === "string" && Number.isInteger(d.revision) && d.catalog_version === catalog.version
    && typeof d.code === "string" && typeof d.title === "string" && typeof d.summary === "string"
    && Array.isArray(d.component_ids) && d.component_ids.length > 0
    && d.component_ids.length <= catalog.modules.length && new Set(d.component_ids).size === d.component_ids.length
    && d.component_ids.every(cid => catalog.modules.some(m => m.id === cid))
    && [d.wiring, d.bom, d.tests, d.features, d.instructions, d.unresolved].every(Array.isArray)
    && d.wiring.every(w => w && d.component_ids.includes(w.componentId))
    && [d.tests, d.features, d.instructions, d.unresolved].every(values => values.every(v => typeof v === "string"))
    && d.bom.every(b => b && typeof b.id === "string" && typeof b.name === "string" && Number.isFinite(b.quantity) && Number.isFinite(b.price))
    && d.component_ids.every(cid => {
      const steps = catalog.modules.find(m => m.id === cid)!.steps;
      const wires = d.wiring.filter(w => w.componentId === cid);
      return wires.length === steps.length && steps.every(s => wires.some(w => w.id === `${cid}:${s.id}`
        && w.componentPin === s.componentPin && w.boardPin === s.boardPin && w.connectionKind === s.connectionKind));
    });
}

export function restoreMaker(raw: string | null): MakerState {
  if (!raw) return initialMaker();
  try {
    const stored = JSON.parse(raw) as MakerState;
    const base = initialMaker();
    if (stored.design && !validDesign(stored.design)) return base;
    if (stored.candidate && !validDesign(stored.candidate)) stored.candidate = null;
    const design = stored.design ?? null;
    const guide = { ...emptyGuide(), ...(stored.guide ?? {}), restored: true, checks: [], phase: "prepare" as const };
    guide.run = Number.isSafeInteger(guide.run) && guide.run! >= 0 ? guide.run : 0;
    guide.componentIndex = Number.isInteger(guide.componentIndex) ? Math.max(0, Math.min(guide.componentIndex, (design?.component_ids.length ?? 1) - 1)) : 0;
    guide.mode = guide.mode === "2d" ? "2d" : "camera";
    guide.confirmed = Object.fromEntries((design?.wiring ?? []).flatMap(w => {
      const record = stored.guide?.confirmed?.[w.id];
      return record && record.signature === wireSignature(w) && ["camera", "2d"].includes(record.mode) && typeof record.at === "string" ? [[w.id, record]] : [];
    }));
    guide.index = 0;
    return { ...base, ...stored, design, guide,
      aiModel: typeof stored.aiModel === "string" && stored.aiModel.length <= 150 ? stored.aiModel : "",
      aiEffort: ["none", "minimal", "low", "medium", "high", "xhigh", "max"].includes(stored.aiEffort) ? stored.aiEffort : "low",
      aiExpectedOutputTokens: Number.isInteger(stored.aiExpectedOutputTokens) && stored.aiExpectedOutputTokens! >= 256 && stored.aiExpectedOutputTokens! <= 128000 ? stored.aiExpectedOutputTokens : null,
      aiIntent: "auto",
      designMode: stored.designMode === "fixed" ? "fixed" : "free",
      aiJobId: typeof stored.aiJobId === "string" && /^[\w-]{1,80}$/.test(stored.aiJobId) ? stored.aiJobId : null,
      stage: ["design", "blueprint", "guide", "debug", "deploy"].includes(stored.stage) && (design || stored.stage === "design" || stored.stage === "debug" || stored.standalone) ? stored.stage : "design",
      hardware: {},
      conversation: Array.isArray(stored.conversation) ? stored.conversation.filter(m => m && ["user", "assistant"].includes(m.role) && typeof m.text === "string").slice(-20) : [],
      selected: Array.isArray(stored.selected) ? [...new Set(stored.selected.filter(id => catalog.modules.some(m => m.id === id)))] : base.selected,
      code: typeof stored.code === "string" ? stored.code : design?.code ?? "" };
  } catch { return initialMaker(); }
}

export async function makerRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST", signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(35000)]) : AbortSignal.timeout(35000),
    headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json().catch(() => null);
    if (!response.ok) throw Object.assign(new Error(typeof result?.detail === "string" ? result.detail : `HTTP ${response.status}`), { status: response.status });
  if (result === null) throw new Error("Invalid API response");
  return result as T;
}
