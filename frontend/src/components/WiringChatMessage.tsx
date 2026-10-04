import { useRef, useState, type PointerEvent } from 'react';
import type { AssistantMessage } from '../lib/assistant';
import { useMakerText } from '../lib/useMaker';
import { boundWiringChatAction, wiringComparisonText, wiringFlowCanAct, wiringFlowReview } from '../lib/wiringChat';
import { AssistantAnalysisTime } from './AssistantAnalysisTime';
import { cropFromPoints, imagePointFromClient, validWiringCrop, wiringPhotoRoles,
  type WiringCrop, type WiringEndpoint, type WiringPhotoRole, type WiringPhotoSlot, type WiringReviewAction, type WiringReviewState } from '../lib/wiringReview';
import './wiringChat.css';

type Translate = (zh: string, en: string) => string;
export const wiringChatRoleLabel = (role: WiringPhotoRole, tr: Translate) => role === 'pi_side_a' ? tr('Pi 第一側', 'Pi first side')
  : role === 'pi_side_b' ? tr('Pi 另一側', 'Pi other side') : tr('零件接頭', 'Module header');
const colorNames: Record<string, [string, string]> = { red: ['紅色', 'red'], orange: ['橘色', 'orange'], yellow: ['黃色', 'yellow'],
  green: ['綠色', 'green'], blue: ['藍色', 'blue'], purple: ['紫色', 'purple'], black: ['黑色', 'black'], white: ['白色', 'white'],
  brown: ['棕色', 'brown'], gray: ['灰色', 'gray'], grey: ['灰色', 'gray'], pink: ['粉紅色', 'pink'], teal: ['藍綠色', 'teal'] };
const colorLabel = (color: string | null, tr: Translate) => color && colorNames[color] ? tr(...colorNames[color]) : color || tr('線色不明', 'Unknown color');

export interface WiringChatReceipt {
  pending: boolean;
  error?: string | null;
  onRetry?: () => Promise<boolean>;
}

/** Retry reads the saved decision receipt; it does not repeat a human decision. */
export function WiringReceiptStatus({ receipt }: { receipt: WiringChatReceipt }) {
  const tr = useMakerText();
  const [retrying, setRetrying] = useState(false);
  const retryLock = useRef(false);
  async function retry() {
    if (!receipt.onRetry || retryLock.current) return;
    retryLock.current = true; setRetrying(true);
    try { await receipt.onRetry(); } catch { /* The controller keeps the authoritative receipt error. */ }
    finally { retryLock.current = false; setRetrying(false); }
  }
  return <div className="wiring-chat-receipt" aria-busy={retrying}>
    <p role="status">{tr('正在確認剛才的決定…', 'Checking your last decision…')}</p>
    {receipt.error ? <><small>{receipt.error}</small><div className="wiring-chat-actions">
      <button type="button" disabled={retrying || !receipt.onRetry} onClick={() => void retry()}>{tr('重試取得確認結果', 'Retry retrieving the confirmation')}</button>
    </div></> : null}
  </div>;
}

function PhotoThumbnail({ url, role, onError }: { url: string; role?: WiringPhotoRole; onError?: () => void }) {
  const tr = useMakerText();
  const [failed, setFailed] = useState(false);
  if (failed) return <small className="wiring-chat-note" role="status">{tr('照片無法取得；請補拍此視角，不能當作未接線。', 'Photo unavailable. Retake this view; this does not mean unplugged.')}</small>;
  return <a className="wiring-chat-photo" href={url} target="_blank" rel="noreferrer" aria-label={tr('查看原始接線照片', 'View original wiring photo')}>
    <img src={url} loading="lazy" alt={role ? wiringChatRoleLabel(role, tr) : tr('接線照片', 'Wiring photo')} onError={() => { setFailed(true); onError?.(); }} />
  </a>;
}

