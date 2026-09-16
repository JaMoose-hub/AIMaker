import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { structuralParts, type ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { guideFor } from "../lib/componentWiringGuides";
import { CircuitDiagram } from "./CircuitDiagram";
import { MakerSplitLayout } from "./MakerSplitLayout";

export function BlueprintPage({ design, onGuide, onEdit, hasCandidate, generating }: {
  design: ProjectDesign; onGuide: () => void; onEdit: () => void;
  hasCandidate: boolean; generating: boolean;
}) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const id = useId();
  const [tab, setTab] = useState<"materials" | "steps">("materials");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [product, setProduct] = useState<string | null>(null);
  const structure = design.assembly?.parts.map(p => ({ ...structuralParts[p.kind], id: `structure-${p.kind}`, quantity: p.quantity, purpose: p.purpose })) ?? [];
  const material = [...design.bom, ...structure].find(item => item.id === product);
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
  const cards = (items: typeof design.bom) => <div className="maker-bom">{items.map(item => <article key={item.id}>
    <strong>{item.name}</strong><small>{item.purpose}</small><div>× {item.quantity} · NT$ {item.price * item.quantity}</div>
    <button onClick={() => setProduct(item.id)}>{tr("示範導購 ↗", "Demo shop ↗")}</button>
  </article>)}</div>;

  return <MakerSplitLayout stage="blueprint" left={
    <section className="maker-preview maker-blueprint-page" aria-label={tr("作品 Blueprint", "Project Blueprint")}>
      <div className="maker-eyebrow">02 / BLUEPRINT · v{design.revision}</div>
      <div className="maker-preview-heading"><div><h2>{design.title}</h2><p className="maker-muted">{tr("零件與 2D 接線總覽", "Modules & 2D wiring")}</p></div>
        <div className="blueprint-actions"><button onClick={onEdit}>{tr("← 返回設計修改", "← Edit design")}</button>
          <button className="maker-primary" onClick={onGuide}>{tr("開始 Pin 接線引導 →", "Start Pin wiring →")}</button></div>
      </div>
      {generating ? <p className="maker-muted" role="status">{tr("AI 仍在背景處理，這裡保留已確認的藍圖。", "AI is working in the background. This remains the confirmed blueprint.")}</p> : null}
      {hasCandidate ? <button className="maker-candidate-notice" onClick={onEdit}>{tr("有新版作品待確認 → 返回設計查看", "New revision ready → Review in Design")}</button> : null}
      <CircuitDiagram design={design} selectedId={selectedId} onClearSelection={() => setSelectedId(null)}
        onSelect={wire => { setSelectedId(wire.id); setTab("steps"); }} />
    </section>
  }>
    <aside className="maker-preview maker-blueprint-sidebar" aria-label={tr("製作資料", "Build information")}>
      <div className="blueprint-tabs" role="tablist" aria-label={tr("Blueprint 製作資料", "Blueprint build information")} ref={tabs}>
        {(["materials", "steps"] as const).map(value => <button key={value} id={`${id}-${value}-tab`} data-tab={value}
          role="tab" aria-selected={tab === value} aria-controls={`${id}-${value}-panel`} tabIndex={tab === value ? 0 : -1}
          onClick={() => setTab(value)} onKeyDown={switchTab}>{value === "materials" ? tr("材料與導購", "Parts & shopping") : tr("製作步驟", "Build steps")}</button>)}
      </div>
      <div role="tabpanel" id={`${id}-materials-panel`} aria-labelledby={`${id}-materials-tab`} hidden={tab !== "materials"} tabIndex={0}>
        <p className="maker-muted">{tr("價格與商品頁均為示範。", "Prices and product pages are illustrative.")}</p>
        {cards(design.bom)}
        {structure.length ? <><h3>{tr("結構配件 · 組裝示意", "Structural accessories · illustrative")}</h3>
          <p className="maker-muted">{design.assembly?.description}</p>
          <p className="maker-muted">{tr("尺寸與固定方式需實物確認。", "Check actual dimensions and mounting.")}</p>{cards(structure)}</> : null}
      </div>
      <div role="tabpanel" id={`${id}-steps-panel`} aria-labelledby={`${id}-steps-tab`} hidden={tab !== "steps"} tabIndex={0}>
        <ol className="blueprint-instructions">{design.instructions.map((line, i) => <li key={i}>{line}</li>)}</ol>
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
      <dialog ref={dialog} className="maker-product" onCancel={() => setProduct(null)} aria-label={tr("示範商品頁", "Demo product page")}>{material ? <>
        <span className="maker-badge">DEMO SHOP</span><h2>{material.name}</h2><p>{material.purpose}</p><h3>NT$ {material.price}</h3>
        <p>{tr("沒有真實賣家、庫存或付款功能。", "No real seller, stock or checkout.")}</p><button autoFocus onClick={() => setProduct(null)}>{tr("返回 Blueprint", "Back to Blueprint")}</button>
      </> : null}</dialog>
    </aside>
  </MakerSplitLayout>;
}
