import { useState, type ReactNode } from 'react';
import { useMakerText } from '../lib/useMaker';
import { acceptPhotoImageSize, photoMissingEndpoints } from '../lib/photoWiring';
import type { PhotoWire } from '../lib/photoWiring';
import type { GpioPhotoRecord } from '../lib/gpioPhotoWorkspace';
import { PhotoViewport } from './PhotoWiringPoc';
import '../gpioPhotoWorkspace.css';

/** Passive photo renderer, shared by phone and webcam. No acquisition, inference or AI effects. */
export function GpioPhotoWorkspace({ record, records = [], onRecord, wire, historical, onReturn, captureAction, busy = false }: {
    record: GpioPhotoRecord | null; wire?: PhotoWire; historical: boolean; onReturn: () => void;
    records?: GpioPhotoRecord[]; onRecord?: (record: GpioPhotoRecord) => void;
    captureAction?: ReactNode; busy?: boolean;
}) {
    const tr = useMakerText();
    const [loaded, setLoaded] = useState(false), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
    const capture = record?.capture;
    const missing = capture && !historical && wire ? photoMissingEndpoints(capture, wire) : [];
    const missingNames = missing.map(id => id === 'raspberry-pi-5' ? 'Pi 5' : id === 'hc-sr04' ? 'HC-SR04+' : 'MRD-TFT240').join('、');
    const photographed = capture ? new Date(typeof capture.captured_at === 'number' ? capture.captured_at * 1000 : capture.captured_at) : null;
    const photoTime = photographed && Number.isFinite(photographed.getTime()) ? photographed : null;
    return <section className="gpio-photo-workspace" aria-label={tr('接線照片', 'Wiring photo')}>
        <header><div><strong>{tr('接線照片', 'Wiring photo')}</strong><small>{record ? record.source === 'phone' ? tr('手機擷取', 'Phone capture') : 'Webcam' : ''}
            {photoTime ? <> · <time dateTime={photoTime.toISOString()}>{new Intl.DateTimeFormat(tr('zh-TW', 'en'), {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
            }).format(photoTime)}</time></> : null}
            {capture ? ` · ${capture.video_size.join(' × ')}` : ''}</small></div>
            {records.length > 1 ? <select aria-label={tr('選擇接線照片', 'Choose wiring photo')} value={record ? `${record.source}:${record.capture.capture_id}` : ''}
                onChange={e => { const next = records.find(r => `${r.source}:${r.capture.capture_id}` === e.target.value); if (next) onRecord?.(next); }}>
                {records.map((r, i) => <option key={`${r.source}:${r.capture.capture_id}`} value={`${r.source}:${r.capture.capture_id}`}>{i + 1} · {r.source === 'phone' ? tr('手機', 'Phone') : 'Webcam'}</option>)}
            </select> : null}
            <div className="gpio-photo-actions">{captureAction}<button type="button" disabled={busy} onClick={onReturn}>{tr('返回即時畫面', 'Back to live view')}</button></div></header>
        {historical ? <p className="gpio-photo-notice" role="status">{tr('先前作品／接線輪次的照片；不作為目前接線證據。', 'Photo from an earlier project or wiring round; not current wiring evidence.')}</p> : null}
        {capture ? <PhotoViewport compact capture={capture} wire={historical ? undefined : wire} imageAttempt={attempt} imageLoaded={loaded}
            onLoad={(w, h) => { const valid = acceptPhotoImageSize(capture, w, h); setLoaded(valid); setError(valid ? '' : tr('照片尺寸不符，暫不顯示 GPIO。', 'Photo size mismatch; GPIO is hidden.')); }}
            onError={() => { setLoaded(false); setError(tr('照片讀取失敗', 'Could not load the photo')); }} />
            : <div className="gpio-photo-empty">{tr('尚無接線照片。拍攝後可在這裡查看 GPIO 標示。', 'No wiring photos yet. Capture a photo to see its GPIO markers here.')}</div>}
        {error ? <p className="gpio-photo-notice" role="alert">{error}<button type="button" onClick={() => { setLoaded(false); setAttempt(v => v + 1); }}>{tr('重新載入', 'Reload')}</button></p> : null}
        {loaded && !error && missing.length > 0 ? <p className="gpio-photo-notice" role="status">{tr(
            `${missingNames} 腳位尚未定位，暫不畫連線。請拍清楚零件與接腳後重新擷取。`,
            `${missingNames} pins are not located; the wire is hidden. Retake a clear photo of the module and its pins.`)}</p> : null}
        <footer>{!historical && wire ? `${wire.component_pin} → ${wire.board_pin} · ` : ''}{tr('虛線是預期接法，不代表接線已通過；移動板卡或改線後請重拍。', 'Dashed lines show intended wiring, not a wiring pass. Retake after moving boards or changing wires.')}</footer>
    </section>;
}
