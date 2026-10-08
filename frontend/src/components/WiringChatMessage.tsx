import { useRef, useState, type PointerEvent, type ReactNode } from 'react';
import type { AssistantMessage } from '../lib/assistant';
import { useMakerText } from '../lib/useMaker';
import { boundWiringChatAction, compactWiringText, wiringChatSummary, wiringComparisonText, wiringFlowCanAct, wiringFlowReview, type WiringChatSummary } from '../lib/wiringChat';
import { sameWiringCrop, wiringPhotoStatus, wiringPhotosReady } from '../lib/wiringPhotoStatus';
import { AssistantAnalysisTime } from './AssistantAnalysisTime';
import { WiringFramingGuide } from './WiringFramingGuide';
import { WiringExpectedLocation } from './WiringExpectedLocation';
import { wiringVisualSummary } from '../lib/wiringExpectedLocation';
import { cropFromPoints, imagePointFromClient, validWiringCrop, wiringPhotoRoles, wiringFindingStatus, wiringFindingLabel, wiringPhotoRoleLabel, wiringPhotoRow, wiringSuspectedConnectionText, wiringPinSeatText,
  type WiringCapturePlan, type WiringCrop, type WiringEndpoint, type WiringPhotoRole, type WiringPhotoSlot, type WiringReviewAction, type WiringReviewState } from '../lib/wiringReview';
import './wiringChat.css';

type Translate = (zh: string, en: string) => string;
export const wiringChatRoleLabel = wiringPhotoRoleLabel;
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

function PhotoThumbnail({ url, role, capturePlan, onError }: { url: string; role?: WiringPhotoRole; capturePlan?: WiringCapturePlan; onError?: () => void }) {
  const tr = useMakerText();
  const [failed, setFailed] = useState(false);
  if (failed) return <small className="wiring-chat-note" role="status">{tr('照片無法取得；請補拍此視角，不能當作未接線。', 'Photo unavailable. Retake this view; this does not mean unplugged.')}</small>;
  return <a className="wiring-chat-photo" href={url} target="_blank" rel="noreferrer" aria-label={tr('查看原始接線照片', 'View original wiring photo')}>
    <img src={url} loading="lazy" alt={role ? wiringChatRoleLabel(role, tr, capturePlan) : tr('接線照片', 'Wiring photo')} onError={() => { setFailed(true); onError?.(); }} />
  </a>;
}

function CropPhoto({ slot, disabled, delivery, onSave }: { slot: WiringPhotoSlot; disabled: boolean;
  delivery: ReturnType<typeof wiringPhotoStatus>; onSave: (crop: WiringCrop | null) => Promise<boolean> }) {
  const tr = useMakerText();
  const image = useRef<HTMLImageElement>(null), drag = useRef<[number, number] | null>(null);
  const [crop, setCrop] = useState<WiringCrop | null>(slot.crop), [loaded, setLoaded] = useState(false), [failed, setFailed] = useState(false);
  const point = (event: PointerEvent<HTMLDivElement>, clamp = false) => image.current
    ? imagePointFromClient(event.clientX, event.clientY, image.current.getBoundingClientRect(), slot.size, clamp) : null;
  const percentages = crop ?? [0, 0, 1, 1];
  const dirty = !sameWiringCrop(crop, slot.crop);
  async function save(value: WiringCrop | null) { if (await onSave(value)) setCrop(value); }
  return <div className="wiring-chat-crop">
    <p className="wiring-chat-delivery-status" role="status">{dirty
      ? tr('框選尚未儲存，AI 還沒收到這個範圍。', 'Unsaved crop. This region has not been sent to AI.')
      : photoDeliveryLabel(delivery, Boolean(slot.crop), tr)}</p>
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
    <div className="wiring-chat-actions"><button type="button" disabled={disabled || failed || !loaded} onClick={() => void save(null)}>{tr('使用完整原圖', 'Use full original')}</button>
      <button type="button" disabled={disabled || failed || !loaded || !validWiringCrop(crop)} onClick={() => void save(crop)}>{tr('儲存框選', 'Save crop')}</button></div>
    {dirty || delivery.state === 'pending' ? <small>{tr('儲存後按「開始分析」，才會送出全景與框選局部圖；不用重拍原照片。', 'After saving, choose Start analysis to send the overview and crop. Keep the existing photo.')}</small> : null}
  </div>;
}

