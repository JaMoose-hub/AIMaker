import { useState, type Dispatch, type SetStateAction } from "react";
import { discardConcept, needsDraftConsent, type MakerState } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { systemText } from "../lib/systemText";
import { ProjectConcept, ProjectGenerationStatus, type ProjectGenerationPhase } from "./ProjectConcept";
import { DesignViewSwitch, type DesignView } from "./DesignViewSwitch";

export function DesignStudio({ state, setState, onAdopt, onViewChange, generationPhase, busy = false }: { state: MakerState; setState: Dispatch<SetStateAction<MakerState>>; onAdopt: (replaceManual?: boolean) => void; onViewChange: (view: DesignView) => void; generationPhase?: ProjectGenerationPhase | "demo"; busy?: boolean }) {
  const tr = useMakerText();
  const { locale } = useI18n();
  const design = state.candidate ?? state.design;
  const projectText = (text: string) => design?.source === "demo" ? systemText(text, locale) : text;
  // A login/demo request is not a generation job. No local timers or polling.
  const activePhase = state.aiJobId ? (generationPhase === "image" ? "image" : "design") : undefined;
  const [consentFor, setConsentFor] = useState("");
  const [discardedFor, setDiscardedFor] = useState<string | null>(null);
  const approvedKey = state.design ? `${state.design.id}:${state.design.revision}:${state.design.image?.url ?? ""}` : "empty";
  const processing = busy || Boolean(state.aiJobId);
  const discarded = discardedFor === approvedKey && !state.candidate && !processing;
  const revisionKey = `${design?.id}:${design?.revision}`;
  const confirming = consentFor === revisionKey && needsDraftConsent(state);
  const cannotConfirm = Boolean(processing || (state.candidate && (state.candidate.image_required || state.candidate.source === "ai") && !state.candidate.image));
  function discardPreview() {
    if (processing || !state.candidate) return;
    const preview = state.candidate;
    setState(s => discardConcept(s, preview));
    setConsentFor("");
    setDiscardedFor(approvedKey);
  }
  return <section className="maker-preview maker-concept-page" data-proposal={Boolean(state.candidate)} data-concept-state={state.candidate ? "preview" : state.design ? "approved" : "empty"} aria-label={tr("作品設計預覽", "Project concept preview")} aria-busy={processing}>
    <div className="maker-view-heading"><span className="maker-eyebrow">01 / CONCEPT STUDIO</span>
      <DesignViewSwitch view="concept" hasBlueprint={Boolean(state.design)} onChange={onViewChange} />
      {state.candidate ? <button className="maker-primary maker-concept-confirm" disabled={cannotConfirm} onClick={() => needsDraftConsent(state) ? setConsentFor(revisionKey) : onAdopt()}>{tr("確認作品並查看藍圖 →", "Confirm and view blueprint →")}</button> : null}</div>
    {discarded ? <p className="maker-concept-feedback" role="status">{state.design ? tr(`已捨棄預覽，目前顯示已確認作品 v${state.design.revision}。`, `Preview discarded. Showing confirmed project v${state.design.revision}.`) : tr("已捨棄預覽，尚未有已確認作品。", "Preview discarded. No project has been confirmed yet.")}</p> : null}
    {design ? <>
      <div className="maker-preview-heading"><div><div className="maker-concept-meta"><span className="maker-concept-version">{state.candidate ? tr("未確認預覽", "Unconfirmed preview") : tr("已確認作品", "Confirmed project")} · v{design.revision}</span><span className="maker-badge">{design.source === "demo" ? tr("示範資料", "DEMO") : "AI DESIGN"}{design.generation?.design_mode ? ` · ${design.generation.design_mode === "fixed" ? tr("局部修改", "Revision") : tr("全新造型", "New design")}` : ""}</span></div><h2>{projectText(design.title)}</h2></div></div>
      {confirming ? <div className="maker-draft-consent" role="alert"><p>{tr("你有手動修改的程式草稿。套用此版本會以新版程式取代它。", "Your code draft has manual edits. Applying this revision will replace it with the new code.")}</p>
        <button onClick={() => setConsentFor("")}>{tr("取消，保留草稿", "Cancel, keep draft")}</button>
        <button className="maker-primary" disabled={cannotConfirm} onClick={() => onAdopt(true)}>{tr("確認取代並進入 Blueprint", "Replace draft & open Blueprint")}</button></div> : null}
      <details className="maker-concept-description" key={revisionKey}><summary>{tr("作品說明", "About this project")}</summary><p className="maker-muted">{projectText(design.summary)}</p></details>
      {state.candidate ? <p className="maker-warning proposal-status">{tr("新版預覽，尚未套用。確認後才更新 Blueprint、接線配置與程式。", "Unapplied revision. Confirm to update the blueprint, wiring and code.")}</p> : null}
      <ProjectConcept design={design} generationPhase={activePhase} />
      {state.candidate ? <button type="button" disabled={processing} title={processing ? tr("AI 處理完成後才能捨棄預覽。", "Wait for AI processing to finish before discarding the preview.") : undefined} onClick={discardPreview}>{tr("捨棄此預覽", "Discard preview")}</button> : null}
    </> : activePhase ? <ProjectGenerationStatus phase={activePhase} /> : <div className="maker-empty"><span aria-hidden="true">✧</span><h2>{tr("先看見你的作品", "See your idea take shape")}</h2><p>{tr("在左側描述需求。雲端 AI 完成設計後，作品概念畫面會直接出現在這裡。", "Describe your idea on the left. The cloud-generated concept will appear here.")}</p><div>CONCEPT → BLUEPRINT → WIRE → DEPLOY</div></div>}
  </section>;
}
