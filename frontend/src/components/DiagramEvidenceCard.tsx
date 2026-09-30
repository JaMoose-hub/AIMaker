import { useState } from "react";
import type { ProjectDesign } from "../lib/maker";
import type { DebugMessage, DiagramSnapshot } from "../lib/debugSessions";
import { createDiagramInspection, diagramMatchesCurrent, diagramWires, type DiagramInspection } from "../lib/debugEvidence";
import { useMakerText } from "../lib/useMaker";

export function DiagramEvidenceCard({ snapshot, reference, currentDesign, onDiagram }: {
  snapshot?: DiagramSnapshot; reference: NonNullable<DebugMessage["diagram_refs"]>[number];
  currentDesign: ProjectDesign | null; onDiagram?: (inspection: DiagramInspection) => void;
}) {
  const tr = useMakerText();
  const [selection, setSelection] = useState<string>();
  if (!snapshot || snapshot.schema_version !== "debug-diagram-v1" || !snapshot.render_snapshot?.modules?.length) return <small className="ai-evidence-expired">{tr("這份歷史接線圖無法取得。", "This historical diagram is unavailable.")}</small>;
  const wires = diagramWires(snapshot, reference.wire_ids);
  if (!wires.length) return null;
  const initialWire = wires.find(wire => wire.id === reference.initial_focus_wire_id) ?? wires[0];
  const selected = wires.find(wire => wire.id === selection) ?? initialWire;
  const current = diagramMatchesCurrent(snapshot, currentDesign);
  const inspection = createDiagramInspection(snapshot, selected.id, currentDesign);
  return <div className="ai-diagram-card">
    <div className="ai-evidence-heading"><strong>{tr("設計接法", "Designed wiring")} · v{snapshot.project_revision}</strong><span>{current ? tr("目前版本", "Current version") : tr("歷史版本・僅供檢視", "Historical · read only")}</span></div>
    {wires.length > 1 ? <div className="ai-evidence-tabs" role="group" aria-label={tr("AI 指出的接線", "Wires referenced by AI")}>{wires.map(wire => <button type="button" key={wire.id} aria-pressed={wire.id === selected?.id} onClick={() => setSelection(wire.id)}>{wire.componentId === "hc-sr04" ? "HC" : "TFT"} · {wire.componentPin}</button>)}</div> : null}
    <p className="ai-diagram-summary"><strong>{selected.componentId === "hc-sr04" ? "HC-SR04+" : "MRD-TFT240"} · {selected.componentPin}</strong><span aria-hidden="true">→</span><strong>Pi {selected.boardLabel}</strong></p>
    {selected.connectionKind === "divider" ? <small className="maker-warning">{tr("ECHO 需分壓，不可直連 GPIO", "ECHO needs a divider, not a direct GPIO wire")}</small> : null}
    <div className="ai-evidence-actions"><button type="button" className="ai-diagram-open" aria-controls="current-step-diagram" disabled={!inspection || !onDiagram}
      onClick={() => { if (inspection) onDiagram?.(inspection); }}>{tr("在左側查看接法", "View wiring on the left")} <span aria-hidden="true">↖</span></button></div>
    <details className="ai-diagram-context"><summary>{tr("示意接法，非實物驗證", "Intended wiring, not hardware verification")}</summary><p>{reference.caption || tr("實際插線請對照照片與實物。", "Compare it with the photo and hardware.")}</p></details>
  </div>;
}
