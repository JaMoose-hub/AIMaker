import { usePiConnection } from "../lib/PiConnection";
import { executionPending } from "../lib/piApi";
import { useMakerText } from "../lib/useMaker";

export function PiConnectionControl() {
  const pi = usePiConnection(), tr = useMakerText();
  const status = pi.status;
  const connected = Boolean(status?.connected) && !pi.networkError;
  const jobs = status?.execution?.jobs ?? [];
  const pending = jobs.filter(executionPending);
  const question = pending.find(j => j.state === "awaiting_confirmation");
  const labels = {
    queued: tr("排隊中", "Queued"), preflight: tr("檢查環境", "Preflight"), awaiting_confirmation: tr("等待交接確認", "Confirm handoff"),
    stopping: tr("確認停止中", "Stopping"), blocked: tr("等待連線／核對", "Waiting for reconciliation"), running: tr("執行中", "Running"),
    finished: tr("已完成", "Completed"), failed: tr("未執行／失敗", "Failed"), cancelled: tr("已取消", "Cancelled"),
  };
  return <div className="pi-global-control" aria-label={tr("Pi 連線與執行管理", "Pi connection and execution")}>
    <span className="pi-global-label">{tr("Pi 連線", "Pi connection")}</span>
    <div className="pi-global-row">
      <button type="button" className={`pi-global-connect ${connected ? "connected" : ""}`}
        disabled={pi.pending || Boolean(status?.busy) || Boolean(status?.component_test_id)} onClick={() => void pi.connect()}
        title={status ? `${status.username}@${status.host}` : "Raspberry Pi 5"}>
        <span aria-hidden="true">●</span> {pi.pending ? tr("處理中…", "Working…") : connected ? tr("已連線", "Connected") : tr("連線 Pi", "Connect Pi")}
      </button>
      <details className="pi-execution-menu" open={question ? true : undefined}>
        <summary aria-label={tr("Pi 執行佇列", "Pi execution queue")}>{question ? tr("確認交接", "Handoff") : tr("執行管理", "Execution")} <span>{pending.length}</span></summary>
        <div className="pi-execution-popover">
          <strong>{tr("一次執行一個，依序交接", "One program at a time · FIFO")}</strong>
          <p className="pi-current-owner" role="status">{tr("目前", "Current")}: {status?.component_test_id ? tr("硬體測試／整合試跑", "Hardware test / trial") : status?.program === "running" ? tr("作品程式執行中", "Project running") : connected ? tr("沒有執行中的作品", "No running project") : tr("尚未連線／狀態未知", "Disconnected / unknown")}</p>
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
    </div>
    {pi.error || pi.networkError ? <span className="pi-global-error" role="alert" title={pi.error ?? "Network error"}>{tr("連線／操作失敗，請重試", "Connection / action failed")}</span> : null}
  </div>;
}
