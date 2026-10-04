import type { ReactNode } from "react";
import type { GuideMode, ProjectDesign, ProjectWire } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { CircuitDiagram } from "./CircuitDiagram";

export function WiringViewToggle({ diagramVisible, captureRequired = false, disabled = false, onChange }: {
  diagramVisible: boolean; captureRequired?: boolean; disabled?: boolean; onChange: (mode: GuideMode) => void;
}) {
  const tr = useMakerText();
  return <button type="button" className="mirror-toggle wiring-view-toggle"
    aria-pressed={diagramVisible} aria-controls="current-step-diagram"
    disabled={disabled}
    title={captureRequired ? tr("可先查看接線圖；拍攝實物時請返回鏡頭。", "Inspect the diagram first; return to the camera to photograph the hardware.") :
      tr("只切換畫面，保留接線進度與 AI 對話。", "Switch the view without changing wiring progress or AI chat.")}
    onClick={() => onChange(diagramVisible ? "camera" : "2d")}>
    {diagramVisible ? tr("返回鏡頭", "Back to camera") : tr("本步驟 2D 接線圖", "This step's 2D wiring")}
  </button>;
}

export function StepDiagramView({ design, wire, capturePending = false, viewControls }: { design: ProjectDesign; wire: ProjectWire; capturePending?: boolean; viewControls?: ReactNode }) {
  const tr = useMakerText();
  return <section id="current-step-diagram" className="maker-2d-main" aria-label={tr("本步驟 2D 接線圖", "This step's 2D wiring")}>
    {capturePending ? <p className="step-diagram-capture-notice" role="status">{tr("AI 正在等待實物照片；查看接法後可返回鏡頭拍攝。", "AI is waiting for a hardware photo; return to the camera after checking the wiring.")}</p> : null}
    <CircuitDiagram design={design} activeId={wire.id} readableDefault workspace viewControls={viewControls} />
  </section>;
}
