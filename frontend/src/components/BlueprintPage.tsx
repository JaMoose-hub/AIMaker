import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { makerCatalog, structuralParts, type ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { systemText } from "../lib/systemText";
import { conciseMaterialName, materialPurchaseLink } from "../lib/blueprintResources";
import { guideFor } from "../lib/componentWiringGuides";
import { CircuitDiagram } from "./CircuitDiagram";
import { DesignViewSwitch, type DesignView } from "./DesignViewSwitch";
import { HardwarePartsCheck } from "./HardwarePartsCheck";
import { AssemblyGuide } from "./AssemblyGuide";
import './BlueprintPage.css';

const blueprintTabs = ['overview', 'parts-check', 'materials', 'steps'] as const;
type BlueprintTab = typeof blueprintTabs[number];

export function BlueprintPage({ design, onGuide, onEdit, onViewChange, hasCandidate, generating, onCheckParts, partsCheckDisabledReason, partsPhotoLabel, partsPhotoKey, onOpenAI }: {
  design: ProjectDesign; onGuide: () => void; onEdit: () => void; onViewChange: (view: DesignView) => void;
  hasCandidate: boolean; generating: boolean;
  onCheckParts?: (prompt: string, includePhoto: boolean) => Promise<boolean>;
  partsCheckDisabledReason?: string; partsPhotoLabel?: string; partsPhotoKey?: string; onOpenAI?: () => void;
}) {
  const tr = useMakerText();
  const { tx, locale } = useI18n();
  const projectText = (text: string) => design.source === "demo" ? systemText(text, locale) : text;
  const id = useId();
  const [tab, setTab] = useState<BlueprintTab>('overview');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const structure = design.assembly?.parts.map(p => ({ ...structuralParts[p.kind], id: `structure-${p.kind}`, quantity: p.quantity, purpose: p.purpose })) ?? [];
  const materials = [...design.bom, ...structure].map(item => ({...item,
    name: conciseMaterialName(makerCatalog.modules.some(module => module.id === item.id) ? tx(makerCatalog.modules.find(module => module.id === item.id)!.name) : systemText(item.name, locale), locale),
    purpose: systemText(item.purpose, locale)}));
  const tabs = useRef<HTMLDivElement>(null);
  const wireSteps = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (tab !== "steps" || !selectedId) return;
    Array.from(wireSteps.current?.querySelectorAll("button") ?? [])
      .find(element => element.dataset.blueprintWire === selectedId)?.scrollIntoView({ block: "nearest" });
  }, [selectedId, tab]);
  function switchTab(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? blueprintTabs[0] : event.key === 'End' ? blueprintTabs.at(-1)!
      : blueprintTabs[(blueprintTabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : -1) + blueprintTabs.length) % blueprintTabs.length];
    setTab(next);
    tabs.current?.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus();
  }
  const cards = (items: typeof design.bom) => <div className="blueprint-shop-grid">{items.map(original => { const item = materials.find(material => material.id === original.id)!;
    const link = materialPurchaseLink(item);
    return <article key={item.id} className="blueprint-shop-card">
    <span className="blueprint-shop-quantity">× {item.quantity}</span><strong>{item.name}</strong>
    <small>{item.id === 'hc-sr04' ? tr('核對供電與 ECHO 3.3V 相容性', 'Check supply and 3.3V ECHO compatibility')
      : item.id === 'mrd-tf240-8p-cs' ? 'ILI9341 · 8 pin · 240×320' : conciseMaterialName(item.purpose, locale)}</small>
    <div className="blueprint-shop-footer"><span>{link.official ? tr('官方購買入口', 'Official purchase entry') : tr('商品搜尋', 'Product search')}</span>
      <a href={link.url} target="_blank" rel="noopener noreferrer" aria-label={`${tr('查找', 'Find')} ${item.name}`}>{tr('找同款', 'Find this part')} <span aria-hidden="true">↗</span></a>
    </div>
  </article>; })}</div>;

  const tabNames = { overview: tr('接線總覽', 'Wiring overview'), 'parts-check': tr('零件核對', 'Check hardware'),
    materials: tr('購買材料', 'Find parts'), steps: tr('組裝引導', 'Assembly guide') };
  return <div className="assistant-blueprint blueprint-workspace">
    <section className="maker-preview maker-blueprint-page" aria-label={tr("作品 Blueprint", "Project Blueprint")}>
      <div className="maker-view-heading"><span className="maker-eyebrow">01 / BLUEPRINT · v{design.revision}</span>
        <DesignViewSwitch view="blueprint" hasBlueprint onChange={onViewChange} /></div>
      <div className="maker-preview-heading"><div className="blueprint-title"><h2>{projectText(design.title)}</h2>
        <div className="blueprint-title-meta">
          <p className="maker-muted">{tr("零件與 2D 接線總覽", "Modules & 2D wiring")}</p>
          {generating ? <span className="blueprint-background-status" role="status" title={tr("AI 仍在背景處理，這裡保留已確認的藍圖。", "AI is working in the background. This remains the confirmed blueprint.")}>{tr("AI 處理中 · 保留已確認藍圖", "AI working · Confirmed blueprint retained")}</span> : null}
          {hasCandidate ? <button type="button" className="maker-candidate-notice blueprint-revision-link" onClick={onEdit}
            aria-label={tr("有新版作品待確認 → 返回設計查看", "New revision ready → Review in Design")}>{tr("新版待確認", "New revision ready")} <span aria-hidden="true">↗</span></button> : null}
        </div>
      </div>
        <div className="blueprint-actions"><button type="button" className="blueprint-check-shortcut" onClick={() => setTab('parts-check')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m5 12 4 4L19 6" /><rect x="2" y="2" width="20" height="20" rx="6" /></svg>{tr('核對零件', 'Check parts')}</button>
          <button className="maker-primary" onClick={onGuide}>{tr("開始 Pin 接線引導 →", "Start Pin wiring →")}</button></div>
      </div>
      <div className="blueprint-tabs" role="tablist" aria-label={tr("Blueprint 製作資料", "Blueprint build information")} ref={tabs}>
        {blueprintTabs.map(value => <button key={value} id={`${id}-${value}-tab`} data-tab={value}
          role="tab" aria-selected={tab === value} aria-controls={`${id}-${value}-panel`} tabIndex={tab === value ? 0 : -1}
          onClick={() => setTab(value)} onKeyDown={switchTab}>{tabNames[value]}</button>)}
      </div>
      <div className="blueprint-panel blueprint-overview" role="tabpanel" id={`${id}-overview-panel`} aria-labelledby={`${id}-overview-tab`} hidden={tab !== 'overview'} tabIndex={0}>
        <CircuitDiagram design={design} workspace readableDefault hideWorkspaceNotes selectedId={selectedId} onClearSelection={() => setSelectedId(null)}
          onSelect={wire => { setSelectedId(wire.id); }} />
        {selectedId ? <button type="button" className="blueprint-wire-reference" onClick={() => setTab('steps')}>{tr('查看此線接法與組裝說明 →', 'View this wire and assembly instructions →')}</button> : null}
      </div>
      <div className="blueprint-panel" role="tabpanel" id={`${id}-parts-check-panel`} aria-labelledby={`${id}-parts-check-tab`} hidden={tab !== 'parts-check'} tabIndex={0}>
        <HardwarePartsCheck projectScope={`${design.id}:${design.revision}`} onAsk={onCheckParts} disabledReason={partsCheckDisabledReason} photoLabel={partsPhotoLabel} photoKey={partsPhotoKey} onOpenAI={onOpenAI} />
      </div>
      <div className="blueprint-panel" role="tabpanel" id={`${id}-materials-panel`} aria-labelledby={`${id}-materials-tab`} hidden={tab !== "materials"} tabIndex={0}>
        <header className="blueprint-resource-heading">
          <div className="blueprint-material-heading"><h3>{tr('備齊作品材料', 'Find your project parts')}</h3>
            <div className="blueprint-partner-note"><span>{tr('招商中', 'Partners wanted')}</span><small>{tr('歡迎電子零件廠合作', 'Electronic component manufacturers welcome')}</small></div>
          </div>
          <p className="maker-muted">{tr('外部商品入口；價格、規格與庫存以商家為準。', 'External product links. Confirm seller specifications, price and stock.')}</p>
        </header>
        {cards(design.bom)}
        {structure.length ? <><header className="blueprint-resource-heading"><h3>{tr("結構配件", "Structural parts")}</h3><p className="maker-muted">{tr("尺寸與固定方式需實物確認。", "Check actual dimensions and mounting.")}</p></header>{cards(structure)}</> : null}
      </div>
      <div className="blueprint-panel" role="tabpanel" id={`${id}-steps-panel`} aria-labelledby={`${id}-steps-tab`} hidden={tab !== "steps"} tabIndex={0}>
        <AssemblyGuide instructions={design.instructions.map(projectText)} onGuide={onGuide} />
        <details className="blueprint-reference blueprint-wire-reference-list" open={selectedId !== null}><summary>{tr("逐線接法", "Wire-by-wire reference")} · {design.wiring.length}</summary>
        <ol className="blueprint-wire-steps" ref={wireSteps}>{design.wiring.map((wire, i) => <li key={wire.id}>
          <button className={selectedId === wire.id ? "active" : ""} aria-pressed={selectedId === wire.id}
            data-blueprint-wire={wire.id} onClick={() => { setSelectedId(wire.id); setTab('overview'); }}>
            <span className="blueprint-step-number">{String(i + 1).padStart(2, "0")}</span>
            <span><strong>{tx(guideFor(wire.componentId).name)} · {wire.componentPin}</strong><span>{tx(wire.instruction)}</span>
              {wire.connectionKind === "divider" ? <small className="maker-warning">{tr("需分壓，禁止直連 GPIO", "Voltage divider required; never connect directly to GPIO")}</small> : null}</span>
          </button>
        </li>)}</ol></details>
        {design.unresolved.length ? <div className="maker-warning">{design.unresolved.map((line, i) => <p key={i}>{line}</p>)}</div> : null}
        <details className="blueprint-reference"><summary>{tr('規格與接線注意事項', 'Specifications and wiring precautions')}</summary>
          {design.component_ids.map(componentId => <p key={componentId} className="maker-warning">{tx(guideFor(componentId).safety)}</p>)}</details>
      </div>
    </section>
  </div>;
}
