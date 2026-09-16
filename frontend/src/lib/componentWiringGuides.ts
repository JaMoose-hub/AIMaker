import type { ComponentPoseMessage, DetectionMessage, I18nText } from "./types";
import catalog from "../../../profiles/component-catalog.json";

export type GuidedComponentId = "hc-sr04" | "mrd-tf240-8p-cs";
export type ConnectionKind = "direct" | "divider";
export interface ActiveGuideTarget {
  componentId: string;
  boardPinId: string | null;
  componentPinId: string | null;
  connectionKind: ConnectionKind;
  manualOnly: boolean;
}
export interface ComponentGuideStep {
  id: string;
  componentPin: string;
  boardPin: string;
  boardLabel: string;
  connectionKind: ConnectionKind;
  instruction: I18nText;
  hint: I18nText;
}
export interface ComponentGuide {
  id: GuidedComponentId;
  boardId: "raspberry-pi-5";
  name: I18nText;
  safety: I18nText;
  prerequisites: Array<{ id: string; text: I18nText }>;
  steps: ComponentGuideStep[];
  unresolved: Array<{ pin: string; reason: I18nText }>;
  functionalTest: I18nText;
}
// Shared with the design backend; preserve the existing guide contracts.
export const COMPONENT_GUIDES = catalog.modules as readonly ComponentGuide[];

export interface GuideSession {
  componentId: GuidedComponentId;
  phase: "prepare" | "active" | "review";
  index: number;
  checked: string[];
  confirmed: string[];
}
export const initialGuideSession = (componentId: GuidedComponentId = "hc-sr04"): GuideSession => ({
  componentId, phase: "prepare", index: 0, checked: [], confirmed: [],
});
export const guideFor = (id: GuidedComponentId): ComponentGuide => COMPONENT_GUIDES.find((guide) => guide.id === id)!;
export const prerequisitesMet = (state: GuideSession): boolean => guideFor(state.componentId).prerequisites.every((item) => state.checked.includes(item.id));
export type GuideAction =
  | { type: "select"; id: GuidedComponentId }
  | { type: "check"; id: string; checked: boolean }
  | { type: "start" }
  | { type: "confirm"; ready: boolean }
  | { type: "previous" }
  | { type: "end" }
  | { type: "reset" };
export function guideReducer(state: GuideSession, action: GuideAction): GuideSession {
  const guide = guideFor(state.componentId);
  switch (action.type) {
    case "select": return state.phase === "active" ? state : initialGuideSession(action.id);
    case "check": return state.phase !== "prepare" ? state : { ...state, checked: action.checked ? [...new Set([...state.checked, action.id])] : state.checked.filter((id) => id !== action.id) };
    case "start": return state.phase === "prepare" && prerequisitesMet(state) ? { ...state, phase: "active" } : state;
    case "confirm": {
      if (state.phase !== "active" || !action.ready) return state;
      const confirmed = [...state.confirmed.slice(0, state.index), guide.steps[state.index].id];
      return state.index === guide.steps.length - 1
        ? { ...state, confirmed, phase: "review" }
        : { ...state, confirmed, index: state.index + 1 };
    }
    case "previous": {
      if (state.phase === "prepare") return state;
      const index = Math.max(0, state.phase === "review" ? Math.min(state.confirmed.length, guide.steps.length - 1) : state.index - 1);
      return { ...state, phase: "active", index, confirmed: state.confirmed.slice(0, index) };
    }
    case "end": return state.phase === "active" ? { ...state, phase: "review" } : state;
    case "reset": return initialGuideSession(state.componentId);
  }
}

/** No cross-component fallback: GND/VCC on another module are not this target. */
export function guidePoseReady(detection: DetectionMessage | null, pose: ComponentPoseMessage | null, target: ActiveGuideTarget | null, fresh: boolean): boolean {
  return Boolean(fresh && target && detection?.tracking === "locked" && pose?.tracking === "locked"
    && pose.component_id === target.componentId
    && (!target.boardPinId || detection.pins.some((pin) => pin.id === target.boardPinId && pin.v))
    && (!target.componentPinId || pose.pins.some((pin) => pin.id === target.componentPinId && pin.v)));
}

/**
 * Geometry that is safe to keep drawing while the detector deliberately
 * publishes its last trusted pose as `stale`. This is display-only; a new
 * ready state still requires guidePoseReady's stricter locked requirement.
 */
export function guidePoseVisible(detection: DetectionMessage | null, pose: ComponentPoseMessage | null, target: ActiveGuideTarget | null, fresh: boolean): boolean {
  return Boolean(fresh && target && detection && detection.tracking !== "searching"
    && pose && pose.tracking !== "searching"
    && pose.component_id === target.componentId
    && (!target.boardPinId || detection.pins.some((pin) => pin.id === target.boardPinId && pin.v))
    && (!target.componentPinId || pose.pins.some((pin) => pin.id === target.componentPinId && pin.v)));
}
