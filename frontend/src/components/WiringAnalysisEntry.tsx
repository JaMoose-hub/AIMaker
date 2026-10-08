import { useRef, useState } from 'react';
import { useMakerText } from '../lib/useMaker';
import type { AssistantMessage } from '../lib/assistant';
import type { WiringReviewAction, WiringReviewState } from '../lib/wiringReview';
import { boundWiringChatAction } from '../lib/wiringChat';

/** Visible shortcut into the existing conversation; owns no review or photos. */
export function WiringAnalysisEntry({ components, preferredId, message, review, busy, aiReady, onStart, onShow, onAnalyse }: {
  components: { id: string; label: string }[];
  preferredId?: string;
  message?: AssistantMessage;
  review?: WiringReviewState | null;
  busy: boolean;
  aiReady: boolean;
  onStart: (componentId: string) => Promise<boolean>;
  onShow: (message: AssistantMessage) => void;
  onAnalyse?: (message: AssistantMessage, action: WiringReviewAction) => Promise<boolean>;
}) {
  const tr = useMakerText();
  const [choice, setChoice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const flight = useRef(false);
  const flow = message?.wiring_flow?.current ? message.wiring_flow : undefined;
  const selected = flow?.component_id ?? [choice, preferredId, components[0]?.id].find(id => components.some(c => c.id === id)) ?? '';
  const matched = flow && review?.id === flow.review_id && review.revision === flow.revision && review.round === flow.round
    && review.component_id === flow.component_id ? review : null;
  const count = matched ? Object.values(matched.slots).filter(slot => slot && slot.available !== false).length : null;
  const analyse = flow && ['analysis_request', 'error'].includes(flow.kind) ? boundWiringChatAction(flow, { op: 'analyse' }) : null;
  const label = pending ? tr('處理中…', 'Working…') : analyse ? flow?.kind === 'error' ? tr('重新分析', 'Retry analysis') : tr('開始分析', 'Start analysis')
    : flow?.kind === 'photo_request' ? tr('繼續拍照', 'Continue photos')
    : flow?.kind === 'analysing' ? tr('查看分析進度', 'View analysis progress')
    : flow ? tr('查看接線核對', 'View wiring review') : tr('拍照檢查接線', 'Check wiring with photos');
  const disabled = pending || (!flow || analyse ? busy || !aiReady || !selected || Boolean(analyse && !onAnalyse) : false);
  async function activate() {
    if (flight.current || disabled) return;
    if (flow && message && !analyse) { onShow(message); return; }
    flight.current = true; setPending(true); setError('');
    try {
      const ok = analyse && message ? await onAnalyse!(message, analyse) : await onStart(selected);
      if (!ok) setError(tr('尚未完成，請查看對話中的錯誤說明後重試。', 'Not completed. Check the conversation error and retry.'));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { flight.current = false; setPending(false); }
  }
  return <section className="wiring-analysis-entry" aria-label={tr('接線照片分析', 'Wiring photo analysis')} aria-busy={pending}>
    <div className="wiring-analysis-entry-controls">
      <label><span className="sr-only">{tr('要檢查的零件', 'Module to check')}</span>
        <select value={selected} disabled={busy || pending || Boolean(flow)} onChange={event => { setChoice(event.target.value); setError(''); }}>
          {components.map(component => <option key={component.id} value={component.id}>{component.label}</option>)}
        </select>
      </label>
      <button type="button" className="maker-primary" disabled={disabled} onClick={() => void activate()}>{label}</button>
    </div>
    <small>{flow ? flow.kind === 'analysing' ? tr('雲端正在分析，可查看進度。', 'Cloud analysis is running. View its progress.')
      : analyse && flow.kind === 'error' ? tr('上次分析未完成，使用保留的照片重試。', 'Analysis did not finish. Retry with the saved photos.')
      : count !== null ? tr(`已收 ${count}/3 張照片 · ${analyse ? '照片齊了，可以開始分析' : '在同一段對話繼續'}`,
        `${count}/3 photos received · ${analyse ? 'Ready to analyse' : 'Continue in this conversation'}`)
      : tr('在同一段對話繼續接線核對。', 'Continue the wiring review in this conversation.')
      : tr('Pi 內排 → Pi 外排 → 零件接頭，共 3 張；不需連接 Pi。', '3 photos: Pi inner row → Pi outer row → module header. No Pi connection needed.')}</small>
    {!aiReady && (!flow || analyse) ? <small>{tr('請先在下方登入 AI 並選擇模型。', 'Sign in to AI and select a model below.')}</small> : null}
    {error ? <small role="alert">{error}</small> : null}
  </section>;
}