function CropPhoto({ slot, disabled, onSave }: { slot: WiringPhotoSlot; disabled: boolean; onSave: (crop: WiringCrop | null) => Promise<boolean> }) {
  const tr = useMakerText();
  const image = useRef<HTMLImageElement>(null), drag = useRef<[number, number] | null>(null);
  const [crop, setCrop] = useState<WiringCrop | null>(slot.crop), [loaded, setLoaded] = useState(false), [failed, setFailed] = useState(false);
  const point = (event: PointerEvent<HTMLDivElement>, clamp = false) => image.current
    ? imagePointFromClient(event.clientX, event.clientY, image.current.getBoundingClientRect(), slot.size, clamp) : null;
  const percentages = crop ?? [0, 0, 1, 1];
  return <div className="wiring-chat-crop">
    <small>{tr('框入排針、插接底部、接頭及線色。框選不代表已確認腳號。', 'Include the header, insertion points, connectors and wire colors. A crop does not confirm pin identity.')}</small>
    <div className="wiring-chat-crop-stage" onPointerDown={event => {
      if (disabled || failed || !loaded || event.button !== 0) return;
      const start = point(event); if (!start) return;
      drag.current = start; event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault();
    }} onPointerMove={event => { const end = point(event, true); if (drag.current && end) setCrop(cropFromPoints(drag.current, end)); }}
      onPointerUp={event => { const end = point(event, true); if (drag.current && end) setCrop(cropFromPoints(drag.current, end)); drag.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { drag.current = null; }}>
      {!failed ? <><img ref={image} src={slot.image_url} alt={tr('供框選的原始照片', 'Original photo for cropping')} draggable={false}
        onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
        <svg viewBox={`0 0 ${slot.size[0]} ${slot.size[1]}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
          {crop ? <rect x={crop[0] * slot.size[0]} y={crop[1] * slot.size[1]} width={(crop[2] - crop[0]) * slot.size[0]} height={(crop[3] - crop[1]) * slot.size[1]}
            fill="#2cb5dc22" stroke="#00d2ff" strokeWidth="2" vectorEffect="non-scaling-stroke" /> : null}
        </svg></> : <small role="alert">{tr('原圖無法取得，請補拍此視角。', 'Original photo unavailable. Retake this view.')}</small>}
    </div>
    <fieldset disabled={disabled || failed || !loaded}><legend>{tr('拖曳框選，或輸入邊界百分比', 'Drag a crop, or enter boundary percentages')}</legend>
      {([tr('左', 'Left'), tr('上', 'Top'), tr('右', 'Right'), tr('下', 'Bottom')] as string[]).map((label, index) => <label key={label}>{label}
        <input type="number" min="0" max="100" step="0.1" value={Math.round(percentages[index] * 1000) / 10} onChange={event => {
          if (!event.target.value) return; const value = Number(event.target.value); if (!Number.isFinite(value)) return;
          const next = [...percentages] as WiringCrop; next[index] = Math.max(0, Math.min(1, value / 100)); if (validWiringCrop(next)) setCrop(next);
        }} /></label>)}
    </fieldset>
    <div className="wiring-chat-actions"><button type="button" disabled={disabled || failed || !loaded} onClick={() => void onSave(null)}>{tr('使用完整原圖', 'Use full original')}</button>
      <button type="button" disabled={disabled || failed || !loaded || !validWiringCrop(crop)} onClick={() => void onSave(crop)}>{tr('儲存框選', 'Save crop')}</button></div>
  </div>;
}

function EndpointText({ candidates, tr }: { candidates: WiringEndpoint[]; tr: Translate }) {
  if (!candidates.length) return <span>{tr('沒有足夠觀察；不能當作未接線。', 'Insufficient observation; this does not mean unplugged.')}</span>;
  return <ul>{candidates.map((candidate, index) => <li key={`${candidate.capture_id}:${candidate.id}:${index}`}>
    {candidate.physical_pin !== null ? `${tr('實體 Pin', 'Physical pin')} ${candidate.physical_pin}`
      : candidate.pin_label || `${tr('接頭', 'Connector')} ${candidate.id}（${tr('腳號待確認', 'pin unconfirmed')}）`} · {colorLabel(candidate.color, tr)}
    {candidate.color_visibility && candidate.color_visibility !== 'clear' ? ` · ${tr('線色遮擋或不可見', 'color partly hidden or not visible')}` : ''}
    {candidate.evidence ? <small>{candidate.evidence}</small> : null}
  </li>)}</ul>;
}

/** The current photo question shows its framing example on both desktop and phone. */
export function WiringCaptureFraming({ role, current = false }: { role: WiringPhotoRole; current?: boolean }) {
  const tr = useMakerText();
  return <details className="wiring-chat-framing" open={current}><summary>{tr('拍攝要點', 'Framing tips')}</summary><p>{role === 'component_header'
    ? tr('保留 pin 文字、插接底部、接頭及線色。', 'Keep pin labels, insertion points, connectors and wire colors visible.')
    : tr('保留板子方向、排針、插接底部及線色；另一側要露出被遮住的接頭。', 'Include board orientation, the header, insertion points and wire colors. Use the other side to reveal hidden connectors.')}</p>
    <svg className="wiring-chat-framing-image" viewBox="0 0 220 104" role="img" aria-label={tr('取景示意：排針、插接底部、接頭和線色一起入鏡，不是 GPIO 腳位圖。', 'Framing example: include the header, insertion points, connectors and wire colors. This is not a GPIO pin map.')}>
      <rect x="18" y="71" width="184" height="18" rx="4" fill="#527b68" /><rect x="40" y="61" width="139" height="12" fill="#35424b" />
      {[0, 1, 2, 3, 4, 5, 6, 7].map(n => <g key={n}><path d={`M${51 + n * 16} 62v-12`} stroke="#9caab2" strokeWidth="3" />
        {n < 5 ? <><rect x={47 + n * 16} y="32" width="10" height="25" rx="2" fill="#263444" />
          <path d={`M${52 + n * 16} 32v-18`} stroke={['#d56b62', '#dcb64c', '#739ab6', '#82976c', '#9b7ea6'][n]} strokeWidth="5" /></> : null}</g>)}
      <rect x="34" y="8" width="148" height="75" rx="8" fill="none" stroke="#407a9c" strokeWidth="2" strokeDasharray="5 4" />
      <text x="110" y="101" textAnchor="middle" fontSize="10" fill="currentColor">{role === 'component_header' ? tr('保留 pin 文字', 'Keep pin labels') : tr('保留板緣與插接底部', 'Keep board edge and insertion points')}</text>
    </svg><small>{tr('同一輪拍照時保持接線不變。', 'Keep the wiring unchanged throughout this photo round.')}</small></details>;
}

/** One ordinary persisted message, with only its current server-authorised actions. */
export function WiringChatMessage({ message, review, busy = false, inactive = false, receipt, onAction }: {
  message: AssistantMessage; review?: WiringReviewState | null; busy?: boolean; inactive?: boolean;
  receipt?: WiringChatReceipt;
  onAction?: (message: AssistantMessage, action: WiringReviewAction) => Promise<boolean>;
}) {
  const tr = useMakerText(), flow = message.wiring_flow;
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const lock = useRef(false), latest = useRef({ message, busy, onAction });
  latest.current = { message, busy, onAction };
  if (!flow || flow.kind === 'human_decision') return null;
  const matched = wiringFlowReview(flow, review);
  const disabled = busy || pending || !onAction;
  const can = (op: Parameters<typeof wiringFlowCanAct>[1]) => !inactive && wiringFlowCanAct(flow, op);
  async function act(action: WiringReviewAction) {
    const current = latest.current, active = current.message.wiring_flow;
    if (lock.current || current.busy || !current.onAction || !active || active.flow_id !== flow?.flow_id
      || active.revision !== flow.revision || active.round !== flow.round || current.message.id !== message.id) return false;
    const bound = boundWiringChatAction(active, action); if (!bound) return false;
    lock.current = true; setPending(true); setError('');
    const stillCurrent = () => {
      const next = latest.current.message;
      return next.id === current.message.id && next.wiring_flow?.current === true && next.wiring_flow.flow_id === active.flow_id
        && next.wiring_flow.review_id === active.review_id && next.wiring_flow.revision === active.revision && next.wiring_flow.round === active.round;
    };
    try {
      const ok = await current.onAction(current.message, bound);
      if (!ok && stillCurrent()) setError(tr('操作尚未完成，請再試一次。', 'Action did not complete. Try again.'));
      return ok;
    } catch (cause) {
      if (stillCurrent()) setError(cause instanceof Error ? cause.message : tr('操作失敗，請再試一次。', 'Action failed. Try again.'));
      return false;
    } finally { lock.current = false; setPending(false); }
  }
  const photoUrl = flow.image_url || (flow.capture_id && message.session_id
    ? `/api/debug/sessions/${encodeURIComponent(message.session_id)}/evidence/${encodeURIComponent(flow.capture_id)}` : undefined);
  const roles = flow.kind === 'photo_request' && flow.role ? [flow.role] : wiringPhotoRoles;
  const hasPhotoOptions = can('crop') || can('capture') && flow.kind !== 'photo_request';
  return <div className="wiring-chat-message" data-wiring-flow={flow.kind} aria-busy={pending}>
    {flow.kind === 'analysing' && flow.current && !inactive ? <AssistantAnalysisTime startedAt={flow.started_at} /> : null}
    {!(flow.kind === 'analysing' && flow.current && !inactive) && typeof flow.elapsed_ms === 'number'
      ? <AssistantAnalysisTime active={false} durationMs={flow.elapsed_ms} /> : null}
    {flow.kind === 'photo' && photoUrl ? <PhotoThumbnail key={photoUrl} url={photoUrl} role={flow.role} /> : null}
    {flow.kind === 'photo_request' && flow.role ? <>
      <WiringCaptureFraming role={flow.role} current={flow.current && !inactive} />
      {can('capture') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'capture', role: flow.role })}>
        {pending ? tr('拍攝中…', 'Capturing…') : tr(`拍攝${wiringChatRoleLabel(flow.role, tr)}`, `Capture ${wiringChatRoleLabel(flow.role, tr)}`)}</button></div> : null}
    </> : null}
    {flow.kind === 'wire_review' && flow.result ? <div className="wiring-chat-wire">
      <dl><dt>{tr('預期接法', 'Expected connection')}</dt><dd>{flow.result.expected.component_pin} → {flow.result.expected.physical_pin !== null
        ? `${tr('實體 Pin', 'Physical pin')} ${flow.result.expected.physical_pin}` : flow.result.expected.board_pin || tr('腳位待確認', 'Pin unconfirmed')}
        {flow.result.expected.bcm !== null ? ` · BCM ${flow.result.expected.bcm}` : ''}</dd></dl>
      <details><summary>{tr('查看腳位與線色依據', 'View pin and color evidence')}</summary>
        <p className="wiring-chat-basis">{wiringComparisonText(flow.result.comparison, tr)}</p>
        <dl>
        <dt>{tr('Pi 端觀察', 'Pi observation')}</dt><dd><EndpointText candidates={flow.result.pi_candidates} tr={tr} /></dd>
        <dt>{tr('零件端觀察', 'Module observation')}</dt><dd><EndpointText candidates={flow.result.component_candidates} tr={tr} /></dd></dl>
        {flow.result.evidence ? <p>{flow.result.evidence}</p> : null}</details>
      <p>{flow.result.next_step}</p>
      {can('review') ? <div className="wiring-chat-actions"><button type="button" className="wiring-chat-decision is-confirmed" disabled={disabled} title={tr('我已親自確認接對', 'I personally confirmed this connection')} aria-label={tr('我已親自確認接對', 'I personally confirmed this connection')}
        onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'confirmed' })}>{tr('接對', 'Correct')}</button>
        <button type="button" className="wiring-chat-decision is-needs-change" disabled={disabled} title={tr('我發現接錯，準備修正', 'I found a wiring error; I will correct it')} aria-label={tr('我發現接錯，準備修正', 'I found a wiring error; I will correct it')}
          onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'needs_change' })}>{tr('接錯', 'Incorrect')}</button>
        <button type="button" className="wiring-chat-decision is-unsure" disabled={disabled} title={tr('仍無法確定', 'Still unsure')} aria-label={tr('仍無法確定', 'Still unsure')}
          onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'unsure' })}>{tr('不確定', 'Unsure')}</button></div> : null}
    </div> : null}
    {can('analyse') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'analyse' })}>{pending ? tr('送出中…', 'Sending…') : tr('開始核對', 'Start review')}</button></div> : null}
    {hasPhotoOptions ? <details className="wiring-chat-evidence"><summary>{tr('查看照片／補拍／框選', 'View photos / retake / crop')}</summary>
      {roles.map(role => {
        const slot = matched?.slots[role];
        return <div key={role} className="wiring-chat-photo-option"><strong>{wiringChatRoleLabel(role, tr)}</strong>
          {slot?.available !== false && slot ? <PhotoThumbnail key={slot.capture_id} url={slot.image_url} role={role} /> : <small>{tr('目前沒有可用照片。', 'No available photo yet.')}</small>}
          {can('capture') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'capture', role })}>{tr('補拍此視角', 'Retake this view')}</button></div> : null}
          {can('crop') && slot && slot.available !== false ? <details><summary>{tr('手動框選分析區域', 'Select an analysis area')}</summary>
            <CropPhoto key={`${slot.capture_id}:${matched?.revision}`} slot={slot} disabled={disabled} onSave={crop => act({ op: 'crop', role, capture_id: slot.capture_id, sha256: slot.sha256, crop })} /></details> : null}
        </div>;
      })}</details> : null}
    {can('changed') ? <details className="wiring-chat-changed"><summary>{tr('修正接線後', 'After changing the wiring')}</summary><p>{tr('實際改線後建立新一輪，舊照片及確認會保留為歷史。', 'Start a new round after changing the wiring. Earlier photos and confirmations remain in history.')}</p>
      <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'changed' })}>{tr('我已改線，重新拍照', 'I changed the wiring; take new photos')}</button></div></details> : null}
    {error && flow.current && !inactive && !receipt?.pending ? <p className="wiring-chat-error" role="alert">{error}</p> : null}
    {receipt?.pending || receipt?.error ? <WiringReceiptStatus receipt={receipt} /> : null}
  </div>;
}
