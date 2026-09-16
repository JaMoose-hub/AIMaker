import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { defaultPrompt, makerCatalog, type DesignMode, type MakerState, type MakerStage } from "../lib/maker";
import type { GuidedComponentId } from "../lib/componentWiringGuides";
import type { useMakerAI } from "../lib/useMakerAI";
import { useI18n } from "../lib/i18n";
import { useMakerText } from "../lib/useMaker";

export function MakerAssistant({ state, setState, assistant, onReview, showHeading = true }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>;
  assistant: ReturnType<typeof useMakerAI>; onReview: () => void;
  showHeading?: boolean;
}) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const { ai, aiOptions, busy, error, generate } = assistant;
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [state.conversation.length]);
  const names: Record<MakerStage, string> = { design: tr("作品設計", "Concept"), blueprint: "Blueprint", guide: tr("接線引導", "Wiring"), deploy: tr("部署與測試", "Deploy & test") };
  return <section className="maker-prompt-panel maker-assistant" aria-label={tr("雲端 AI 對話", "Cloud AI conversation")}>
    {showHeading ? <div className="maker-assistant-heading"><div><div className="maker-eyebrow">CLOUD / CO-DESIGNER</div><h2>{tr("一起把想法做出來", "Build it together")}</h2></div><span className={ai?.logged_in ? "maker-online" : "maker-muted"}>● {ai?.logged_in ? tr("已連線", "Online") : tr("未連線", "Offline")}</span></div> : null}
    <p className="maker-context">{names[state.stage]} · {tr("對話與作品跨頁保留", "Conversation follows your project")}</p>
    {busy ? <p className="maker-generating" role="status">{assistant.phase === "image" ? tr("正在生成作品圖片…通常需要一至數分鐘，可切換頁面。", "Generating the project image… this may take a few minutes; you can switch pages.") : tr("雲端模型正在設計／回覆…", "Cloud model designing / answering…")}</p> : null}
    <div ref={log} className="maker-conversation" role="log" aria-label={tr("作品對話紀錄", "Project conversation")} aria-live="polite">
      {state.conversation.length ? state.conversation.map((msg, i) => <div className={`maker-message ${msg.role}`} key={i}><small>{msg.role === "user" ? "YOU" : "ASSISTANT"}</small><p>{msg.text}</p></div>) : <p className="maker-muted">{tr("告訴我你想做什麼。先看作品概念，確認後再一起準備 Blueprint 與接線。", "Tell me what you want to make. Review the concept first, then work through the blueprint and wiring together.")}</p>}
    </div>
    {state.candidate && state.stage !== "design" ? <button className="maker-candidate-notice" onClick={onReview}>{tr("有新版作品待確認 → 查看預覽", "New revision ready → Review concept")}</button> : null}
    {error || aiOptions.estimateError ? <pre className="maker-error" role="alert">{error || aiOptions.estimateError}</pre> : null}
    {state.candidate?.image_error && state.candidate.image_job_id ? <div className="maker-warning"><p>{tr("作品文字已保留，可以只重新生成圖片；會再次使用生圖額度。", "The text design is saved. Retry just the image; this uses image allowance again.")}</p><button disabled={busy || !ai?.logged_in} onClick={() => void assistant.retryImage()}>{tr("只重試生圖", "Retry image only")}</button></div> : null}
    <form onSubmit={e => { e.preventDefault(); void generate(); }}>
      <div className="maker-mode-buttons" role="group" aria-label={tr("雲端對話用途", "Cloud request type")}>
        <button type="button" disabled={busy} aria-pressed={state.aiIntent === "design"} className={state.aiIntent === "design" ? "active" : ""} onClick={() => setState(s => ({ ...s, aiIntent: "design" }))}>{tr("設計／修改作品", "Design / revise")}</button>
        <button type="button" disabled={busy} aria-pressed={state.aiIntent === "ask"} className={state.aiIntent === "ask" ? "active" : ""} onClick={() => setState(s => ({ ...s, aiIntent: "ask" }))}>{tr("詢問 AI", "Ask AI")}</button>
      </div>
      {state.aiIntent === "design" ? <label className="maker-design-mode">{tr("生成方式", "Design mode")}
        <select value={state.designMode} disabled={busy} onChange={e => setState(s => ({ ...s, designMode: e.target.value as DesignMode }))}>
          <option value="free">{tr("自由版 · 重新設計造型", "Free · New shape")}</option>
          <option value="fixed">{tr("固定版 · 保留造型微調", "Fixed · Refine current shape")}</option>
        </select>
      </label> : null}
      <label className="maker-field">{state.aiIntent === "ask" ? tr("詢問目前步驟或程式", "Ask about this step or code") : tr("描述你想做的作品", "Describe your project")}
        <textarea value={state.prompt} maxLength={8000} onChange={e => setState(s => ({ ...s, prompt: e.target.value }))} rows={4} /></label>
      <div className="maker-compose-footer"><button type="button" className="maker-text-button" disabled={busy} onClick={() => setState(s => ({ ...s, prompt: defaultPrompt, aiIntent: "design" }))}>{tr("範例需求", "Sample prompt")}</button>
        <button type="submit" className="maker-primary" disabled={busy || !ai?.logged_in || !aiOptions.estimate || !aiOptions.selectionValid || !state.prompt.trim() || !state.selected.length}>{busy ? tr("雲端處理中…", "Working…") : tr("送出 →", "Send →")}</button></div>
    </form>
    <details className="maker-assistant-options maker-assistant-parts"><summary>{tr("限定零件", "Supported parts")} · Pi 5 + {state.selected.length}</summary>
      <fieldset className="maker-parts"><legend>{tr("沿用現有零件，每種最多一個", "Existing modules only, at most one each")}</legend>
        {makerCatalog.modules.map(module => <label key={module.id}><input type="checkbox" disabled={busy} checked={state.selected.includes(module.id as GuidedComponentId)} onChange={e => setState(s => ({ ...s, selected: e.target.checked ? [...s.selected, module.id as GuidedComponentId] : s.selected.filter(id => id !== module.id) }))} />{tx(module.name)}</label>)}
      </fieldset>
      <small className="maker-muted">{tr("電子模組不增加；可加入輪子、銅柱、壓克力板等被動結構配件。", "No extra electronic modules. Passive wheels, standoffs, acrylic and mounting hardware are allowed.")}</small>
    </details>
  </section>;
}
