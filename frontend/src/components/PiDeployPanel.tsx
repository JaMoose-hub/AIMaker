import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "../lib/i18n";
import { connectPi, deployPi, fetchPiStatus, type PiStatus } from "../lib/piApi";
import { piPhotoresistorExample } from "../lib/wiringGuideProfiles";
import type { ProjectDesign } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";

const DRAFT_KEY = "boardvision.pi-python-draft.v1";

function initialCode(): string {
  try {
    return window.localStorage.getItem(DRAFT_KEY) ?? piPhotoresistorExample();
  } catch {
    return piPhotoresistorExample();
  }
}

export function PiDeployPanel({ project, draft, onDraftChange }: { project?: ProjectDesign; draft?: string; onDraftChange?: (code: string) => void }) {
  const { t } = useI18n();
  const tr = useMakerText();
  const [localCode, setCode] = useState(initialCode);
  const code = draft ?? localCode;
  const [saved, setSaved] = useState(true);
  const [status, setStatus] = useState<PiStatus | null>(null);
  const [pending, setPending] = useState<"connect" | "deploy" | null>(null);
  const [networkError, setNetworkError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const requestActive = useRef(false);
  const consoleRef = useRef<HTMLPreElement>(null);
  const followOutput = useRef(true);
  const logs = status?.logs.join("\n") ?? "";
  const busy = pending !== null || Boolean(status?.busy) || Boolean(status?.component_test_id);
  const connected = Boolean(status?.connected) && !networkError;
  const error = status?.connection_error || status?.error || actionError;
  const hasDisplay = project?.component_ids.includes("mrd-tf240-8p-cs");

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function poll() {
      if (!requestActive.current) {
        try {
          const next = await fetchPiStatus();
          if (!cancelled && !requestActive.current) {
            setStatus(next);
            setNetworkError(false);
          }
        } catch {
          if (!cancelled) setNetworkError(true);
        }
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), 1000);
    }
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, []);

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

  async function perform(action: "connect" | "deploy") {
    if (requestActive.current || busy) return;
    requestActive.current = true;
    setPending(action);
    setActionError(null);
    try {
      const result = await (action === "connect" ? connectPi() : deployPi(code, project ? { component_ids: project.component_ids, catalog_version: project.catalog_version, profile_versions: project.profile_versions } : undefined));
      setStatus(result.status);
      setNetworkError(false);
      if (!result.ok) setActionError(result.error ?? t("pi.actionFailed"));
    } catch (failure) {
      setNetworkError(true);
      setActionError(failure instanceof Error ? failure.message : t("pi.actionFailed"));
    } finally {
      requestActive.current = false;
      setPending(null);
    }
  }

  return <section className="pi-deploy-panel" aria-label={t("pi.title")}>
    <div className="pi-panel-heading">
      <div><div className="card-kicker">{t("pi.kicker")}</div><h2>{t("pi.title")}</h2></div>
      <span className={`pi-connection ${connected ? "connected" : ""}`} role="status">
        <span aria-hidden="true">●</span> {t(connected ? "pi.connected" : "pi.disconnected")}
      </span>
    </div>
    <div className="pi-target">
      <code>{status ? `${status.username}@${status.host}` : "Raspberry Pi 5"}</code>
      <button type="button" className="pi-connect-button" disabled={busy || networkError}
        onClick={() => void perform("connect")}>{t(pending === "connect" ? "pi.connecting" : "pi.connect")}</button>
    </div>
    <p className="pi-intro">{project ? project.title : t("pi.intro")}</p>
    {status?.component_test_id ? <p className="guide-caution" role="status">{tr("零件測試尚未結束或停止待確認。請返回 Pin 接線引導完成／停止該測試，再部署作品。", "A component test is pending or its stop is unconfirmed. Return to Pin wiring to complete/stop it before deploying.")}</p> : null}
    {project ? <small className="maker-muted">{tr("載入作品不會自動部署。下方狀態來自 Pi 目前服務，可能是上次部署的程式。", "Loading a project does not deploy it. Status below is the current Pi service, possibly an earlier program.")}</small> : null}
    {project?.unresolved.length ? <pre className="pi-error" role="alert">{project.unresolved.join("\n")}</pre> : null}
    {hasDisplay ? <div className="guide-module-review" aria-label={tr("螢幕首次測試", "First display test")}>
      <strong>ILI9341 · 240×320</strong>
      <p>{tr("接線方案：VCC → Pin 17（3.3V），BLK 留空。照片已確認型號；上電前仍須核對模組支援 3.3V。", "Plan: VCC → Pin 17 (3.3V), BLK disconnected. Photos confirm identity; verify module supply compatibility before power-on.")}</p>
      <p>{tr("核對後接 Pi USB-C 電源 → 連線 Pi → 部署。先看 3 秒 RGB 色塊／文字，再看距離與警告；無回波顯示 NO ECHO。", "After checking, connect Pi USB-C power → Connect Pi → Deploy. Check the 3-second RGB/text card, then distance and warnings; missing echoes show NO ECHO.")}</p>
      <small>{tr("只有螢幕的作品會保留測試圖。BLK 留空若未亮，先核對背光規格；不要改接 5V 或任意 GPIO。", "Display-only projects keep the test card. If BLK left open does not light the backlight, check its specifications; do not switch to 5V or an arbitrary GPIO.")}</small>
    </div> : null}
    {project ? <details><summary>{tr("執行環境與硬體準備", "Runtime prerequisites")}</summary>
      <p>{tr("部署前檢查目錄指定的 GPIO 套件，不自動安裝 AI 指定的依賴。", "Catalog GPIO dependencies are checked before deployment; AI cannot install packages.")}</p>
      <code>{project.requirements.imports.join(", ") || tr("驅動待確認", "Drivers pending")}</code>
      {hasDisplay ? <>
        <p>{tr("在 Pi 終端機準備一次：raspi-config → Interface Options → SPI → Enable。以下指令由你手動執行，本頁不會自動安裝。", "Prepare once on the Pi: raspi-config → Interface Options → SPI → Enable. Run the following commands manually; this page does not install packages automatically.")}</p>
        <pre>{`sudo apt install python3-venv python3-gpiozero python3-lgpio python3-spidev python3-pil\npython3 -m venv --system-site-packages ${status?.remote_dir ?? "~/Desktop/Pi_deployer"}/.venv\n${status?.remote_dir ?? "~/Desktop/Pi_deployer"}/.venv/bin/python -m pip install luma.lcd==2.13.0`}</pre>
      </> : null}
      {project.requirements.devices.length ? <p>{tr("規格核實後，需先在 Pi 啟用對應 I²C／SPI 介面並檢查裝置：", "After specifications are confirmed, enable the required I²C / SPI interface and check: ")}{project.requirements.devices.join(", ")}</p> : null}
    </details> : null}
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
    <button type="button" className="pi-deploy-button"
      disabled={!connected || busy || !code.trim() || Boolean(project?.unresolved.length)} onClick={() => void perform("deploy")}>
      {t(pending === "deploy" || status?.busy ? "pi.deploying" : "pi.deploy")}
    </button>
    <div className="pi-status-lines" role="status">
      <span>{t("pi.deploymentLabel")} · {t(`pi.deployment.${status?.deployment ?? "idle"}`)}</span>
      <span>{t("pi.programLabel")} · {t(`pi.program.${networkError ? "unknown" : status?.program ?? "unknown"}`)}
        {status?.exit_code != null && status.program !== "running" ? ` (${status.exit_code})` : ""}</span>
    </div>
    {networkError ? <p className="pi-error" role="alert">{t("pi.networkError")}</p> : null}
    {error ? <pre className="pi-error" role="alert">{error}</pre> : null}
    <div className="pi-console-heading"><span>{t("pi.output")}</span><small>{t("pi.outputLimit")}</small></div>
    <pre ref={consoleRef} className="pi-console" aria-label={t("pi.output")} tabIndex={0}
      onScroll={(event) => {
        const el = event.currentTarget;
        followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
      }}>{logs || t("pi.noOutput")}</pre>
    <small className="pi-footer">{project ? tr("SSH 斷線後仍會執行；Pi 重開機後需再次部署。此頁輸出不等於硬體測試通過。", "Execution continues after SSH disconnects; redeploy after Pi reboot. Output is not a hardware pass.") : t("pi.rebootHint")}</small>
  </section>;
}
