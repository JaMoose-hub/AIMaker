import catalog from "../../../profiles/component-catalog.json";
import type { ComponentGuideStep, GuidedComponentId } from "./componentWiringGuides";

export type MakerStage = "design" | "guide" | "deploy";
export type DesignView = "concept" | "blueprint";
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
  /** Visual placeholders only; excluded from the BOM, wiring and runtime. */
  concept_only_parts?: { kind: "motor"; quantity: number; purpose: string }[];
  image?: { id: string; url: string; width: number; height: number; provider: string; created_at: string; sha256: string };
  image_required?: boolean; image_error?: string; image_job_id?: string;
  preview?: { scene: string; interaction: string; screen_title: string; screen_lines: string[];
    accent: "teal" | "blue" | "amber"; layout: "console" | "tower" | "flat" } | null;
}
export interface Confirmation { signature: string; mode: GuideMode; at: string }
export interface MakerMessage { role: "user" | "assistant"; text: string; source?: "demo" }
export interface ProjectGuideState {
  componentIndex: number; index: number; phase: "prepare" | "active" | "review";
  mode: GuideMode; checks: string[]; confirmed: Record<string, Confirmation>; restored: boolean;
  run?: number;
  inspection?: boolean;
  inspectionSource?: "guide" | "debug";
  inspectionReturn?: { componentIndex: number; index: number; phase: "prepare" | "active" | "review"; mode: GuideMode };
}
export interface MakerState {
  aiModel: string; aiEffort: string; aiExpectedOutputTokens: number | null;
  aiIntent: "auto" | "design" | "ask"; aiJobId: string | null;
  designMode: DesignMode;
  standalone: boolean;
  stage: MakerStage; designView: DesignView; prompt: string; selected: GuidedComponentId[];
  design: ProjectDesign | null; candidate: ProjectDesign | null; code: string;
  guide: ProjectGuideState; conversation: MakerMessage[];
  hardware: Record<string, string>;
  debug?: { panelOpen?: boolean; intent?: "wiring" | "debug"; caseId?: string; componentId?: string; selectedComponentId?: string; runId?: string; trialId?: string; wireId?: string; source?: "guide" | "deploy"; symptom?: string;
    deployment?: {invocation_id?:string;code_hash?:string;run_id?:string;exit_code:number|null;logs?:string[];captured_at?:number} };
}
export const makerCatalog = catalog;
export const emptyGuide = (): ProjectGuideState => ({ componentIndex: 0, index: 0, phase: "prepare", mode: "camera", checks: [], confirmed: {}, restored: false });
const previousDefaultPrompt = `我想做一個桌上型距離監測器。

需求：
- 可以偵測前方物體的距離
- 螢幕即時顯示目前距離與狀態
- 當距離小於 20 cm 時，顯示警告，並在螢幕上顯示一台靠近障礙物的小車圖示
- 裝置使用上下兩層圓形壓克力圓盤組成，並使用支柱固定
- 整體大小適合放在桌面上

請根據以上需求，幫我決定需要哪些電子零件、感測器、控制板、螢幕與其他必要元件，並規劃如何組裝與接線。`;
const previousDefaultPromptEn = `I want to build a desktop distance monitor.

Requirements:
- Detect the distance to objects in front of it
- Display the current distance and status on a screen
- Warn below 20 cm and show a small car approaching an obstacle on the screen
- Use two stacked circular acrylic plates held together by standoffs
- Keep the overall size suitable for a desktop

Based on these requirements, help me choose the electronic components, sensors, controller, display and other necessary parts, and plan the assembly and wiring.`;

