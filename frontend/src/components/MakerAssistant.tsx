import { useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { makerCatalog, fillStarterPrompt, type MakerState, type MakerStage } from "../lib/maker";
import type { GuidedComponentId } from "../lib/componentWiringGuides";
import type { useMakerAI } from "../lib/useMakerAI";
import { useI18n } from "../lib/i18n";
import { useMakerText } from "../lib/useMaker";
import { makerReplyPreview } from "../lib/makerReply";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { systemText } from "../lib/systemText";

export function MakerAssistant({ state, setState, assistant, onReview, onNewProject, showHeading = true }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>;
  assistant: ReturnType<typeof useMakerAI>; onReview: () => void;
  onNewProject?: () => Promise<boolean>;
  showHeading?: boolean;
}) {
  const tr = useMakerText();
  const { tx, locale } = useI18n();
  const { ai, aiOptions, busy, error, generate } = assistant;
  const promptId = useId();
  const hintId = `${promptId}-hint`;
  const contextId = `${promptId}-context`;
  const demoHintId = `${promptId}-demo-hint`;
  const demoHint = tr("載入示範對話與作品預覽，不需 AI；確認後才套用作品。", "Load sample chat and a project preview without AI. Confirm before applying the project.");
  const composeHint = tr("提問或修改都可以；作品確認後才更新。", "Ask or request changes. Your project updates only after confirmation.");
  const canSend = !busy && Boolean(ai?.logged_in && aiOptions.estimate && aiOptions.selectionValid && state.prompt.trim() && state.selected.length);
  const sendLabel = busy ? tr("處理中…", "Working…") : tr("送出訊息", "Send message");
  const log = useRef<HTMLDivElement>(null);
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const partsMenu = useRef<HTMLDetailsElement>(null);
  const [confirmAction, setConfirmAction] = useState<"clear" | "demo" | "new" | null>(null);
  const closeParts = () => {
    if (partsMenu.current) {
      partsMenu.current.open = false;
      partsMenu.current.querySelector("summary")?.focus();
    }
  };
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      const menu = partsMenu.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    };
    document.addEventListener("pointerdown", dismiss, true);
    return () => document.removeEventListener("pointerdown", dismiss, true);
  }, []);
  useEffect(() => { if (partsMenu.current) partsMenu.current.open = false; }, [state.stage]);
  useEffect(() => {
    const panel = log.current;
    const latest = panel?.lastElementChild;
    if (panel && latest) panel.scrollTop += latest.getBoundingClientRect().top - panel.getBoundingClientRect().top - 4;
  }, [state.conversation]);
  const names: Record<MakerStage, string> = { design: tr("設計與藍圖", "Design & blueprint"), guide: tr("接線引導＋AI 除錯", "Wiring + AI debug"), deploy: tr("部署與執行", "Deploy & run") };
  const contextHint = `${names[state.stage]} · ${tr("對話與作品跨頁保留", "Conversation follows your project")}`;
  return <section className="maker-prompt-panel maker-assistant" aria-label={tr("雲端 AI 對話", "Cloud AI conversation")} aria-describedby={contextId}>
    <header className="maker-assistant-header">
    {showHeading ? <div className="maker-assistant-heading"><h2 title={contextHint}>{tr("一起把想法做出來", "Build it together")}</h2><span className={ai?.logged_in ? "maker-online" : "maker-muted"}>● {ai?.logged_in ? tr("已連線", "Online") : tr("未連線", "Offline")}</span></div> : null}
    <span id={contextId} className="maker-compose-hint">{contextHint}</span>
    <div className="maker-chat-tools">
      {!state.prompt.trim() ? <button type="button" disabled={busy} title={tr("帶入目前語言的預設需求，不會自動送出", "Fill the starter prompt in this language without sending it")} onClick={() => {
        if (busy) return;
        setState(s => fillStarterPrompt(s, locale));
        promptInput.current?.focus();
      }}>{tr("帶入預設", "Use starter prompt")}</button> : null}
      <button type="button" title={demoHint} aria-describedby={demoHintId} disabled={busy} onClick={() => state.candidate ? setConfirmAction("demo") : void assistant.loadDemo()}>{tr("載入 Demo 示範", "Load demo")}</button>
      <button type="button" disabled={busy || !state.conversation.length} onClick={() => setConfirmAction("clear")}>{tr("清除對話", "Clear conversation")}</button>
      {onNewProject ? <button type="button" disabled={busy} title={tr("清空目前作品與圖片；內建 Demo 圖會保留", "Clear the current project and image; keep the built-in Demo image")} onClick={() => { if (!busy) setConfirmAction("new"); }}>{tr("新作品", "New project")}</button> : null}
      <details ref={partsMenu} className="maker-assistant-parts" onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeParts(); }
      }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }}>
        <summary title={tr("限定零件", "Supported parts")}>{tr("零件", "Parts")} · {state.selected.length}<span aria-hidden="true">⌄</span></summary>
        <div className="maker-parts-popover">
          <header><strong>{tr("限定零件", "Supported parts")} · Pi 5 + {state.selected.length}</strong><button type="button" onClick={closeParts} aria-label={tr("關閉零件設定", "Close parts settings")}>×</button></header>
          <fieldset className="maker-parts"><legend>{tr("沿用現有零件，每種最多一個", "Existing modules only, at most one each")}</legend>
            {makerCatalog.modules.map(module => <label key={module.id}><input type="checkbox" disabled={busy} checked={state.selected.includes(module.id as GuidedComponentId)} onChange={e => setState(s => ({ ...s, selected: e.target.checked ? [...s.selected, module.id as GuidedComponentId] : s.selected.filter(id => id !== module.id) }))} />{tx(module.name)}</label>)}
          </fieldset>
          <p className="maker-muted">{tr("可加入輪子、銅柱、壓克力板等結構配件。馬達可出現在概念圖，但不納入藍圖、接線、測試或部署。", "Wheels, standoffs, acrylic and mounting hardware are allowed. Motors may appear in the concept image only, not the blueprint, wiring, tests or deployment.")}</p>
          <p className="maker-parts-hint">{composeHint}</p>
        </div>
      </details>
    </div>
    <span id={demoHintId} className="maker-compose-hint">{demoHint}</span>
    </header>
    {confirmAction ? <div className="maker-chat-confirm" role="group" aria-label={tr("確認操作", "Confirm action")}>
      <p>{confirmAction === "new" ? tr("從頭開始？目前作品、圖片、預覽、對話、程式與接線進度將清空。內建 Demo 圖會保留，之後仍可按「載入 Demo 示範」。舊草稿先備份，相機設定不變。", "Start over? This clears the current project, image, preview, conversation, code and wiring progress. The built-in Demo image stays available through Load demo. The old draft is backed up; camera settings stay.") : confirmAction === "clear" ? tr("清除這裡的對話紀錄？作品、接線進度、程式與未送出的文字都會保留。", "Clear this conversation? Your project, wiring progress, code and unsent text will stay.") : tr("載入 Demo 會取代目前尚未套用的預覽；已確認作品與程式不會改變。", "Demo replaces the unapproved preview only. Your approved project and code will stay.")}</p>
      <button disabled={busy} onClick={async () => { if (busy) return; if (confirmAction === "new") { if (await onNewProject?.()) setConfirmAction(null); return; } if (confirmAction === "clear") assistant.clearConversation(); else void assistant.loadDemo(); setConfirmAction(null); }}>{confirmAction === "new" ? tr("確認從頭開始", "Confirm start over") : confirmAction === "clear" ? tr("確認清除", "Clear conversation now") : tr("載入示範預覽", "Load demo preview")}</button>
      <button onClick={() => setConfirmAction(null)}>{tr("取消", "Cancel")}</button>
    </div> : null}
    {busy ? <p className="maker-generating" role="status">{assistant.resetting ? tr("正在核對工作並準備新作品…", "Checking active work and preparing a new project…") : assistant.phase === "demo" ? tr("正在載入示範作品…", "Loading demo…") : assistant.phase === "image" ? tr("正在生成作品圖片…通常需要一至數分鐘，可切換頁面。", "Generating the project image… this may take a few minutes; you can switch pages.") : tr("雲端模型正在設計／回覆…", "Cloud model designing / answering…")}</p> : null}
    <div ref={log} className="maker-conversation" role="log" aria-label={tr("作品對話紀錄", "Project conversation")} aria-live="polite">
      {state.conversation.length ? state.conversation.map((msg, i) => {
        const preview = msg.role === "assistant" && msg.source !== "demo" ? makerReplyPreview(msg.text) : null;
        return <div className={`maker-message ${msg.role}`} key={i}>
          <small>{msg.role === "user" ? tr("你", "You") : "Tinkro AI"}{msg.source === "demo" ? tr(" · 示範對話", " · Sample chat") : ""}</small>
          {preview ? <>
            {preview.blocks.map((block, index) => {
              if (block.kind === "paragraph") return <AssistantMarkdown className="maker-reply-text" key={index} text={block.text} />;
              const List = block.ordered ? "ol" : "ul";
              return <List className="maker-reply-points" key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex} value={block.ordered ? item.ordinal : undefined}><AssistantMarkdown text={item.text} /></li>)}</List>;
            })}
            {preview.hasMore ? <details className="maker-reply-full"><summary>{tr("查看完整回覆", "Read full reply")}</summary><AssistantMarkdown text={msg.text} /></details> : null}
          </> : msg.role === 'assistant' ? <AssistantMarkdown text={msg.text} /> : <p>{msg.text}</p>}
        </div>;
      }) : <p className="maker-muted">{tr("告訴我你想做什麼。先看作品概念，確認後再一起準備 Blueprint 與接線。", "Tell me what you want to make. Review the concept first, then work through the blueprint and wiring together.")}</p>}
    </div>
    {state.candidate && state.stage !== "design" ? <button className="maker-candidate-notice" onClick={onReview}>{tr("有新版作品待確認 → 查看預覽", "New revision ready → Review concept")}</button> : null}
    {error || aiOptions.estimateError ? <pre className="maker-error" role="alert">{systemText(error || aiOptions.estimateError || "", locale)}</pre> : null}
    {state.candidate?.image_error && state.candidate.image_job_id ? <div className="maker-warning"><p>{tr("作品文字已保留，可以只重新生成圖片；會再次使用生圖額度。", "The text design is saved. Retry just the image; this uses image allowance again.")}</p><button disabled={busy || !ai?.logged_in} onClick={() => void assistant.retryImage()}>{tr("只重試生圖", "Retry image only")}</button></div> : null}
    <form className="maker-composer" onSubmit={e => { e.preventDefault(); if (canSend) void generate(); }}>
      <label className="maker-compose-label" htmlFor={promptId}>{tr("想做什麼，或想問什麼？", "What would you like to make or ask?")}</label>
      <div className="maker-compose-row">
        <textarea ref={promptInput} id={promptId} aria-describedby={hintId} value={state.prompt} placeholder={tr("例如：這個零件做什麼？／把螢幕移到前面／換一個全新造型", "Ask about a component, move the screen, or request a new design…")} maxLength={8000} onChange={e => setState(s => ({ ...s, prompt: e.target.value }))} rows={2} />
        <button type="submit" className="maker-primary maker-compose-send" aria-label={sendLabel} title={sendLabel} disabled={!canSend}>
          {busy ? <span aria-hidden="true">…</span> : <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>}
        </button>
      </div>
      <span id={hintId} className="maker-compose-hint">{composeHint}</span>
    </form>
  </section>;
}
