import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { DeploySplitLayout } from "./DeploySplitLayout";
import { useI18n } from "../lib/i18n";
import { deployPi, executionPending, programOwner, stopPiProgram } from "../lib/piApi";
import { usePiConnection } from "../lib/PiConnection";
import { piPhotoresistorExample } from "../lib/wiringGuideProfiles";
import type { ProjectDesign, MakerState } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { systemText } from "../lib/systemText";

const DRAFT_KEY = "boardvision.pi-python-draft.v1";

function initialCode(): string {
  try {
    return window.localStorage.getItem(DRAFT_KEY) ?? piPhotoresistorExample();
  } catch {
    return piPhotoresistorExample();
  }
}

export function PiDeployPanel({ project, draft, onDraftChange, onDebug, livePreview }: { project?: ProjectDesign; draft?: string; onDraftChange?: (code: string) => void; onDebug?: (evidence:NonNullable<MakerState['debug']>['deployment']) => void; livePreview?: ReactNode }) {
  const { t, locale } = useI18n();
  const tr = useMakerText();
  const [localCode, setCode] = useState(initialCode);
  const code = draft ?? localCode;
  const [saved, setSaved] = useState(true);
  const [editorHeight, setEditorHeight] = useState(() => { try { return Math.min(640, Math.max(160, Number(localStorage.getItem("boardvision.code-height.v1")) || 200)); } catch { return 200; } });
  const pi = usePiConnection();
  const { status, pending, networkError } = pi;
  const consoleRef = useRef<HTMLPreElement>(null);
  const followOutput = useRef(true);
  const logs = status?.logs.join("\n") ?? "";
  const busy = pending;
  const connected = Boolean(status?.connected) && !networkError;
  const error = status?.connection_error || status?.error || pi.error;
  const queued = status?.execution?.jobs.some(job => job.kind === "deploy" && executionPending(job));
  const failed = Boolean(error || status?.deployment === "failed" || status?.program === "failed");
  const running = connected && status?.program === "running";
  const transferring = ["preparing", "uploading", "checking", "starting"].includes(status?.deployment ?? "");
  const deployNotice = !connected
    ? tr("先連線 Pi，才能部署程式。", "Connect Pi before deploying.")
    : !status?.execution
      ? tr("請重新啟動 Tinkro 後端，再部署程式。", "Restart the Tinkro backend before deploying.")
      : project?.unresolved.length
        ? tr("請先確認接線或規格問題，才能部署。", "Resolve the wiring or specification issues before deploying.")
        : !code.trim()
          ? tr("請先填入程式碼。", "Add program code before deploying.")
          : null;
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

  const stopAction = running ? <button type="button" disabled={pending || !programOwner(status)} onClick={() => { const owner = programOwner(status); if (owner) void pi.perform(() => stopPiProgram(owner)); }}>{tr("停止作品", "Stop project")}</button> : null;
  const debugAction = onDebug ? <button type="button" className="workflow-secondary" onClick={diagnoseCurrent}>{tr("沒有反應？幫我檢查", "No response? Help me check")}</button> : null;
  const runtimeInfo = <>
    <p className="deploy-output-context">{!connected ? tr("暫時無法更新狀態；恢復連線後會重新核對。", "Status updates are unavailable. They will refresh after reconnecting.") : failed ? tr("先查看錯誤訊息，再請右側 AI 分析原因。", "Review the error, then ask the AI on the right to analyze it.") : tr("顯示 Pi 程式狀態與最近輸出。", "Shows Pi program status and recent output.")}</p>
    <small className="deploy-version">{tr("執行版本", "Running version")}: {status?.version?.code_hash.slice(0,12) ?? tr("尚未取得", "Not available")}{status?.exit_code!=null?` · ${tr("結束代碼", "Exit code")}: ${status.exit_code}`:""}</small>
  </>;

  return <section className="pi-deploy-panel" aria-label={tr("部署與執行", "Deploy & run")}>
    <div className="pi-panel-heading workflow-heading deploy-project-heading">
      <div><div className="workflow-eyebrow">{tr("03 · 部署與執行", "03 · Deploy & run")}</div>
        <h2>{project?.title ? project.source === "demo" ? systemText(project.title, locale) : project.title : tr("自訂 Pi 程式", "Custom Pi program")}</h2>
        <p className="deploy-project-meta">Raspberry Pi 5{project?.component_ids.map(id => ` · ${id === "hc-sr04" ? "HC-SR04+" : id === "mrd-tf240-8p-cs" ? "MRD-TFT240" : id}`).join("")}</p></div>
    </div>
    <DeploySplitLayout editorHeight={editorHeight}>
      <div className="deploy-primary-column">
        <section className="deploy-code-card workflow-surface">
          <div className="deploy-section-heading deploy-code-title">
            <div><span className="workflow-eyebrow">{tr("作品程式", "Project code")}</span><h3>{project ? tr("AI 設計程式", "AI-designed code") : tr("Pi 程式碼", "Pi code")}</h3></div>
            <button type="button" className="pi-deploy-button deploy-code-deploy"
              disabled={!connected || !status?.execution || busy || queued || !code.trim() || Boolean(project?.unresolved.length)} onClick={() => void pi.perform(() => deployPi(code, project ? {id:project.id,component_ids:project.component_ids,catalog_version:project.catalog_version,profile_versions:project.profile_versions} : undefined))}>
              {queued ? tr("已加入佇列", "Queued") : busy ? tr("送出中…", "Sending…") : tr("部署並啟動", "Deploy & start")}
            </button>
          </div>
          <p className="deploy-code-description">{tr("部署前先檢視或修改；部署時會使用目前編輯器中的版本。", "Review or edit before deploying. The current editor contents are sent to Pi.")}</p>
          {deployNotice ? <p className="deploy-action-notice" role="status">{deployNotice}</p> : null}
          {project?.unresolved.length ? <ul className="deploy-blockers" role="alert">{project.unresolved.map((item,index)=><li key={index}>{item}</li>)}</ul> : null}
          <div className="pi-editor-heading">
            <label htmlFor="pi-python-code">{t("pi.editor")}</label>
            {project && code !== project.code ? <button type="button" className="pi-text-button" onClick={() => {
              if (window.confirm(tr("以新版作品程式替換目前編輯器內容？", "Replace the current editor content with the updated project program?"))) updateCode(project.code);
            }}>{tr("載入新版作品程式", "Load updated project program")}</button> : null}
            {!project ? <button type="button" className="pi-text-button" onClick={() => updateCode(piPhotoresistorExample())}>{t("pi.example")}</button> : null}
          </div>
          <textarea id="pi-python-code" className="pi-code-editor" value={code}
            onChange={(event) => updateCode(event.currentTarget.value)} onKeyDown={indent}
            spellCheck={false} autoCapitalize="off" autoCorrect="off" wrap="off" />
          <div className="pi-editor-foot"><small>{t(saved ? "pi.saved" : "pi.saveFailed")}</small><small>{t("pi.indent")}</small></div>
          {livePreview ? <label className="assistant-code-height">{tr("程式區高度", "Editor height")}<input type="range" min={160} max={640} step={20} value={editorHeight} onChange={event => { const value = Number(event.target.value); setEditorHeight(value); try { localStorage.setItem("boardvision.code-height.v1", String(value)); } catch { /* session only */ } }} /></label> : null}
        </section>
      </div>
      <div className={`deploy-results-column${livePreview ? ' has-live-preview' : ''}`}>
        {livePreview}
        <section className="deploy-output workflow-surface" aria-label={tr("輸出結果", "Output results")}>
          <div className="deploy-section-heading"><div><span className="workflow-eyebrow">{tr("執行監控", "RUNTIME")}</span><h3>{tr("輸出結果", "Output results")}</h3></div>
            <span className={`deploy-output-indicator ${!connected ? "neutral" : failed ? "warning" : running ? "good" : queued || transferring ? "working" : "neutral"}`}>
              {!connected ? tr("Pi 狀態待確認", "Pi status unknown") : failed ? tr("需要檢查", "Needs attention") : queued ? tr("排隊中", "Queued") : transferring ? tr("部署中", "Deploying") : running ? tr("執行中", "Running") : tr("待機", "Idle")}
            </span></div>
          <div className="pi-status-lines" role="status"><span>{t("pi.deploymentLabel")} · {t(`pi.deployment.${status?.deployment ?? "idle"}`)}</span><span>{t("pi.programLabel")} · {t(`pi.program.${!connected ? "unknown" : status?.program ?? "unknown"}`)}</span></div>
          {!livePreview ? <label className="assistant-code-height">{tr("程式區高度", "Editor height")}<input type="range" min={160} max={640} step={20} value={editorHeight} onChange={event => { const value = Number(event.target.value); setEditorHeight(value); try { localStorage.setItem("boardvision.code-height.v1", String(value)); } catch { /* session only */ } }} /></label> : null}
          {livePreview ? <div className="deploy-runtime-tools">
            <details className="deploy-output-details"><summary>{tr("執行資訊", "Run details")}</summary>{runtimeInfo}</details>
            {stopAction}{debugAction}
          </div> : <>{stopAction}{runtimeInfo}{debugAction}</>}
          {networkError ? <p className="pi-error" role="alert">{t("pi.networkError")}</p> : null}
          {error ? <pre className="pi-error" role="alert">{error}</pre> : null}
          <div className="pi-console-heading"><span>{t("pi.output")}</span><small>{t("pi.outputLimit")}</small></div>
          <pre ref={consoleRef} className="pi-console" aria-label={t("pi.output")} tabIndex={0}
            onScroll={(event) => {
              const el = event.currentTarget;
              followOutput.current = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
            }}>{logs || t("pi.noOutput")}</pre>
        </section>
      </div>
    </DeploySplitLayout>
  </section>;
}