const previousStructuredPrompt = `我想做一個桌上型距離監測器。

需求：
- 可以偵測前方物體的距離
- 螢幕即時顯示目前距離與狀態
- 當距離小於 20 cm 時，顯示警告，並在螢幕上顯示一台靠近障礙物的小車圖示
- 裝置使用上下兩層圓形壓克力圓盤組成，並使用支柱固定
- 底部加裝三個輪胎，形成可手動推動的三輪底座
- 整體大小適合放在桌面上

請直接依照以上需求生成完整作品設計與組裝圖片，並規劃所需零件、組裝方式與接線。已提供的需求不要重複詢問，其餘造型與結構細節請自行採用合理配置。`;
const previousStructuredPromptEn = `I want to build a desktop distance monitor.

Requirements:
- Detect the distance to objects in front of it
- Display the current distance and status on a screen
- Warn below 20 cm and show a small car approaching an obstacle on the screen
- Use two stacked circular acrylic plates held together by standoffs
- Add three wheels underneath to form a manually movable three-wheel base
- Keep the overall size suitable for a desktop

Generate the complete project design and assembly image directly from these requirements, including the parts, assembly and wiring plan. Do not ask me to repeat or reconfirm requirements already provided. Choose reasonable defaults for the remaining appearance and structural details.`;

const previousConversationalPrompt = `我想做一個放在桌上的小型距離監測器。

它要能顯示前方物體離它多遠。如果距離小於 20 cm，就在螢幕上顯示警告，還有一台快要碰到障礙物的小車。

我希望機身用兩片圓形壓克力板，底下裝三個輪子。

我不知道該用哪些零件，請幫我全部選好，並教我怎麼組裝和接線。

也請生成完成後的設計與組裝圖片。

不用再問我問題，請直接做合理的選擇，幫我把它設計出來。`;
const previousConversationalPromptEn = `I want to make a small distance monitor for my desk.

It should show how far away something is in front of it. If something gets closer than 20 cm, show a warning and a small car getting close to an obstacle on the screen.

I want the body to use two round acrylic plates with three wheels underneath.

I don’t know what parts to use, so please choose everything for me and show me how to build and connect it.

Also generate an image of the finished design and assembly.

Don’t ask me questions. Just make reasonable choices and design it for me.`;

export const defaultPrompt = `我想做一台桌上型小車，可以偵測前面的距離。

螢幕要顯示距離，小於 20 cm 就顯示警告和快撞到東西的小車圖案。

外型用兩片圓形壓克力板，下面有馬達和三個輪子。

我不太懂硬體，請直接幫我選零件、教我組裝和接線，並做出完成後的示意圖。

不用問我，直接幫我設計。`;
export const defaultPromptEn = `I want to make a small desktop car that can detect how far away things are.

The screen should show the distance. If something is closer than 20 cm, show a warning and a small car about to hit an obstacle.

I want to use two round acrylic plates, with motors and three wheels underneath.

I don’t know much about hardware, so please choose the parts for me and show me how to assemble and wire everything.

Also, show me what the finished project will look like.

Don’t ask me questions. Just design it for me.`;

/** Explicitly refill only an empty composer; never submit or replace an edited draft. */
export function fillStarterPrompt(state: MakerState, locale: string): MakerState {
  if (state.aiJobId || state.prompt.trim()) return state;
  return { ...state, prompt: locale === "en" ? defaultPromptEn : defaultPrompt };
}

