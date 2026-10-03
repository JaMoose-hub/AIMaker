import { useId } from 'react';
import { useMakerText } from '../lib/useMaker';
import './GpioCaptureAction.css';

export function GpioCaptureAction({ source, busy, needsResume, error, disabledReason, retake = false, onCapture, onResume }: {
    source: 'webcam' | 'phone'; busy: boolean; needsResume: boolean;
    error: 'capture' | 'source' | null; disabledReason: string; retake?: boolean;
    onCapture: () => void; onResume: () => void;
}) {
    const tr = useMakerText(), id = useId();
    const notice = needsResume ? tr('需恢復即時辨識', 'Live recognition needs to resume')
        : error === 'source' ? tr('來源已改變，請重新擷取', 'Source changed. Please retake.')
        : error ? tr('擷取失敗，請重試', 'Capture failed. Please retry.') : disabledReason;
    const label = busy ? needsResume ? tr('恢復中…', 'Resuming…') : tr('擷取中…', 'Capturing…')
        : needsResume ? tr('恢復即時辨識', 'Resume live recognition')
        : retake ? tr('重新擷取', 'Retake photo') : tr('擷取接線照片', 'Capture wiring photo');
    return <div className="gpio-capture-action" aria-busy={busy}>
        <button type="button" className={`gpio-capture-button${busy ? ' is-busy' : ''}`}
            disabled={busy || (!needsResume && !!disabledReason)}
            title={`${source === 'phone' ? tr('手機串流', 'Phone stream') : 'Webcam'} · ${tr('擷取後顯示 GPIO 照片', 'Capture and show GPIO photo')}`}
            aria-describedby={notice ? id : undefined} onClick={needsResume ? onResume : onCapture}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 5 6 8H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2h-2l-2-3Z" />
                <circle cx="12" cy="14" r="4" />
            </svg><span>{label}</span>
        </button>
        {notice ? <small id={id} role={error || needsResume ? 'alert' : 'status'}>{notice}</small> : null}
    </div>;
}
