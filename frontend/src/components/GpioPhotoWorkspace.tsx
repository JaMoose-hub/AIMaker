import { useState, type ReactNode } from 'react';
import { useMakerText } from '../lib/useMaker';
import { acceptPhotoImageSize, photoLocalizationFor } from '../lib/photoWiring';
import { photoGuidanceState, type GpioPhotoRecord, type PhotoRecordMismatch } from '../lib/gpioPhotoWorkspace';
import type { ProjectWire } from '../lib/maker';
import { PhotoViewport } from './PhotoWiringPoc';
import './GpioCaptureAction.css';
import '../gpioPhotoWorkspace.css';

const componentName = (id: string) => id === 'raspberry-pi-5' ? 'Pi 5' : id === 'hc-sr04' ? 'HC-SR04+' : id === 'mrd-tf240-8p-cs' ? 'MRD-TFT240' : id;

/** Passive photo renderer, shared by phone and webcam. No acquisition, inference or AI effects. */
export function GpioPhotoWorkspace({ record, records = [], onRecord, target,
    historical, historicalReason, onReturn, showReturn = true, captureAction, viewControls, sourceError = '', busy = false, overlayComponentId = null }: {
    record: GpioPhotoRecord | null; target?: ProjectWire; historical: boolean; historicalReason?: PhotoRecordMismatch | null; onReturn: () => void;
    records?: GpioPhotoRecord[]; onRecord?: (record: GpioPhotoRecord) => void;
    showReturn?: boolean; captureAction?: ReactNode; viewControls?: ReactNode; sourceError?: string; busy?: boolean;
    overlayComponentId?: string | null;
}) {
    const tr = useMakerText();
    const [loaded, setLoaded] = useState(false), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
    const capture = record?.capture;
    const guidance = capture ? photoGuidanceState(capture, target, historical, historicalReason) : null;
    const messages = {
        historical: tr('歷史照片：不顯示目前連線，請重新擷取。', 'Historical photo: current wiring is hidden. Retake the photo.'),
        'no-target': tr('請按「開始接線」，或選擇接線查看示意。', 'Press Start wiring, or choose a wire to inspect.'),
        'plan-mismatch': tr('這張照片沒有目前線路的資料，請重新擷取。', 'This photo has no matching wiring data. Retake the photo.'),
        'missing-endpoints': guidance?.missing.map(id => {
            const localization = photoLocalizationFor(capture!, id);
            const reason = localization.reason === 'invalid_model_geometry'
                ? tr('角度／腳位幾何未通過檢查', 'orientation / pin geometry not validated')
                : localization.status === 'not_found' ? tr('未辨識到', 'not detected') : tr('腳位尚未定位', 'pins not located');
            return `${componentName(id)} ${reason}`;
        }).join(' · ') + tr('；暫不連線，請拍清楚接腳後重拍。', '; wire hidden. Retake with the pins clearly visible.'),
        divider: tr('這條線需要分壓，請依接線圖連接，不畫直連線。', 'This wire needs a divider. Follow the wiring diagram; no direct link is drawn.'),
    };
    const historyLabels = {
        project: tr('不同作品', 'Different project'), revision: tr('作品版本已更新', 'Project revision changed'),
        round: tr('接線輪次已更新', 'Wiring round changed'), invalidated: tr('照片已失效', 'Photo invalidated'),
    };
    const photographed = capture ? new Date(typeof capture.captured_at === 'number' ? capture.captured_at * 1000 : capture.captured_at) : null;
    const photoTime = photographed && Number.isFinite(photographed.getTime()) ? photographed : null;
    const targetLabel = target ? `${componentName(target.componentId)} · ${target.componentPin} → Pi ${target.boardLabel || target.boardPin}` : tr('尚未選擇', 'None selected');
    return <section className="gpio-photo-workspace" aria-label={tr('接線照片', 'Wiring photo')}>
        <header className={viewControls ? 'image-workspace-heading' : undefined}>
            {viewControls}
            <div className="gpio-photo-metadata">{viewControls ? null : <strong>{tr('接線照片', 'Wiring photo')}</strong>}<small>{record ? record.source === 'phone' ? tr('手機擷取', 'Phone capture') : 'Webcam' : ''}
            {photoTime ? <> · <time dateTime={photoTime.toISOString()}>{new Intl.DateTimeFormat(tr('zh-TW', 'en'), {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
            }).format(photoTime)}</time></> : null}
            {capture ? ` · ${capture.video_size.join(' × ')}` : ''}</small></div>
            {records.length > 1 ? <select aria-label={tr('選擇接線照片', 'Choose wiring photo')} value={record ? `${record.source}:${record.capture.capture_id}` : ''}
                onChange={e => { const next = records.find(r => `${r.source}:${r.capture.capture_id}` === e.target.value); if (next) onRecord?.(next); }}>
                {records.map((r, i) => <option key={`${r.source}:${r.capture.capture_id}`} value={`${r.source}:${r.capture.capture_id}`}>{i + 1} · {r.source === 'phone' ? tr('手機', 'Phone') : 'Webcam'}</option>)}
            </select> : null}
            <div className="gpio-photo-actions">{captureAction}{showReturn ? <button type="button" className="gpio-capture-button gpio-photo-return" disabled={busy} onClick={onReturn}>
                <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="5" width="13" height="14" rx="3" /><path d="m16 9 5-3v12l-5-3" />
                </svg><span>{tr('返回即時畫面', 'Back to live view')}</span>
            </button> : null}</div></header>
        {sourceError ? <p className="gpio-photo-notice" role="status" title={sourceError}>
            {tr('未能切換，保留原來源', 'Switch failed · original source retained')}
        </p> : null}
        {guidance?.referenceOnly ? <div className="gpio-photo-guidance" data-state="reference-only">
            <p role="status">{tr('上一輪照片：僅供預期接法參考；移動板卡或改線後請重新擷取。', 'Previous-round photo: intended wiring reference only. Retake after moving boards or changing wires.')}</p>
        </div> : null}
        {capture && guidance && guidance.kind !== 'ready' ? <div className="gpio-photo-guidance" data-state={guidance.kind} aria-label={targetLabel}>
            <p role="status">{guidance.kind === 'historical' && historicalReason ? `${historyLabels[historicalReason]} · ` : ''}{messages[guidance.kind]}</p>
        </div> : null}
        {capture ? <PhotoViewport compact capture={capture} wire={guidance?.wire} imageAttempt={attempt} imageLoaded={loaded}
            overlayComponentId={overlayComponentId}
            onLoad={(w, h) => { const valid = acceptPhotoImageSize(capture, w, h); setLoaded(valid); setError(valid ? '' : tr('照片尺寸不符，暫不顯示 GPIO。', 'Photo size mismatch; GPIO is hidden.')); }}
            onError={() => { setLoaded(false); setError(tr('照片讀取失敗', 'Could not load the photo')); }} />
            : <div className="gpio-photo-empty">{tr('尚無接線照片。拍攝後可在這裡查看 GPIO 標示。', 'No wiring photos yet. Capture a photo to see its GPIO markers here.')}</div>}
        {error ? <p className="gpio-photo-notice" role="alert">{error}<button type="button" onClick={() => { setLoaded(false); setAttempt(v => v + 1); }}>{tr('重新載入', 'Reload')}</button></p> : null}
        <footer>{tr('虛線是預期接法，不代表接線已通過；移動板卡或改線後請重拍。', 'Dashed lines show intended wiring, not a wiring pass. Retake after moving boards or changing wires.')}</footer>
    </section>;
}