export function photoDeliveryLabel(delivery: ReturnType<typeof wiringPhotoStatus>, cropped: boolean, tr: Translate) {
  if (delivery.state === 'missing') return tr('缺少照片', 'Photo missing');
  if (delivery.state === 'unaccepted') return tr('照片已儲存，待選用', 'Photo saved; select it for analysis');
  if (delivery.state === 'analysing') return tr('本輪分析進行中…', 'Analysis is in progress…');
  if (delivery.state === 'reused') return tr('沿用先前分析（這次未重送）', 'Previous analysis reused (not resent this time)');
  if (delivery.state === 'analysed') {
    const detail = delivery.images.find(image => image.view === 'detail');
    return delivery.detail && detail ? tr(`AI 已分析此框選 · ${detail.size[0]} × ${detail.size[1]}`, `AI analysed this crop · ${detail.size[0]} × ${detail.size[1]}`)
      : tr('AI 已分析這張全景', 'AI analysed this overview');
  }
  if (delivery.state === 'pending') return cropped
    ? tr('框選已儲存，等待開始分析。', 'Crop saved; waiting to start analysis.')
    : tr('照片已備妥，等待開始分析。', 'Photo ready; waiting to start analysis.');
  return tr('尚無這個範圍的分析完成紀錄。', 'No verified completed analysis for this region.');
}

/** Uses source-bound tool receipts, never a model's claim to have seen a photo. */
export function WiringPhotoDelivery({ review }: { review?: WiringReviewState | null }) {
  const tr = useMakerText();
  if (!review) return null;
  const entries = wiringPhotoRoles.map(role => ({ role, delivery: wiringPhotoStatus(review, role) }));
  const ready = wiringPhotosReady(review);
  const completed = entries.every(({ delivery }) => ['analysed', 'reused'].includes(delivery.state));
  const count = entries.filter(({ delivery }) => !['missing', 'unaccepted'].includes(delivery.state)).length;
  return <div className="wiring-chat-delivery">
    <p className="wiring-chat-delivery-status" role="status">{review.status === 'analysing'
      ? tr('照片已提交，AI 分析中…', 'Photos submitted; AI is analysing…')
      : ready && completed ? tr('三張照片已齊 · AI 已完成分析', 'All 3 photos ready · AI analysis completed')
        : ready && review.status === 'error' ? tr('三張照片已齊 · 分析未完成', 'All 3 photos ready · analysis incomplete')
          : ready && review.status === 'collecting' ? tr('三張照片已齊 · 等待分析', 'All 3 photos ready · awaiting analysis')
          : ready ? tr('三張照片已齊 · 分析送出紀錄待確認', 'All 3 photos ready · analysis receipt unverified')
          : tr(`已備妥 ${count} / 3 張照片`, `${count} / 3 photos ready`)}</p>
    <details><summary>{tr('AI 收到哪些圖片？', 'Which images reached AI?')}</summary>
      {entries.map(({ role, delivery }) => <div className="wiring-chat-delivery-entry" key={role}>
        <strong>{wiringChatRoleLabel(role, tr, review.capture_plan)}</strong>
        <small>{photoDeliveryLabel(delivery, Boolean(review.slots[role]?.crop), tr)}</small>
        {delivery.images.map(image => <small key={`${image.view}:${image.supplied_sha256}`}>
          {image.view === 'detail' ? tr('框選局部', 'Selected crop') : tr('全景', 'Overview')} · {image.size[0]} × {image.size[1]}
        </small>)}
      </div>)}
      <small>{tr('這是照片分析的送出紀錄。一般文字聊天不會自動重新傳圖。', 'This records the photo analysis inputs. Ordinary text chat does not automatically resend images.')}</small>
    </details>
  </div>;
}

