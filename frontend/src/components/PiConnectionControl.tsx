import { useEffect, useId, useRef, useState } from "react";
import { usePiConnection } from "../lib/PiConnection";
import { executionPending, programOwner, stopPiProgram } from "../lib/piApi";
import { useMakerText } from "../lib/useMaker";

export function PiConnectionControl() {
  const pi = usePiConnection(), tr = useMakerText();
  const status = pi.status;
  const connected = Boolean(status?.connected) && !pi.networkError;
  const jobs = status?.execution?.jobs ?? [];
  const pending = jobs.filter(executionPending);
  const question = pending.find(j => j.state === "awaiting_confirmation");
  const [menuOpen, setMenuOpen] = useState(Boolean(question));
  const controlRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const [stopConsent, setStopConsent] = useState<string | null>(null);
  const stopping = useRef(false);
  const owner = programOwner(status);
  const canStop = connected && Boolean(status?.execution) && Boolean(owner) && !pi.pending && !status?.busy
    && !status?.component_test_id && !pending.length && status?.program !== "stopping";
  const inactive = connected && !status?.pid && ["stopped", "exited", "failed", "not_deployed"].includes(status?.program ?? "unknown");
  const runtimeActive = connected && (Boolean(status?.component_test_id)
    || ["running", "starting", "stopping"].includes(status?.program ?? "unknown")
    || pending.some(job => job.state === "running"));
  const connectionLabel = pi.networkError ? tr("狀態未知", "State unknown")
    : pi.pending || status?.busy ? tr("處理中", "Working")
    : question ? tr("待確認", "Confirm handoff")
    : pi.error ? tr("操作失敗", "Action failed")
    : !connected ? tr("未連線", "Disconnected")
    : status?.program === "stopping" ? tr("停止中", "Stopping")
    : runtimeActive ? tr("執行中", "Running")
    : pending.length ? tr("排隊中", "Queued") : tr("已連線", "Connected");
  useEffect(() => { if (question) setMenuOpen(true); }, [question?.id]);
  useEffect(() => {
    if (!menuOpen) return;
    const outside = (event: Event) => {
      if (event.target instanceof Node && !controlRef.current?.contains(event.target)) {
        setMenuOpen(false); setStopConsent(null);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault(); setMenuOpen(false); setStopConsent(null);
      controlRef.current?.querySelector("summary")?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);
  const stopHint = !connected || status?.program === "unknown"
    ? tr("先連線並核對 Pi 狀態。", "Connect and verify the Pi state first.")
    : !status?.execution ? tr("請重啟 Tinkro 後端後再操作。", "Restart the Tinkro backend first.")
    : status.component_test_id ? tr("硬體測試仍在進行，請先在測試卡停止。", "Stop the active hardware test from its test card first.")
    : pending.length ? tr("請先取消下方排隊工作，避免停止後自動啟動。", "Cancel the queued jobs below first so they cannot start after stopping.")
    : status.busy ? tr("目前操作進行中，請稍候。", "An operation is in progress. Please wait.")
    : inactive ? tr("作品已停止，可以回接線引導重新開始。", "Project stopped. You can restart the wiring guide.")
    : !owner ? tr("無法確認作品程序，請重新連線。", "Cannot identify the project process. Reconnect first.") : null;
  const stopError = pi.error === "stop_queue_active" ? tr("有排隊工作，請先取消再停止作品。", "Cancel queued jobs before stopping the project.")
    : pi.error === "stop_test_active" ? tr("測試仍在進行，請先在測試卡停止。", "Stop the active test from its test card first.")
    : pi.error === "stop_owner_changed" ? tr("執行中的作品已變更，請重新確認停止。", "The running project changed. Confirm stopping again.")
    : pi.error === "stop_program_busy" ? tr("Pi 正在處理其他操作，請稍候。", "The Pi is handling another operation. Please wait.")
    : pi.error === "stop_state_unknown" ? tr("無法確認 Pi 作品程序，請重新連線再核對。", "Cannot verify the Pi project process. Reconnect and check again.")
    : pi.error === "stop_backend_restart_required" || pi.error === "Pi API: HTTP 404" ? tr("請重啟 Tinkro 後端，以啟用停止作品功能。", "Restart the Tinkro backend to enable Stop project.")
    : pi.error || pi.networkError ? tr("操作未確認成功，請核對 Pi 狀態後再試。", "Action not confirmed. Verify the Pi state before retrying.") : null;
  async function confirmStop() {
    if (!canStop || !stopConsent || stopConsent !== owner || stopping.current) return;
    stopping.current = true;
    const approved = stopConsent;
    setStopConsent(null);
    try { await pi.perform(() => stopPiProgram(approved)); }
    finally { stopping.current = false; }
  }
  const labels = {
    queued: tr("排隊中", "Queued"), preflight: tr("檢查環境", "Preflight"), awaiting_confirmation: tr("等待交接確認", "Confirm handoff"),
    stopping: tr("確認停止中", "Stopping"), blocked: tr("等待連線／核對", "Waiting for reconciliation"), running: tr("執行中", "Running"),
    finished: tr("已完成", "Completed"), failed: tr("未執行／失敗", "Failed"), cancelled: tr("已取消", "Cancelled"),
  };
  return <div ref={controlRef} className="pi-global-control pi-device-control" aria-label={tr("Pi 連線與執行管理", "Pi connection and execution")}>
    <div className="pi-global-row">
      <details className="pi-execution-menu pi-device-menu" open={menuOpen} onToggle={event => setMenuOpen(event.currentTarget.open)}>
        <summary className={`pi-device-trigger${connected ? " connected" : ""}${question || pi.error || pi.networkError ? " is-warning" : ""}`}
          aria-label={`${tr("Pi 連線與執行管理", "Pi connection and execution")} · ${connectionLabel}`}
          aria-expanded={menuOpen} aria-controls={menuId} aria-haspopup="dialog">
          <i className="pi-device-dot" aria-hidden="true" />
          <span className="pi-device-state" aria-live="polite">Pi · {connectionLabel}</span>
          {pending.length ? <span className="pi-device-count" title={tr("待處理工作", "Pending jobs")}>{pending.length}</span> : null}
          <span className="pi-device-chevron" aria-hidden="true">⌄</span>
        </summary>
        <div id={menuId} className="pi-execution-popover" role="dialog" aria-label={tr("Pi 連線與執行管理", "Pi connection and execution")}>
          <div className="pi-device-panel-heading">
            <div><strong>Raspberry Pi</strong>{status?.host ? <small>{status.username ? `${status.username}@` : ""}{status.host}</small> : null}</div>
            <button type="button" className={`pi-global-connect ${connected ? "connected" : ""}`}
              disabled={pi.pending || Boolean(status?.busy) || Boolean(status?.component_test_id)} onClick={() => void pi.connect()}>
              {pi.pending ? tr("處理中…", "Working…") : connected ? tr("重新連線", "Reconnect") : tr("連線 Pi", "Connect Pi")}
            </button>
          </div>
          <strong>{tr("一次執行一個，依序交接", "One program at a time · FIFO")}</strong>
          <section className="pi-project-control" aria-label={tr("作品執行控制", "Project runtime control")}>
            <p className="pi-current-owner" role="status">{tr("目前", "Current")}: {!connected ? tr("尚未連線／狀態未知", "Disconnected / unknown") : status?.component_test_id ? tr("硬體測試／整合試跑", "Hardware test / trial") : status?.program === "running" ? tr("作品程式執行中", "Project running") : status?.program === "starting" ? tr("作品啟動中", "Project starting") : status?.program === "stopping" ? tr("確認停止中", "Stopping") : inactive ? tr("作品已停止", "Project stopped") : tr("Pi 狀態待確認", "Pi state unconfirmed")}</p>
            <button type="button" className="pi-project-stop" disabled={!canStop} onClick={() => setStopConsent(owner)}>
              {tr("停止作品", "Stop project")}
            </button>
            {stopHint ? <small>{stopHint}</small> : null}
            {stopConsent ? <div className="pi-stop-confirmation" role="group" aria-label={tr("確認停止作品", "Confirm stopping project")}>
              <strong>{tr("停止目前的作品程式？", "Stop the current project program?")}</strong>
              <p>{tr("只停止 Pi 上的作品；保留程式、接線與 AI 紀錄，不關閉 Pi 或相機。", "Stops only the project on the Pi. Code, wiring and AI history are kept; the Pi and camera stay on.")}</p>
              {stopConsent !== owner ? <p role="alert">{tr("作品程序已變更，請取消後重新確認。", "The project process changed. Cancel and confirm again.")}</p> : null}
              <div><button type="button" className="pi-project-stop" disabled={!canStop || stopConsent !== owner} onClick={() => void confirmStop()}>{tr("確認停止", "Confirm stop")}</button>
                <button type="button" onClick={() => setStopConsent(null)}>{tr("取消", "Cancel")}</button></div>
            </div> : null}
            <small>{tr("停止程式不等於斷電；改接線前仍需關閉硬體電源。", "Stopping a program does not power off hardware. Turn off power before rewiring.")}</small>
            {stopError ? <p role="alert" title={pi.error ?? undefined}>{stopError}</p> : null}
          </section>
          <small>{tr("先確認停止目前程式，再執行下一個；不自動恢復舊作品。", "Confirm stopping the current program before the next; no automatic restore.")}</small>
          {jobs.slice(-8).map(job => <div className="pi-queue-job" key={job.id}>
            <div><strong>{job.label}</strong><span>{job.kind === "test" && job.state === "finished"
              ? job.result === "passed" ? tr("功能通過", "Function passed") : job.result === "failed" ? tr("未通過", "Not passed") : tr("已結束／無法判定", "Ended / inconclusive")
              : labels[job.state]}</span></div>
            {job.error ? <p role="alert">{job.error}</p> : null}
            {job.state === "awaiting_confirmation" ? <button className="guide-primary-action" disabled={pi.pending} onClick={() => void pi.action(job.id, "confirm", job.owner)}>
              {tr("確認停止目前程式，接著執行", "Confirm stop, then run next")}
            </button> : null}
            {["queued", "preflight", "awaiting_confirmation", "blocked"].includes(job.state) ? <button disabled={pi.pending} onClick={() => void pi.action(job.id, "cancel")}>{tr("取消排隊", "Cancel queued job")}</button> : null}
          </div>)}
          {!jobs.length ? <p>{tr("尚無排隊工作", "Queue is empty")}</p> : null}
          <small>{tr("重新整理會保留佇列；後端重啟會取消尚未開始的工作，不自動重跑。", "Refresh preserves the queue. Backend restart cancels waiting jobs without replay.")}</small>
        </div>
      </details>
      {runtimeActive ? <button type="button" className="pi-header-stop" disabled={!canStop} title={stopHint ?? tr("停止目前作品", "Stop the current project")}
        onClick={() => { setMenuOpen(true); setStopConsent(owner); }}>
        <span aria-hidden="true">■</span> {tr("停止", "Stop")}
      </button> : null}
    </div>
  </div>;
}
