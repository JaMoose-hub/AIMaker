import { useRef, useState, type ReactNode } from "react";
import type { ProjectDesign, ProjectWire } from "../lib/maker";
import { guideFor, type GuidedComponentId } from "../lib/componentWiringGuides";
import { circuitLayout, circuitSelection, wireColor, CIRCUIT_WIDTH, PI_TERMINAL_X, MODULE_X, type DiagramPin, type FrozenCircuitProfile } from "../lib/circuitLayout";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { CircuitModuleArt } from "./CircuitModuleArt";
import { CircuitViewport } from "./CircuitViewport";

const shortNames: Record<GuidedComponentId, string> = { "hc-sr04": "HC-SR04+", "mrd-tf240-8p-cs": "MRD-TFT240" };

export function CircuitDiagram({ design, activeId, onSelect, selectedId, onClearSelection, readableDefault = false, frozenProfile, compactPreview = false, workspace = false, focusLabel, viewControls }: {
  design: ProjectDesign; activeId?: string; onSelect?: (wire: ProjectWire) => void;
  selectedId?: string | null; onClearSelection?: () => void; readableDefault?: boolean; frozenProfile?: FrozenCircuitProfile; compactPreview?: boolean; workspace?: boolean; focusLabel?: string; viewControls?: ReactNode;
}) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const [selected, setSelected] = useState<{ componentId: GuidedComponentId; pinId: string }>();
  const [moduleFilter, setModuleFilter] = useState<GuidedComponentId>();
  const expanded = useRef<HTMLDialogElement>(null);
  const [expandedOpen, setExpandedOpen] = useState(false);
  const { activeWire, focus, filter } = circuitSelection(design, { activeId, selectedId, selected, moduleFilter });
  const layout = circuitLayout(design, filter, frozenProfile);
  const moduleGuide = (id: GuidedComponentId) => frozenProfile ? frozenProfile.modules.find(module => module.id === id) : guideFor(id);
  const selectedModule = selected && design.component_ids.includes(selected.componentId) ? moduleGuide(selected.componentId) : undefined;
  const pending = selectedModule?.unresolved.find(p => p.pin === selected?.pinId);
  function choose(componentId: GuidedComponentId, pin: DiagramPin) {
    setSelected({ componentId, pinId: pin.id });
    if (pin.wire) onSelect?.(pin.wire);
    else onClearSelection?.();
  }

  const drawing = <svg className="circuit-schematic" viewBox={`0 0 ${CIRCUIT_WIDTH} ${layout.height}`} role="group" aria-label={tr("作品 2D 接線圖", "Project wiring diagram")}>
      <text x="20" y="24" className="circuit-column-title">{tr("控制板", "CONTROLLER")}</text>
      <text x="450" y="24" className="circuit-column-title">{tr("外部零件 · 外觀與接腳", "MODULES · BODY & PINS")}</text>
      <rect x="12" y="42" width="240" height={layout.height - 56} rx="15" fill="#142c2b" stroke="#386c62" strokeWidth="1.5" />
      <text x="28" y="72" fill="#b7efdd" fontSize="23" fontWeight="650">Raspberry Pi 5</text>
      <text x="28" y="95" fill="#9abbae" fontSize="13">{tr("GPIO 接點展開 · 標示實體腳號", "GPIO breakout · physical pin numbers")}</text>
      {layout.modules.map(module => {
        const guide = moduleGuide(module.id);
        const dim = Boolean(focus && focus.componentId !== module.id);
        return <g key={module.id} data-circuit-module={module.id} opacity={dim ? .42 : 1}>
          <rect x="432" y={module.top} width="394" height={module.height} rx="13" fill="#141f2e" stroke="#324157" />
          <text x="450" y={module.top + 28} fill="#eef5fc" fontSize="21" fontWeight="650">{shortNames[module.id]}</text>
          <text x="450" y={module.top + 49} fill="#aebdce" fontSize="14">{guide ? tx(guide.name).replace(shortNames[module.id], "").trim() : ""}</text>
          <CircuitModuleArt id={module.id} x={MODULE_X} y={module.bodyY} height={module.bodyHeight} />
          <text x="28" y={module.top + (module.headerAtTop ? 27 : 144)} fill="#9bbdaf" fontSize="13">{shortNames[module.id]}</text>
          {module.routes.map(route => {
            const { wire, pin, boardY } = route;
            const active = focus?.id === wire.id;
            const color = wireColor(wire);
            const divided = wire.connectionKind === "divider";
            const path = divided
              ? `M ${PI_TERMINAL_X} ${boardY} H 366 M 422 ${boardY} H ${pin.x} V ${pin.y}`
              : `M ${PI_TERMINAL_X} ${boardY} H ${pin.x} V ${pin.y}`;
            return <g key={wire.id} className={`circuit-connection${active ? " active" : ""}`} data-circuit-wire={wire.id}
              opacity={focus && !active ? .32 : 1} role={compactPreview ? undefined : "button"} tabIndex={compactPreview ? undefined : 0} aria-pressed={active}
              aria-label={`${shortNames[module.id]} ${wire.componentPin} — ${wire.boardLabel}`}
              onClick={compactPreview ? undefined : () => choose(module.id, pin)} onKeyDown={compactPreview ? undefined : e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(module.id, pin); } }}>
              <title>{`${tx(wire.instruction)} — ${tx(wire.hint)}`}</title>
              <rect className="circuit-pin-label" x="22" y={boardY - 15} width="223" height="29" rx="5" fill={active ? "#284f50" : "#173534"} />
              <text x="30" y={boardY + 5} fill="#e3efec" fontSize="16">{wire.boardLabel}</text>
              <path d={path} fill="none" stroke="transparent" strokeWidth="16" />
              <path d={path} fill="none" stroke={color} strokeWidth={active ? 4 : 2.3} strokeLinejoin="round" />
              <circle cx={PI_TERMINAL_X} cy={boardY} r={active ? 6 : 4} fill={color} />
              {divided ? <>
                <rect x="366" y={boardY - 9} width="56" height="18" rx="2" fill="#3b3220" stroke={color} />
                <text x="394" y={boardY + 5} textAnchor="middle" fill="#ffe1a2" fontSize="13">330Ω</text>
                {route.groundY !== undefined ? <>
                  <path d={`M 318 ${boardY} V ${route.groundY}`} stroke={color} strokeWidth={active ? 3 : 2} />
                  <rect x="312" y={(boardY + route.groundY) / 2 - 9} width="12" height="18" fill="#3b3220" stroke={color} />
                  <text x="305" y={(boardY + route.groundY) / 2 + 5} textAnchor="end" fill="#ffe1a2" fontSize="12">470Ω</text>
                  <circle cx="318" cy={route.groundY} r="4" fill={color} />
                  <circle cx="318" cy={boardY} r="4" fill={color} />
                </> : null}
              </> : null}
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
    <CircuitViewport key={`${design.component_ids.join(":")}:${filter ?? "all"}`} width={CIRCUIT_WIDTH} height={layout.height}
      preferredScale={readableDefault ? 0.65 : undefined} fitToViewport={fill}
      toolbarStart={fill ? activeWire ? <span className="circuit-step-module" aria-label={tr("本步零件", "Current module")}>{shortNames[activeWire.componentId]}</span> : moduleTabs : undefined}
      toolbarEnd={fill ? expandButton : undefined}>
    {drawing}
    </CircuitViewport>
    {fill ? <details className="circuit-workspace-notes"><summary>{tr("接線提醒 · 示意圖不代表導通驗證", "Wiring notes · diagram does not verify continuity")}</summary><div>{notes(true)}</div></details> : notes()}
  </>;
  return <div className={`maker-circuit${workspace ? " circuit-workspace" : ""}`}>
    {!workspace ? expandButton : null}
    {diagram(workspace)}
    <dialog className="maker-diagram-dialog" ref={expanded} onClose={() => setExpandedOpen(false)} aria-label={tr("放大接線圖", "Expanded wiring diagram")}>
      <button type="button" className="maker-expand" onClick={() => expanded.current?.close()}>{tr("關閉", "Close")}</button>{expandedOpen ? diagram() : null}
    </dialog>
  </div>;
}
