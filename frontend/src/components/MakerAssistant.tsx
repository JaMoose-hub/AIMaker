import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { makerCatalog, type MakerState, type MakerStage } from "../lib/maker";
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
  const [confirmAction, setConfirmAction] = useState<"clear" | "demo" | null>(null);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [state.conversation.length]);
  const names: Record<MakerStage, string> = { design: tr("作品設計", "Concept"), blueprint: "Blueprint", guide: tr("接線引導", "Wiring"), debug: tr("測試與除錯", "Test & debug"), deploy: tr("部署與執行", "Deploy & run") };
  return <section className="maker-prompt-panel maker-assistant" aria-label={tr("雲端 AI 對話", "Cloud AI conversation")}>
    {showHeading ? <div className="maker-assistant-heading"><div><div className="maker-eyebrow">CLOUD / CO-DESIGNER</div><h2>{tr("一起把想法做出來", "Build it together")}</h2></div><span className={ai?.logged_in ? "maker-online" : "maker-muted"}>● {ai?.logged_in ? tr("已連線", "Online") : tr("未連線", "Offline")}</span></div> : null}
    <p className="maker-context">{names[state.stage]} · {tr("對話與作品跨頁保留", "Conversation follows your project")}</p>
    <div className="maker-chat-tools">
      <button type="button" disabled={busy} onClick={() => state.candidate ? setConfirmAction("demo") : void assistant.loadDemo()}>{tr("載入 Demo 示範", "Load demo")}</button>
      <button type="button" disabled={busy || !state.conversation.length} onClick={() => setConfirmAction("clear")}>{tr("清除對話", "Clear conversation")}</button>
    </div>
    <small className="maker-muted">{tr("Demo 不需 AI，先載入預覽；確認後才套用。", "Demo needs no AI. Review the preview before applying it.")}</small>
    {confirmAction ? <div className="maker-chat-confirm" role="group" aria-label={tr("確認操作", "Confirm action")}>
      <p>{confirmAction === "clear" ? tr("清除這裡的對話紀錄？作品、接線進度、程式與未送出的文字都會保留。", "Clear this conversation? Your project, wiring progress, code and unsent text will stay.") : tr("載入 Demo 會取代目前尚未套用的預覽；已確認作品與程式不會改變。", "Demo replaces the unapproved preview only. Your approved project and code will stay.")}</p>
      <button disabled={busy} onClick={() => { if (confirmAction === "clear") assistant.clearConversation(); else void assistant.loadDemo(); setConfirmAction(null); }}>{confirmAction === "clear" ? tr("確認清除", "Clear conversation now") : tr("載入示範預覽", "Load demo preview")}</button>
      <button onClick={() => setConfirmAction(null)}>{tr("取消", "Cancel")}</button>
    </div> : null}
    {busy ? <p className="maker-generating" role="status">{assistant.phase === "demo" ? tr("正在載入示範作品…", "Loading demo…") : assistant.phase === "image" ? tr("正在生成作品圖片…通常需要一至數分鐘，可切換頁面。", "Generating the project image… this may take a few minutes; you can switch pages.") : tr("雲端模型正在設計／回覆…", "Cloud model designing / answering…")}</p> : null}
    <div ref={log} className="maker-conversation" role="log" aria-label={tr("作品對話紀錄", "Project conversation")} aria-live="polite">
      {state.conversation.length ? state.conversation.map((msg, i) => <div className={`maker-message ${msg.role}`} key={i}><small>{msg.role === "user" ? "YOU" : "ASSISTANT"}</small><p>{msg.text}</p></div>) : <p className="maker-muted">{tr("告訴我你想做什麼。先看作品概念，確認後再一起準備 Blueprint 與接線。", "Tell me what you want to make. Review the concept first, then work through the blueprint and wiring together.")}</p>}
    </div>
    {state.candidate && state.stage !== "design" ? <button className="maker-candidate-notice" onClick={onReview}>{tr("有新版作品待確認 → 查看預覽", "New revision ready → Review concept")}</button> : null}
    {error || aiOptions.estimateError ? <pre className="maker-error" role="alert">{error || aiOptions.estimateError}</pre> : null}
    {state.candidate?.image_error && state.candidate.image_job_id ? <div className="maker-warning"><p>{tr("作品文字已保留，可以只重新生成圖片；會再次使用生圖額度。", "The text design is saved. Retry just the image; this uses image allowance again.")}</p><button disabled={busy || !ai?.logged_in} onClick={() => void assistant.retryImage()}>{tr("只重試生圖", "Retry image only")}</button></div> : null}
    <form onSubmit={e => { e.preventDefault(); void generate(); }}>
      <label className="maker-field">{tr("想做什麼，或想問什麼？", "What would you like to make or ask?")}
        <textarea value={state.prompt} placeholder={tr("例如：這個零件做什麼？／把螢幕移到前面／換一個全新造型", "Ask about a component, move the screen, or request a new design…")} maxLength={8000} onChange={e => setState(s => ({ ...s, prompt: e.target.value }))} rows={4} /></label>
      <small className="maker-muted">{tr("提問就回答，想修改就產生預覽。不確定時會先問你；確認後才更新作品。", "Ask a question or request a change. Changes stay as previews until you confirm; unclear requests get a follow-up question.")}</small>
      <div className="maker-compose-footer">
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
