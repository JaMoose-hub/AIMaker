import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useMakerText } from '../lib/useMaker';
import { acceptedWiringPhotos, acceptWiringPhoto, loadWiringPhotoReceipts, wiringPhotoFlowKey } from '../lib/wiringPhotoFlow';
import { canAnalyseWiring, wiringPhotoRoles, wiringPhotoRoleLabel, wiringPhotoInstruction, wiringPhotoRow, type WiringPhotoRole, type WiringPhotoSlot, type WiringReviewState } from '../lib/wiringReview';

const storage = () => { try { return typeof sessionStorage === 'undefined' ? undefined : sessionStorage; } catch { return undefined; } };

/** Fixed capture guidance is derived from shared evidence, without a model call per turn. */
export function WiringPhotoSequence({ review, disabled, waiting, captureReady, humanOnly, failedCaptures,
    onCapture, onAccept, onAnalyse, onPhoto, onImageError, framing, captureLabel, photoDetailsLabel, photoActionLabel }: {
    review: WiringReviewState; disabled: boolean; waiting: boolean; captureReady: boolean; humanOnly: boolean; failedCaptures: string[];
    onCapture: (role: WiringPhotoRole) => void; onAccept?: (role: WiringPhotoRole, slot: WiringPhotoSlot) => Promise<unknown>;
    onAnalyse: () => void; onPhoto: (slot: WiringPhotoSlot) => void; onImageError: (id: string) => void;
    framing: (role: WiringPhotoRole) => ReactNode; captureLabel?: string; photoDetailsLabel?: string; photoActionLabel?: string;
}) {
    const tr = useMakerText();
    const key = wiringPhotoFlowKey(review);
    const [receipts, setReceipts] = useState(() => loadWiringPhotoReceipts(review, storage()));
    const [choice, setChoice] = useState<{ key: string; role: WiringPhotoRole } | null>(null);
    const [loaded, setLoaded] = useState<string[]>([]);
    const [accepting, setAccepting] = useState(false);
    const [error, setError] = useState('');
    const lock = useRef(false);
    const latest = useRef(review); latest.current = review;
    const accepted = acceptedWiringPhotos(review, receipts, failedCaptures);
    const next = wiringPhotoRoles.find(value => !accepted.includes(value));
    const role = choice?.key === key ? choice.role : next;
    const slot = role ? review.slots[role] : null;
    const available = Boolean(slot && slot.available !== false && !failedCaptures.includes(slot.capture_id));
    const blocked = disabled || waiting || accepting;
    const label = (value: WiringPhotoRole) => wiringPhotoRoleLabel(value, tr, review.capture_plan);
    const row = role ? wiringPhotoRow(role, review.capture_plan) : null;
    const question = row && role ? wiringPhotoInstruction(role, tr, review.capture_plan)
        : role === 'pi_side_a' ? tr('先拍 Pi 的第一側，好嗎？', 'First, take a photo of one side of the Pi.')
            : role === 'pi_side_b' ? tr('接著，換到 Pi 的另一側拍一張。', 'Next, take a photo from the other side of the Pi.')
                : tr('最後，靠近這個零件的接頭拍一張。', 'Finally, take a close-up of this module’s header.');
    const hint = row ? tr('稍微降低相機，拍到插接底部，不要只拍線的上段。這一輪保持接線不變。', 'Lower the camera to show the insertion points, not just the upper wires. Keep this round’s wiring unchanged.')
        : role === 'pi_side_a' ? tr('讓排針、黑色接頭底部、露出的線色一起入鏡，並保留板子方向。', 'Include the header, black connector bases, exposed wire colors and board orientation.')
            : role === 'pi_side_b' ? tr('拍出上一張被遮住的插接底部。這一輪保持接線不變。', 'Show the insertion points hidden in the first photo. Keep this round’s wiring unchanged.')
                : tr('讓 pin 文字、每個接頭和線色看得清楚。保持接線不變。', 'Make the pin labels, each connector and wire colors visible. Keep the wiring unchanged.');
    useEffect(() => {
        if ((review.photo_flow_version ?? 1) >= 2 || onAccept || receipts.key !== key) return;
        try { storage()?.setItem(`boardvision.wiring-photo-flow.v1.${review.id}`, JSON.stringify(receipts)); } catch { /* Legacy progress can be selected again. */ }
    }, [key, receipts, review.id, review.photo_flow_version, onAccept]);

    async function usePhoto() {
        if (!role || !slot || !available || blocked || lock.current || !loaded.includes(slot.capture_id)
            || latest.current !== review) return;
        if (accepted.includes(role)) { setChoice(null); return; }
        lock.current = true; setAccepting(true); setError('');
        try {
            if (onAccept) {
                const result = await onAccept(role, slot);
                if (result === null || result === false) throw new Error(tr('照片尚未選用成功，請再試一次。', 'Photo selection was not saved. Try again.'));
                // The server receipt in the next review snapshot advances the conversation.
                if (wiringPhotoFlowKey(latest.current) === key) setChoice(null);
            } else if ((review.photo_flow_version ?? 1) < 2) {
                setReceipts(acceptWiringPhoto(review, receipts, role)); setChoice(null);
            } else {
                throw new Error(tr('無法儲存照片選用，請重新連線後再試。', 'Cannot save photo selection. Reconnect and try again.'));
            }
        } catch (cause) {
            if (wiringPhotoFlowKey(latest.current) === key) setError(cause instanceof Error ? cause.message : tr('操作失敗，請重試。', 'Action failed. Try again.'));
        } finally { lock.current = false; setAccepting(false); }
    }

    return <div className="wr-photo-sequence wr-photo-dialogue" aria-label={tr('AI 逐張引導拍照', 'AI step-by-step photo guidance')} aria-busy={waiting || accepting}>
        <div className="wr-dialogue-progress"><span role="status">{tr('已選用', 'Selected')} {accepted.length} / 3</span>
            {accepted.length ? <details className="wr-dialogue-history"><summary>{tr('查看已選照片', 'Selected photos')}</summary>
                <div>{accepted.map(value => <button key={value} type="button" disabled={blocked} onClick={() => { setChoice({ key, role: value }); setError(''); }}>
                    <span aria-hidden="true">✓</span> {label(value)} <small>{tr('查看／重拍', 'View / retake')}</small></button>)}</div>
            </details> : <small>{tr('一次拍一張，接線保持不變', 'One photo at a time; keep wiring unchanged')}</small>}
        </div>
        {role ? <article className="wr-dialogue-turn" key={`${key}:${role}:${slot?.capture_id ?? 'empty'}`} data-photo-role={role}>
            <div className="wr-dialogue-message is-assistant">
                <div className="wr-dialogue-speaker"><strong>Tinkro AI</strong><small>{wiringPhotoRoles.indexOf(role) + 1} / 3</small></div>
                <p>{question}</p><p className="wr-dialogue-hint">{hint}</p>
                <>{row ? framing(role) : <details className="wr-photo-more wr-framing-details"><summary>{tr('怎麼拍？看取景示意', 'How to frame the photo')}</summary>{framing(role)}</details>}</>
                {!available ? <div className="wr-actions"><button className="wr-primary" type="button" disabled={blocked || humanOnly || !captureReady}
                    onClick={() => { setError(''); onCapture(role); }}>{captureLabel ?? tr(`拍攝${label(role)}`, `Capture ${label(role)}`)}</button></div> : null}
            </div>
            {slot && available ? <>
                <div className="wr-dialogue-message is-user"><div className="wr-dialogue-speaker"><strong>{tr('你', 'You')}</strong><span>{label(role)}</span></div>
                    <img className="wr-step-photo" src={slot.image_url} alt={label(role)}
                        onLoad={() => setLoaded(previous => previous.includes(slot.capture_id) ? previous : [...previous, slot.capture_id])}
                        onError={() => onImageError(slot.capture_id)} />
                </div>
                <div className="wr-dialogue-message is-assistant">
                    <strong className="wr-dialogue-speaker">Tinkro AI</strong>
                    <p>{tr('這張的接頭底部和線色看得清楚嗎？', 'Can you see the connector bases and wire colors in this photo?')}</p>
                    <small className="wr-photo-check">{role === 'component_header' ? tr('也請確認 pin 文字入鏡。選用照片後，我才會一起分析。', 'Also check the pin labels. I’ll analyse the selected photos together.')
                        : tr('先由你選用照片，下一張再換角度；這一步還沒判斷接線。', 'Choose the photo, then move to the next view. Wiring has not been judged yet.')}</small>
                    <div className="wr-actions"><button className="wr-primary" type="button" disabled={blocked || !loaded.includes(slot.capture_id)} onClick={() => void usePhoto()}>
                        {accepting ? tr('儲存照片選用…', 'Saving photo selection…') : accepted.includes(role) ? tr('保留這張，繼續', 'Keep photo, continue')
                            : wiringPhotoRoles.filter(value => value !== role).every(value => accepted.includes(value)) ? tr('使用這張，完成拍攝', 'Use photo, finish capture') : tr('使用這張，下一步', 'Use photo, next step')}</button>
                        <button type="button" disabled={blocked || humanOnly || !captureReady} onClick={() => { setError(''); onCapture(role); }}>{tr('看不清楚，重拍', 'Not clear, retake')}</button></div>
                    <details className="wr-photo-more"><summary>{photoDetailsLabel ?? tr('放大查看或調整分析範圍', 'View larger or adjust analysis area')}</summary>
                        <button type="button" disabled={blocked} onClick={() => onPhoto(slot)}>{photoActionLabel ?? tr('查看／框選', 'View / crop')}</button>
                        <small>{tr('框選只指定分析區域，不代表腳號或接線已確認。', 'Cropping selects an analysis area; it does not confirm pins or wiring.')}</small></details>
                </div>
            </> : slot ? <p className="wr-error" role="alert">{tr('照片無法取得，請重拍這一張。', 'Photo unavailable. Retake this photo.')}</p> : null}
        </article> : <div className="wr-dialogue-message is-assistant wr-photo-ready">
            <strong className="wr-dialogue-speaker">Tinkro AI</strong>
            <p>{tr('三張都選好了，要一起分析嗎？', 'All three photos are selected. Ready to analyse them together?')}</p>
            <small>{tr('我會整理兩端腳位與線色依據，再請你逐條沿線確認。', 'I’ll organise pin and wire-color evidence, then ask you to trace and confirm each wire.')}</small>
            <div className="wr-actions"><button className="wr-primary" type="button" disabled={!canAnalyseWiring(review, waiting || accepting, disabled) || accepted.length !== 3}
                onClick={onAnalyse}>{waiting ? tr('正在分析照片…', 'Analysing photos…') : tr('分析這三張照片', 'Analyse these three photos')}</button></div>
        </div>}
        {error ? <p className="wr-error" role="alert">{error}</p> : null}
        {!captureReady && role ? <p className="wr-muted">{tr('請先連接手機或 Webcam，確認即時畫面後拍攝。', 'Connect your phone or webcam and check the live view before capture.')}</p> : null}
    </div>;
}
