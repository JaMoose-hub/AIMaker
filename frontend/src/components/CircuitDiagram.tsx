import { useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent, type MouseEvent as ReactMouseEvent } from "react";
import type { ProjectDesign, ProjectWire } from "../lib/maker";
import { guideFor, type GuidedComponentId } from "../lib/componentWiringGuides";
import { circuitLayout, adjustCircuitBends, circuitSelection, wireColor, CIRCUIT_WIDTH, PI_HEADER_TOP, PI_HEADER_BOTTOM, PI_PANEL_HEIGHT, MODULE_X, type CircuitBendOffsets, type DiagramPin, type DiagramRoute, type FrozenCircuitProfile } from "../lib/circuitLayout";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { CircuitModuleArt } from "./CircuitModuleArt";
import { CircuitViewport } from "./CircuitViewport";

const shortNames: Record<GuidedComponentId, string> = { "hc-sr04": "HC-SR04+", "mrd-tf240-8p-cs": "MRD-TFT240" };

export function CircuitDiagram({ design, activeId, onSelect, selectedId, onClearSelection, readableDefault = false, frozenProfile, compactPreview = false, workspace = false, focusLabel, viewControls, hideWorkspaceNotes = false }: {
  design: ProjectDesign; activeId?: string; onSelect?: (wire: ProjectWire) => void;
  selectedId?: string | null; onClearSelection?: () => void; readableDefault?: boolean; frozenProfile?: FrozenCircuitProfile; compactPreview?: boolean; workspace?: boolean; focusLabel?: string; viewControls?: ReactNode; hideWorkspaceNotes?: boolean;
}) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const [selected, setSelected] = useState<{ componentId: GuidedComponentId; pinId: string }>();
  const [moduleFilter, setModuleFilter] = useState<GuidedComponentId>();
  const expanded = useRef<HTMLDialogElement>(null);
  const [expandedOpen, setExpandedOpen] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [bends, setBends] = useState<{ owner: string; offsets: CircuitBendOffsets }>({ owner: '', offsets: {} });
  const drag = useRef<{ pointer: number; owner: string; wireId: string; startX: number; startY: number; offsetX: number; offsetY: number }>();
  const { activeWire, focus, filter } = circuitSelection(design, { activeId, selectedId, selected, moduleFilter });
  const routeOwner = JSON.stringify([design.id, design.revision, frozenProfile ?? null,
    design.wiring.map(wire => [wire.id, wire.componentId, wire.componentPin, wire.boardPin, wire.connectionKind])]);
  const baseLayout = circuitLayout(design, filter, frozenProfile);
  const offsets = bends.owner === routeOwner ? bends.offsets : {};
  const layout = adjustCircuitBends(baseLayout, compactPreview ? {} : offsets);
  const moduleGuide = (id: GuidedComponentId) => frozenProfile ? frozenProfile.modules.find(module => module.id === id) : guideFor(id);
  const selectedModule = selected && design.component_ids.includes(selected.componentId) ? moduleGuide(selected.componentId) : undefined;
  const pending = selectedModule?.unresolved.find(p => p.pin === selected?.pinId);
  function choose(componentId: GuidedComponentId, pin: DiagramPin) {
    setSelected({ componentId, pinId: pin.id });
    if (pin.wire) onSelect?.(pin.wire);
    else onClearSelection?.();
  }

  function setBend(wireId: string, x: number, y: number) {
    setBends(current => ({ owner: routeOwner,
      offsets: { ...(current.owner === routeOwner ? current.offsets : {}), [wireId]: { x, y } } }));
  }
  function pointerPosition(event: ReactPointerEvent<SVGElement>) {
    const svg = event.currentTarget.ownerSVGElement;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return null;
    const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(matrix.inverse());
  }
  function beginBend(event: ReactPointerEvent<SVGElement>, route: DiagramRoute) {
    if (event.button !== 0 || !event.isPrimary) return;
    event.preventDefault(); event.stopPropagation();
    const point = pointerPosition(event);
    const original = baseLayout.modules.flatMap(module => module.routes).find(candidate => candidate.wire.id === route.wire.id);
    if (!point || !original) return;
    drag.current = { pointer: event.pointerId, owner: routeOwner, wireId: route.wire.id,
      startX: point.x, startY: point.y, offsetX: route.laneX - original.laneX, offsetY: route.boardY - original.boardY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function moveBend(event: ReactPointerEvent<SVGElement>) {
    const current = drag.current;
    if (!current || current.pointer !== event.pointerId || current.owner !== routeOwner) return;
    event.preventDefault(); event.stopPropagation();
    const point = pointerPosition(event);
    if (point) setBend(current.wireId, current.offsetX + point.x - current.startX, current.offsetY + point.y - current.startY);
  }
  function endBend(event: ReactPointerEvent<SVGElement>) {
    if (drag.current?.pointer !== event.pointerId) return;
    event.stopPropagation(); drag.current = undefined;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  const drawing = <svg className="circuit-schematic" viewBox={`0 0 ${CIRCUIT_WIDTH} ${layout.height}`} role="group" aria-label={tr("作品 2D 接線圖", "Project wiring diagram")}>
      <text x="20" y="24" className="circuit-column-title">{tr("控制板", "CONTROLLER")}</text>
      <text x="450" y="24" className="circuit-column-title">{tr("外部零件 · 外觀與接腳", "MODULES · BODY & PINS")}</text>
      <rect x="12" y="42" width="288" height={PI_PANEL_HEIGHT} rx="15" fill="#142c2b" stroke="#386c62" strokeWidth="1.5" />
      <text x="28" y="72" fill="#b7efdd" fontSize="23" fontWeight="650">Raspberry Pi 5</text>
      <text x="28" y="95" fill="#9abbae" fontSize="13">{tr("J8 · 40 支實體腳位 · 2 排 × 20", "J8 · 40 physical pins · 2 × 20")}</text>
      <g data-pi-header="J8" role="group" aria-label={tr("Pi 5 完整 40 支 GPIO 排針；內排奇數、外排偶數", "Pi 5 full 40-pin GPIO header; odd inner row, even outer row")}>
        <text x="108" y="132" textAnchor="end" fill="#9abbae" fontSize="12">{tr("內排 · 奇數", "INNER · ODD")}</text>
        <text x="216" y="132" fill="#9abbae" fontSize="12">{tr("外排 · 偶數", "OUTER · EVEN")}</text>
        <rect x="136" y={PI_HEADER_TOP - 14} width="56" height={PI_HEADER_BOTTOM - PI_HEADER_TOP + 28} rx="6" fill="#0c191d" stroke="#43625e" />
        {layout.boardPins.map(pin => {
          const active = focus?.boardPin === pin.id;
          const used = layout.modules.some(module => module.routes.some(route => route.boardPin.id === pin.id));
          const odd = pin.column === 0;
          return <g key={pin.id} data-pi-pin={pin.id} data-physical-pin={pin.number} data-pin-column={pin.column}
            className={`circuit-board-pin${active ? " active" : ""}`}>
            <title>{`Pin ${pin.number} · ${pin.label}`}</title>
            {active ? <rect x={odd ? 24 : 170} y={pin.y - 9} width="120" height="18" rx="4" fill="#284f50" /> : null}
            <text x={odd ? 108 : 216} y={pin.y + 4} textAnchor={odd ? "end" : "start"}
              fill={active ? "#ffffff" : used ? pin.color : "#a5bdb6"} fontSize="12" fontWeight={active ? "700" : "400"}>{pin.label}</text>
            <text x={odd ? 134 : 194} y={pin.y + 3.5} textAnchor={odd ? "end" : "start"}
              fill={active ? "#ffffff" : "#b7cdc7"} fontSize="10" fontWeight={active ? "700" : "500"}>{pin.number}</text>
            {pin.number === 1 ? <rect x={pin.x - 6} y={pin.y - 6} width="12" height="12" rx="1" fill={active ? pin.color : "#213938"} stroke={pin.color} />
              : <circle cx={pin.x} cy={pin.y} r="5.5" fill={active ? pin.color : "#213938"} stroke={pin.color} strokeOpacity={used || active ? 1 : .5} />}
            <circle cx={pin.x} cy={pin.y} r="2" fill={active ? "#ffffff" : used ? pin.color : "#0c191d"} />
          </g>;
        })}
        <text x="28" y={PI_HEADER_BOTTOM + 28} fill="#9abbae" fontSize="12">{tr("方形接點為 Pin 1 · 非等比例", "Square contact = Pin 1 · not to scale")}</text>
      </g>
      {layout.modules.map(module => {
        const guide = moduleGuide(module.id);
        const dim = Boolean(focus && focus.componentId !== module.id);
        return <g key={module.id} data-circuit-module={module.id} opacity={dim ? .42 : 1}>
          <rect x="432" y={module.top} width="394" height={module.height} rx="13" fill="#141f2e" stroke="#324157" />
          <text x="450" y={module.top + 28} fill="#eef5fc" fontSize="21" fontWeight="650">{shortNames[module.id]}</text>
          <text x="450" y={module.top + 49} fill="#aebdce" fontSize="14">{guide ? tx(guide.name).replace(shortNames[module.id], "").trim() : ""}</text>
          <CircuitModuleArt id={module.id} x={MODULE_X} y={module.bodyY} height={module.bodyHeight} />
          {module.routes.map(route => {
            const { wire, pin, boardPin, laneX, boardY } = route;
            const active = focus?.id === wire.id;
            const color = wireColor(wire);
            const divided = wire.connectionKind === "divider";
            // Escape between pin pairs, never across the neighbouring contact.
            const escapeY = boardPin.y + (boardPin.column === 0 ? -9 : 9);
            const lead = `M ${boardPin.x} ${boardPin.y} V ${escapeY} H ${laneX} V ${boardY}`;
            const path = divided
              ? `${lead} H 366 M 422 ${boardY} H ${pin.x} V ${pin.y}`
              : `${lead} H ${pin.x} V ${pin.y}`;
            const bendEvents = adjusting && !compactPreview ? {
              onPointerDown: (event: ReactPointerEvent<SVGElement>) => beginBend(event, route),
              onPointerMove: moveBend, onPointerUp: endBend, onPointerCancel: endBend,
              onLostPointerCapture: () => { drag.current = undefined; },
              onClick: (event: ReactMouseEvent<SVGElement>) => { event.preventDefault(); event.stopPropagation(); },
              style: { cursor: 'move', touchAction: 'none' },
            } : {};
            return <g key={wire.id} className={`circuit-connection${active ? " active" : ""}`} data-circuit-wire={wire.id}
              data-board-pin={boardPin.id} data-physical-pin={boardPin.number}
              opacity={focus && !active ? adjusting ? .65 : .32 : 1} role={compactPreview ? undefined : adjusting ? "group" : "button"} tabIndex={compactPreview || adjusting ? undefined : 0} aria-pressed={adjusting ? undefined : active}
              aria-label={`${shortNames[module.id]} ${wire.componentPin} — ${wire.boardLabel}`}
              onClick={compactPreview ? undefined : () => choose(module.id, pin)} onKeyDown={compactPreview ? undefined : e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(module.id, pin); } }}>
              <title>{`${tx(wire.instruction)} — ${tx(wire.hint)}`}</title>
              <rect className="circuit-pin-label" x={boardPin.x - 10} y={boardPin.y - 9} width="20" height="18" rx="4" fill="transparent" />
              <path d={path} fill="none" stroke="transparent" strokeWidth="16" {...bendEvents} />
              <path className="circuit-wire-path" d={path} fill="none" stroke={color} strokeWidth={active ? 3 : 2.3} strokeLinejoin="round" {...bendEvents} />
              <circle cx={boardPin.x} cy={boardPin.y} r={active ? 3.5 : 2.5} fill={color} />
              {divided ? <>
                <rect x="366" y={boardY - 9} width="56" height="18" rx="2" fill="#3b3220" stroke={color} />
                <text x="394" y={boardY + 5} textAnchor="middle" fill="#ffe1a2" fontSize="13">330Ω</text>
                {route.groundY !== undefined && route.groundX !== undefined ? <>
                  <path d={`M ${route.groundX} ${boardY} V ${route.groundY}`} stroke={color} strokeWidth={active ? 3 : 2} />
                  <rect x={route.groundX - 6} y={(boardY + route.groundY) / 2 - 9} width="12" height="18" fill="#3b3220" stroke={color} />
                  <text x={route.groundX - 13} y={(boardY + route.groundY) / 2 + 5} textAnchor="end" fill="#ffe1a2" fontSize="12">470Ω</text>
                  <circle cx={route.groundX} cy={route.groundY} r="4" fill={color} />
                  <circle cx={route.groundX} cy={boardY} r="4" fill={color} />
                </> : null}
              </> : null}
              {adjusting && !compactPreview ? <circle data-wire-bend={wire.id} cx={laneX} cy={boardY} r="8"
                fill={color} stroke="#0a111b" strokeWidth="2" role="button" tabIndex={0}
                aria-label={`${tr('調整走線', 'Adjust route')} · ${shortNames[module.id]} ${wire.componentPin} — ${wire.boardLabel}`}
                style={{ cursor: 'move', touchAction: 'none' }}
                onPointerDown={event => beginBend(event, route)} onPointerMove={moveBend} onPointerUp={endBend} onPointerCancel={endBend}
                onLostPointerCapture={() => { drag.current = undefined; }}
                onClick={event => { event.preventDefault(); event.stopPropagation(); }}
                onKeyDown={event => {
                  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home'].includes(event.key)) return;
                  event.preventDefault(); event.stopPropagation();
                  const original = baseLayout.modules.flatMap(item => item.routes).find(item => item.wire.id === wire.id)!;
                  const step = event.shiftKey ? 24 : 8;
                  setBend(wire.id, event.key === 'Home' ? 0 : laneX - original.laneX + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0),
                    event.key === 'Home' ? 0 : boardY - original.boardY + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0));
                }}><title>{tr('拖曳圓點調整路徑；方向鍵微調、Home 恢復此線。接腳不會改變。', 'Drag the bend to move its route. Arrow keys adjust; Home resets this wire. Endpoints stay fixed.')}</title></circle> : null}
            </g>;
          })}
          {module.pins.map(pin => {
            const active = focus ? focus.componentId === module.id && focus.componentPin === pin.id : selected?.componentId === module.id && selected.pinId === pin.id;
            const color = pin.wire ? wireColor(pin.wire) : pin.state === "pending" ? "#e2af61" : "#8190a1";
            const labelY = pin.y + (module.headerAtTop ? 33 : -19);
            return <g key={pin.id} className={`circuit-module-pin${active ? " active" : ""}`} data-module-pin={`${module.id}:${pin.id}`}
              role={compactPreview ? undefined : "button"} tabIndex={compactPreview ? undefined : 0} aria-pressed={active}
              aria-label={`${shortNames[module.id]} ${pin.id} · ${pin.wire ? pin.wire.boardLabel : pin.state === "pending" ? tr("待確認，勿接", "Pending, do not connect") : tr("未使用", "Not used")}`}
              onClick={compactPreview ? undefined : () => choose(module.id, pin)} onKeyDown={compactPreview ? undefined : e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(module.id, pin); } }}>
              <rect className="circuit-pin-hit" x={pin.x - 20} y={Math.min(pin.y - 10, labelY - 16)} width="40" height="51" rx="5" fill={active ? "#305265" : "transparent"} />
              <rect x={pin.x - 5} y={pin.y - 10} width="10" height="20" rx="2" fill={pin.wire ? "#dfc084" : "#182632"} stroke={color} strokeWidth={active ? 3 : 1.5} />
              <circle cx={pin.x} cy={pin.y} r={active ? 6 : 3} fill={color} />
              <text x={pin.x} y={labelY} textAnchor="middle" fill={color} fontSize="13" fontWeight="650">{pin.id}</text>
              {!pin.wire ? <text x={pin.x} y={pin.y + (module.headerAtTop ? -18 : 30)} textAnchor="middle" fill={color} fontSize="11">{pin.state === "pending" ? "!" : "NC"}</text> : null}
            </g>;
          })}
          <text x="450" y={module.top + module.height - 13} fill="#8e9fb2" fontSize="12">{module.headerAtTop ? tr("正面朝上 · 排針在上方", "Front view · header at top") : tr("元件面朝上 · 排針在下方", "Component side up · header at bottom")}</text>
        </g>;
      })}
    </svg>;
  if (compactPreview) return <div className="ai-diagram-preview-image" aria-hidden="true">{drawing}</div>;

  const moduleTabs = <div className="circuit-module-tabs" role="group" aria-label={tr("篩選接線模組", "Filter wiring modules")}>
      <button className={!filter ? "active" : ""} disabled={Boolean(activeWire)} onClick={() => { setModuleFilter(undefined); setSelected(undefined); onClearSelection?.(); }}>{tr("全部零件", "All modules")}</button>
      {design.component_ids.map(id => <button key={id} className={filter === id ? "active" : ""} disabled={Boolean(activeWire)} onClick={() => { setModuleFilter(id); setSelected(undefined); onClearSelection?.(); }}>{shortNames[id]}</button>)}
    </div>;
  const expandButton = <button type="button" className="maker-expand" onClick={() => { setExpandedOpen(true); expanded.current?.showModal(); }}>{tr("放大接線圖 ↗", "Expand diagram ↗")}</button>;
  const routingTools = <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
    <button type="button" aria-pressed={adjusting} title={tr('只調整示意圖路徑，不修改接腳或接線進度', 'Change diagram routes only, not pins or wiring progress')}
      onClick={() => { drag.current = undefined; setAdjusting(value => !value); }}>
      <span aria-hidden="true">↝ </span>{adjusting ? tr('完成調整', 'Done adjusting') : tr('調整線路', 'Adjust routes')}</button>
    {adjusting ? <button type="button" disabled={!Object.keys(offsets).length}
      title={tr('恢復所有線路的預設位置', 'Restore default positions for all routes')}
      aria-label={tr('恢復預設走線', 'Reset routes')}
      onClick={() => { drag.current = undefined; setBends({ owner: routeOwner, offsets: {} }); }}>↺</button> : null}
  </span>;
  const notes = (onlyCurrent = false) => <>
    <div className="circuit-legend"><span><i className="signal" />{tr("訊號", "Signal")}</span><span><i className="power" />{tr("電源", "Power")}</span><span><i className="ground" />GND</span>{design.wiring.some(w => w.connectionKind === "divider") && <span><i className="divider" />{tr("分壓保護", "Divider")}</span>}<span>NC · {tr("未使用", "Unused")}</span><span>! · {tr("待確認，勿接", "Pending")}</span></div>
    {onlyCurrent && focus ? <p>{tx(focus.instruction)} {tx(focus.hint)}</p> : null}
    <small>{tr("外觀為辨識示意；腳位依既有 Profile 排列並拉開間距，非等比例。實際接線以模組絲印核對；線路不代表導通驗證。", "Illustrative bodies; pin order follows existing profiles, with spacing expanded. Check the actual silkscreen. Lines do not verify continuity.")}</small>
    {design.component_ids.filter(id => !onlyCurrent || !filter || id === filter).map(id => { const guide = moduleGuide(id); return guide ? <p key={id} className="maker-warning">{tx(guide.safety)}</p> : null; })}
    {design.unresolved.length ? <p className="maker-warning">{design.unresolved.join("\n")}</p> : null}
  </>;
  const diagram = (fill = false) => <>
    {!fill ? moduleTabs : null}
    <div className={`circuit-inspector${fill && viewControls ? ' image-workspace-heading' : ''}`}>
      {fill ? viewControls : null}
      <div className="circuit-inspector-content" aria-live="polite">
      {fill && focus ? <><small>{focusLabel ?? tr("目前這一步", "Current step")}</small><h2>{focus.componentPin} <span aria-hidden="true">→</span> {focus.boardLabel}</h2>
        {focus.connectionKind === "divider" ? <span className="maker-warning">{tr("ECHO 需分壓，不可直連 GPIO", "ECHO needs a divider, not a direct GPIO wire")}</span> : null}</>
        : focus ? <><strong>{shortNames[focus.componentId]} · {focus.componentPin} <span>→</span> Pi {focus.boardLabel}</strong><span>{tx(focus.instruction)} {focus.connectionKind === "divider" ? tr("不可直接接線。", "Never connect directly.") : ""}</span></>
        : selectedModule && selected ? <><strong>{shortNames[selected.componentId]} · {selected.pinId}</strong><span>{pending ? tx(pending.reason) : tr("此作品未使用此腳位，不需要接線。", "Not used in this project. Leave unconnected.")}</span></>
        : <><strong>{tr("認零件 → 找接腳 → 沿線接到 Pi", "Identify module → find pin → follow the wire")}</strong><span>{tr("點選模組接腳或線路，查看兩端腳位與接法。", "Select a module pin or wire to inspect both endpoints.")}</span></>}
      </div>
    </div>
    {adjusting ? <small role="status" style={{ padding: '5px 10px', color: 'var(--text-dim)', fontSize: 11 }}>
      {tr('拖曳線段或轉折圓點，把路徑拉開；兩端接腳固定。', 'Drag a wire or its bend to separate routes; both endpoints stay fixed.')}</small> : null}
    <CircuitViewport key={`${design.component_ids.join(":")}:${filter ?? "all"}`} width={CIRCUIT_WIDTH} height={layout.height}
      preferredScale={readableDefault ? 0.65 : undefined} fitToViewport={fill && !readableDefault}
      toolbarStart={fill ? activeWire ? <span className="circuit-step-module" aria-label={tr("本步零件", "Current module")}>{shortNames[activeWire.componentId]}</span> : moduleTabs : undefined}
      toolbarEnd={fill ? <>{routingTools}{expandButton}</> : undefined}>
    {drawing}
    </CircuitViewport>
    {fill ? hideWorkspaceNotes ? null : <details className="circuit-workspace-notes"><summary>{tr("接線提醒 · 示意圖不代表導通驗證", "Wiring notes · diagram does not verify continuity")}</summary><div>{notes(true)}</div></details> : notes()}
  </>;
  return <div className={`maker-circuit${workspace ? " circuit-workspace" : ""}`}>
    {!workspace ? <>{routingTools}{expandButton}</> : null}
    {diagram(workspace)}
    <dialog className="maker-diagram-dialog" ref={expanded} onClose={() => setExpandedOpen(false)} aria-label={tr("放大接線圖", "Expanded wiring diagram")}>
      <button type="button" className="maker-expand" onClick={() => expanded.current?.close()}>{tr("關閉", "Close")}</button>{expandedOpen ? <>{routingTools}{diagram()}</> : null}
    </dialog>
  </div>;
}
