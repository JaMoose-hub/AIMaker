import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { makerCatalog, structuralParts, type ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { systemText } from "../lib/systemText";
import { MATERIAL_USD_REFERENCE, materialUsdEstimate } from "../lib/materialPricing";
import { guideFor } from "../lib/componentWiringGuides";
import { CircuitDiagram } from "./CircuitDiagram";
import { MakerSplitLayout } from "./MakerSplitLayout";
import { DesignViewSwitch, type DesignView } from "./DesignViewSwitch";

export function BlueprintPage({ design, onGuide, onEdit, onViewChange, hasCandidate, generating }: {
  design: ProjectDesign; onGuide: () => void; onEdit: () => void; onViewChange: (view: DesignView) => void;
  hasCandidate: boolean; generating: boolean;
}) {
  const tr = useMakerText();
  const { tx, locale } = useI18n();
  const projectText = (text: string) => design.source === "demo" ? systemText(text, locale) : text;
  const id = useId();
  const [tab, setTab] = useState<"materials" | "steps">("materials");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [product, setProduct] = useState<string | null>(null);
  const structure = design.assembly?.parts.map(p => ({ ...structuralParts[p.kind], id: `structure-${p.kind}`, quantity: p.quantity, purpose: p.purpose })) ?? [];
  const materials = [...design.bom, ...structure].map(item => ({...item,
    name: makerCatalog.modules.some(module => module.id === item.id) ? tx(makerCatalog.modules.find(module => module.id === item.id)!.name) : systemText(item.name, locale),
    purpose: systemText(item.purpose, locale)}));
  const material = materials.find(item => item.id === product);
  const estimate = (price: number, quantity: number) => materialUsdEstimate(price, quantity) ?? tr("待估價", "Not estimated");
  const dialog = useRef<HTMLDialogElement>(null);
  const tabs = useRef<HTMLDivElement>(null);
  const wireSteps = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (material && element && !element.open) element.showModal();
    return () => element?.close();
  }, [product, design.id, design.revision]);
  useEffect(() => {
    if (tab !== "steps" || !selectedId) return;
    Array.from(wireSteps.current?.querySelectorAll("button") ?? [])
      .find(element => element.dataset.blueprintWire === selectedId)?.scrollIntoView({ block: "nearest" });
  }, [selectedId, tab]);
  function switchTab(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "materials" : event.key === "End" ? "steps" : tab === "materials" ? "steps" : "materials";
    setTab(next);
    tabs.current?.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus();
  }
  const cards = (items: typeof design.bom) => <div className="maker-bom">{items.map(original => { const item = materials.find(material => material.id === original.id)!; return <article key={item.id}>
    <strong>{item.name}</strong><small>{item.purpose}</small>
    <div className="maker-material-footer"><span className="maker-material-price">× {item.quantity} · {tr("預估小計", "Est. subtotal")} <strong>{estimate(item.price, item.quantity)}</strong></span>
      <button aria-haspopup="dialog" aria-controls={`${id}-partner-dialog`} aria-label={`${tr("合作招商中", "Partner opportunities")} · ${item.name}`}
        onClick={() => setProduct(item.id)}>{tr("合作招商中", "Partner opportunities")} <span aria-hidden="true">→</span></button>
    </div>
  </article>; })}</div>;

  return <MakerSplitLayout stage="blueprint" left={
    <section className="maker-preview maker-blueprint-page" aria-label={tr("作品 Blueprint", "Project Blueprint")}>
      <div className="maker-view-heading"><span className="maker-eyebrow">01 / BLUEPRINT · v{design.revision}</span>
        <DesignViewSwitch view="blueprint" hasBlueprint onChange={onViewChange} /></div>
      <div className="maker-preview-heading"><div><h2>{projectText(design.title)}</h2><p className="maker-muted">{tr("零件與 2D 接線總覽", "Modules & 2D wiring")}</p></div>
        <div className="blueprint-actions"><button className="maker-primary" onClick={onGuide}>{tr("開始 Pin 接線引導 →", "Start Pin wiring →")}</button></div>
      </div>
      {generating ? <p className="maker-muted" role="status">{tr("AI 仍在背景處理，這裡保留已確認的藍圖。", "AI is working in the background. This remains the confirmed blueprint.")}</p> : null}
      {hasCandidate ? <button className="maker-candidate-notice" onClick={onEdit}>{tr("有新版作品待確認 → 返回設計查看", "New revision ready → Review in Design")}</button> : null}
      <CircuitDiagram design={design} readableDefault selectedId={selectedId} onClearSelection={() => setSelectedId(null)}
        onSelect={wire => { setSelectedId(wire.id); setTab("steps"); }} />
    </section>
  }>
    <aside className="maker-preview maker-blueprint-sidebar" aria-label={tr("製作資料", "Build information")}>
      <div className="blueprint-tabs" role="tablist" aria-label={tr("Blueprint 製作資料", "Blueprint build information")} ref={tabs}>
        {(["materials", "steps"] as const).map(value => <button key={value} id={`${id}-${value}-tab`} data-tab={value}
          role="tab" aria-selected={tab === value} aria-controls={`${id}-${value}-panel`} tabIndex={tab === value ? 0 : -1}
          onClick={() => setTab(value)} onKeyDown={switchTab}>{value === "materials" ? tr("材料與合作", "Parts & partners") : tr("製作步驟", "Build steps")}</button>)}
      </div>
      <div role="tabpanel" id={`${id}-materials-panel`} aria-labelledby={`${id}-materials-tab`} hidden={tab !== "materials"} tabIndex={0}>
        <div className="maker-material-notice">
          <p>{tr("美元預估參考 · 合作商家招募中，尚未開放購買。", "USD estimates · Seeking partners; purchasing is not available yet.")}</p>
          <details><summary>{tr("估算方式", "How estimates work")}</summary>
            <p>{tr("依原有新台幣示範價格換算，非即時售價；不含運費與稅。小計已含所需數量。", "Converted from illustrative TWD prices, not live retail quotes. Excludes shipping and taxes. Subtotals include the required quantities.")}</p>
            <p>US$1 = NT${MATERIAL_USD_REFERENCE.twdPerUsd} · {MATERIAL_USD_REFERENCE.date} · <a href={MATERIAL_USD_REFERENCE.source} target="_blank" rel="noreferrer">{tr("央行參考匯率 ↗", "CBC reference rate ↗")}</a></p>
          </details>
        </div>
        {cards(design.bom)}
        {structure.length ? <><h3>{tr("結構配件 · 組裝示意", "Structural accessories · illustrative")}</h3>
          <p className="maker-muted">{design.assembly?.description}</p>
          <p className="maker-muted">{tr("尺寸與固定方式需實物確認。", "Check actual dimensions and mounting.")}</p>{cards(structure)}</> : null}
      </div>
      <div role="tabpanel" id={`${id}-steps-panel`} aria-labelledby={`${id}-steps-tab`} hidden={tab !== "steps"} tabIndex={0}>
        <ol className="blueprint-instructions">{design.instructions.map((line, i) => <li key={i}>{projectText(line)}</li>)}</ol>
        <h3>{tr("逐線接法", "Wire-by-wire reference")}</h3>
        <p className="maker-muted">{tr("點選查看對應線路；不會標記接線完成。", "Select to highlight a wire; this does not confirm wiring.")}</p>
        <ol className="blueprint-wire-steps" ref={wireSteps}>{design.wiring.map((wire, i) => <li key={wire.id}>
          <button className={selectedId === wire.id ? "active" : ""} aria-pressed={selectedId === wire.id}
            data-blueprint-wire={wire.id} onClick={() => setSelectedId(wire.id)}>
            <span className="blueprint-step-number">{String(i + 1).padStart(2, "0")}</span>
            <span><strong>{tx(guideFor(wire.componentId).name)} · {wire.componentPin}</strong><span>{tx(wire.instruction)}</span>
              {wire.connectionKind === "divider" ? <small className="maker-warning">{tr("需分壓，禁止直連 GPIO", "Voltage divider required; never connect directly to GPIO")}</small> : null}</span>
          </button>
        </li>)}</ol>
        {design.unresolved.length ? <div className="maker-warning">{design.unresolved.map((line, i) => <p key={i}>{line}</p>)}</div> : null}
      </div>
      <dialog ref={dialog} id={`${id}-partner-dialog`} className="maker-product maker-partnership" onCancel={() => setProduct(null)}
        aria-labelledby={`${id}-partner-title`} aria-describedby={`${id}-partner-status`}>{material ? <>
        <header className="maker-partnership-heading"><span className="maker-badge">{tr("合作招商中", "PARTNER OPPORTUNITIES")}</span>
          <button type="button" autoFocus onClick={() => setProduct(null)} aria-label={tr("關閉合作說明", "Close partner information")}>×</button></header>
        <h2 id={`${id}-partner-title`}>{tr("一起把好點子，變成做得出來的作品。", "Help makers turn ideas into real projects.")}</h2>
        <p>{tr("歡迎電子零件供應商、Maker 材料品牌與教育夥伴，一起提供從零件到完整套件的選擇。", "We welcome electronics suppliers, maker brands and education partners to explore component and complete-kit offerings.")}</p>
        <div className="maker-partnership-material"><strong>{material.name}</strong><small>{material.purpose}</small>
          <span>× {material.quantity} · {tr("預估小計", "Est. subtotal")} <strong>{estimate(material.price, material.quantity)}</strong></span></div>
        <h3>{tr("開放合作方向", "Partnership opportunities")}</h3>
        <ul className="maker-partnership-options">
          <li><strong>{tr("零件供應", "Component supply")}</strong><span>{tr("提供適合作品的電子零件與結構配件。", "Electronic components and structural parts for maker projects.")}</span></li>
          <li><strong>{tr("作品材料包", "Project kits")}</strong><span>{tr("依材料清單搭配完整套件，減少備料時間。", "Complete kits matched to the parts list, with less sourcing work.")}</span></li>
          <li><strong>{tr("教育合作", "Education")}</strong><span>{tr("為課程、工作坊與 Maker 空間規劃材料套件。", "Material kits for courses, workshops and makerspaces.")}</span></li>
        </ul>
        <p id={`${id}-partner-status`} className="maker-partnership-status">{tr("此處為合作招募說明，尚未串接商家、庫存或付款。價格僅為美元估算，非報價，亦不含運費與稅。", "This is a partnership invitation. No sellers, inventory or checkout are connected. USD estimates are not offers and exclude shipping and taxes.")}</p>
        <footer><button type="button" onClick={() => setProduct(null)}>{tr("返回材料清單", "Back to parts")}</button></footer>
      </> : null}</dialog>
    </aside>
  </MakerSplitLayout>;
}
