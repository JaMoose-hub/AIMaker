import { useState, type Dispatch, type SetStateAction } from "react";
import { needsDraftConsent, type MakerState } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { ProjectConcept } from "./ProjectConcept";

export function DesignStudio({ state, setState, onAdopt }: { state: MakerState; setState: Dispatch<SetStateAction<MakerState>>; onAdopt: (replaceManual?: boolean) => void }) {
  const tr = useMakerText();
  const design = state.candidate ?? state.design;
  const [consentFor, setConsentFor] = useState("");
  const revisionKey = `${design?.id}:${design?.revision}`;
  const confirming = consentFor === revisionKey && needsDraftConsent(state);
  const cannotConfirm = Boolean(state.aiJobId || (state.candidate && (state.candidate.image_required || state.candidate.source === "ai") && !state.candidate.image));
  return <section className="maker-preview maker-concept-page" aria-label={tr("作品設計預覽", "Project concept preview")} aria-busy={Boolean(state.aiJobId)}>
    <div className="maker-eyebrow">01 / CONCEPT STUDIO</div>
    {design ? <>
      <div className="maker-preview-heading"><div><span className="maker-badge">{design.source === "demo" ? tr("示範資料", "DEMO") : "AI DESIGN"} · v{design.revision}{design.generation?.design_mode ? ` · ${design.generation.design_mode === "fixed" ? tr("固定版", "Fixed") : tr("自由版", "Free")}` : ""}</span><h2>{design.title}</h2></div>
        <button className="maker-primary" disabled={cannotConfirm} onClick={() => needsDraftConsent(state) ? setConsentFor(revisionKey) : onAdopt()}>{state.candidate ? tr("確認作品 → Blueprint", "Confirm concept → Blueprint") : tr("查看 Blueprint →", "View Blueprint →")}</button></div>
      {confirming ? <div className="maker-draft-consent" role="alert"><p>{tr("你有手動修改的程式草稿。套用此版本會以新版程式取代它。", "Your code draft has manual edits. Applying this revision will replace it with the new code.")}</p>
        <button onClick={() => setConsentFor("")}>{tr("取消，保留草稿", "Cancel, keep draft")}</button>
        <button className="maker-primary" disabled={cannotConfirm} onClick={() => onAdopt(true)}>{tr("確認取代並進入 Blueprint", "Replace draft & open Blueprint")}</button></div> : null}
      <p className="maker-muted">{design.summary}</p>
      {state.candidate && state.design ? <p className="maker-warning">{tr("新版預覽，尚未套用。確認後才更新 Blueprint、接線配置與程式。", "Unapplied revision. Confirm to update the blueprint, wiring and code.")}</p> : null}
      <ProjectConcept design={design} />
      {state.candidate ? <button onClick={() => setState(s => ({ ...s, candidate: null }))}>{tr("捨棄此預覽", "Discard preview")}</button> : null}
    </> : <div className="maker-empty"><span aria-hidden="true">✧</span><h2>{tr("先看見你的作品", "See your idea take shape")}</h2><p>{tr("在左側描述需求。雲端 AI 完成設計後，作品概念畫面會直接出現在這裡。", "Describe your idea on the left. The cloud-generated concept will appear here.")}</p><div>CONCEPT → BLUEPRINT → WIRE → DEPLOY</div></div>}
    {state.aiJobId ? <p className="maker-generating" role="status">{tr("雲端模型處理中，可切換頁面；目前作品不會被自動覆蓋。", "Cloud model working. You can switch pages; your current project stays unchanged.")}</p> : null}
  </section>;
}
