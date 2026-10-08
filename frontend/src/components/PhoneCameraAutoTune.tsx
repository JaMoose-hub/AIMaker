import type { RefObject } from "react";
import { useI18n } from "../lib/i18n";
import type { usePhoneCameraTune } from "../lib/usePhoneCameraTune";
import "./phoneCameraAutoTune.css";

export function PhoneCameraAutoTune({ controller, video, disabled }: {
  controller: ReturnType<typeof usePhoneCameraTune>; video: RefObject<HTMLVideoElement>; disabled: boolean;
}) {
  const { locale } = useI18n(), tr = (zh: string, en: string) => locale === "en" ? en : zh;
  // Standalone legacy fixtures without a camera owner remain inert.
  if (!controller) return null;
  const { result, error, busy, phase } = controller;
  const messages: Record<string, [string, string]> = {
    cancelled: ["已取消，原設定已保留。", "Cancelled; original settings kept."],
    restored: ["已還原本輪調整前的設定。", "Settings from before this check restored."],
    phone_tune_source_changed: ["串流來源已改變，請重新檢查。", "The stream changed; run a new check."],
    phone_tune_frame_unavailable: ["未取得新的影格，請保持串流並重試。", "No fresh frame; keep streaming and retry."],
    phone_tune_unsupported: ["Safari 未確認可套用的參數，已保留原設定。", "Safari did not confirm the controls; original settings kept."],
    phone_tune_restore_failed: ["未能確認還原，請按「還原」重試；勿把此結果當成已完成調整。", "Restore is unconfirmed. Retry Restore; adjustment is not confirmed."],
  };
  const hints: Record<string, [string, string]> = {
    dark: ["光線偏暗，請補光，避免只提高亮度。", "Low light: add lighting rather than only increasing brightness."],
    glare: ["亮部或反光偏多，請調整燈光／拍攝角度。", "Bright areas or glare: adjust lighting / camera angle."],
    detail: ["細節偏少或可能失焦，請穩住手機、調整距離再檢查。", "Few details or possible defocus: hold steady, adjust distance, then recheck."],
    motion: ["畫面變動較大，未改設定；請放穩手機再檢查。", "The scene changed too much; settings kept. Hold still and recheck."],
  };
  return <section className="mw-auto-tune" aria-label={tr("手機智慧調整", "Phone smart adjustment")} aria-busy={busy}>
    <div className="mw-auto-tune-actions">
      <button type="button" className="mw-button mw-secondary mw-auto-tune-trigger" disabled={disabled || busy}
        onClick={() => void controller.start(video.current)}><span aria-hidden="true">✦</span>
        {busy ? phase === "cancelling" ? tr("取消並還原中…", "Cancelling & restoring…") : phase === "restoring" ? tr("還原中…", "Restoring…") : tr("正在檢查與調整…", "Checking & adjusting…") : tr("智慧調整", "Smart adjustment")}</button>
      {phase === "checking" ? <button type="button" className="mw-quiet" onClick={controller.cancel}>{tr("取消", "Cancel")}</button> : null}
      {controller.canRestore && !busy ? <button type="button" className="mw-quiet" disabled={disabled} onClick={() => void controller.restore()}>{tr("還原", "Restore")}</button> : null}
    </div>
    <div className="mw-auto-tune-feedback" role="status" aria-live="polite">
      {error ? <p className={error === "restored" || error === "cancelled" ? "" : "mw-error-text"}>{messages[error] ? tr(...messages[error]) : tr("檢查未完成，請重試。", "Check did not finish; retry.")}</p>
        : result ? <>
          <p>{result.bitrateChanged ? tr(`串流碼率上限已調整為 ${result.bitrate! / 1000} Mbps；實際速度依網路調整。`, `Stream cap set to ${result.bitrate! / 1000} Mbps; actual rates depend on the network.`)
            : result.camera === "improved" ? tr("相機自動模式的畫質比較有改善，已保留。", "Camera automatic modes improved the image comparison and were kept.")
              : tr("檢查完成，未找到可確認較好的設定；保留目前設定。", "Check complete; no confirmed better setting found. Current settings kept.")}</p>
          {result.quality.issues.length ? result.quality.issues.map(issue => <p key={issue}>{tr(...hints[issue])}</p>) : <p>{tr("未發現明顯過暗／過曝或細節不足；不代表 GPIO 接線已正確。", "No obvious low light, clipping or lack of detail; this does not verify GPIO wiring.")}</p>}
          {result.camera === "unsupported" ? <p>{tr("此相機未開放曝光／對焦／白平衡控制，不顯示無效滑桿。", "This camera does not expose exposure / focus / white-balance controls; unavailable sliders are hidden.")}</p> : null}
        </> : <p>{tr("放穩手機後按一次；檢查原始影像與傳輸負載，不改線材顏色、不另開鏡頭。", "Hold the phone still, then check image quality and transport load. Wire colors stay unchanged; no second camera is opened.")}</p>}
    </div>
  </section>;
}