function EndpointText({ candidates, tr }: { candidates: WiringEndpoint[]; tr: Translate }) {
  if (!candidates.length) return <span>{tr('沒有足夠觀察；不能當作未接線。', 'Insufficient observation; this does not mean unplugged.')}</span>;
  return <ul>{candidates.map((candidate, index) => {
    const modulePin = candidate.role === 'component_header' ? candidate.module_pin_id : null;
    const seatText = wiringPinSeatText(candidate, tr);
    return <li key={`${candidate.capture_id}:${candidate.id}:${index}`}>
    {candidate.physical_pin !== null ? `${tr('實體 Pin', 'Physical pin')} ${candidate.physical_pin}`
      : modulePin || candidate.pin_label || `${tr('接頭', 'Connector')} ${candidate.id}（${tr('腳號待確認', 'pin unconfirmed')}）`} · {colorLabel(candidate.color, tr)}
    {modulePin && !candidate.pin_id ? <small>{tr('標字位置已辨識；插接待確認', 'Label position identified; plug contact unconfirmed')}</small> : null}
    {candidate.color_visibility && candidate.color_visibility !== 'clear' ? ` · ${tr('線色遮擋或不可見', 'color partly hidden or not visible')}` : ''}
    {modulePin && candidate.module_pin_evidence && candidate.module_pin_evidence !== candidate.evidence ? <small>{candidate.module_pin_evidence}</small> : null}
    {candidate.evidence ? <small>{candidate.evidence}</small> : null}
    {seatText ? <><small>{seatText}</small><small>{candidate.pin_seat?.orientation_anchor} {candidate.pin_seat?.count_evidence}</small></> : null}
    {candidate.local_color ? <small>{tr('局部色票：', 'Local color sample: ')}{colorLabel(candidate.local_color.name, tr)}
      {candidate.color_agreement === 'different' ? tr(' · 與照片辨色不同，需核對', ' · differs from the visual color; check this area') : ''}
      {tr('（僅輔助辨色）', ' (color aid only)')}</small> : null}
  </li>;
  })}</ul>;
}

/** Show the requested row immediately; keep historical examples collapsed. */
export function WiringCaptureFraming({ role, capturePlan, current = false }: { role: WiringPhotoRole; capturePlan?: WiringCapturePlan; current?: boolean }) {
  const tr = useMakerText();
  const row = wiringPhotoRow(role, capturePlan);
  const diagram = <WiringFramingGuide role={role} capturePlan={capturePlan} />;
  const tips = <><p>{row ? tr('稍微降低相機，拍到這排的插接底部與線色，不要只拍線的上段。', 'Lower the camera slightly to show this row’s insertion points and wire colours, not just the upper wires.')
    : role === 'component_header' ? tr('保留 pin 文字、插接底部、接頭及線色。', 'Keep pin labels, insertion points, connectors and wire colors visible.')
      : tr('保留板子方向、排針、插接底部及線色；另一側要露出被遮住的接頭。', 'Include board orientation, the header, insertion points and wire colors. Use the other side to reveal hidden connectors.')}</p>
    <small>{tr('同一輪拍照時保持接線不變。', 'Keep the wiring unchanged throughout this photo round.')}</small></>;
  return row && current ? <div className="wiring-chat-row-framing">
    {diagram}<small>{tr('內外依板中央／板邊緣區分，不看畫面左右。', 'Use the board centre and edge, not screen left or right.')}</small>
    <details className="wiring-chat-framing"><summary>{tr('取景提醒', 'Framing tips')}</summary>{tips}</details>
  </div> : <details className="wiring-chat-framing"><summary>{tr('怎麼拍？', 'Framing tips')}</summary>{diagram}{tips}</details>;
}

