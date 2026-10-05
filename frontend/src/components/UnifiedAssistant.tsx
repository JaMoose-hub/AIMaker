import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type Dispatch, type SetStateAction } from "react";
import { useChatScroll } from "../lib/useChatScroll";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { currentWire, fillStarterPrompt, makerCatalog, type MakerState } from "../lib/maker";
import { currentAssistantMedia, type AssistantController, type AssistantConversation, type AssistantMessage } from "../lib/assistant";
import { conversationMessageNote, conversationMessages } from "../lib/assistantHistory";
import type { useMakerAI } from "../lib/useMakerAI";
import { ProjectConcept } from "./ProjectConcept";
import { MakerModelMenu } from "./MakerModelMenu";
import { MobileCompanion, MobileAttachmentCards, type MobileWorkspaceTargets } from "./MobileCompanion";
import { WiringChatMessage, WiringReceiptStatus } from './WiringChatMessage';
import { AssistantMarkdown } from './AssistantMarkdown';
import { AssistantAnalysisTime } from './AssistantAnalysisTime';
import { assistantProgress } from '../lib/assistantProgress';
import { AssistantJobProgress } from './AssistantJobProgress';
import type { WiringReviewAction, WiringReviewState } from '../lib/wiringReview';
import { ConversationGuideHost } from './ConversationGuideDock';

export function DemoChecklist({ record, controller, compact = false, aiReady = false }: { record: AssistantConversation; controller: AssistantController; compact?: boolean; aiReady?: boolean }) {
  const tr = useMakerText();
  const { tx } = useI18n();
  const demo = record.demo!;
  const list = demo.checklist;
  const wireCount = list.component_ids.reduce((count, cid) => count + (makerCatalog.modules.find(m => m.id === cid)?.steps.filter(step => step.connectionKind !== "not-connected").length ?? 0), 0);
  return <section className="assistant-checklist" aria-label={tr("待確認設計清單", "Design checklist awaiting confirmation")}>
    <h3>{tr("設計清單", "Design checklist")} · v{demo.revision}</h3>
    <span className="maker-badge">{demo.confirmed_revision === demo.revision ? tr("已確認清單 · 成果尚未套用", "Checklist confirmed · result not applied") : tr("待確認", "Awaiting confirmation")}</span>
    <h4>{tr("功能需求", "Requirements")}</h4><ul>{list.requirements.map((text, i) => <li key={i}>{text}</li>)}</ul>
    <h4>{tr("實際接線零件", "Wired electronics")}</h4><ul><li>Raspberry Pi 5 × 1</li>
      {list.component_ids.map(cid => <li key={cid}>{tx(makerCatalog.modules.find(m => m.id === cid)!.name)} × 1</li>)}
      <li>{tr("杜邦線", "Jumper wires")} × {wireCount} · {tr("依接線表", "from wiring table")}</li></ul>
    <h4>{tr("外觀與結構", "Appearance & structure")}</h4><ul>{list.structure.map(part => <li key={part.kind}>{part.purpose} × {part.quantity}</li>)}</ul>
    {list.concept_only.map(part => <p className="maker-warning" key={part.kind}>{tr("馬達", "Motors")} × {part.quantity} · {tr("僅概念圖，不接線、不加入程式", "Image only; no wiring or code")}</p>)}
    {!compact ? <><p className="maker-muted">{tr("內建示範不使用 AI 額度；真正生成需要 AI 連線並使用額度。", "Built-in preview uses no AI quota. AI generation requires a connection and uses quota.")}</p>
      <div className="assistant-checklist-actions">
        <button type="button" disabled={controller.busy} onClick={() => { controller.setDraft(tr("我想修改清單：", "I want to change the checklist: ")); document.getElementById("unified-prompt")?.focus(); }}>{tr("修改需求", "Edit requirements")}</button>
        <button type="button" disabled={controller.busy} onClick={() => void controller.restoreChecklist()}>{tr("還原示範清單", "Restore demo checklist")}</button>
        <button type="button" className="maker-primary" disabled={controller.busy} onClick={() => void controller.confirmDemo("builtin")}>{tr("確認並查看內建示範", "Confirm & view built-in example")}</button>
        <button type="button" disabled={controller.busy || !aiReady} onClick={() => void controller.confirmDemo("ai")}>{tr("確認並用 AI 生成", "Confirm & generate with AI")}</button>
      </div></> : null}
  </section>;
}

