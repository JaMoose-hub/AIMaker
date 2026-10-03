import type { ReactNode } from 'react';
import { useI18n } from "../lib/i18n";
import "./LiveCameraOverlay.css";

/** Presentation only: the existing VideoView and source controller retain ownership. */
export function LiveCameraOverlay({ controls, changing, unavailable, offline, phone, error, onRetry }: {
  controls?: ReactNode; changing: boolean; unavailable: boolean; offline: boolean;
  phone: boolean; error: string; onRetry?: () => void;
}) {
  const { locale } = useI18n();
  const tr = (zh: string, en: string) => locale === 'zh-TW' ? zh : en;
  const blocked = changing || unavailable || offline;
  const title = offline ? tr('影像服務連線中', 'Connecting to video service')
    : changing ? tr('切換影像中', 'Switching camera')
    : phone ? tr('等待手機串流', 'Waiting for phone stream') : tr('等待鏡頭影像', 'Waiting for camera');
  const hint = offline ? tr('連線恢復後會自動繼續', 'Video resumes when the connection returns')
    : changing ? tr('畫面準備好後會自動顯示', 'Video will appear when ready')
    : phone ? tr('請確認手機已開啟串流', 'Make sure streaming is on your phone')
    : tr('請確認鏡頭已連接', 'Check that the camera is connected');
  return <div className="live-camera-overlay">
    {controls ? <div className="live-camera-dock">{controls}
      {error && !blocked ? <span className="live-camera-switch-error" role="status" title={error}>
        {tr('未能切換，保留原來源', 'Switch failed · original source retained')}
      </span> : null}
    </div> : null}
    {blocked ? <div className="live-camera-message" role="status">
      <div className="live-camera-message-card">
        <svg className="live-camera-message-icon" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
          <rect x="3" y="5" width="14" height="14" rx="4"/><path d="m17 10 4-3v10l-4-3"/>
        </svg>
        <strong>{title}</strong><p>{hint}</p>
        {error ? <small title={error}>{tr('連線尚未恢復，請再試一次', 'Still disconnected. Please try again.')}</small> : null}
        {!changing && !offline && onRetry ? <button type="button" onClick={onRetry}>
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M13 7a5 5 0 1 0-1 4M13 3v4H9"/></svg>
          {tr('重新連接', 'Reconnect')}
        </button> : null}
      </div>
    </div> : null}
  </div>;
}