/** This summary is visual advice; it never records a human wiring decision. */
export function WiringReviewOverview({ summary, focusWireId, children }: { summary: WiringChatSummary; focusWireId?: string; children?: ReactNode }) {
  const tr = useMakerText();
  const visual = wiringVisualSummary(summary, tr, focusWireId);
  return <div className="wiring-chat-overview">
    <p className="wiring-chat-headline">{visual.headline}</p>
    {visual.evidence ? <p className="wiring-chat-observation">{visual.evidence}</p> : null}
    <p className="wiring-chat-instruction">{visual.next_step}</p>
    {visual.targets.length ? <WiringExpectedLocation rows={visual.targets} /> : null}
    {children}
    <details className="wiring-chat-summary-detail"><summary>{tr('查看分析詳情', 'View analysis details')}</summary>
      {summary.observation && summary.observation !== summary.evidence ? <p>{summary.observation}</p> : null}
      {summary.evidence ? <p>{summary.evidence}</p> : null}
      <ul>{summary.results.map(row => <li key={row.wire_id}>
        <strong>{row.expected.component_pin} → {row.expected.physical_pin != null ? `Pin ${row.expected.physical_pin}` : row.expected.board_pin}</strong>
        <span>{wiringFindingLabel(row, tr)}</span>
        <small>{row.diagnosis?.evidence || row.evidence}</small>
      </li>)}</ul>
      <small>{tr('照片判讀與人工接線確認分開記錄。', 'Photo findings and your wiring confirmations are recorded separately.')}</small>
    </details>
  </div>;
}

/** Avoid repeating the original long paragraph above structured message content. */
export function wiringMessageHasBody(message: AssistantMessage) {
  const flow = message.wiring_flow;
  return message.role === 'assistant' && Boolean(flow && (
    ['photo_request', 'analysis_request', 'analysing'].includes(flow.kind) || flow.kind === 'wire_review' && flow.result));
}

