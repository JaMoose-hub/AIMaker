import { validWiringCrop, wiringPhotoRoles, wiringPhotoInstruction, type WiringCapturePlan, type WiringTargetRow, type WiringPhotoRole, type WiringReviewAction, type WiringReviewResult, type WiringReviewState } from './wiringReview';

/** Server-persisted dialogue metadata. Text remains a normal chat message. */
export interface WiringChatFlow {
  capture_plan?: WiringCapturePlan;
  target_row?: WiringTargetRow | null;
  started_at?: number | null;
  elapsed_ms?: number | null;
  flow_id: string;
  review_id: string;
  revision: number;
  round: number;
  component_id: string;
  kind: 'photo_request' | 'photo' | 'analysis_request' | 'analysing' | 'wire_review' | 'human_decision' | 'complete' | 'error';
  role?: WiringPhotoRole;
  wire_id?: string;
  capture_id?: string;
  image_url?: string;
  result?: WiringReviewResult;
  summary?: WiringChatSummary;
  error?: string | null;
  decision?: 'confirmed' | 'unsure' | 'needs_change';
  current: boolean;
  can_act: boolean;
  actions: WiringChatActionOp[];
}
export interface WiringChatSummary {
  schema_version?: number;
  headline: string;
  next_step: string;
  retake_role: WiringPhotoRole | null;
  counts: { suspected: number; uncertain: number; no_issue_seen: number };
  results: WiringReviewResult[];
  evidence: string;
  observation?: string;
  observation_role?: WiringPhotoRole | null;
}
type Translate = (zh: string, en: string) => string;

/** Reading old receipts must not mix in results from another round or revision. */
export function wiringChatSummary(flow: WiringChatFlow, review: WiringReviewState | null | undefined, tr: Translate): WiringChatSummary | null {
  if (flow.kind !== 'wire_review' || !flow.result) return null;
  if (flow.summary) {
    // Legacy summaries equated missing pin identity with an unclear photograph.
    // Without the original view observation, do not invent the reason it is missing.
    const saved = flow.summary;
    if (!saved.schema_version && saved.retake_role && !saved.counts.suspected) return {
      ...saved,
      headline: saved.retake_role === 'component_header'
        ? tr('零件端的接線位置尚未確認。', 'The module connection positions are not yet confirmed.')
        : tr('Pi 端的接線位置尚未確認。', 'The Pi connection positions are not yet confirmed.'),
    };
    return saved;
  }
  const matched = wiringFlowReview(flow, review);
  const rows = matched?.results.length ? matched.results : [flow.result];
  const counts = { suspected: 0, uncertain: 0, no_issue_seen: 0 };
  for (const row of rows) counts[row.diagnosis?.status ?? 'uncertain']++;
  const suspected = rows.filter(row => row.diagnosis?.status === 'suspected');
  const retake = suspected.length || (matched?.no_progress_count ?? 0) >= 2 ? null
    : (rows.find(row => row.diagnosis?.retake_roles?.includes('component_header')) ? 'component_header'
      : rows.flatMap(row => row.diagnosis?.retake_roles ?? [])[0] ?? null);
  return {
    headline: suspected.length ? tr(`先檢查 ${suspected.map(row => row.expected.component_pin).join('、')}`, `Check ${suspected.map(row => row.expected.component_pin).join(', ')}`)
      : retake === 'component_header' ? tr('零件端的接線位置尚未確認。', 'The module connection positions are not yet confirmed.')
        : retake ? tr('Pi 端的接線位置尚未確認。', 'The Pi connection positions are not yet confirmed.')
          : counts.uncertain ? tr('還需要確認線路兩端', 'The wire endpoints still need checking')
            : matched ? tr('照片未見明顯錯接，仍需親自確認。', 'No obvious mismatch in the photos; check the wiring yourself.')
              : tr(`${flow.result.expected.component_pin} 未見明顯錯接，仍需親自確認。`, `No obvious mismatch seen for ${flow.result.expected.component_pin}; check it yourself.`),
    next_step: suspected.length ? tr('先斷電，再對照接法核對這些線。', 'Power off, then check these wires against the design.')
      : retake === 'component_header' ? tr('靠近接頭，拍清楚標字與插頭底部。', 'Move closer and show the labels and connector bases.')
        : retake ? flow.capture_plan === 'pi_rows_v1' ? wiringPhotoInstruction(retake, tr, flow.capture_plan)
          : tr('換個角度，露出兩排針與插頭底部。', 'Change the angle to show both pin rows and connector bases.')
          : tr('可展開接法，沿線核對兩端。', 'Expand the connections and trace both ends.'),
    retake_role: retake, counts, results: rows, evidence: flow.result.diagnosis?.evidence || flow.result.evidence || '',
  };
}

