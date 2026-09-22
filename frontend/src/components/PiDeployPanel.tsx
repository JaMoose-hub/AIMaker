import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "../lib/i18n";
import { deployPi, executionPending } from "../lib/piApi";
import { usePiConnection } from "../lib/PiConnection";
import { piPhotoresistorExample } from "../lib/wiringGuideProfiles";
import type { ProjectDesign, MakerState } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";

const DRAFT_KEY = "boardvision.pi-python-draft.v1";

function initialCode(): string {
  try {
    return window.localStorage.getItem(DRAFT_KEY) ?? piPhotoresistorExample();
  } catch {
    return piPhotoresistorExample();
  }
}

export function PiDeployPanel({ project, draft, onDraftChange, onDebug }: { project?: ProjectDesign; draft?: string; onDraftChange?: (code: string) => void; onDebug?: (evidence:NonNullable<MakerState['debug']>['deployment']) => void }) {
  const { t } = useI18n();
  const tr = useMakerText();
  const [localCode, setCode] = useState(initialCode);
  const code = draft ?? localCode;
  const [saved, setSaved] = useState(true);
  const pi = usePiConnection();
  const { status, pending, networkError } = pi;
  const consoleRef = useRef<HTMLPreElement>(null);
  const followOutput = useRef(true);
  const logs = status?.logs.join("\n") ?? "";
  const busy = pending;
  const connected = Boolean(status?.connected) && !networkError;
  const error = status?.connection_error || status?.error || pi.error;
  const queued = status?.execution?.jobs.some(job => job.kind === "deploy" && executionPending(job));
  const hasDisplay = project?.component_ids.includes("mrd-tf240-8p-cs");
  const failed = Boolean(error || status?.deployment === "failed" || status?.program === "failed");
  const running = connected && status?.program === "running";
  const transferring = ["preparing", "uploading", "checking", "starting"].includes(status?.deployment ?? "");
  // Connection setup belongs to the shared toolbar. Show this panel only when
  // there is program activity/evidence, including stale evidence after disconnect.
  const hasRunStatus = Boolean(queued || (status?.deployment && status.deployment !== "idle")
    || (status?.program && !["unknown", "not_deployed"].includes(status.program))
    || status?.version || status?.invocation_id || logs);
  const launchHint = !connected
    ? tr("先按上方「連線 Pi」，連上後就能啟動作品。", "Connect Pi at the top, then start your project.")
    : project?.unresolved.length
      ? tr("還有接線或規格需要確認，請先查看下方提醒。", "Some wiring or specifications still need checking. Review the notes below.")
      : !code.trim()
        ? tr("還沒有可執行的程式。請展開「查看或修改程式」補上內容，或回到設計頁準備作品。", "There is no code to run yet. Open View or edit code, or return to Design to prepare your project.")
      : queued
        ? tr("已安排執行。若上方出現交接提示，請先確認是否停止目前程式。", "Your project is queued. Confirm any handoff request at the top before it starts.")
        : tr("按下後會把這份程式傳到 Pi 並啟動；如果已有程式在執行，會先請你確認停止。", "Sends this program to Pi and starts it. If another program is running, you will be asked before it is stopped.");
  function diagnoseCurrent() {
    onDebug?.({invocation_id:status?.invocation_id,code_hash:status?.version?.code_hash,run_id:status?.version?.run_id,exit_code:status?.exit_code??null,logs:status?.logs?.slice(-60),captured_at:Date.now()/1000});
  }

  useEffect(() => {
    const target = consoleRef.current;
    if (target && followOutput.current) target.scrollTop = target.scrollHeight;
  }, [logs]);

  function updateCode(value: string) {
    if (onDraftChange) { onDraftChange(value); return; }
    setCode(value);
    try {
      window.localStorage.setItem(DRAFT_KEY, value);
      setSaved(true);
    } catch { setSaved(false); }
  }

  function indent(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Tab" || event.shiftKey) return;
    event.preventDefault();
    const editor = event.currentTarget;
    const start = editor.selectionStart;
    updateCode(code.slice(0, start) + "    " + code.slice(editor.selectionEnd));
    window.requestAnimationFrame(() => editor.setSelectionRange(start + 4, start + 4));
  }

  return <section className="pi-deploy-panel" aria-label={tr("部署與執行", "Deploy & run")}>
    <div className="pi-panel-heading workflow-heading">
      <div><div className="workflow-eyebrow">{tr("05 · 部署與執行", "05 · Deploy & run")}</div><h2>{tr("讓作品開始運作", "Bring your project to life")}</h2>
        <p className="workflow-subtitle">{tr("不用手動複製程式。確認接線後，就可以在 Pi 上啟動。", "No manual code copying. Check the wiring, then start the project on Pi.")}</p></div>
    </div>
    <div className="deploy-overview">
      <section className="deploy-launch workflow-surface">
        <span className="workflow-eyebrow">{tr("準備啟動的作品", "Your project")}</span>
        <h3>{project?.title || tr("自訂 Pi 程式", "Custom Pi program")}</h3>
        <div className="workflow-chips"><span>Raspberry Pi 5</span>{project?.component_ids.map(id=><span key={id}>{id==="hc-sr04"?"HC-SR04+":id==="mrd-tf240-8p-cs"?"MRD-TFT240":id}</span>)}</div>
        <p className="deploy-launch-hint" role="status">{launchHint}</p>
        <button type="button" className="pi-deploy-button"
          disabled={!connected || !status?.execution || busy || queued || !code.trim() || Boolean(project?.unresolved.length)} onClick={() => void pi.perform(() => deployPi(code, project ? {id:project.id,component_ids:project.component_ids,catalog_version:project.catalog_version,profile_versions:project.profile_versions} : undefined))}>
          {queued ? tr("已加入執行佇列", "Waiting to start") : busy ? tr("正在送出…", "Sending…") : tr("部署並啟動作品", "Deploy & start project")}
        </button>
        <small>{tr("一次只執行一個程式，不會和零件測試同時運作。", "Only one program runs at a time, including component tests.")}</small>
        {hasDisplay?<small>{tr("MRD-TFT240：先核對支援 3.3V 再上電；BLK 留空，不自行改接 5V。", "MRD-TFT240: verify 3.3V support before power-on. Leave BLK disconnected; do not switch to 5V.")}</small>:null}
        {status && !status.execution ? <p className="guide-caution" role="status">{tr("請重新啟動 Board Vision 後端，啟用共用執行佇列後再部署。", "Restart the Board Vision backend to enable the shared queue before deploying.")}</p> : null}
        {project?.unresolved.length ? <div className="guide-caution" role="alert"><b>{tr("先確認這些項目", "Check these items first")}</b><ul>{project.unresolved.map((item,index)=><li key={index}>{item}</li>)}</ul></div> : null}
      </section>
      {hasRunStatus ? <section className="deploy-live workflow-surface">
        <span className="workflow-eyebrow">{tr("作品執行狀態", "Program activity")}</span>
        <h3 className={`workflow-state ${!connected?"neutral":failed?"warning":running?"good":"neutral"}`} role="status">
          {!connected?tr("執行狀態待確認", "Program status needs checking"):failed?tr("程式需要檢查", "The program needs attention"):queued?tr("等待開始", "Waiting to start"):transferring?tr("正在準備作品", "Preparing your project"):running?tr("程式執行中", "A program is running"):tr("目前沒有確認到執行中的程式", "No running program confirmed")}
        </h3>
        <p>{!connected?tr("暫時無法更新狀態，Pi 上的程式可能仍在執行。以下保留上次紀錄，恢復連線後會重新核對。", "Status updates are unavailable; the program may still be running on Pi. The last record is kept below and will be checked when the connection returns."):failed?tr("先不要急著重接線。到「測試與除錯」，我們會帶你檢查原因。", "Don't rewire yet. Test & debug will help you find the next step."):tr("這裡是 Pi 上目前程式的狀態，可能是上次啟動的作品，不代表這份作品已通過測試。", "This is the current Pi program, possibly an earlier project. It does not mean this project passed its tests.")}</p>
        <div className="pi-status-lines" role="status">
          <span>{t("pi.deploymentLabel")} · {t(`pi.deployment.${status?.deployment ?? "idle"}`)}</span>
          <span>{t("pi.programLabel")} · {t(`pi.program.${!connected ? "unknown" : status?.program ?? "unknown"}`)}</span>
        </div>
        {onDebug ? <button type="button" className="workflow-secondary" onClick={diagnoseCurrent}>{tr("沒有反應？幫我檢查", "No response? Help me check")}</button> : null}
        {networkError ? <p className="pi-error" role="alert">{t("pi.networkError")}</p> : null}
        {error ? <p className="pi-error" role="alert">{tr("這次操作遇到問題，原因已保存在下方「執行紀錄」。", "Something went wrong. Details are saved under Run details below.")}</p> : null}
      </section> : null}
    </div>
    {hasDisplay ? <aside className="deploy-observe">
      <h3>{tr("啟動後，看這裡", "After starting, look for this")}</h3>
      <p>{tr("看 MRD-TFT240：先出現約 3 秒的紅、綠、藍與文字，再觀察作品畫面。", "Watch MRD-TFT240: about 3 seconds of red, green, blue and text, then the project display.")}</p>
      <small>{project?.component_ids.includes("hc-sr04")?tr("移動前方物體，確認距離跟著改變。NO ECHO 表示目前沒有有效距離，不能當作正常測距。", "Move an object in front of the sensor and check that distance changes. NO ECHO means no valid reading."):tr("只有螢幕的作品會保留測試圖，請確認實體畫面正常。", "Display-only projects keep the test card. Check the physical screen.")}</small>
    </aside> : null}
    <p className="workflow-safety">{tr("改接線前先斷電，接好再上電。執行成功不代表所有接線與電壓都已驗證。", "Power off before rewiring. A running program does not verify every connection or voltage.")}</p>
    <details className="workflow-details deploy-code"><summary><strong>{tr("查看或修改程式", "View or edit code")}</strong><span>{tr("選用 · 已準備好，不需要手動貼上", "Optional · prepared for you")}</span></summary>
    <div className="workflow-details-body">
    <div className="pi-editor-heading">
      <label htmlFor="pi-python-code">{t("pi.editor")}</label>
      {project && code !== project.code ? <button type="button" className="pi-text-button" onClick={() => {
        if (window.confirm(tr("以新版作品程式替換目前編輯器內容？", "Replace the current editor content with the updated project program?"))) updateCode(project.code);
      }}>{tr("載入新版作品程式", "Load updated project program")}</button> : null}
      {!project ? <button type="button" className="pi-text-button" onClick={() => updateCode(piPhotoresistorExample())}>
        {t("pi.example")}
      </button> : null}
    </div>
    <textarea id="pi-python-code" className="pi-code-editor" value={code}
      onChange={(event) => updateCode(event.currentTarget.value)} onKeyDown={indent}
      spellCheck={false} autoCapitalize="off" autoCorrect="off" wrap="off" />
    <div className="pi-editor-foot"><small>{t(saved ? "pi.saved" : "pi.saveFailed")}</small><small>{t("pi.indent")}</small></div>
    </div></details>
    {project ? <details className="workflow-details"><summary><strong>{tr("第一次使用？查看準備事項", "First time? Check the setup")}</strong><span>{tr("供電、螢幕與 Pi 環境", "Power, display and Pi setup")}</span></summary><div className="workflow-details-body">
      {hasDisplay ? <>
        <h3>MRD-TFT240 · ILI9341 · 240×320</h3>
        <p>{tr("VCC → Pin 17（3.3V），BLK 留空；上電前先核對模組支援 3.3V。若螢幕不亮，先核對背光規格，不要改接 5V 或任意 GPIO。", "VCC → Pin 17 (3.3V), BLK disconnected. Check 3.3V support before powering on. If the screen stays dark, check backlight specifications; do not switch to 5V or an arbitrary GPIO.")}</p>
      </> : null}
      <p>{tr("部署前檢查目錄指定的 GPIO 套件，不自動安裝 AI 指定的依賴。", "Catalog GPIO dependencies are checked before deployment; AI cannot install packages.")}</p>
      <code>{project.requirements.imports.join(", ") || tr("驅動待確認", "Drivers pending")}</code>
      {hasDisplay ? <>
        <p>{tr("在 Pi 終端機準備一次：raspi-config → Interface Options → SPI → Enable。以下指令由你手動執行，本頁不會自動安裝。", "Prepare once on the Pi: raspi-config → Interface Options → SPI → Enable. Run the following commands manually; this page does not install packages automatically.")}</p>
        <pre>{`sudo apt install python3-venv python3-gpiozero python3-lgpio python3-spidev python3-pil\npython3 -m venv --system-site-packages ${status?.remote_dir ?? "~/Desktop/Pi_deployer"}/.venv\n${status?.remote_dir ?? "~/Desktop/Pi_deployer"}/.venv/bin/python -m pip install luma.lcd==2.13.0`}</pre>
      </> : null}
      {project.requirements.devices.length ? <p>{tr("規格核實後，需先在 Pi 啟用對應 I²C／SPI 介面並檢查裝置：", "After specifications are confirmed, enable the required I²C / SPI interface and check: ")}{project.requirements.devices.join(", ")}</p> : null}
    </div></details> : null}
    <details className="workflow-details deploy-logs"><summary><strong>{tr("執行紀錄", "Run details")}</strong><span>{tr("需要時再展開 · 訊息與版本", "Messages and version, when you need them")}</span></summary><div className="workflow-details-body">
    <small>{tr("實際執行版本", "Running version")}: {status?.version?.code_hash.slice(0,12) ?? tr("尚未取得", "Not available")}{status?.exit_code!=null?` · ${tr("結束代碼", "Exit code")}: ${status.exit_code}`:""}</small>
    {error ? <pre className="pi-error" role="alert">{error}</pre> : null}
    <div className="pi-console-heading"><span>{t("pi.output")}</span><small>{t("pi.outputLimit")}</small></div>
    <pre ref={consoleRef} className="pi-console" aria-label={t("pi.output")} tabIndex={0}
      onScroll={(event) => {
        const el = event.currentTarget;
        followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
      }}>{logs || t("pi.noOutput")}</pre>
    </div></details>
    <small className="pi-footer">{project ? tr("SSH 斷線後仍會執行；Pi 重開機後需再次部署。此頁輸出不等於硬體測試通過。", "Execution continues after SSH disconnects; redeploy after Pi reboot. Output is not a hardware pass.") : t("pi.rebootHint")}</small>
  </section>;
}
