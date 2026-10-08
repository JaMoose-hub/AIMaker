import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useMakerText } from '../lib/useMaker';
import { useStreamWaitingNotice } from '../lib/useStreamWaitingNotice';
import './deploymentLivePreview.css';

/** A second display of VideoView's current image, never another camera owner. */
export function DeploymentLivePreview({ image, unavailable, phone, controls, onLoad, onError, onRetry, waitingForFrame = false }: {
  image?: string; unavailable: boolean; phone: boolean; controls?: ReactNode;
  onLoad?: () => void; onError?: () => void; onRetry?: () => void;
  waitingForFrame?: boolean;
}) {
  const tr = useMakerText();
  const root = useRef<HTMLElement>(null);
  const [painted, setPainted] = useState(false);
  const [failed, setFailed] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [fullscreenError, setFullscreenError] = useState(false);
  const ready = Boolean(image) && !unavailable && painted && !failed;
  const briefFrameGap = waitingForFrame && !failed;
  const waitingNotice = useStreamWaitingNotice(!ready && briefFrameGap);
  const showNotice = !ready && (!briefFrameGap || waitingNotice);
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === root.current);
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  async function expand() {
    setFullscreenError(false);
    try {
      if (document.fullscreenElement === root.current) await document.exitFullscreen();
      else if (root.current?.requestFullscreen) await root.current.requestFullscreen();
      else setFullscreenError(true);
    } catch { setFullscreenError(true); }
  }
  return <section ref={root} className="deployment-live-preview workflow-surface" aria-label={tr('實際畫面', 'Live hardware view')}>
    <header className="deployment-preview-heading">
      <h3>{tr('實際畫面', 'Live hardware view')}</h3>
      <span className={`deployment-stream-status${ready ? ' is-live' : ''}`} role="status">
        <i aria-hidden="true" />{ready ? tr('即時', 'Live') : tr('等待影像', 'Waiting')}
      </span>
      <div className="deployment-preview-controls">{controls}
        <button type="button" className="deployment-preview-expand" onClick={() => void expand()}
          aria-label={fullscreen ? tr('退出全螢幕', 'Exit fullscreen') : tr('全螢幕實際畫面', 'Fullscreen hardware view')}
          title={fullscreen ? tr('退出全螢幕', 'Exit fullscreen') : tr('全螢幕實際畫面', 'Fullscreen hardware view')}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d={fullscreen ? 'M3 9h6V3m12 6h-6V3M3 15h6v6m12-6h-6v6' : 'M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6'} />
          </svg>
        </button>
      </div>
    </header>
    <div className="deployment-preview-viewport">
      {image ? <img src={image} alt={tr('目前鏡頭的實際畫面', 'Current camera image of the hardware')} draggable={false}
        hidden={unavailable || failed}
        onLoad={() => { setPainted(true); setFailed(false); onLoad?.(); }}
        onError={() => { setFailed(true); onError?.(); }} /> : null}
      {showNotice ? <div className="deployment-preview-waiting">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><rect x="3" y="5" width="13" height="14" rx="3" /><path d="m16 9 5-3v12l-5-3" /></svg>
        <span>{failed ? tr('影像暫時無法顯示', 'Video is temporarily unavailable') : phone ? tr('等待手機串流', 'Waiting for phone stream') : tr('等待 Webcam 影像', 'Waiting for Webcam')}</span>
        {onRetry && (failed || unavailable) ? <button type="button" onClick={onRetry}>{tr('重新連接', 'Reconnect')}</button> : null}
      </div> : null}
    </div>
    {fullscreenError ? <small className="deployment-preview-error" role="status">{tr('此瀏覽器暫不支援全螢幕，仍可在面板觀看。', 'Fullscreen is unavailable in this browser. The embedded view remains available.')}</small> : null}
  </section>;
}