/** One ordinary persisted message, with only its current server-authorised actions. */
export function WiringChatMessage({ message, review, busy = false, inactive = false, receipt, onAction }: {
  message: AssistantMessage; review?: WiringReviewState | null; busy?: boolean; inactive?: boolean;
  receipt?: WiringChatReceipt;
  onAction?: (message: AssistantMessage, action: WiringReviewAction) => Promise<boolean>;
}) {
  const tr = useMakerText(), flow = message.wiring_flow;
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const [positionChoice, setPositionChoice] = useState<string | null>(null);
  const [positionFailure, setPositionFailure] = useState<string | null>(null);
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
  const finding = flow.result?.diagnosis;
  const findingStatus = flow.result ? wiringFindingStatus(flow.result) : 'uncertain';
  const observation = finding?.evidence || flow.result?.evidence;
  const summary = wiringChatSummary(flow, review, tr);
  const swapAdvisory = finding?.kind === 'reciprocal_endpoint_swap';
  const unconnectedTerminal = finding?.kind === 'unconnected_terminal';
  const rowPositionCheck = finding?.kind === 'row_position_check';
  const moduleWrong = findingStatus === 'suspected' && !swapAdvisory && !unconnectedTerminal && finding?.observed_component_pin != null && finding.observed_component_pin !== flow.result?.expected.component_pin;
  const positionCandidate = swapAdvisory || unconnectedTerminal || rowPositionCheck ? undefined : matched?.observations.find(c => c.id === (moduleWrong ? finding?.component_connector_id : finding?.board_connector_id));
  const positionSlot = positionCandidate ? Object.values(matched?.slots ?? {}).find(slot => slot?.capture_id === positionCandidate.capture_id) : null;
  const expectedCandidate = matched?.observations.find(c => c.capture_id === positionCandidate?.capture_id
    && c.pin_id === (moduleWrong ? flow.result?.expected.component_pin : flow.result?.expected.board_pin));
  const positionKey = `${flow.review_id}:${flow.revision}:${flow.round}:${flow.wire_id}`;
  const routine = ['photo_request', 'analysis_request', 'analysing'].includes(flow.kind);
  const history = routine && (!flow.current || inactive);
  const content = <div className="wiring-chat-message" data-wiring-flow={flow.kind} aria-busy={pending}>
    {flow.current && !inactive && ['analysis_request', 'analysing', 'wire_review', 'error'].includes(flow.kind)
      ? <WiringPhotoDelivery review={matched} /> : null}
    {routine ? <p className="wiring-chat-instruction">{history ? message.text : compactWiringText(flow, message.text, tr)}</p> : null}
    {flow.kind === 'analysing' && flow.current && !inactive ? <AssistantAnalysisTime startedAt={flow.started_at} /> : null}
    {flow.kind !== 'wire_review' && !(flow.kind === 'analysing' && flow.current && !inactive) && typeof flow.elapsed_ms === 'number'
      ? <AssistantAnalysisTime active={false} durationMs={flow.elapsed_ms} /> : null}
    {flow.kind === 'photo' && photoUrl ? <PhotoThumbnail key={photoUrl} url={photoUrl} role={flow.role} capturePlan={flow.capture_plan} /> : null}
    {flow.kind === 'photo_request' && flow.role ? <>
      <small className="wiring-chat-photo-progress">{tr('照片', 'Photo')} {wiringPhotoRoles.indexOf(flow.role) + 1} / 3</small>
      <WiringCaptureFraming role={flow.role} capturePlan={flow.capture_plan} current={flow.current && !inactive} />
      {can('capture') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'capture', role: flow.role })}>
        {pending ? tr('拍攝中…', 'Capturing…') : tr(`拍攝${wiringChatRoleLabel(flow.role, tr, flow.capture_plan)}`, `Capture ${wiringChatRoleLabel(flow.role, tr, flow.capture_plan)}`)}</button></div> : null}
    </> : null}
    {summary ? <WiringReviewOverview summary={summary} focusWireId={flow.wire_id}>
      {summary.retake_role && can('capture') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled}
        onClick={() => void act({ op: 'capture', role: summary.retake_role! })}>
        {pending ? tr('拍攝中…', 'Capturing…') : tr(`補拍${wiringChatRoleLabel(summary.retake_role, tr, flow.capture_plan)}`, `Retake ${wiringChatRoleLabel(summary.retake_role, tr, flow.capture_plan)}`)}</button></div> : null}
    </WiringReviewOverview> : null}
    {flow.kind === 'wire_review' && flow.result ? <details className="wiring-chat-manual"><summary>{tr('逐線核對（選用）', 'Check each wire (optional)')}</summary><div className="wiring-chat-wire">
      {typeof flow.elapsed_ms === 'number' ? <AssistantAnalysisTime active={false} durationMs={flow.elapsed_ms} /> : null}
      <strong className={`wiring-chat-finding is-${findingStatus}`}>{wiringFindingLabel(flow.result, tr)}</strong>
      <dl><dt>{tr('預期接法', 'Expected connection')}</dt><dd>{flow.result.expected.component_pin} → {flow.result.expected.physical_pin !== null
        ? `${tr('實體 Pin', 'Physical pin')} ${flow.result.expected.physical_pin}` : flow.result.expected.board_pin || tr('腳位待確認', 'Pin unconfirmed')}
        </dd></dl>
      {findingStatus === 'suspected' ? <p className="wiring-chat-suspected">{wiringSuspectedConnectionText(flow.result, tr)}</p> : null}
      <div className="wiring-chat-observation"><strong>{rowPositionCheck ? tr('位置線索', 'Position clue') : findingStatus === 'uncertain' ? tr('還不確定', 'Still uncertain') : tr('照片依據', 'Photo evidence')}</strong>
        <p>{observation || wiringComparisonText(flow.result.comparison, tr)}</p></div>
      <div className="wiring-chat-next"><strong>{tr('下一步', 'Next step')}</strong>
        <p>{flow.result.next_step}</p>
        {findingStatus === 'suspected' ? <small>{unconnectedTerminal ? tr('先斷電，再核對或調整接線。', 'Power off before checking or changing the connection.')
          : tr('先斷電，再沿線核對或調整。', 'Power off before tracing or changing wires.')}</small> : null}
      </div>
      {positionSlot?.available !== false && positionSlot && validWiringCrop(positionCandidate?.box) ? <>
        <div className="wiring-chat-actions"><button type="button" aria-expanded={positionChoice === positionKey}
          onClick={() => { setPositionFailure(null); setPositionChoice(positionChoice === positionKey ? null : positionKey); }}>{tr('查看照片位置', 'View position in photo')}</button></div>
        {positionChoice === positionKey ? <figure className="wiring-chat-position">{positionFailure === positionKey
          ? <small role="alert">{tr('照片無法取得，請補拍此側；不能只看標記判定接錯。', 'Photo unavailable. Retake this side; markers alone cannot establish a fault.')}</small>
          : <><div className="wiring-chat-crop-stage"><img src={positionSlot.image_url} alt={tr('本輪接線照片與候選位置', 'Current wiring photo and candidate positions')}
              onError={() => setPositionFailure(positionKey)} />
          <svg viewBox={`0 0 ${positionSlot.size[0]} ${positionSlot.size[1]}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
            {[positionCandidate, ...(expectedCandidate && expectedCandidate !== positionCandidate && validWiringCrop(expectedCandidate.box) ? [expectedCandidate] : [])].map((c, i) => c && validWiringCrop(c.box) ? <g key={c.id} className={i === 0 ? 'wiring-chat-marker-observed' : 'wiring-chat-marker-expected'}>
              <rect x={c.box[0] * positionSlot.size[0]} y={c.box[1] * positionSlot.size[1]} width={(c.box[2] - c.box[0]) * positionSlot.size[0]}
                height={(c.box[3] - c.box[1]) * positionSlot.size[1]} fill="none" stroke="currentColor" strokeWidth="3" vectorEffect="non-scaling-stroke" />
              <text x={c.box[0] * positionSlot.size[0]} y={i === 0 ? Math.max(positionSlot.size[0] * .036, c.box[1] * positionSlot.size[1] - positionSlot.size[0] * .014)
                : Math.min(positionSlot.size[1] * .97, c.box[3] * positionSlot.size[1] + positionSlot.size[0] * .045)}
                fontSize={positionSlot.size[0] * .036} fill="currentColor" stroke="var(--bg-inset, #10151c)" strokeWidth={positionSlot.size[0] * .004} paintOrder="stroke">{c.physical_pin !== null ? `Pin ${c.physical_pin}` : c.pin_label}</text>
            </g> : null)}</svg></div><figcaption>{tr('橘框：照片位置 · 藍框：應接腳位的可見接頭', 'Orange: observed position · blue: visible connector at the expected pin')}</figcaption></>}</figure> : null}
      </> : null}
      <details><summary>{tr('查看腳位與線色依據', 'View pin and color evidence')}</summary>
        {flow.result.expected.bcm != null ? <small>BCM {flow.result.expected.bcm}</small> : null}
        <p className="wiring-chat-basis">{wiringComparisonText(flow.result.comparison, tr)}</p>
        <dl>
        <dt>{tr('Pi 端觀察', 'Pi observation')}</dt><dd><EndpointText candidates={flow.result.pi_candidates} tr={tr} /></dd>
        <dt>{tr('零件端觀察', 'Module observation')}</dt><dd><EndpointText candidates={flow.result.component_candidates} tr={tr} /></dd></dl>
        {observation ? <p>{observation}</p> : null}
        {flow.result.evidence && flow.result.evidence !== observation ? <p>{flow.result.evidence}</p> : null}</details>
      {can('review') ? <div className="wiring-chat-actions"><button type="button" className="wiring-chat-decision is-confirmed" disabled={disabled} title={tr('我已親自確認接對', 'I personally confirmed this connection')} aria-label={tr('我已親自確認接對', 'I personally confirmed this connection')}
        onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'confirmed' })}>{tr('接對', 'Correct')}</button>
        <button type="button" className="wiring-chat-decision is-needs-change" disabled={disabled} title={tr('我發現接錯，準備修正', 'I found a wiring error; I will correct it')} aria-label={tr('我發現接錯，準備修正', 'I found a wiring error; I will correct it')}
          onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'needs_change' })}>{tr('接錯', 'Incorrect')}</button>
        <button type="button" className="wiring-chat-decision is-unsure" disabled={disabled} title={tr('仍無法確定', 'Still unsure')} aria-label={tr('仍無法確定', 'Still unsure')}
          onClick={() => void act({ op: 'review', wire_id: flow.wire_id, decision: 'unsure' })}>{tr('不確定', 'Unsure')}</button></div> : null}
      <details><summary>{tr('原始分析紀錄', 'Original analysis record')}</summary><p>{message.text}</p></details>
    </div></details> : null}
    {can('analyse') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'analyse' })}>{pending ? tr('送出中…', 'Sending…') : tr('開始分析', 'Start analysis')}</button></div> : null}
    {flow.kind === 'error' && flow.error ? <details><summary>{tr('查看錯誤原因', 'View error details')}</summary><p>{flow.error}</p></details> : null}
    {hasPhotoOptions ? <details className="wiring-chat-evidence"><summary>{tr('查看照片／補拍／框選', 'View photos / retake / crop')}</summary>
      {roles.map(role => {
        const slot = matched?.slots[role];
        return <div key={role} className="wiring-chat-photo-option"><strong>{wiringChatRoleLabel(role, tr, flow.capture_plan)}</strong>
          {slot?.available !== false && slot ? <PhotoThumbnail key={slot.capture_id} url={slot.image_url} role={role} capturePlan={flow.capture_plan} /> : <small>{tr('目前沒有可用照片。', 'No available photo yet.')}</small>}
          {can('capture') ? <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'capture', role })}>{tr('補拍此視角', 'Retake this view')}</button></div> : null}
          {can('crop') && slot && slot.available !== false ? <details><summary>{tr('手動框選分析區域', 'Select an analysis area')}</summary>
            <CropPhoto key={`${slot.capture_id}:${matched?.revision}`} slot={slot} disabled={disabled} delivery={wiringPhotoStatus(matched, role)} onSave={crop => act({ op: 'crop', role, capture_id: slot.capture_id, sha256: slot.sha256, crop })} /></details> : null}
        </div>;
      })}</details> : null}
    {can('changed') ? <details className="wiring-chat-changed"><summary>{tr('修正接線後', 'After changing the wiring')}</summary><p>{tr('實際改線後建立新一輪，舊照片及確認會保留為歷史。', 'Start a new round after changing the wiring. Earlier photos and confirmations remain in history.')}</p>
      <div className="wiring-chat-actions"><button type="button" disabled={disabled} onClick={() => void act({ op: 'changed' })}>{tr('我已改線，重新拍照', 'I changed the wiring; take new photos')}</button></div></details> : null}
    {error && flow.current && !inactive && !receipt?.pending ? <p className="wiring-chat-error" role="alert">{error}</p> : null}
    {receipt?.pending || receipt?.error ? <WiringReceiptStatus receipt={receipt} /> : null}
  </div>;
  return history ? <details className="wiring-chat-history"><summary>{compactWiringText(flow, message.text, tr)}</summary>{content}</details> : content;
}
