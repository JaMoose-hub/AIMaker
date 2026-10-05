import catalog from "../../../profiles/component-catalog.json";
import ultrasonic from "../../../profiles/components/hc-sr04/vision_profile.json";
import display from "../../../profiles/components/mrd-tf240-8p-cs/vision_profile.json";
import pi5 from "../../../profiles/boards/raspberry-pi-5/board.json";
import type { ProjectDesign, ProjectWire } from "./maker";
import type { GuidedComponentId } from "./componentWiringGuides";

const visions = { "hc-sr04": ultrasonic, "mrd-tf240-8p-cs": display };
export interface FrozenCircuitProfile {
  modules: { id: string; name: { "zh-TW": string; en: string }; safety: { "zh-TW": string; en: string };
    unresolved: { pin: string; reason: { "zh-TW": string; en: string } }[];
    pins: { id: string; x_norm: number; y_norm: number }[]; pin_order: string[];
    header_at_top: boolean; canonical_orientation?: string }[];
}
export const CIRCUIT_WIDTH = 840;
export const PI_HEADER_TOP = 158;
export const PI_HEADER_PITCH = 22;
export const PI_HEADER_BOTTOM = PI_HEADER_TOP + 19 * PI_HEADER_PITCH;
export const PI_PANEL_HEIGHT = PI_HEADER_BOTTOM + 44 - 42;
export const MODULE_X = 452;
export const MODULE_WIDTH = 352;
export interface DiagramPin {
  id: string; x: number; y: number; wire?: ProjectWire; state: "connected" | "unused" | "pending";
}
export interface DiagramBoardPin {
  id: string; number: number; row: number; column: 0 | 1;
  x: number; y: number; label: string; color: string;
}
export interface DiagramRoute {
  wire: ProjectWire; pin: DiagramPin; boardPin: DiagramBoardPin;
  laneX: number; boardY: number; groundY?: number; groundX?: number;
}
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
export function circuitLayout(design: ProjectDesign, only?: GuidedComponentId, frozenProfile?: FrozenCircuitProfile) {
  // J8 identity is shared with camera guidance. Never infer a physical pin from
  // the lesson index or a display label (GPIO18, for example, is physical 12).
  const boardPins: DiagramBoardPin[] = pi5.pins.filter(pin => pin.header === "J8")
    .sort((a, b) => a.index - b.index).map(pin => {
      const column = (pin.index % 2 === 0 ? 1 : 0) as 0 | 1;
      const row = Math.floor((pin.index - 1) / 2);
      const ground = pin.id.startsWith("GND_");
      const power = pin.id.startsWith("3V3_") || pin.id.startsWith("5V_");
      return { id: pin.id, number: pin.index, row, column,
        x: column === 0 ? 148 : 180, y: PI_HEADER_TOP + row * PI_HEADER_PITCH,
        label: ground ? "GND" : pin.id.startsWith("3V3_") ? "3.3V" : pin.id.startsWith("5V_") ? "5V" : pin.id,
        color: ground ? "#aab8cb" : power ? "#ffae72" : "#6dc9f4" };
    });
  let top = 112;
  let routeIndex = 0;
  const modules: DiagramModule[] = [];
  for (const id of design.component_ids.filter(cid => !only || cid === only)) {
    const frozen = frozenProfile?.modules.find(m => m.id === id);
    // Historical diagrams must never silently borrow a newer pin profile.
    if (frozenProfile && !frozen) continue;
    const vision = frozen ?? visions[id];
    const guide = frozen ?? catalog.modules.find(m => m.id === id)!;
    const physicalPins = frozen ? frozen.pin_order.flatMap(pinId => frozen.pins.filter(pin => pin.id === pinId))
      : [...vision.pins].sort((a, b) => a.x_norm - b.x_norm);
    if (!physicalPins.length) continue;
    const headerAtTop = frozen?.header_at_top ?? physicalPins.reduce((sum, p) => sum + p.y_norm, 0) / physicalPins.length < .5;
    const wires = physicalPins.flatMap(p => design.wiring.filter(w => w.componentId === id && w.componentPin === p.id
      && boardPins.some(boardPin => boardPin.id === w.boardPin)));
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
      boardPin: boardPins.find(p => p.id === wire.boardPin)!, laneX: 316 + routeIndex++ * 4,
      boardY: headerY + (headerAtTop ? -1 : 1) * (34 + i * 34) }));
    for (const route of routes) if (route.wire.connectionKind === "divider") {
      const ground = routes.find(r => r.wire.componentPin === "GND");
      route.groundY = ground?.boardY;
      route.groundX = ground ? Math.max(route.laneX, ground.laneX) + 12 : undefined;
    }
    const height = (headerAtTop ? bodyY + bodyHeight : Math.max(headerY, ...routes.map(r => r.boardY))) - top + 38;
    modules.push({ id, top, height, bodyY, bodyHeight, headerAtTop, pins, routes });
    top += height + 24;
  }
  return { modules, boardPins, height: Math.max(top, PI_HEADER_BOTTOM + 68) };
}

export function wireColor(wire: ProjectWire) {
  return wire.componentPin === "GND" ? "#aab8cb" : wire.componentPin === "VCC" ? "#ffae72"
    : wire.connectionKind === "divider" ? "#edc364" : "#6dc9f4";
}

/** Presentation-only bend offsets. Endpoints and ProjectWire objects stay canonical. */
export type CircuitBendOffsets = Record<string, { x: number; y: number }>;
export function adjustCircuitBends(layout: ReturnType<typeof circuitLayout>, offsets: CircuitBendOffsets) {
  const finite = (value: number | undefined) => Number.isFinite(value) ? value! : 0;
  const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
  return { ...layout, modules: layout.modules.map(module => {
    // Leave the divider's branching region before its series resistor. Its
    // ground join is recalculated below from the adjusted, real GND route.
    const divider = module.routes.some(route => route.wire.connectionKind === 'divider');
    const routes = module.routes.map(route => {
      const offset = offsets[route.wire.id];
      if (!offset) return { ...route };
      return { ...route,
        laneX: clamp(route.laneX + finite(offset.x), 304, divider ? 342 : 420),
        boardY: clamp(route.boardY + finite(offset.y),
          module.headerAtTop ? module.top + 58 : route.pin.y + 22,
          module.headerAtTop ? route.pin.y - 22 : module.top + module.height - 28),
      };
    });
    for (const route of routes) if (route.wire.connectionKind === 'divider') {
      const ground = routes.find(candidate => candidate.wire.componentPin === 'GND');
      route.groundY = ground?.boardY;
      route.groundX = ground ? Math.max(route.laneX, ground.laneX) + 12 : undefined;
    }
    return { ...module, routes };
  }) };
}
