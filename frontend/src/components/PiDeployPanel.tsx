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
  const busy = pending !== null || Boolean(status?.busy);
  const connected = Boolean(status?.connected) && !networkError;
  const error = status?.connection_error || status?.error || actionError;

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
    {project ? <small className="maker-muted">{tr("載入作品不會自動部署。下方狀態來自 Pi 目前服務，可能是上次部署的程式。", "Loading a project does not deploy it. Status below is the current Pi service, possibly an earlier program.")}</small> : null}
    {project?.unresolved.length ? <pre className="pi-error" role="alert">{project.unresolved.join("\n")}</pre> : null}
    {project ? <details><summary>{tr("執行環境與硬體準備", "Runtime prerequisites")}</summary>
      <p>{tr("部署前檢查目錄指定的 GPIO 套件，不自動安裝 AI 指定的依賴。", "Catalog GPIO dependencies are checked before deployment; AI cannot install packages.")}</p>
      <code>{project.requirements.imports.join(", ") || tr("驅動待確認", "Drivers pending")}</code>
      {project.requirements.devices.length ? <p>{tr("規格核實後，需先在 Pi 啟用對應 I²C／SPI 介面並檢查裝置：", "After specifications are confirmed, enable the required I²C / SPI interface and check: ")}{project.requirements.devices.join(", ")}</p> : null}
    </details> : null}
    <div className="pi-editor-heading">
      <label htmlFor="pi-python-code">{t("pi.editor")}</label>
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
