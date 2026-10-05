import { useEffect, useId, useRef, useState } from "react";
import { useHeaderPanel } from "../lib/headerPanels";
import { useMakerText } from "../lib/useMaker";
import "./workflowReset.css";

/** A global, confirmed reset; the existing project owner performs the transaction. */
export function WorkflowResetControl({ onReset, busy, error = "" }: {
  onReset: () => Promise<boolean>; busy: boolean; error?: string;
}) {
  const tr = useMakerText();
  const [open, setOpen] = useHeaderPanel("reset");
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const flight = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) { element.showModal(); cancel.current?.focus(); }
    else if (!open && element.open) { element.close(); trigger.current?.focus({ preventScroll: true }); }
  }, [open]);
  useEffect(() => {
    if (open && failed && !pending) cancel.current?.focus();
  }, [open, failed, pending]);

  async function confirm() {
    if (busy || flight.current) return;
    flight.current = true; setPending(true); setFailed(false);
    try {
      if (await onReset()) setOpen(false);
      else setFailed(true);
    } catch { setFailed(true); }
    finally { flight.current = false; setPending(false); }
  }
  const locked = busy || pending;
  return <>
    <button ref={trigger} type="button" className="workflow-reset-trigger" disabled={locked}
      aria-label={tr("重新開始工作流程", "Restart workflow")}
      title={locked ? tr("請等待目前操作完成", "Wait for the current operation") : tr("重新開始整個工作流程", "Restart the entire workflow")}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={id}
      onClick={() => { if (!locked) { setFailed(false); setOpen(true); } }}>
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5" />
      </svg>
    </button>
    <dialog ref={dialog} id={id} className="workflow-reset-dialog" aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`} aria-busy={pending}
      onCancel={event => { event.preventDefault(); if (!flight.current) setOpen(false); }}>
      <div className="workflow-reset-content">
        <span className="workflow-reset-eyebrow">WORKFLOW RESET</span>
        <h2 id={`${id}-title`}>{tr("重新開始工作流程？", "Restart the workflow?")}</h2>
        <p id={`${id}-description`}>{tr("先備份目前作品，再回到 01「設計與藍圖」。", "Back up your current project, then return to 01 · Design & blueprint.")}</p>
        <dl className="workflow-reset-scope">
          <div><dt>{tr("重新開始", "Start fresh")}</dt><dd>{tr("作品與程式草稿、接線進度、這輪照片選取與對話", "Project and code drafts, wiring progress, current photo selection and chat")}</dd></div>
          <div><dt>{tr("保留", "Keep")}</dt><dd>{tr("裝置與影像來源、AI／零件偏好、照片和對話歷史", "Devices and image source, AI / component preferences, photo and chat history")}</dd></div>
        </dl>
        <p className="workflow-reset-safety">{tr("不會停止 Pi 或替硬體斷電。有執行中的程式／測試時，請先停止；無法確認狀態時不會重置。", "This does not stop or power off Pi. Stop any running program / test first; reset is blocked if its status cannot be verified.")}</p>
        {failed && !pending ? <p className="workflow-reset-error" role="alert">{error || tr("未完成重置，目前工作已保留。請確認連線後重試。", "Reset did not complete. Your work is kept; check the connection and retry.")}</p> : null}
        <div className="workflow-reset-actions">
          <button ref={cancel} type="button" disabled={pending} onClick={() => setOpen(false)}>{tr("取消", "Cancel")}</button>
          <button type="button" className="workflow-reset-confirm" disabled={locked} onClick={() => void confirm()}>
            {pending ? tr("正在備份與重置…", "Backing up and resetting…") : tr("備份並重新開始", "Back up & restart")}
          </button>
        </div>
      </div>
    </dialog>
  </>;
}
