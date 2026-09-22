import { useState } from "react";
import { useMakerText } from "../lib/useMaker";
import { componentComplete, componentTestKey, missingDependencyMessage, testReasons } from "../lib/componentTests";
import type { useComponentTests } from "../lib/useComponentTests";
import type { ProjectDesign, ProjectGuideState } from "../lib/maker";

export function ComponentTestCard({ design, session, tests, onViewWiring, onDebug, view = "all" }: {
  design: ProjectDesign; session: ProjectGuideState; tests: ReturnType<typeof useComponentTests>;
  view?: "all" | "controls" | "results";
  onViewWiring: () => void;
  onDebug?: (componentId: string, runId?: string, symptom?: string) => void;
}) {
  const tr = useMakerText();
  const cid = design.component_ids[session.componentIndex];
  const complete = componentComplete(design, session, cid);
  const key = componentTestKey(design, session, cid);
  const last = tests.status.results.filter(r => r.component_id === cid).at(-1);
  const queued = tests.status.execution?.jobs.find(job => job.kind === "test" && job.project_id === design.id
    && job.component_id === cid && job.guide_key === key && !["finished", "failed", "cancelled"].includes(job.state));
  const lastJob = tests.status.execution?.jobs.filter(job => job.kind === "test" && job.project_id === design.id
    && job.component_id === cid && job.guide_key === key).at(-1);
  const failedJob = lastJob?.state === "failed" && (lastJob.created_at ?? 0) >= (last?.created_at ?? 0) ? lastJob : null;
  const active = tests.status.active;
  const foreign = active && (active.project_id !== design.id || active.component_id !== cid);
  const run = (view === "results" && foreign ? null : active) ?? (failedJob ? undefined : last);
  const stale = Boolean(run && (run.invalidated || run.guide_key !== key || (foreign && run === active)));
  const [choice, setChoice] = useState<{runId:string; code:string; normal:boolean}>({runId:"",code:"",normal:false});
  const [copied, setCopied] = useState(false);
  const [openedAt] = useState(() => Date.now() / 1000);
  if (!complete && !active && !last) return null;
  const reason = tests.error ?? failedJob?.reason ?? (stale && (!foreign || view === "results") ? "wiring_changed" : run?.reason);
  const detail = (reason === "missing_dependency" ? missingDependencyMessage(failedJob?.error ?? run?.detail ?? "", failedJob ? "preflight" : run?.failed_phase ?? run?.phase) : null)
    ?? (reason ? testReasons[reason] : null);
  const outcome = failedJob || (tests.error && run?.reserved) ? "inconclusive" : stale && (!foreign || view === "results") ? "inconclusive" : run?.outcome;
  const labels = {running: tr("測試中", "Testing"), awaiting_confirmation: tr("等待使用者確認", "Awaiting confirmation"),
    passed: tr("功能通過", "Function passed"), failed: tr("未通過", "Not passed"), inconclusive: tr("無法判定", "Inconclusive")};
  const phase = run?.phase;
  const historical = Boolean(run && !run.reserved && (run.finished_at ?? run.created_at) < openedAt);
  const busy = tests.pending;
  const canAct = run?.reserved && !stale && !tests.error && !["connection_lost", "remote_state_unknown"].includes(run.reason ?? "");
  const name = cid === "hc-sr04" ? "HC-SR04+" : "MRD-TFT240";
  const phases: Record<string,string> = {
    preflight: tr("檢查 Pi 連線、套件與裝置權限", "Checking Pi connection, dependencies and devices"),
    starting: tr("啟動本次測試", "Starting this test"),
    awaiting_stop_consent: tr("環境已就緒；原作品仍在執行", "Environment ready; original project is running"),
    awaiting_near: tr("請將平整物體放在感測器前方約 15 公分，再按「準備好了」。", "Place a flat target about 15 cm in front, then press Ready."),
    awaiting_far: tr("請將同一物體移遠至約 30 公分，再按「準備好了」。", "Move the same target to about 30 cm, then press Ready."),
    sampling_near: tr("近距離取樣中，請保持 5 秒", "Sampling near position; hold for 5 seconds"),
    sampling_far: tr("遠距離取樣中，請保持 5 秒", "Sampling far position; hold for 5 seconds"),
    display_red: tr("顯示紅色", "Displaying red"), display_lime: tr("顯示綠色", "Displaying green"), display_blue: tr("顯示藍色", "Displaying blue"),
    display_code: tr("正在顯示四位測試碼，至少保留 15 秒。請看實體螢幕，記下數字；稍後再確認結果。", "Showing the four-digit code for at least 15 seconds. Read the physical screen and note the code; confirm afterwards."),
    awaiting_visual: tr("請選出實體螢幕上看到的四位數字，並確認三色正常。沒看到數字請勿猜選或勾選通過。", "Select the four digits you saw on the physical screen and confirm the colors. Do not guess or confirm a pass if no code was visible."),
    reconnecting: tr("重新查詢遠端測試，不會重複啟動", "Rechecking remote test without starting another"),
  };
  return <section className="component-test-card" aria-label={tr("零件功能測試", "Component function test")}>
    {view === "controls" && foreign ? <p role="status">{tr("其他零件仍在測試；下方停止按鈕會停止該次測試。新測試須經上方執行管理確認交接。", "Another component is testing; Stop below stops that run. Confirm handoff in Execution before the next test.")}</p> : null}
    {onDebug && (reason || outcome === "failed" || outcome === "inconclusive") ? <button type="button" onClick={() => onDebug(cid, run?.id, reason ?? undefined)}>{tr("前往除錯", "Troubleshoot")}</button> : null}
    {view !== "controls" ? <><header><span>{tr("零件功能測試", "COMPONENT TEST")} · {view !== "results" && foreign ? run?.component_id : name}</span>
      <strong className={`test-outcome ${outcome ?? "untested"}`} role="status">{outcome ? labels[outcome] : tr("未測試", "Not tested")}</strong></header>
    {foreign ? <p>{tr("另一個零件仍在測試。可以將本零件加入佇列，並在上方「執行管理」確認停止與交接。", "Another component is testing. Queue this module and confirm handoff in Execution above.")}</p> : null}
    {queued && queued.state !== "running" ? <p className="guide-caution" role="status">{tr("本零件已加入執行佇列；請看上方「執行管理」的交接提示。", "This module is queued. Check Execution above for the handoff prompt.")}</p> : null}
    {failedJob ? <p role="alert">{tr("本次未能啟動測試", "This test could not start")}: {failedJob.error}</p> : null}
    {run && !run.reserved ? <small>{historical ? tr("上次測試紀錄", "Last test record") : tr("本次測試結果", "This test result")} · {new Date((run.finished_at ?? run.created_at)*1000).toLocaleString()}{historical ? tr("（先前保存，非目前接線證據）", " (saved history, not current wiring evidence)") : ""}</small> : null}
    {outcome === "passed" && run?.evidence === "user_visual_confirmation" ? <small>{tr("判定依據：本次測試碼及顏色由使用者目視確認。", "Evidence: the user visually confirmed this run's code and colors.")}</small> : null}
    </> : null}
    {view !== "results" ? <div className="test-next-step" role="status">{detail ? tr(...detail) : tests.error ? tr("狀態更新失敗，請查看診斷或重新連線。", "Status update failed. Check diagnostics or reconnect.") : run?.reserved ? phases[phase ?? ""] ?? tr("等待本次測試回報", "Waiting for test progress") : historical ? tr("這是先前紀錄；可重新測試確認目前接線。", "This is a saved record. Retest to check the current wiring.") : outcome === "passed" ? tr("本次功能測試通過，可以繼續下一個零件。", "This function test passed. Continue to the next component.") : tr("接好並核對供電後，可執行一次零件測試。", "After wiring and checking power ratings, run a component test.")}</div> : null}
    {view !== "controls" ? <>
    {run?.component_id === "hc-sr04" && run.reserved ? <p className="test-reading">{run.latest && !tests.error && !stale && Date.now()/1000-run.latest.at < 2 ? run.latest.cm.toFixed(1) : "—"} <small>cm</small></p> : null}
    {run && (run.reserved || Object.keys(run.samples).length > 0) ? <div className="test-facts">
      {run.reserved ? <span>{tr("最後回報時間", "Last report time")}: {run.heartbeat_at ? new Date(run.heartbeat_at*1000).toLocaleString() : tr("等待首次回報", "Waiting for first report")}</span> : null}
      {Object.entries(run.samples).map(([phase, sample]) => <span key={phase}>{phase === "near" ? tr("近", "Near") : tr("遠", "Far")}: {sample.count} {tr("筆", "samples")} · {sample.median_cm ?? "—"} cm</span>)}</div> : null}
    </> : null}
    {view !== "results" ? <><div className="test-actions">
      {!tests.status.connected ? <small>{tr("請使用上方「連線 Pi」", "Use Connect Pi at the top")}</small> : null}
      {complete && (!active || foreign) && !queued ? <button className="guide-primary-action" disabled={busy || !tests.status.connected} onClick={() => {setCopied(false);void tests.start(cid);}}>{busy ? tr("處理中…", "Working…") : `${tr(last ? "重新測試" : "測試", last ? "Retest" : "Test")} ${name}`}</button> : null}
      {canAct && phase === "awaiting_stop_consent" ? <button className="guide-primary-action" disabled={busy} onClick={() => void tests.action(run, "stop_project")}>{tr("確認停止原作品，開始測試", "Stop original project and test")}</button> : null}
      {canAct && (phase === "awaiting_near" || phase === "awaiting_far") ? <button className="guide-primary-action" disabled={busy} onClick={() => void tests.action(run, phase === "awaiting_near" ? "near" : "far")}>{tr("準備好了，取樣 5 秒", "Ready · sample for 5 seconds")}</button> : null}
      {run?.reserved ? <button disabled={busy} onClick={() => void tests.action(run, "stop")}>{tr("停止本次測試", "Stop this test")}</button> : null}
      <button disabled={busy} onClick={onViewWiring}>{tr("查看本零件接線", "Review module wiring")}</button>
    </div>
    {canAct && phase === "awaiting_visual" ? <fieldset disabled={busy} className="test-visual-confirm"><legend>{tr("本次螢幕顯示哪個數字？", "Which code is on the screen?")}</legend>
      <div className="test-code-options">{run.options.map(code => <label key={code}><input type="radio" name={`test-code-${run.id}`} checked={choice.runId === run.id && choice.code === code}
        onChange={() => setChoice(c => ({runId:run.id,code,normal:c.runId === run.id && c.normal}))} />{code}</label>)}</div>
      <label><input type="checkbox" checked={choice.runId === run.id && choice.normal} onChange={event => setChoice(c => ({runId:run.id,code:c.runId === run.id ? c.code : "",normal:event.target.checked}))} />{tr("紅、綠、藍三色正常", "Red, green and blue were normal")}</label>
      <button disabled={choice.runId !== run.id || !choice.code || !choice.normal} onClick={() => void tests.action(run, "visual", {code:choice.code,appearance:"normal"})}>{tr("確認顯示結果", "Confirm display result")}</button>
      <div className="test-actions">{([['black','全黑','Black screen'],['white','白屏','White screen'],['abnormal','亂碼／顏色異常','Abnormal image/colors']] as const).map(([appearance,zh,en]) => <button key={appearance} onClick={() => void tests.action(run,"visual",{appearance})}>{tr(zh,en)}</button>)}</div>
    </fieldset> : null}
    </> : null}
    {view !== "controls" ? <details><summary>{tr("診斷與環境設定", "Diagnostics and setup")}</summary>
      <p>{tr("Pi 需先準備 gpiozero、lgpio；TFT 另需 spidev、Pillow、luma.lcd 2.13.0 與 SPI0。沿用部署頁的環境設定，不會自動安裝。", "Prepare gpiozero/lgpio on Pi; TFT also needs spidev, Pillow, luma.lcd 2.13.0 and SPI0. Use the deployment setup instructions; nothing is installed automatically.")}</p>
      <p>{tr("缺套件：到「05 部署與執行 → 執行環境與硬體準備」，依指定部署目錄建立虛擬環境並手動安裝套件。SPI：在 Pi 執行 sudo raspi-config → Interface Options → SPI。權限：用 id 與 ls -l /dev/gpiochip* /dev/spidev0.0 核對群組與裝置權限，調整後重新登入。", "Dependencies: open 05 Deploy & run → Runtime prerequisites and prepare the configured virtual environment manually. SPI: sudo raspi-config → Interface Options → SPI. Permissions: compare id with ls -l /dev/gpiochip* /dev/spidev0.0 and log in again after correcting groups.")}</p>
      <pre>{JSON.stringify(run ? {id:run.id,target:run.target_id,phase:run.phase,failed_phase:run.failed_phase,reason:run.reason,error:tests.error,detail:run.detail,exit_code:run.exit_code,latest_valid_at:run.latest_valid_at,template:run.template_version,samples:run.samples,logs:run.logs} : {error:tests.error},null,2)}</pre>
      <button onClick={() => { void navigator.clipboard.writeText(JSON.stringify({run,error:tests.error},null,2)).then(()=>setCopied(true)).catch(()=>setCopied(false)); }}>{tr(copied ? "已複製" : "複製診斷", copied ? "Copied" : "Copy diagnostics")}</button>
    </details> : null}
    {view !== "results" ? <small>{tr("改接線前斷電，接好再上電測試。功能通過不等於所有線路與電壓均已驗證。", "Power off before rewiring. Function success is not complete electrical verification.")}</small> : null}
  </section>;
}