export function DemoWorkspace({ controller }: { controller: AssistantController }) {
  const tr = useMakerText();
  const [confirm, setConfirm] = useState(false);
  const record = controller.demo;
  const demo = record?.demo;
  const currentResult = demo?.confirmed_revision === demo?.revision ? demo?.result : null;
  return <section className="assistant-demo-workspace maker-preview">
    <header><h2>{tr("示範體驗", "Demo workspace")}</h2><button onClick={() => controller.setDemoOpen(false)}>{tr("返回目前作品", "Return to current project")}</button></header>
    <p className="maker-muted">{tr("獨立示範，不會改動目前作品。離開後生成仍會繼續，成果會保留。", "Isolated from your project. Leaving does not cancel generation; results are retained.")}</p>
    {record && demo ? currentResult ? <><h3>{currentResult.title}</h3><span className="maker-badge">{tr("未套用預覽", "Unapplied preview")} · {demo.result_source === "builtin" ? "DEMO" : "AI"}</span>
      <ProjectConcept design={currentResult} />
      <button className="maker-primary" disabled={controller.busy || Boolean(currentResult.image_required && !currentResult.image)} onClick={() => setConfirm(true)}>{tr("使用此作品", "Use this project")}</button>
      {confirm ? <div role="alertdialog" aria-label={tr("確認採用示範作品", "Confirm demo adoption")} className="assistant-checklist">
        <p>{tr("將先備份目前作品並核對工作，再以此預覽建立新作品。", "Back up the current project and check active work, then adopt this preview as a new project.")}</p>
        <button disabled={controller.busy} onClick={() => void controller.adoptDemo().then(ok => { if (ok) setConfirm(false); })}>{tr("確認採用", "Confirm adoption")}</button>
        <button onClick={() => setConfirm(false)}>{tr("取消", "Cancel")}</button></div> : null}
    </> : <><DemoChecklist record={record} controller={controller} compact />
      {demo.state === "generating" ? <p role="status">{tr("生成中，可以返回目前作品。", "Generating; you may return to your project.")}</p> : null}
      {demo.result ? <details><summary>{tr("先前成果（舊清單）", "Previous result (older checklist)")}</summary><ProjectConcept design={demo.result} /></details> : null}</> : <p role="status">{tr("正在載入示範…", "Loading demo…")}</p>}
  </section>;
}

