import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMakerText } from "../lib/useMaker";
import type { MakerState } from "../lib/maker";
import type { DebugContext } from "../lib/debug";
import type { DebugMessage, DebugResponseMode, DebugSessionAction, useDebugSession } from "../lib/debugSessions";
import { sameDebugTestKeys } from "../lib/debugSessions";
import { componentComplete } from "../lib/componentTests";

type SessionControl = ReturnType<typeof useDebugSession>;
const isTerminal = (status?: string) => status === "complete" || status === "stopped" || status === "error";
const epochTime = (value: string | number) => new Date(typeof value === "string" ? value : value < 1e12 ? value * 1000 : value).toLocaleTimeString();

export function AiDebugPanel({ state, context, currentCodeHash, repairCaseId, repairAppliedHash, repairCandidateReady, session, webcamReady, eyeActive, cameraSource, cameraRuntimeRevision, onReturnWebcam,
  onCase, onRetest, onTrial, onReviewRepair, onManual, onWiring }: {
  state: MakerState; context: DebugContext; currentCodeHash: string; session: SessionControl; webcamReady: boolean; eyeActive: boolean;
  repairCaseId: string | null; repairAppliedHash: string | null; repairCandidateReady: boolean;
  cameraSource: string | null; cameraRuntimeRevision: number | null;
  onReturnWebcam: () => void; onCase: (id: string) => void; onRetest: (id: string) => void;
  onTrial: () => void; onReviewRepair: () => void; onManual: () => void; onWiring: (id: string) => void;
}) {
  const tr = useMakerText();
  const initialSymptom = state.debug?.symptom ?? "";
  const [entry, setEntry] = useState(/^[a-z]+(?:_[a-z]+)+$/.test(initialSymptom) ? "" : initialSymptom);
  const [kind, setKind] = useState("custom");
  const [responseMode, setResponseMode] = useState<DebugResponseMode>(session.record?.response_mode ?? "fast");
  const [now, setNow] = useState(Date.now());
  const chatRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const followTail = useRef(true);
  const composing = useRef(false);
  const staleNotified = useRef<string | null>(null);
  const record = session.record;
  const active = Boolean(record && !isTerminal(record.status));
  const missingWiring = state.design?.component_ids.find(id => !componentComplete(state.design!, state.guide, id));
  const latestObservation = record?.observations?.at(-1);
  const latestVisualObservation = [...(record?.observations ?? [])].reverse().find(item => item.observation_kind !== "conversation" && item.capture_ids.length > 0);
  const currentInstruction = record?.instruction || record?.report?.next_step || tr("正在整理本次證據。", "Collecting this session's evidence.");
  const sameInstruction = (left?: string, right?: string) => Boolean(left && right &&
    left.replace(/[\s\p{P}]+/gu, "").toLowerCase() === right.replace(/[\s\p{P}]+/gu, "").toLowerCase());
  const awaitingReply = record?.phase === "awaiting_user";
  const captureHint = record?.status === "awaiting_capture" && !awaitingReply && !record.model_busy && record.capture_task?.instruction &&
    !sameInstruction(record.capture_task.instruction, currentInstruction) &&
    !sameInstruction(record.capture_task.instruction, latestObservation?.next_step)
    ? record.capture_task.instruction : null;
  const messages: DebugMessage[] = record?.messages?.length ? record.messages : record ? [
    { id: "initial", role: "user", text: record.symptom, created_at: record.observations?.[0]?.created_at ?? record.updated_at },
    ...(record.observations ?? []).map(observation => ({
      id: observation.id, role: "assistant" as const,
      text: [observation.seen, observation.explanation, observation.next_step]
        .filter((text, index, values): text is string => Boolean(text && !values.slice(0, index).some(value => sameInstruction(value, text))))
        .join("\n\n"),
      created_at: observation.created_at, capture_ids: observation.capture_ids, model: observation.model,
    })),
  ] : [];
  const lastMessage = messages.at(-1);
  const normalize = (value: string) => value.replace(/[\s\p{P}]+/gu, "").toLowerCase();
  const instructionAlreadyShown = lastMessage?.role === "assistant" &&
    normalize(lastMessage.text).includes(normalize(currentInstruction));
  const elapsedSeconds = record?.model_started_at ? Math.max(0, Math.floor((now - record.model_started_at * 1000) / 1000)) : null;
  const binding = record?.binding;
  const sameProject = !binding?.project_id || binding.project_id === state.design?.id;
  const sameCode = !binding?.code_hash || !currentCodeHash || binding.code_hash === currentCodeHash;
  const sameWiring = !binding?.test_keys || sameDebugTestKeys(binding.test_keys, context.test_keys);
  // A newly created session can know the new camera revision before the
  // browser's config request catches up. Only trust that lag when the server
  // confirms this session still uses the current camera.
  const sameCamera = !record?.camera || cameraSource === null || cameraRuntimeRevision === null ||
    (record.camera.source === cameraSource && (record.camera.runtime_revision === cameraRuntimeRevision ||
      (record.camera_current === true && record.camera.runtime_revision > cameraRuntimeRevision)));
  const current = record?.current_target !== false && record?.camera_current !== false && sameProject && sameCode && sameWiring && sameCamera;
  const canStart = Boolean(state.design && webcamReady && !session.pending);
  const canAct = Boolean(active && record?.phase !== "backend_restarted" && current && webcamReady && !session.pending && (!binding?.code_hash || currentCodeHash));
  const approvedRepairCode = record?.status === "awaiting_repair" && sameProject && sameWiring && sameCamera &&
    record.current_target !== false && record.camera_current !== false && !sameCode &&
    Boolean(repairAppliedHash && repairAppliedHash === currentCodeHash && repairCaseId === record?.diagnosis?.case_id);
  const canResumeRepair = Boolean(approvedRepairCode && !session.pending && webcamReady);
  const expectedModules = state.design?.component_ids.filter(id => id === "hc-sr04" || id === "mrd-tf240-8p-cs") ?? [];
  const testOutcomes = expectedModules.map(id => [...(record?.test_results ?? [])].reverse().find(run => run.component_id === id && !run.invalidated)?.outcome);
  const componentOutcome = !current ? tr("紀錄已過期", "Record is stale")
    : expectedModules.length > 0 && testOutcomes.every(value => value === "passed") ? tr("功能通過", "Function passed")
    : testOutcomes.some(value => value === "awaiting_confirmation") ? tr("等待實體確認", "Waiting for physical confirmation")
    : testOutcomes.some(value => value === "failed" || value === "inconclusive") ? tr("未通過／不確定", "Failed or uncertain")
    : testOutcomes.some(value => value === "running") ? tr("測試中", "Testing")
    : tr("尚未通過", "Not yet passed");
  const wholeOutcome = !current ? tr("紀錄已過期", "Record is stale")
    : record?.trial_result?.outcome === "passed" ? tr("試跑通過", "Trial passed")
    : record?.trial_result?.outcome === "awaiting_confirmation" ? tr("等待目視確認", "Waiting for visual confirmation")
    : record?.trial_result?.outcome === "failed" || record?.trial_result?.outcome === "inconclusive" ? tr("未通過／不確定", "Failed or uncertain")
    : record?.trial_result?.outcome === "running" ? tr("試跑中", "Trial running")
    : tr("尚未通過", "Not yet passed");

  useEffect(() => {
    if (active && record?.diagnosis?.case_id && record.diagnosis.case_id !== state.debug?.caseId) onCase(record.diagnosis.case_id);
  }, [active, record?.diagnosis?.case_id, state.debug?.caseId, onCase]);
  useEffect(() => { if (record?.id) setEntry(""); }, [record?.id]);
  useLayoutEffect(() => {
    const input = composerRef.current;
    if (!input) return;
    const resize = () => {
      input.style.height = "0px";
      input.style.height = `${input.scrollHeight}px`;
    };
    resize();
    let width = input.clientWidth;
    const observer = new ResizeObserver(() => {
      if (input.clientWidth === width) return;
      width = input.clientWidth;
      resize();
    });
    observer.observe(input);
    return () => observer.disconnect();
  }, [entry]);
  useEffect(() => { if (record?.response_mode) setResponseMode(record.response_mode); }, [record?.id, record?.response_mode]);
  useEffect(() => {
    if (!record?.model_busy) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [record?.model_busy, record?.model_started_at]);
  useEffect(() => {
    if (chatRef.current && followTail.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages.length, record?.phase, record?.model_busy]);
  useEffect(() => {
    if (!record || !active || record.phase === "backend_restarted" || current || approvedRepairCode || !sameProject || record.current_target === false || !currentCodeHash || cameraSource === null || cameraRuntimeRevision === null) return;
    if (staleNotified.current === record.id) return;
    staleNotified.current = record.id;
    void session.contextChanged(context);
  }, [record?.id, active, current, approvedRepairCode, sameProject, currentCodeHash, cameraSource, cameraRuntimeRevision, context, session]);

  const examples: Record<string, [string, string]> = {
    distance: ["HC-SR04+ 測不到距離，請檢查感測器與目標。", "HC-SR04+ has no distance reading. Check the sensor and target."],
    display: ["MRD-TFT240 沒有畫面或顏色不對，請檢查螢幕。", "MRD-TFT240 has no picture or wrong colors. Check the display."],
    program: ["作品執行後沒有反應，請檢查程式、距離與螢幕。", "The project does not respond. Check its code, distance readings, and display."],
  };
  function selectKind(value: string) {
    setKind(value);
    if (examples[value]) setEntry(tr(...examples[value]));
  }
  async function send() {
    const text = entry.trim() || (!active ? tr("請查看目前 Webcam 畫面，結合 Pi 狀態與作品程式，找出需要確認的異常並引導我完成下一步。", "Inspect the current Webcam image alongside Pi status and the project code, identify what needs checking, and guide my next step.") : "");
    if (!text || session.pending || record?.model_busy) return;
    if (active) {
      if (!canAct) return;
      const result = await session.action("message", context, text, responseMode);
      if (result) setEntry("");
    } else if (canStart) {
      const result = await session.create(context, text, state.aiModel, state.aiEffort, responseMode);
      if (result) setEntry("");
    }
  }
  function act(actionName: DebugSessionAction) { void session.action(actionName, context, undefined, responseMode); }
  function onComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) {
      event.preventDefault();
      void send();
    }
  }
  const statusName: Record<string, string> = {
    diagnosing: tr("正在檢查", "Checking"), awaiting_capture: tr("等待拍攝", "Waiting for capture"),
    awaiting_ready: tr("等待你擺好目標", "Waiting for your setup"), testing: tr("正在測試", "Testing"),
    awaiting_visual: tr("等待螢幕目視確認", "Waiting for screen confirmation"),
    awaiting_repair: tr("檢查程式修復", "Reviewing code repair"),
    awaiting_trial_visual: tr("等待試跑目視確認", "Waiting for trial confirmation"),
    complete: tr("本次除錯完成", "Debug session complete"), paused: tr("已暫停", "Paused"),
    stopped: tr("已停止", "Stopped"), error: tr("執行出錯", "Error"),
  };
  const frameUrl = (sessionId: string, id: string) => `/api/debug/sessions/${encodeURIComponent(sessionId)}/evidence/${encodeURIComponent(id)}`;
  const cameraVerdict = record?.camera_verdict === "read_current_frame" ? tr("鏡頭讀到本次畫面", "Camera read this test's frame")
    : record?.camera_verdict === "display_abnormal" ? tr("鏡頭看到畫面異常", "Camera saw an abnormal display")
    : record?.camera_verdict === "inconclusive" ? tr("鏡頭尚無法判定", "Camera cannot determine the result") : null;
  const readableError = (value: string) => {
    const messages: Record<string, [string, string]> = {
      session_active: ["這台 Pi 已有另一個 AI 除錯工作階段。請先停止該工作階段。", "This Pi already has an active AI debug session. Stop it first."],
      webcam_required: ["請先啟用 Webcam。", "Enable a Webcam first."],
      webcam_restore_required: ["請先從 Eye 恢復 Webcam。", "Restore the Webcam from Eye first."],
      wiring_confirmation_required: ["請回到 03 完成逐腳接線確認。", "Complete the pin confirmations in step 03."],
      wiring_confirmation_changed: ["接線確認已更新，請重新開始本次除錯。", "Wiring confirmations changed. Start a new debug session."],
      pi5_required: ["請切換到 Raspberry Pi 5 工作流程。", "Switch to the Raspberry Pi 5 workflow."],
      stale_debug_context: ["作品或接線已變更，請重新開始除錯。", "The project or wiring changed. Start a new debug session."],
      camera_changed: ["鏡頭已變更，請重新開始除錯。", "The camera changed. Start a new debug session."],
      camera_source_unavailable: ["目前無法取得 Webcam 來源，請確認鏡頭已連接並啟用。", "The Webcam source is unavailable. Check that the camera is connected and enabled."],
      camera_frame_unavailable: ["尚未收到鏡頭畫面。請確認 Webcam 有畫面後再拍照。", "No camera image is available. Wait for the Webcam image, then capture again."],
      camera_frame_not_new: ["還沒有取得新的鏡頭影格。請確認畫面持續更新後再拍照。", "No fresh camera frame arrived. Check that the video is updating, then capture again."],
      camera_frame_invalid: ["這次鏡頭影格無法讀取，請重新拍照。", "This camera frame could not be read. Capture again."],
      camera_encode_failed: ["這次照片無法編碼，請重新拍照。", "This photo could not be encoded. Capture again."],
      camera_frame_too_large: ["這次照片超過大小上限，請降低鏡頭解析度後重試。", "This photo exceeds the size limit. Lower the camera resolution and retry."],
      "Codex request timed out": ["雲端 AI 回應逾時，請按下方按鈕重新拍照分析。", "Cloud AI timed out. Use the button below to capture and analyze again."],
      "AI generation failed": ["雲端 AI 這次未完成分析，請按下方按鈕重新拍照分析。", "Cloud AI could not finish this analysis. Use the button below to capture and analyze again."],
      model_call_limit_reached: ["本次 AI 分析已達上限，請查看現有證據。", "This session reached its AI analysis limit. Review the evidence."],
      model_call_in_progress: ["AI 正在回覆，請等這一輪完成後再傳送。", "AI is replying. Wait for this turn before sending another message."],
      backend_restarted: ["後端已重新啟動。請先核對 Pi 工作狀態並停止舊案件，再以目前作品開始新案件。", "The backend restarted. Check the Pi job state, stop this old session, then start a new one with the current project."],
      restart_requires_new_session: ["重啟後的案件僅供檢視。請停止舊案件，再開始新的 AI 除錯。", "A session from before the restart is read only. Stop it, then start a new AI debug session."],
      restart_requires_stop: ["請先核對 Pi 工作並停止重啟前的案件，再開始新的 AI 除錯。", "Check Pi jobs and stop the session from before the restart before starting a new one."],
    };
    return messages[value] ? tr(...messages[value]) : value.startsWith("HTTP ") ? tr("除錯服務暫時無法回應，請稍後再試。", "The debug service is unavailable. Try again shortly.") : value;
  };

  return <section className="ai-debug-panel" aria-labelledby="ai-debug-heading">
    <div className="ai-debug-head">
      <div><h3 id="ai-debug-heading">{tr("與 AI 一起除錯", "Debug with AI")}</h3><span className="ai-debug-model">{record?.model || state.aiModel || "Codex"} · {tr("沿用目前作品與接線資料", "Using this project's wiring and specifications")}</span></div>
      <div className="ai-debug-head-actions">{active ? <button type="button" disabled={session.pending} onClick={() => act("stop")}>{tr("停止本次除錯", "Stop this session")}</button> : null}<button type="button" className="workflow-secondary" onClick={onManual}>{tr("手動測試工具", "Manual test tools")}</button></div>
    </div>
    {!webcamReady ? <div className="guide-caution" role="status">
      <p>{eyeActive ? tr("目前是 Eye 畫面。請先恢復 Webcam，再開始 AI 協作除錯。", "Eye is active. Restore the Webcam before starting AI guided debugging.") : tr("請先啟用 Webcam，才能用相機協作除錯。", "Enable a Webcam before camera guided debugging.")}</p>
      {eyeActive ? <button type="button" onClick={onReturnWebcam}>{tr("返回 Webcam", "Restore Webcam")}</button> : null}
    </div> : null}
    {!state.design ? <p className="guide-caution">{tr("先建立作品，系統才能對照目前接線、程式與測試結果。", "Create a project so the system can compare its wiring, code, and tests.")}</p> : null}
    <div className="ai-debug-chat" ref={chatRef} role="log" aria-label={tr("AI 除錯對話", "AI debugging conversation")} aria-live="polite" aria-relevant="additions" onScroll={event => {
      const node = event.currentTarget;
      followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
    }}>
      {!record ? <div className="ai-debug-welcome"><span className="ai-debug-avatar">AI</span><h4>{tr("哪裡沒有照預期運作？", "What isn't working as expected?")}</h4><p>{tr("直接告訴我。我會看目前的鏡頭畫面，對照 Pi 與作品資料，接著一步一步排查。", "Tell me what's happening. I'll inspect the camera image and your project's Pi data, then guide you step by step.")}</p>{missingWiring ? <p className="workflow-muted">{tr("可以先讓 AI 看畫面並引導排查；硬體測試前再完成接線確認。", "AI can inspect the image first; confirm wiring before hardware tests.")}</p> : null}</div> : null}
      {messages.map(message => <article key={message.id} className={`ai-debug-message is-${message.role}`} data-message-id={message.id}>
        <div className="ai-debug-message-meta"><strong>{message.role === "user" ? tr("你", "You") : "AI"}</strong><time>{epochTime(message.created_at)}</time>{message.role === "assistant" && message.elapsed_ms != null ? <span>{(message.elapsed_ms / 1000).toFixed(1)} s</span> : null}</div>
        <p>{message.text}</p>
        {message.capture_ids?.length ? <div className="ai-debug-message-photos">{message.capture_ids.map(id => {
          const photo = record?.evidence.find(item => item.id === id);
          return photo && photo.available !== false && record ? <a key={id} href={frameUrl(record.id, id)} target="_blank" rel="noreferrer"><img src={frameUrl(record.id, id)} alt={tr("AI 本次查看的鏡頭照片", "Camera image reviewed for this reply")} loading="lazy" /><small>{tr("拍攝於", "Captured")} {epochTime(photo.captured_at)}</small></a> : <small key={id}>{tr("此輪照片已過期", "This turn's photo has expired")}</small>;
        })}</div> : null}
        {message.role === "assistant" && message.model ? <small className="ai-debug-message-model">{message.model}</small> : null}
      </article>)}
    {record ? <>
      <div className="ai-debug-current">
        <div className="ai-debug-current-title"><span className="workflow-eyebrow">{tr("目前這一步", "Current step")}</span><strong>{record.phase === "backend_restarted" ? tr("重啟後的舊紀錄", "Record after restart") : record.model_busy ? tr("雲端 AI 分析中", "Cloud AI is analyzing") : awaitingReply ? tr("等待你回覆", "Waiting for your reply") : statusName[record.status] ?? record.status}</strong></div>
        {!instructionAlreadyShown && !record.model_busy ? <p>{currentInstruction}</p> : null}
        {record.phase === "backend_restarted" ? <p className="guide-caution" role="status">{tr("此案件僅供檢視，不能接續自動測試。請先在執行管理核對 Pi 工作，停止本次除錯後，使用目前作品重新開始。", "This session is read only and cannot resume automated tests. Check Pi jobs in Execution, stop this session, then start again with the current project.")}</p> : null}
        {record.phase === "wiring_required" && missingWiring ? <button type="button" onClick={() => onWiring(missingWiring)}>{tr("完成 03 接線確認", "Complete wiring confirmation in 03")}</button> : null}
        {record.error && (active || record.status === "error") && record.phase !== "backend_restarted" ? <p className="pi-error" role="alert">{readableError(record.error)}</p> : null}
        {record.model_busy ? <div className="ai-debug-busy" role="status"><p><span className="ai-debug-busy-dot" />{record.model_capture_ids?.length ? tr("正在分析本次拍攝的畫面", "Analyzing the images just captured") : tr("正在閱讀你的訊息與除錯紀錄", "Reviewing your message and debugging history")}{elapsedSeconds != null ? ` · ${elapsedSeconds} ${tr("秒", "s")}` : "…"}</p><small>{elapsedSeconds !== null && elapsedSeconds >= 30 ? tr("這一輪需要較久時間；回覆完成後會直接顯示在對話中。", "This turn is taking longer. The reply will appear here when ready.") : tr("你可以先輸入下一則訊息，等回覆完成後送出。", "You can draft your next message while waiting for the reply.")}</small></div> : null}
        {captureHint ? <p className="ai-debug-capture-hint">{tr("拍攝提示", "Framing tip")}: {captureHint}</p> : null}
        {active && !current ? <p className="guide-caution">{!sameProject ? tr("這台 Pi 正在處理另一個作品的 AI 除錯。請先停止該工作階段，再開始目前作品。", "This Pi has an active AI debug session for another project. Stop that session before starting this project.") : approvedRepairCode ? tr("修復已改變草稿；請在下方確認修改，完成後接回本次試跑。", "The repair changed the draft. Confirm the change below, then resume this trial.") : tr("作品、接線、程式或相機已變更。請停止舊工作階段並重新檢查。", "The project, wiring, code, or camera changed. Stop the old session and check again.")}</p> : null}
        {record.status === "awaiting_capture" && !awaitingReply && !record.model_busy ? ["guided_observation", "capture_needed"].includes(record.phase)
          ? <div className="ai-debug-actions"><span>{latestObservation ? tr("照上方指示調整後，讓 AI 再看一次。", "Follow the guidance above, then let AI look again.") : tr("依錯誤提示處理後，重新拍照分析。", "Address the error above, then capture and analyze again.")}</span><button type="button" className="guide-primary-action" disabled={!canAct} onClick={() => act("capture")}>{latestObservation ? tr("已調整，讓 AI 再看", "Adjusted, let AI look again") : tr("重新拍照分析", "Capture and analyze again")}</button></div>
          : <div className="ai-debug-actions"><span>{tr("取景到位後會自動拍攝；也可以手動擷取。", "The system captures when framing is ready. You can also capture manually.")}</span><button type="button" disabled={!canAct} onClick={() => act("capture")}>{tr("手動拍照", "Capture now")}</button></div> : null}
        {record.status === "awaiting_ready" ? <button type="button" className="guide-primary-action" disabled={!canAct} onClick={() => act("ready")}>{tr("準備好了，取得新讀值", "Ready, take fresh readings")}</button> : null}
        {record.status === "awaiting_visual" ? <div className="ai-debug-actions"><button type="button" onClick={() => onRetest("mrd-tf240-8p-cs")}>{tr("前往螢幕目視確認", "Review the physical screen")}</button><button type="button" disabled={!canAct} onClick={() => act("continue")}>{tr("完成確認後繼續", "Continue after confirmation")}</button></div> : null}
        {record.status === "awaiting_repair" ? <div className="ai-debug-actions"><button type="button" disabled={!record.diagnosis?.case_id || repairCaseId !== record.diagnosis.case_id || record.phase !== "repair_ready"} onClick={onReviewRepair}>{tr("查看診斷與修復提案", "Review diagnosis and repair")}</button>{record.phase === "repair_ready" && !(repairCandidateReady && repairCaseId === record.diagnosis?.case_id) && !approvedRepairCode && (record.budget?.model_calls ?? 0) < (record.budget?.max_model_calls ?? 6) ? <button type="button" disabled={!canAct} onClick={() => act("analyse")}>{tr("請 AI 分析程式邏輯", "Ask AI to review code logic")}</button> : null}{approvedRepairCode ? <button type="button" className="guide-primary-action" disabled={!canResumeRepair} onClick={() => act("continue")}>{tr("修復已確認，接回試跑", "Repair confirmed, resume trial")}</button> : null}</div> : null}
        {record.status === "awaiting_trial_visual" ? <div className="ai-debug-actions"><button type="button" onClick={onTrial}>{tr("前往 60 秒試跑結果", "Review the 60-second trial")}</button><button type="button" disabled={!canAct} onClick={() => act("continue")}>{tr("完成目視確認後繼續", "Continue after visual confirmation")}</button></div> : null}
        {record.status === "paused" && !["context_changed", "camera_changed", "backend_restarted"].includes(record.phase) && !(record.phase === "wiring_required" && missingWiring) && current && webcamReady ? <button type="button" disabled={session.pending} onClick={() => act("continue")}>{tr("重新檢查後繼續", "Recheck and continue")}</button> : null}
      </div>
    </> : null}
    </div>
    <div className="ai-debug-entry ai-debug-composer">
      {!active ? <div className="ai-debug-quick" role="group" aria-label={tr("常見現象", "Common symptoms")}>
        {(["distance", "display", "program"] as const).map(value => <button key={value} type="button" aria-pressed={kind === value} onClick={() => selectKind(value)}>{value === "distance" ? tr("測不到距離", "No distance reading") : value === "display" ? tr("螢幕異常", "Screen issue") : tr("作品沒反應", "Not responding")}</button>)}
      </div> : null}
      <label htmlFor="ai-debug-message">{awaitingReply ? tr("回覆 AI 的問題", "Answer AI's question") : tr("傳訊息給 AI", "Message AI")}</label>
      <textarea ref={composerRef} id="ai-debug-message" value={entry} onChange={event => setEntry(event.target.value)} onKeyDown={onComposerKeyDown} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} rows={1} placeholder={active ? tr("直接回覆，或說明你剛才做了什麼…", "Reply, or describe what you just tried…") : tr("例如：螢幕亮著，但沒有顯示距離", "For example: the screen is on, but no distance appears")} />
      <div className="ai-debug-composer-toolbar"><label className="ai-debug-response-mode"><span>{tr("回覆方式", "Response style")}</span><select value={responseMode} disabled={Boolean(record?.model_busy || session.pending)} onChange={event => setResponseMode(event.target.value as DebugResponseMode)}><option value="fast">{tr("快速引導", "Quick guidance")}</option><option value="thorough">{tr("深入分析", "Detailed analysis")}</option></select></label><div className="ai-debug-composer-send">{record?.status === "awaiting_capture" && awaitingReply && !record.model_busy ? <button type="button" disabled={!canAct} onClick={() => act("capture")}>{tr("拍目前畫面", "Capture current view")}</button> : null}<button type="button" className="guide-primary-action" disabled={Boolean(record?.model_busy || (active ? !canAct || !entry.trim() : !canStart))} onClick={() => void send()}>{session.pending ? tr("傳送中…", "Sending…") : active ? tr("送出", "Send") : tr("幫我檢查", "Check for me")}</button></div></div>
      <small className="ai-debug-composer-hint">{tr("Enter 傳送 · Shift + Enter 換行", "Enter to send · Shift + Enter for a new line")}</small>
      {session.error ? <p className="pi-error" role="alert">{readableError(session.error)}</p> : null}
    </div>
    <details className="ai-debug-session-details"><summary>{tr("照片使用與檢查紀錄", "Photo use and inspection records")}</summary>
    <p className="ai-debug-disclosure">{tr("開始後，本次選取的 Webcam 照片與遮蔽密碼、金鑰後的診斷資料會送給上方選擇的 Codex 模型分析。文字回覆沿用本次對話；需要新畫面時，才重新拍照。", "After you start, selected Webcam photos and diagnostics with passwords and keys redacted are sent to the Codex model selected above. Text replies use this conversation; a new photo is captured when needed.")}</p>
    {record ? <>
      <div className="ai-debug-evidence-levels" aria-label={tr("證據層級", "Evidence levels")}>
        <span>{tr("AI 看圖", "AI camera view")}: {cameraVerdict ?? (latestVisualObservation?.visibility === "clear" ? tr("畫面可讀", "Readable") : latestVisualObservation ? tr("尚不確定", "Uncertain") : tr("尚未觀察", "Not observed"))}</span>
        <span>{tr("零件功能", "Component function")}: {componentOutcome}</span>
        <span>{tr("整體作品", "Whole project")}: {wholeOutcome}</span>
      </div>
      {cameraVerdict ? <p className="ai-debug-camera-verdict">{cameraVerdict} · {tr("相機觀察仍需正式測試與人工目視確認。", "Camera observations still need fixed tests and human visual confirmation.")}</p> : null}
      {record.report ? <section className="ai-debug-report"><h4>{tr("本次結果", "Session result")}</h4>
        {record.report.confirmed?.length ? <><strong>{tr("已確認", "Confirmed")}</strong><ul>{record.report.confirmed.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
        {record.report.uncertain?.length ? <><strong>{tr("仍不確定", "Still uncertain")}</strong><ul>{record.report.uncertain.map((item, index) => <li key={index}>{item}</li>)}</ul></> : null}
        {record.report.next_step && !sameInstruction(record.report.next_step, currentInstruction) && !messages.some(message => normalize(message.text).includes(normalize(record.report!.next_step))) ? <p>{record.report.next_step}</p> : null}</section> : null}
      <details className="ai-debug-timeline"><summary>{tr("照片、測試與工作紀錄", "Photos, tests, and activity")} ({(record.evidence?.length ?? 0) + (record.jobs?.length ?? 0)})</summary>
        <ol>{[...(record.evidence ?? [])].reverse().map(item => <li key={item.id}>{item.available === false ? <span>{item.target} · frame {item.frame_id} · {tr("照片已過期", "Photo expired")}</span> : <a href={frameUrl(record.id, item.id)} target="_blank" rel="noreferrer">{item.target} · frame {item.frame_id}</a>} <time>{epochTime(item.captured_at)}</time> {item.phase ?? ""}</li>)}</ol>
        <ul>{(record.jobs ?? []).map(job => <li key={job.id}>{job.component_id ?? job.kind} · {job.state}{job.error ? ` · ${job.error}` : ""}</li>)}</ul>
        {record.budget ? <small>{tr("AI 呼叫", "AI calls")} {record.budget.model_calls}/{record.budget.max_model_calls} · {tr("照片", "Photos")} {record.budget.captures}/{record.budget.max_captures}</small> : null}
      </details>
    </> : null}
    </details>
  </section>;
}
