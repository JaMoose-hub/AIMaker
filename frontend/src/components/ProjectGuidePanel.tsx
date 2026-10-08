import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { guideFor, type ActiveGuideTarget } from "../lib/componentWiringGuides";
import { startProjectGuide, restartProjectGuide, confirmProjectWire, previousProjectWire, reviewProjectWire, resumeProjectGuide, editProjectComponent, wireSignature, type ProjectDesign, type ProjectGuideState, type ProjectWire } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { CompactGuide } from "./CompactGuide";
import { useComponentTests } from "../lib/useComponentTests";
import { componentComplete, componentTestKey, selectTestModule } from "../lib/componentTests";
import { ComponentTestCard } from "./ComponentTestCard";
import { ComponentRowLocator } from "./ComponentRowLocator";
import { componentHeaderGuideText, componentModelName } from "../lib/componentHeaderGuide";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import type { Pin } from "../lib/types";
import type { ComponentTestHelpEvidence } from "../lib/componentTestHelp";

interface Props {
  design: ProjectDesign; session: ProjectGuideState; visible: boolean; disabled: boolean;
  pinsById: ReadonlyMap<string, Pin>;
  onChange: (session: ProjectGuideState) => void;
  onTargetChange: (target: ActiveGuideTarget | null) => void;
  onVisibleChange: (visible: boolean) => void;
  onDeploy: () => void;
  onDebug?: (componentId?: string, runId?: string, symptom?: string, evidence?: ComponentTestHelpEvidence) => void | Promise<boolean>;
  onBeforeEdit?: (componentId?: string) => Promise<boolean>;
  /** Owner commits the fresh guide and cleared AI state together. */
  onRestart?: (session: ProjectGuideState) => Promise<boolean>;
  embedded?: boolean;
  floating?: boolean;
  toolbar?: boolean;
  visibilityControl?: ReactNode;
  /** Photo navigation browses the same guide cursor, including completed modules. */
  onInspectComponent?: (componentId: string) => void;
}
export function ProjectGuidePanel({ design, session, visible, disabled, pinsById, onChange, onTargetChange, onVisibleChange, onDeploy, onDebug, onBeforeEdit, onRestart, embedded, floating = false, toolbar = false, visibilityControl, onInspectComponent }: Props) {
  const tr = useMakerText();
  const { t, tx } = useI18n();
  const tests = useComponentTests(design, session);
  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState("");
  const [openedAt] = useState(() => Date.now() / 1000);
  const editFlight = useRef(false);
  const latest = useRef({design, session, mounted:true});
  latest.current = {design, session, mounted:true};
  useEffect(() => { latest.current.mounted = true; return () => { latest.current.mounted = false; }; }, []);
  const cid = design.component_ids[session.componentIndex];
  const guide = guideFor(cid);
  const steps = design.wiring.filter(w => w.componentId === cid);
  const step = steps[session.index] ?? steps[0];
  const target = useMemo<ActiveGuideTarget | null>(() => session.mode !== "camera" ? null : ({
    componentId: cid, boardPinId: step.boardPin, componentPinId: step.componentPin,
    connectionKind: step.connectionKind, manualOnly: true,
  }), [cid, step.boardPin, step.componentPin, step.connectionKind, session.mode]);
  const active = session.phase === "active";
  const preparing = session.phase === "prepare";
  const complete = componentComplete(design, session, cid);
  // Old confirmations never skip preparation. A live test still keeps its Stop
  // controls reachable, including on reopening or after a wiring restart.
  const showTestCard = (!preparing && complete) || Boolean(tests.status.active);
  const reviewing = session.phase === "review";
  const lastTest = tests.status.results.filter(r => r.component_id === cid).at(-1);
  const passed = lastTest?.outcome === "passed" && !lastTest.invalidated && lastTest.guide_key === componentTestKey(design, session, cid);
  useEffect(() => {
    onTargetChange(active ? target : null);
    return () => onTargetChange(null);
  }, [active, target, onTargetChange]);
  const confirmed = (wire: ProjectWire) => session.confirmed[wire.id]?.signature === wireSignature(wire);
  const count = design.wiring.filter(confirmed).length;
  const moduleCount = steps.filter(confirmed).length;
  function start() {
    onChange(startProjectGuide(session));
  }
  function confirm() {
    onChange(confirmProjectWire(design, session));
  }
  function previous() {
    onChange(previousProjectWire(design, session));
  }
  async function edit(restart = false) {
    if (editFlight.current || editing || tests.pending) return;
    editFlight.current = true;
    setEditing(true); setEditError("");
    const unchanged = () => latest.current.mounted && latest.current.design === design && latest.current.session === session;
    try {
      if (onBeforeEdit && !await onBeforeEdit(restart ? undefined : cid)) {
        setEditError(tr("請先在執行管理或測試卡停止相關工作，確認停止後再修改接線。", "Stop related work in Execution or the test card, then edit wiring once stopped."));
        return;
      }
      if (!unchanged()) return;
      if (!onBeforeEdit && tests.status.active?.reserved) {
        setEditError(tr("測試仍在執行或等待核對，請先停止本次測試。", "The test is running or awaiting reconciliation. Stop it first."));
        return;
      }
      if (await tests.invalidate(restart ? undefined : cid) === false) throw new Error("invalidation_failed");
      if (!unchanged()) return;
      if (restart && onRestart) {
        if (!await onRestart(restartProjectGuide(session))) throw new Error("ai_reset_unconfirmed");
        return;
      }
      if (unchanged()) onChange(restart ? restartProjectGuide(session) : editProjectComponent(design, session));
    } catch (cause) {
      const reason = cause instanceof Error ? cause.message : "";
      const messages: Record<string, [string, string]> = {
        hardware_work_active: ["Pi 仍有程式、測試或待核對的工作。請先在執行管理或測試卡停止並核對，再重新開始。", "The Pi has active or unreconciled work. Stop it in Execution or the test card before restarting the guide."],
        other_debug_active: ["另一個作品的 AI 檢查仍在進行。請先停止該次 AI 檢查，再重新開始接線引導。", "Another project's AI check is active. Stop that check before restarting the wiring guide."],
        ai_stop_unconfirmed: ["本次 AI 檢查尚未確認停止，接線紀錄保留；請稍後重試。", "This AI check has not confirmed stopping. Wiring records are kept; retry shortly."],
        ai_reset_pending: ["AI 協作操作尚未完成，接線與對話保留；請稍後再重新開始。", "An AI operation is still pending. Wiring and conversation are kept; retry shortly."],
        ai_reset_unconfirmed: ["AI 對話尚未確認清空，接線紀錄保留；請稍後重試。", "The AI conversation reset is not confirmed. Wiring records are kept; retry shortly."],
        conversation_restarted: ["另一個頁面已更新 AI 對話，請稍候同步後再試；接線紀錄保留。", "Another tab changed the AI conversation. Wait for synchronization and retry; wiring records are kept."],
        wiring_backend_restart_required: ["目前執行中的後端不支援這次操作。請重新啟動 Board Vision 後端，再重新整理頁面；接線紀錄保留。", "The running backend does not support this operation. Restart the Board Vision backend and refresh; wiring records are kept."],
      };
      setEditError(messages[reason] ? tr(...messages[reason]) : tr("無法取得工作狀態，接線紀錄保留。請確認 Board Vision 後端可用後重試。", "Work status could not be retrieved. Wiring records are kept. Check the Board Vision backend and retry."));
    } finally { editFlight.current = false; setEditing(false); }
  }
  const [boardPhysical, ...boardSignals] = step.boardLabel.split(" · ");
  const boardPin = pinsById.get(step.boardPin);
  const piGuide = piHeaderGuideText(boardPin, t);
  const componentGuide = componentHeaderGuideText(cid, step.componentPin, t);
  // When browsing wires, saved/idle test information is reference material.
  // A live test (including a disconnected/foreign run) stays visible with Stop.
  const recentTest = lastTest && (lastTest.finished_at ?? lastTest.created_at) >= openedAt;
  const testJobNeedsAttention = tests.status.execution?.jobs.some(job => job.kind === "test" && job.project_id === design.id
    && job.component_id === cid && job.guide_key === componentTestKey(design, session, cid)
    && (!["finished", "failed", "cancelled"].includes(job.state) || (job.state === "failed" && (job.created_at ?? 0) >= openedAt)));
  const testInfoInDetails = active && !tests.status.active && !tests.pending && !tests.error && !recentTest && !testJobNeedsAttention;
  const testInstructions = showTestCard ? <ComponentTestCard design={design} session={session} tests={tests} view={floating && !toolbar ? "dock" : "instructions"} onDebug={floating && !toolbar ? onDebug : undefined}
    onViewWiring={() => onChange(reviewProjectWire(design, session, cid))} /> : null;
  const testControls = showTestCard && (!floating || toolbar) ? <div className="guide-test-controls">
    <ComponentTestCard design={design} session={session} tests={tests} view="actions" inlineActions={toolbar} onDebug={onDebug}
      onViewWiring={() => onChange(reviewProjectWire(design, session, cid))} />
  </div> : null;
  const iconTestNavigation = toolbar && !active && !preparing && !session.inspection;
  const nextModule = session.componentIndex < design.component_ids.length - 1;
  const deferTest = complete && !passed;
  const continueLabel = nextModule
    ? deferTest ? tr("稍後測試，繼續", "Test later · Continue") : tr("下一模組", "Next module")
    : deferTest ? tr("稍後測試，前往部署", "Test later · Deploy") : tr("前往部署", "Deploy");
  return <CompactGuide contextKey={`${design.id}:${design.revision}:${cid}:${session.phase}:${session.index}:${session.run ?? 0}`} phase={reviewing ? "review" : session.phase}
    headerActions={<><button type="button" className={`guide-restart-action${floating ? " guide-icon-action" : ""}`}
      aria-label={tr("重新開始接線引導", "Restart wiring guide")}
          title={tr("清除本輪接線與 AI 協作對話，回到第一步；保留作品、程式與歷史測試紀錄", "Clear this wiring run and AI conversation, then return to the first step; keep the project, code and historical test records")}
      disabled={tests.pending || editing} onClick={() => void edit(true)}>
      {floating ? <svg aria-hidden="true" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3.5 8a6.5 6.5 0 1 1 .6 5M3.5 3.5V8H8" />
      </svg> : <><span aria-hidden="true">↻</span>{tr("重新開始", "Restart")}</>}
    </button>{!toolbar ? visibilityControl : null}</>}
    embedded={embedded} floating={floating} toolbar={toolbar} visibilityControl={visibilityControl} visible={visible} title={componentGuide?.name ?? tx(guide.name)} progress={<>
      <div className="guide-progress-label"><span>{tr("作品人工紀錄", "Project manual records")}</span><strong>{count}<span> / {design.wiring.length}</span></strong></div>
      <progress max={design.wiring.length} value={count} aria-label={tr("作品人工接線進度", "Project manual wiring progress")} />
      <div className="guide-module-track">{design.component_ids.map((id, i) => <button type="button" key={id} disabled={tests.pending} aria-current={i === session.componentIndex ? "step" : undefined}
        onClick={() => onInspectComponent && session.phase !== "prepare" ? onInspectComponent(id) : onChange(selectTestModule(design, session, i))}>
        <span className="guide-module-dot" aria-hidden="true">{i + 1}</span>{componentModelName(id, t) ?? id.toUpperCase()}
      </button>)}</div>
    </>}
    targetId={active ? `${cid}:${step.componentPin}` : undefined} onClose={() => onVisibleChange(false)}
    actions={<>{toolbar ? testControls : null}<div className={`guide-navigation${iconTestNavigation ? " is-icon-test-navigation" : ""}`}>{session.inspection ? <>
      <button onClick={() => session.inspectionSource === "debug" ? onDebug?.(cid) : onChange(resumeProjectGuide(session))}>{session.inspectionSource === "debug" ? tr("返回 AI 對話", "Back to AI chat") : tr("返回接線", "Resume wiring")}</button>
      <button disabled={session.index === 0} onClick={() => onChange({ ...session, index: session.index - 1 })}>{tr("上一步", "Back")}</button>
      <button disabled={session.index >= steps.length - 1} onClick={() => onChange({ ...session, index: session.index + 1 })}>{tr("下一步", "Next")}</button>
      <button disabled={editing || tests.pending} onClick={() => void edit()}>{tr("我要修改此零件接線", "Edit this component wiring")}</button>
    </> : preparing ? toolbar && tests.status.active ? null : <button type="button" className="guide-primary-action" onClick={start}>{tr("開始接線 →", "Start wiring →")}</button>
      : active ? <>
        <button type="button" className="guide-back-action" title={tr("回到前一條接線指示，保留已確認紀錄", "Return to the previous wire; keep confirmations")} disabled={session.index === 0 || tests.pending} onClick={previous}>{tr("上一步", "Back")}</button>
        <button type="button" className="guide-primary-action" onClick={confirm}>{confirmed(step) ? tr("下一步 →", "Next →") : floating ? tr("接好了，下一步 →", "Connected · Next →") : tr("我已接好，下一步 →", "Connected · Next →")}</button>
      </> : <>
        <button type="button" className={`guide-back-action${iconTestNavigation ? " guide-action-icon-button" : ""}`} aria-label={iconTestNavigation ? tr("返回接線步驟", "Back to wiring") : undefined} title={tr("回到接線步驟，保留已確認與測試紀錄", "Return to the wiring step; keep confirmations and test records")} disabled={tests.pending} onClick={previous}>
          {iconTestNavigation ? <><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="m14 6-6 6 6 6" /></svg><span>{tr("返回", "Back")}</span></> : tr("上一步", "Back")}</button>
        <button type="button" className={`${deferTest ? "guide-back-action" : "guide-primary-action"}${iconTestNavigation ? ` guide-action-icon-button${deferTest ? " guide-defer-test-action" : ""}` : ""}`}
          aria-label={iconTestNavigation ? continueLabel : undefined} title={iconTestNavigation ? continueLabel : undefined}
          onClick={nextModule ? () => onChange({ ...session, componentIndex: session.componentIndex + 1, index: 0, phase: "prepare", checks: [] }) : onDeploy}>
          {iconTestNavigation ? <><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            {deferTest ? <path d="m5 6 7 6-7 6V6Zm13 0v12" /> : nextModule ? <path d="M5 12h14m-6-6 6 6-6 6" /> : <path d="M6 18 18 6M6 6h12v12" />}
          </svg><span>{deferTest ? tr("稍後測試", "Test later") : continueLabel}</span></> : `${continueLabel} →`}</button>
      </>}</div>
      {!toolbar ? testControls : null}</>}
    details={<>
    {active ? <p>{tx(step.hint)}</p> : null}
    {active ? <ComponentRowLocator componentId={cid} pinId={step.componentPin} /> : null}
    {testInfoInDetails ? testInstructions : null}
    {guide.unresolved.map(item => <p key={item.pin} className="guide-caution">{item.pin} · {tx(item.reason)}</p>)}
    {session.phase === "review" && session.componentIndex === design.component_ids.length - 1
      ? <p>{tr("核對接線與供電規格後，接上 Pi USB-C 電源；開機後前往部署。", "After checking wiring and supply ratings, connect Pi USB-C power; deploy after boot.")}</p> : null}
    <div className="maker-module-progress">{design.component_ids.map((id, i) => <span key={id} className={i === session.componentIndex ? "active" : ""}>{i + 1}. {id} · {design.wiring.filter(w => w.componentId === id && confirmed(w)).length}/{design.wiring.filter(w => w.componentId === id).length}</span>)}</div>
    {session.mode !== "camera" ? <button onClick={() => onChange({ ...session, mode: "camera" })}>{tr("返回鏡頭 Pin 引導", "Return to camera Pin guide")}</button> : null}
    <p className="wiring-safety">{tx(guide.safety)}</p>
    {session.restored ? <small className="maker-warning">{tr("含先前保存的人工紀錄；不是目前接線證據。", "Includes saved manual records, not evidence of current wiring.")}</small> : null}
    {active ? <button type="button" onClick={() => onChange({ ...session, phase: "review" })}>{tr("暫停並看總覽", "Pause & review")}</button> : null}
    <p className="wiring-status">{tr("功能測試透過 Pi 執行，不需要鏡頭定位。", "Function tests run on Pi and do not require camera tracking.")}</p>
    <p className="wiring-status">{tr("人工確認不代表導通、電壓或硬體功能通過。", "Manual confirmation does not verify continuity, voltage or functionality.")}</p>
    <small className="guide-step-note">{tr("接線由你逐腳確認；略過測試不會記錄為通過。", "Confirm each wire yourself; skipping a test never records a pass.")}</small>
    <details className="wiring-summary" open={session.phase === "review" ? true : undefined}><summary>{tr("接線總覽", "Wiring summary")} · {count}/{design.wiring.length}</summary>
      <table><tbody>{design.wiring.map(w => <tr key={w.id}><td>{w.componentId} · {w.componentPin}</td><td>{w.boardLabel}</td><td>{confirmed(w) ? `${tr("人工確認", "Manual")} (${session.confirmed[w.id].mode})` : tr("未確認", "Not confirmed")}</td></tr>)}</tbody></table></details>
    </>}>
    {editError ? <p className="guide-caution" role="alert">{editError}</p> : null}
    {tests.status.results.some(r => r.program_stop_requested && !r.program_stopped) ? <p className="guide-caution">{tr("已送出停止原作品要求，狀態待確認；請重新連線核對。", "A stop request was sent to the original project; reconnect to confirm its state.")}</p> : null}
    {preparing && !(toolbar && tests.status.active) ? <div className="guide-prepare-message">
      <strong>{tr("準備開始接線", "Ready to start wiring")}</strong>
      <p>{tr("先關閉硬體電源，再按「開始接線」。", "Turn off hardware power, then press Start wiring.")}</p>
    </div> : null}
    {active ? <>
      <section key={`${cid}:${step.id}:${session.run ?? 0}`} className={`guide-connection-card ${step.connectionKind}${floating ? " guide-current-step" : ""}${toolbar ? " guide-toolbar-connection" : ""}`} aria-label={tr("本步接線", "Current connection")}>
        <div className="guide-step-label"><span>{floating ? <svg aria-hidden="true" viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="4" cy="10" r="2" /><path d="M6 10h8" /><circle cx="16" cy="10" r="2" /></svg> : null}{floating ? tr("接這條線", "CONNECT NOW") : tr("這一步要接", "CONNECT THIS WIRE")}</span><strong aria-label={tr(`第 ${session.index + 1}／${steps.length} 條接線`, `Wire ${session.index + 1} of ${steps.length}`)}>{session.index + 1}<span> / {steps.length}</span></strong></div>
        <div className="guide-pin-pair">
          <div className="guide-endpoint"><span>{componentGuide?.name ?? cid.toUpperCase()}</span><strong>{step.componentPin}</strong>
            <small>{componentGuide ? floating ? tr(`第 ${componentGuide.number} 腳`, `Pin ${componentGuide.number}`) : tr(`零件端第 ${componentGuide.number} 腳`, `Module pin ${componentGuide.number}`) : tr("零件端", "Module pin")}</small></div>
          <span className="guide-pin-link" aria-hidden="true">{step.connectionKind === "divider" ? "⇢" : "→"}</span>
          <div className="guide-endpoint"><span title={tr("Raspberry Pi 5 · 實體腳位", "Raspberry Pi 5 · Physical pin")}>{floating ? "Pi 5" : <>Raspberry Pi 5 · {tr("實體腳位", "Physical pin")}</>}</span>
            <strong>{piGuide ? `Pin ${piGuide.physical}` : boardPhysical}</strong>
            <small>{piGuide ? `${piGuide.signal} · ${piGuide.rowLabel}` : boardSignals.join(" · ")}</small></div>
        </div>
        {step.connectionKind === "divider" ? <p className="guide-connect-hint">
          {tr("保持斷電，依下方分壓接法連接；不可直連 GPIO。", "Keep power off and use the divider below; do not wire directly to GPIO.")}</p> : null}
        {!piGuide ? <p className="guide-step-instruction">{tx(step.instruction)}</p> : null}
      </section>
      {step.connectionKind === "divider" ? <div className="guide-caution"><strong>{tr("ECHO 需分壓，不可直連 GPIO", "ECHO needs a divider, not a direct GPIO wire")}</strong>
        <div className="wiring-divider"><code>ECHO ─ 330Ω ─ ● ─ GPIO18</code><code>● ─ 470Ω ─ GND</code></div></div> : null}
    </> : reviewing && !complete ? <section className="guide-module-review"><span>{tr("本模組人工紀錄", "MODULE MANUAL RECORDS")}</span>
      <strong>{moduleCount} / {steps.length}</strong>{!complete ? <p>{tr("請繼續完成剩餘接線。", "Finish the remaining wires first.")}</p> : null}</section> : null}
    {!testInfoInDetails ? testInstructions : null}
    {!active ? guide.unresolved.filter(item => cid !== "mrd-tf240-8p-cs" || item.pin !== "BLK")
      .map(item => <p key={item.pin} className="guide-caution">{item.pin} · {tx(item.reason)}</p>) : null}
    {disabled ? <p role="status">{tr("本機服務未連線；接線紀錄保留。", "Local service offline; wiring records are kept.")}</p> : null}
  </CompactGuide>;
}