export function UnifiedAssistant({ state, setState, controller, legacy, debugTools, onNewProject, mobileWorkspace, testHelpFocus, testHelpText, testHelpMessageId, onTestHelpActionTargetChange, wiringReview, onWiringFlowAction, onWiringReceiptRetry }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>; controller: AssistantController;
  legacy: ReturnType<typeof useMakerAI>; debugTools?: ReactNode; onNewProject: () => Promise<boolean>; mobileWorkspace?: MobileWorkspaceTargets;
  testHelpFocus?: string;
  testHelpText?: string;
  testHelpMessageId?: string;
  onTestHelpActionTargetChange?: (target: { invitationId: string; element: HTMLDivElement } | null) => void;
  wiringReview?: WiringReviewState | null;
  onWiringFlowAction?: (message: AssistantMessage, action: WiringReviewAction) => Promise<boolean>;
  onWiringReceiptRetry?: () => Promise<boolean>;
}) {
  const tr = useMakerText();
  const { locale, tx } = useI18n();
  const input = useRef<HTMLTextAreaElement>(null);
  const suggestions = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (suggestions.current?.open && event.target instanceof Node && !suggestions.current.contains(event.target)) suggestions.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside, true);
    return () => document.removeEventListener("pointerdown", closeOutside, true);
  }, []);
  const [historyScope, setHistoryScope] = useState<string | null>(null);
  const [mobileSelection, setMobileSelection] = useState<{ id: string; nonce: number } | null>(null);
  const [confirm, setConfirm] = useState<"clear" | "new" | "demo" | null>(null);
  const record = controller.record;
  const historyKey = record ? `${record.id}:${record.context_epoch}` : "";
  const history = Boolean(historyKey) && historyScope === historyKey;
  const messages = conversationMessages(record, history);
  const receiptController = controller as AssistantController & {
    wiringReceiptPending?: boolean; wiringReceiptMessageId?: string | null; wiringReceiptError?: string | null;
  };
  const receiptVisible = !controller.demoOpen && Boolean(receiptController.wiringReceiptMessageId)
    && Boolean(receiptController.wiringReceiptPending || receiptController.wiringReceiptError);
  const receipt = { pending: Boolean(receiptController.wiringReceiptPending), error: receiptController.wiringReceiptError,
    onRetry: onWiringReceiptRetry };
  const currentRound = controller.mobileContext?.round ?? state.guide.run ?? 0;
  const referencedMedia = controller.demoOpen ? null : controller.mediaReference !== undefined ? controller.mediaReference
    : currentAssistantMedia(record, currentRound);
  const mediaNames = referencedMedia?.attachments.filter(asset => referencedMedia.asset_ids.includes(asset.asset_id))
    .map(asset => asset.filename || (asset.type === "video" ? tr("最近影片", "Recent video") : tr("最近照片", "Recent photo")));
  const aiReady = Boolean(legacy.ai?.logged_in && legacy.aiOptions.selectionValid);
  const latest = record?.messages.at(-1);
  const progress = assistantProgress(record, controller.pending,
    controller.demoOpen ? undefined : { id: state.aiJobId, phase: legacy.phase });
  const chatKey = `${latest ? `${record?.id}:${latest.id}` : ''}:${progress?.key ?? ''}:${progress?.phase ?? ''}`;
  const chat = useChatScroll(latest || progress ? chatKey : "", true);
  const testHelpMessage = !controller.demoOpen && testHelpFocus && testHelpMessageId
    ? record?.messages.find(message => message.id === testHelpMessageId && message.role === "assistant" && message.source === "legacy-debug"
      && message.epoch === record?.context_epoch && message.round === currentRound && message.text === testHelpText
      && !conversationMessageNote(message, record!)) : undefined;
  const testHelpActionRef = useCallback((element: HTMLDivElement | null) => {
    onTestHelpActionTargetChange?.(element && testHelpFocus ? { invitationId: testHelpFocus, element } : null);
  }, [onTestHelpActionTargetChange, testHelpFocus]);
  useLayoutEffect(() => {
    if (!testHelpFocus) return;
    chat.followNext();
    if (!testHelpMessage || !chat.showMessage(testHelpMessage.id)) chat.showLatest();
  }, [testHelpFocus]);
  const wire = state.design ? currentWire(state.design, state.guide) : undefined;
  const stageName = state.stage === "design" ? tr("01 設計", "01 Design") : state.stage === "guide" ? tr("02 接線", "02 Wiring") : tr("03 程式與輸出", "03 Code & output");
  const assistantTitle = `Tinkro AI - ${controller.demoOpen ? tr("示範對話 · 清單規劃", "Demo conversation · planning") : stageName}`;
  const questions = controller.demoOpen || state.stage === "design" ? [tr("這些零件各做什麼？", "What does each part do?"), tr("可以怎麼修改外型？", "How could I change the shape?"), tr("組裝前要準備什麼？", "What should I prepare before assembly?")]
    : state.stage === "guide" ? [tr("這一步怎麼接？", "How do I connect this?"), tr("Pi 腳位在哪？", "Where is the Pi pin?"), tr("怎麼檢查接線？", "How do I check the wiring?")]
      : [tr("解釋目前程式", "Explain the current code"), tr("幫我分析錯誤輸出", "Analyze the error output"), tr("執行版本和草稿一樣嗎？", "Does the running version match the draft?")];
  async function send() { if (controller.busy || !aiReady || legacy.busy) return; chat.followNext(); await controller.send(); }
  return <section className="unified-assistant" aria-label={tr("Tinkro AI 對話", "Tinkro AI conversation")}>
    <header className="unified-assistant-heading"><strong className="unified-assistant-title" title={assistantTitle}>{assistantTitle}</strong>
      <MobileCompanion controller={controller} aiReady={aiReady && !legacy.busy} selection={mobileSelection} workspace={mobileWorkspace} />
      <details className="assistant-more"><summary>{tr("更多", "More")}</summary><div>
        {!controller.demoOpen ? <><button disabled={controller.busy || legacy.busy} onClick={() => setConfirm("demo")}>{tr("載入 Demo 示範", "Load demo")}</button>
          <button disabled={controller.busy || legacy.busy} onClick={() => setConfirm("new")}>{tr("新作品", "New project")}</button>
          <button onClick={() => { setState(s => fillStarterPrompt(s, locale)); input.current?.focus(); }}>{tr("帶入預設", "Use starter prompt")}</button>
          <fieldset><legend>{tr("可用零件", "Available modules")}</legend>{makerCatalog.modules.map(module => <label key={module.id}><input type="checkbox" checked={state.selected.includes(module.id as MakerState["selected"][number])} disabled={controller.busy}
            onChange={event => setState(s => ({ ...s, selected: event.target.checked ? [...s.selected, module.id as MakerState["selected"][number]] : s.selected.filter(id => id !== module.id) }))} />{tx(module.name)}</label>)}</fieldset></> : null}
        <button disabled={controller.busy} onClick={() => setConfirm("clear")}>{tr("清除對話", "Clear conversation")}</button>
        <button onClick={() => setHistoryScope(history ? null : historyKey)}>{history ? tr("隱藏已清除紀錄", "Hide cleared history") : tr("查看已清除紀錄", "View cleared history")}</button>
      </div></details>
    </header>
    {confirm ? <div className="assistant-confirm" role="alertdialog" aria-label={tr("確認操作", "Confirm action")}><p>{confirm === "clear" ? tr("清除目前聊天上下文；作品、接線、程式及原始紀錄會保留。", "Clear chat context; keep the project, wiring, code and original records.") : confirm === "demo" ? tr("載入內建示範會取代未確認預覽；已確認作品不變。", "Load the built-in example and replace the unconfirmed preview; keep the confirmed project.") : tr("備份並建立新作品；內建 Demo 圖與舊對話保留。", "Back up and start a new project; keep the built-in Demo image and old conversation.")}</p>
      <button disabled={controller.busy} onClick={() => void (confirm === "clear" ? controller.clear() : confirm === "demo" ? legacy.loadDemo().then(() => true) : onNewProject()).then(ok => { if (ok) setConfirm(null); }).catch(controller.reportError)}>{tr("確認", "Confirm")}</button><button onClick={() => setConfirm(null)}>{tr("取消", "Cancel")}</button></div> : null}
    <div className="unified-message-list" ref={chat.chatRef} onScroll={chat.onScroll} role="log" aria-label={tr("對話紀錄", "Conversation history")} aria-live="polite">
      {record?.before !== null && record?.before !== undefined ? <button onClick={() => void controller.older()}>{tr("載入較早訊息", "Load earlier messages")}</button> : null}
      <div ref={chat.contentRef}>
        {messages.map(message => {
          const note = conversationMessageNote(message, record!);
          return <article key={message.id} data-message-id={message.id} className={`ai-debug-message is-${message.role}${note ? " is-archived" : ""}`}>
          <header><strong>{message.role === "user" ? tr("你", "You") : "Tinkro AI"}</strong><small>{message.source === "demo" ? tr("示範對話", "Sample dialogue") : message.source === "legacy-design" ? tr("舊設計對話", "Legacy design conversation") : message.created_at ? new Date(message.created_at * 1000).toLocaleTimeString(locale) : tr("匯入紀錄", "Imported record")}</small></header>
          {message.role === 'assistant' ? <AssistantMarkdown text={message.text} />
            : <div className="assistant-message-text">{message.text}</div>}
          {message.id === testHelpMessage?.id && onTestHelpActionTargetChange ? <div className="assistant-message-actions" ref={testHelpActionRef} /> : null}
          {message.wiring_flow ? <WiringChatMessage message={message} review={wiringReview} busy={controller.busy || legacy.busy || Boolean(receiptController.wiringReceiptPending)} inactive={Boolean(note)}
            receipt={receiptVisible && message.id === receiptController.wiringReceiptMessageId ? receipt : undefined}
            onAction={note ? undefined : onWiringFlowAction} /> : null}
          {message.wiring_flow?.kind === 'photo' && (message.wiring_flow.image_url || message.wiring_flow.capture_id && message.session_id) ? null
            : <MobileAttachmentCards message={message} onOpen={id => setMobileSelection(previous => ({ id, nonce: (previous?.nonce ?? 0) + 1 }))} />}
          {note ? <small>{note === "previous_context" ? tr("先前聊天上下文", "Earlier chat context") : tr("上一輪紀錄，不作為本輪證據", "Previous round; not evidence for this round")}</small> : null}
          {message.evidence_ids?.length ? <details><summary>{tr("原始照片證據", "Original photo evidence")}</summary>{message.evidence_ids.map(eid => message.session_id ? <a key={eid} href={`/api/debug/sessions/${encodeURIComponent(message.session_id)}/evidence/${encodeURIComponent(eid)}`} target="_blank" rel="noreferrer">{tr("查看照片", "View photo")} ↗</a> : null)}</details> : null}
        </article>;
        })}
        {progress ? <AssistantJobProgress progress={progress} /> : null}
        {receiptVisible && !messages.some(message => message.id === receiptController.wiringReceiptMessageId) ? <article className="ai-debug-message is-assistant"
          data-wiring-receipt-message-id={receiptController.wiringReceiptMessageId}>
          <header><strong>Tinkro AI</strong><small>{tr('剛才的接線核對', 'Your last wiring review')}</small></header>
          <WiringReceiptStatus key={receiptController.wiringReceiptMessageId} receipt={receipt} />
        </article> : null}
        {controller.demoOpen && record?.demo ? <DemoChecklist record={record} controller={controller} aiReady={aiReady} /> : null}
        {record?.jobs.filter(job => job.status === "failed" || job.status === "unknown" || job.result?.image_error).map(job => <div key={job.id} className="assistant-job-error" role="status">
          {job.status === "unknown" ? tr("後端重啟，結果尚未核對；不會自動重送。", "Backend restarted; outcome unknown. Nothing was resubmitted.") : job.error || job.result?.image_error}
          {job.result?.image_error ? <button disabled={controller.busy} onClick={() => void controller.retryImage(job)}>{tr("只重試圖片", "Retry image only")}</button> : null}
        </div>)}
      </div>
    </div>
    {chat.unread ? <button className="ai-debug-latest" onClick={chat.showLatest}>{tr("查看最新回覆 ↓", "View latest reply ↓")}</button> : null}
    {debugTools}
    <ConversationGuideHost enabled={!controller.demoOpen && state.stage === "guide" && Boolean(state.design)} />
    <form className="unified-composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      {!controller.demoOpen && state.stage === "guide" ? <div className="assistant-context-row">
        <small className="assistant-wire-context" title={wire ? `${wire.componentPin} → ${wire.boardLabel}` : undefined}>{wire ? `${wire.componentPin} → ${wire.boardLabel}` : tr("接線協作", "Wiring assistance")}</small>
        <details className="assistant-suggestions" ref={suggestions} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }} onKeyDown={event => {
          if (event.key === "Escape" && suggestions.current?.open) { event.preventDefault(); event.stopPropagation(); suggestions.current.open = false; suggestions.current.querySelector("summary")?.focus(); }
        }}>
          <summary>{tr("建議問題", "Suggestions")} <span aria-hidden="true">⌄</span></summary>
          <div className="assistant-suggestion-list">{questions.map(question => <button key={question} type="button" onClick={() => { if (suggestions.current) suggestions.current.open = false; controller.setDraft(question); input.current?.focus(); }}>{question}</button>)}</div>
        </details>
      </div> : <div className="assistant-quick">{questions.map(question => <button key={question} type="button" onClick={() => { controller.setDraft(question); input.current?.focus(); }}>{question}</button>)}</div>}
      {referencedMedia ? <small className="assistant-media-reference" role="status"><span>{tr("此訊息引用：", "This message references: ")}{mediaNames?.length ? mediaNames.join(" · ") : tr("最近附件", "Recent attachment")}</span>
        <button type="button" disabled={controller.busy || legacy.busy || !controller.removeMediaReference}
          aria-label={tr("移除照片引用", "Remove photo reference")} title={tr("後續訊息不再附上這些照片；保留原始照片與對話紀錄", "Stop attaching these photos to follow-ups; keep the original photos and conversation")}
          onClick={() => { if (controller.removeMediaReference()) input.current?.focus(); }}>{tr("移除引用", "Remove")}</button></small> : null}
      <label className="sr-only" htmlFor="unified-prompt">{tr("傳訊息給 AI", "Message AI")}</label>
      <div className="assistant-input"><textarea id="unified-prompt" ref={input} value={controller.draft} rows={3} maxLength={8000} onChange={event => controller.setDraft(event.target.value)}
        placeholder={tr("提問或修改都可以；操作由你確認。", "Ask or request changes; you confirm actions.")}
        onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!controller.busy) void send(); } }} />
        <div className="assistant-input-actions">
          <MakerModelMenu state={state} setState={setState} assistant={legacy} compact />
          <button type="submit" className="assistant-send" aria-busy={controller.busy}
            title={controller.busy ? tr("AI 處理中", "AI working") : tr("送出訊息", "Send message")}
            disabled={controller.busy || legacy.busy || !controller.record || !controller.draft.trim() || !state.selected.length || !aiReady}>
            {controller.busy ? <span className="assistant-send-pending" aria-hidden="true"><i /><i /><i /></span>
              : <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>}
            <span className="sr-only">{tr("送出", "Send")}</span>
          </button>
        </div>
      </div>
      {controller.wiringAnalysis ? <div className="assistant-analysis-send-status">
        <AssistantAnalysisTime startedAt={controller.wiringAnalysis.startedAt} />
        <small>{tr('分析完成後即可送出，草稿會保留。', 'You can send when analysis finishes. Your draft is kept.')}</small>
      </div> : <small>{controller.busy ? tr("AI 處理中 · 可切換工作區", "AI working · you may switch workspaces") : "Enter ↵ · Shift + Enter"}</small>}
      {!legacy.ai?.logged_in ? <button type="button" onClick={() => void legacy.login()}>{tr("登入 AI", "Sign in to AI")}</button> : null}
      {legacy.loginURL ? <a href={legacy.loginURL} target="_blank" rel="noreferrer">{tr("開啟登入頁", "Open sign-in")}</a> : null}
      {controller.error || legacy.error ? <p role="alert" className="maker-error">{controller.error || legacy.error}</p> : null}
      {controller.storageError ? <p role="alert">{tr("偏好儲存失敗；請勿關閉頁面。", "Could not save preferences; keep this page open.")}</p> : null}
    </form>
  </section>;
}
