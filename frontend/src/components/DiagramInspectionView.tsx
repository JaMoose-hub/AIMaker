import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ProjectDesign } from "../lib/maker";
import { diagramMatchesCurrent, type DiagramInspection } from "../lib/debugEvidence";
import { useMakerText } from "../lib/useMaker";
import { CircuitDiagram } from "./CircuitDiagram";

/** Transient, read-only view of an AI message's frozen diagram, not a guide step. */
export function DiagramInspectionView({ inspection, currentDesign, capturePending = false, onReturn, viewControls }: {
  inspection: DiagramInspection; currentDesign: ProjectDesign; capturePending?: boolean; onReturn: () => void; viewControls?: ReactNode;
}) {
  const tr = useMakerText();
  const { snapshot, wireId } = inspection;
  const [selectedId, setSelectedId] = useState<string | null>(wireId);
  const [view, setView] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const current = diagramMatchesCurrent(snapshot, currentDesign);
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 960px)").matches) panel.current?.scrollIntoView({ block: "start" });
  }, []);
  return <section ref={panel} id="current-step-diagram" className="maker-2d-main ai-diagram-workspace" tabIndex={-1}
    aria-label={tr("AI 引用的 2D 接線圖", "AI-referenced 2D wiring diagram")}>
    <header className="diagram-inspection-heading">
      {viewControls}
      <div><strong>{tr("AI 接法", "AI wiring")} · v{snapshot.project_revision}</strong><span className={current ? "" : "maker-warning"}>{current ? tr("目前版本 · 僅供檢視", "Current version · read only") : tr("歷史版本 · 僅供檢視", "Historical version · read only")}</span></div>
      <button type="button" onClick={() => { setSelectedId(selectedId === null ? wireId : null); setView(value => value + 1); }}>{selectedId === null ? tr("返回 AI 指出的接線", "Return to AI's wire") : tr("查看完整電路", "View full circuit")}</button>
      <button type="button" onClick={onReturn}>{tr("返回目前步驟", "Back to current step")}</button>
    </header>
    {capturePending ? <p className="step-diagram-capture-notice" role="status">{tr("AI 正在等待實物照片；查看接法後可返回鏡頭拍攝。", "AI is waiting for a hardware photo; return to the camera after checking the wiring.")}</p> : null}
    <CircuitDiagram key={view} design={snapshot.design} frozenProfile={snapshot.render_snapshot} activeId={selectedId ?? undefined}
      onSelect={wire => setSelectedId(wire.id)} onClearSelection={() => setSelectedId(null)} readableDefault workspace
      focusLabel={tr("查看接法", "Inspect wiring")} />
  </section>;
}
