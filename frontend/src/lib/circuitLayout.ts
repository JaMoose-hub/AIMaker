import catalog from "../../../profiles/component-catalog.json";
import ultrasonic from "../../../profiles/components/hc-sr04/vision_profile.json";
import display from "../../../profiles/components/mrd-tf240-8p-cs/vision_profile.json";
import type { ProjectDesign, ProjectWire } from "./maker";
import type { GuidedComponentId } from "./componentWiringGuides";

const visions = { "hc-sr04": ultrasonic, "mrd-tf240-8p-cs": display };
export const CIRCUIT_WIDTH = 840;
export const PI_TERMINAL_X = 235;
export const MODULE_X = 452;
export const MODULE_WIDTH = 352;
export interface DiagramPin {
  id: string; x: number; y: number; wire?: ProjectWire; state: "connected" | "unused" | "pending";
}
export interface DiagramRoute { wire: ProjectWire; pin: DiagramPin; boardY: number; groundY?: number }
export interface DiagramModule {
  id: GuidedComponentId; top: number; height: number; bodyY: number; bodyHeight: number;
  headerAtTop: boolean; pins: DiagramPin[]; routes: DiagramRoute[];
}

/** Guide targets stay authoritative; Blueprint selection only inspects a wire. */
export function circuitSelection(design: ProjectDesign, state: {
  activeId?: string; selectedId?: string | null;
  selected?: { componentId: GuidedComponentId; pinId: string }; moduleFilter?: GuidedComponentId;
}) {
  const activeWire = design.wiring.find(w => w.id === state.activeId);
  const selectedWire = design.wiring.find(w => state.selectedId !== undefined ? w.id === state.selectedId
    : w.componentId === state.selected?.componentId && w.componentPin === state.selected.pinId);
  const filter = activeWire?.componentId ?? (state.selectedId ? selectedWire?.componentId : undefined)
    ?? (state.moduleFilter && design.component_ids.includes(state.moduleFilter) ? state.moduleFilter : undefined);
  return { activeWire, focus: activeWire ?? selectedWire, filter };
}

/** Pin order and header edge come from camera profiles. Spacing is illustrative. */
export function circuitLayout(design: ProjectDesign, only?: GuidedComponentId) {
  let top = 112;
  const modules: DiagramModule[] = [];
  for (const id of design.component_ids.filter(cid => !only || cid === only)) {
    const vision = visions[id];
    const guide = catalog.modules.find(m => m.id === id)!;
    const physicalPins = [...vision.pins].sort((a, b) => a.x_norm - b.x_norm);
    const headerAtTop = physicalPins.reduce((sum, p) => sum + p.y_norm, 0) / physicalPins.length < .5;
    const wires = physicalPins.flatMap(p => design.wiring.filter(w => w.componentId === id && w.componentPin === p.id));
    const headerY = headerAtTop ? top + 88 + (wires.length - 1) * 34 : top + 208;
    const bodyY = headerAtTop ? headerY + 14 : top + 66;
    const bodyHeight = headerAtTop ? 180 : 128;
    const spacing = physicalPins.length > 4 ? 41 : 62;
    const startX = MODULE_X + MODULE_WIDTH / 2 - (physicalPins.length - 1) * spacing / 2;
    const pins: DiagramPin[] = physicalPins.map((pin, i) => {
      const wire = wires.find(w => w.componentPin === pin.id);
      return { id: pin.id, x: startX + i * spacing, y: headerY, wire,
        state: wire ? "connected" : guide.unresolved.some(p => p.pin === pin.id) ? "pending" : "unused" };
    });
    const routes: DiagramRoute[] = wires.map((wire, i) => ({ wire,
      pin: pins.find(p => p.id === wire.componentPin)!,
      boardY: headerY + (headerAtTop ? -1 : 1) * (34 + i * 34) }));
    for (const route of routes) if (route.wire.connectionKind === "divider") {
      route.groundY = routes.find(r => r.wire.componentPin === "GND")?.boardY;
    }
    const height = (headerAtTop ? bodyY + bodyHeight : Math.max(...routes.map(r => r.boardY))) - top + 38;
    modules.push({ id, top, height, bodyY, bodyHeight, headerAtTop, pins, routes });
    top += height + 24;
  }
  return { modules, height: top };
}

export function wireColor(wire: ProjectWire) {
  return wire.componentPin === "GND" ? "#aab8cb" : wire.componentPin === "VCC" ? "#ffae72"
    : wire.connectionKind === "divider" ? "#edc364" : "#6dc9f4";
}