/** Only built-in starter text follows language; empty/custom/in-flight drafts stay intact. */
export function localizeStarterPrompt(state: MakerState, locale: string): MakerState {
  if (state.aiJobId || ![defaultPrompt, defaultPromptEn].includes(state.prompt)) return state;
  const prompt = locale === "en" ? defaultPromptEn : defaultPrompt;
  return state.prompt === prompt ? state : { ...state, prompt };
}
// Upgrade only known starters, ignoring surrounding whitespace from textarea input.
// Custom drafts (including a deliberately cleared input) must stay untouched.
const previousStarterPrompts = new Map([
  [previousDefaultPrompt, defaultPrompt], [previousDefaultPromptEn, defaultPromptEn],
  [previousStructuredPrompt, defaultPrompt], [previousStructuredPromptEn, defaultPromptEn],
  [previousConversationalPrompt, defaultPrompt], [previousConversationalPromptEn, defaultPromptEn],
  ["幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與警告狀態，距離小於 20 公分時顯示警告。", defaultPrompt],
  ["幫我做一個桌上型距離與顯示監測器，使用 Pi 5、超音波和螢幕。顯示距離與顯示狀態，距離小於 20 公分時顯示警告的小車車", defaultPrompt],
]);
export const initialMaker = (): MakerState => ({ standalone: false, stage: "design", designView: "concept", prompt: defaultPrompt,
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
  if (session.phase !== "active" || !step || session.inspection) return session;
  const existing = session.confirmed[step.id];
  return { ...session, confirmed: { ...session.confirmed, [step.id]: existing?.signature === wireSignature(step) ? existing : {
    signature: wireSignature(step), mode: session.mode, at: new Date().toISOString(),
  } }, index: session.index === steps.length - 1 ? session.index : session.index + 1,
  phase: session.index === steps.length - 1 ? "review" : "active" };
}

/** Move through wiring instructions without undoing confirmations or test bindings. */
export function previousProjectWire(design: ProjectDesign, session: ProjectGuideState): ProjectGuideState {
  if (session.inspection) return session;
  const steps = design.wiring.filter(w => w.componentId === design.component_ids[session.componentIndex]);
  if (!steps.length) return session;
  if (session.phase === "prepare" && !steps.every(w => session.confirmed[w.id]?.signature === wireSignature(w))) return session;
  if (session.phase === "active" && session.index <= 0) return session;
  const index = session.phase === "prepare" ? steps.length - 1
    : session.phase === "active" ? session.index - 1 : session.index;
  return { ...session, phase: "active", index: Math.max(0, Math.min(index, steps.length - 1)) };
}

/** Browsing never rewrites confirmations or the cursor to resume after review. */
export function reviewProjectWire(design: ProjectDesign, session: ProjectGuideState, componentId: string, pin?: string,
  source: "guide" | "debug" = "guide"): ProjectGuideState {
  const componentIndex = design.component_ids.findIndex(id => id === componentId);
  if (componentIndex < 0) return session;
  const steps = design.wiring.filter(w => w.componentId === componentId);
  const index = pin ? steps.findIndex(w => w.componentPin === pin) : 0;
  if (index < 0 || !steps.length) return session;
  return { ...session, inspection: true, inspectionSource: session.inspectionSource ?? source,
    inspectionReturn: session.inspectionReturn ?? { componentIndex: session.componentIndex, index: session.index, phase: session.phase, mode: session.mode },
    phase: "active", componentIndex, index };
}

export function resumeProjectGuide(session: ProjectGuideState): ProjectGuideState {
  const { inspectionReturn, inspectionSource: _source, inspection: _inspection, ...rest } = session;
  return { ...rest, ...inspectionReturn, inspection: false };
}

/** Only called after stopping/reconciling related hardware work. */
export function editProjectComponent(design: ProjectDesign, session: ProjectGuideState): ProjectGuideState {
  const cid = design.component_ids[session.componentIndex];
  const confirmed = { ...session.confirmed };
  for (const wire of design.wiring.filter(w => w.componentId === cid)) delete confirmed[wire.id];
  const { inspectionReturn: _return, inspectionSource: _source, ...rest } = session;
  return { ...rest, inspection: false, confirmed, phase: "active", index: 0, checks: [] };
}

export function enterDebug(state: MakerState, componentId?: string, runId?: string, symptom?: string): MakerState {
  const newIssue = runId !== undefined || symptom !== undefined;
  return { ...state, stage: "guide", standalone: false, guide: resumeProjectGuide(state.guide),
    debug: { ...state.debug, panelOpen: true, intent: state.guide.inspection && !newIssue ? state.debug?.intent ?? "debug" : "debug", selectedComponentId: componentId ?? state.debug?.selectedComponentId,
      ...(newIssue ? { componentId: componentId ?? state.debug?.componentId, runId, symptom,
        deployment: undefined, source: state.stage === "deploy" ? "deploy" as const : "guide" as const } : {}) } };
}

export const needsDraftConsent = (state: MakerState): boolean => Boolean(state.candidate && state.design
  && state.code !== state.design.code && state.code !== state.candidate.code);
export function confirmConcept(state: MakerState, replaceManual = false): MakerState {
  if (state.candidate && (state.candidate.image_required || state.candidate.source === "ai") && !state.candidate.image) return state;
  if (needsDraftConsent(state) && !replaceManual) return state;
  return state.candidate ? { ...applyDesign(state, state.candidate, "design"), designView: "blueprint" }
    : state.design ? { ...state, standalone: false, stage: "design", designView: "blueprint" } : state;
}

/** Discard only this preview; never the approved project or an in-flight result. */
export function discardConcept(state: MakerState, expectedPreview = state.candidate): MakerState {
  if (state.aiJobId || !state.candidate || state.candidate !== expectedPreview) return state;
  return { ...state, candidate: null };
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
  const viewingBlueprint = state.stage === "design" && state.designView === "blueprint";
  return { prompt: state.prompt, component_ids: state.selected,
    current: state.aiIntent !== "design" && (state.stage !== "design" || viewingBlueprint) ? state.design : state.candidate ?? state.design,
    locale, model, effort: state.aiEffort, expected_output_tokens: state.aiExpectedOutputTokens,
    intent: state.aiIntent, design_mode: state.designMode, generate_image: state.aiIntent !== "ask",
    conversation: fresh ? [] : state.conversation.filter(m => m.source !== "demo").slice(-20).map(m => ({ role: m.role, text: m.text.slice(0, 4000) })),
    workflow: { stage: viewingBlueprint ? "blueprint" : state.stage, active_wire: state.design && state.guide.phase === "active" ? currentWire(state.design, state.guide)?.id ?? null : null,
      manual_confirmations: Object.keys(state.guide.confirmed).length,
      code_draft: state.stage === "deploy" || state.stage === "guide" ? state.code.slice(0, 16000) : "" } };
}

/** Conversation is independent of the approved project, draft, and live tests. */
export function clearMakerConversation(state: MakerState): MakerState {
  return state.aiJobId ? state : {...state, conversation: []};
}

/** A new project drops project context, keeping only AI/parts preferences. */
export function newMakerProject(state: MakerState): MakerState {
  if (state.aiJobId) return state;
  return { ...initialMaker(), aiModel: state.aiModel, aiEffort: state.aiEffort,
    aiExpectedOutputTokens: state.aiExpectedOutputTokens, selected: [...state.selected] };
}

/** Sample bubbles do not consume the existing twenty-message real-history budget. */
export function retainMakerConversation(messages: MakerMessage[]): MakerMessage[] {
  let real = 0, demo = 0;
  return messages.slice().reverse().filter(message => message.source === "demo" ? ++demo <= 2 : ++real <= 20).reverse();
}

/** Demo is a local preview with clearly labelled sample chat, never an AI request. */
export function previewDemo(state: MakerState, demo: ProjectDesign, locale = "zh-TW"): MakerState {
  if (state.aiJobId || !validDesign(demo) || demo.source !== "demo") return state;
  const text = locale === "en"
    ? "Here’s a ready-made desktop car example using a Raspberry Pi 5, an HC-SR04+ distance sensor and an MRD-TFT240 display.\n\nThe sample image shows two round acrylic plates, three wheels and two motors. The motors are for the concept image only; they are not included in the blueprint, wiring, tests or deployment. The car will not drive itself.\n\nReview the image on the right, then confirm the project to see the blueprint and wiring steps. This is a built-in demo, not a newly generated design or a hardware test result."
    : "先幫你準備好一台桌上型小車的示範：使用 Raspberry Pi 5、HC-SR04+ 距離感測器和 MRD-TFT240 螢幕。\n\n右邊的示範圖有兩片圓形壓克力板、三個輪子和兩個馬達。馬達只呈現在概念圖，不會加入藍圖、接線、測試或部署，小車不會自行行駛。\n\n先看看右邊的造型，確認作品後就能查看藍圖並跟著步驟接線。這是內建示範，並非這次即時生成，也不代表硬體已測試通過。";
  const conversation: MakerMessage[] = [
    ...state.conversation.filter(message => message.source !== "demo"),
    { role: "user", text: locale === "en" ? defaultPromptEn : defaultPrompt, source: "demo" },
    { role: "assistant", text, source: "demo" },
  ];
  return {...state, candidate: demo, stage: "design", designView: "concept", standalone: false, conversation};
}

export function validDesign(value: unknown): value is ProjectDesign {
  if (!value || typeof value !== "object") return false;
  const d = value as ProjectDesign;
  if (d.image && (!/^[0-9a-f]{32}$/.test(d.image.id) || d.image.url !== `/api/design/images/${d.image.id}`
    || !Number.isFinite(d.image.width) || !Number.isFinite(d.image.height))) return false;
  if (d.assembly && (typeof d.assembly.description !== "string" || !Array.isArray(d.assembly.parts) || d.assembly.parts.length > 6
    || !d.assembly.parts.every(p => p && Object.prototype.hasOwnProperty.call(structuralParts, p.kind) && Number.isInteger(p.quantity) && p.quantity > 0 && p.quantity <= 32 && typeof p.purpose === "string"))) return false;
  if (d.concept_only_parts !== undefined && (!Array.isArray(d.concept_only_parts) || d.concept_only_parts.length > 1
    || !d.concept_only_parts.every(p => p && p.kind === "motor" && Number.isInteger(p.quantity) && p.quantity > 0 && p.quantity <= 32
      && typeof p.purpose === "string" && p.purpose.length > 0 && p.purpose.length <= 180))) return false;
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
    const stored = JSON.parse(raw) as Omit<MakerState, "stage" | "designView"> & {
      stage: MakerStage | "blueprint" | "debug"; designView?: DesignView;
    };
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
    const legacyDebug = stored.stage === "debug";
    return { ...base, ...stored, design, guide,
      debug: legacyDebug ? { ...stored.debug, panelOpen: true, intent: "debug" } : stored.debug,
      prompt: typeof stored.prompt !== "string" ? defaultPrompt
        : !stored.aiJobId && previousStarterPrompts.has(stored.prompt.trim())
          ? previousStarterPrompts.get(stored.prompt.trim())!
          : stored.prompt,
      aiModel: typeof stored.aiModel === "string" && stored.aiModel.length <= 150 ? stored.aiModel : "",
      aiEffort: ["none", "minimal", "low", "medium", "high", "xhigh", "max"].includes(stored.aiEffort) ? stored.aiEffort : "low",
      aiExpectedOutputTokens: Number.isInteger(stored.aiExpectedOutputTokens) && stored.aiExpectedOutputTokens! >= 256 && stored.aiExpectedOutputTokens! <= 128000 ? stored.aiExpectedOutputTokens : null,
      aiIntent: "auto",
      designMode: stored.designMode === "fixed" ? "fixed" : "free",
      aiJobId: typeof stored.aiJobId === "string" && /^[\w-]{1,80}$/.test(stored.aiJobId) ? stored.aiJobId : null,
      stage: stored.stage === "blueprint" ? "design" : legacyDebug ? "guide"
        : ["design", "guide", "deploy"].includes(stored.stage) && (design || stored.stage === "design" || stored.standalone || stored.stage === "guide" && stored.debug?.panelOpen) ? stored.stage as MakerStage : "design",
      designView: design && (stored.stage === "blueprint" || stored.designView === "blueprint") ? "blueprint" : "concept",
      hardware: {},
      conversation: Array.isArray(stored.conversation) ? retainMakerConversation(stored.conversation
        .filter(m => m && ["user", "assistant"].includes(m.role) && typeof m.text === "string")
        .map(m => ({ role: m.role, text: m.text, ...(m.source === "demo" ? { source: "demo" as const } : {}) }))) : [],
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