/** Compact only routine assistant instructions; retain errors and human wording. */
export function compactWiringText(flow: WiringChatFlow | undefined, text: string, tr: Translate) {
  if (!flow) return text;
  if (flow.kind === 'photo_request' && flow.role) return wiringPhotoInstruction(flow.role, tr, flow.capture_plan);
  if (flow.kind === 'analysis_request') return tr('照片齊了，可以開始分析。', 'Photos ready. Start the analysis.');
  if (flow.kind === 'analysing') return flow.current ? tr('正在看照片…', 'Looking at your photos…') : tr('照片分析紀錄', 'Photo analysis record');
  return text;
}
export type WiringChatActionOp = 'capture' | 'crop' | 'analyse' | 'review' | 'changed';
const kindActions: Record<WiringChatFlow['kind'], readonly WiringChatActionOp[]> = {
  photo_request: ['capture'], photo: [], analysis_request: ['capture', 'crop', 'analyse'], analysing: [],
  wire_review: ['capture', 'crop', 'review', 'changed'], human_decision: [], complete: ['changed'], error: ['capture', 'crop', 'analyse', 'changed'],
};

/** A history photo, an unknown stage, or a disabled receipt never gains an action locally. */
export function wiringFlowCanAct(flow: WiringChatFlow | null | undefined, op: WiringChatActionOp): boolean {
  const allowed = flow && kindActions[flow.kind];
  return Boolean(flow && flow.current === true && flow.can_act === true && flow.flow_id && flow.review_id && flow.component_id
    && Number.isInteger(flow.revision) && flow.revision >= 0 && Number.isInteger(flow.round) && flow.round >= 0
    && Array.isArray(allowed) && allowed.includes(op) && Array.isArray(flow.actions) && flow.actions.includes(op));
}

/** Keep photo/crop evidence tied to the authoritative review behind this exact message. */
export function wiringFlowReview(flow: WiringChatFlow | null | undefined, review?: WiringReviewState | null) {
  return flow && review && review.id === flow.review_id && review.revision === flow.revision && review.round === flow.round
    && review.component_id === flow.component_id && (review.capture_plan ?? null) === (flow.capture_plan ?? null) && review.status !== 'stale' ? review : null;
}

export function boundWiringChatAction(flow: WiringChatFlow, action: WiringReviewAction): WiringReviewAction | null {
  if (!wiringFlowCanAct(flow, action.op as WiringChatActionOp)) return null;
  if (action.op === 'capture' && (!action.role || !wiringPhotoRoles.includes(action.role)
    || (flow.kind === 'photo_request' && action.role !== flow.role))) return null;
  if (action.op === 'crop' && (!action.role || !wiringPhotoRoles.includes(action.role) || !action.capture_id
    || (action.crop !== null && !validWiringCrop(action.crop)))) return null;
  if (action.op === 'review' && (!flow.wire_id || action.wire_id !== flow.wire_id
    || !['confirmed', 'unsure', 'needs_change'].includes(action.decision ?? ''))) return null;
  return { ...action, review_id: flow.review_id, revision: flow.revision, component_id: flow.component_id };
}

/** Color comparison supports a manual check; it is never an electrical verdict. */
export function wiringComparisonText(comparison: WiringReviewResult['comparison'], tr: (zh: string, en: string) => string) {
  return comparison === 'similar' ? tr('線色相符，支持這個接法；請確認為同一條線。', 'Matching colors support this connection; confirm that it is the same wire.')
    : comparison === 'different' ? tr('線色不同，請核對兩端及中間轉接；不能只靠顏色判定接錯。', 'Colors differ. Check both ends and any adapters; color alone cannot prove a wiring error.')
      : comparison === 'ambiguous' ? tr('有多個線色候選，請沿同一條線核對兩端。', 'Several color candidates are visible. Trace the same wire between both ends.')
        : tr('照片資訊不足，請補拍指定接頭或親自沿線核對。', 'Photo evidence is insufficient. Retake the relevant connector or trace the wire yourself.');
}
