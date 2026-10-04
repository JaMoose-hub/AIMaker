import { validWiringCrop, wiringPhotoRoles, type WiringPhotoRole, type WiringReviewAction, type WiringReviewResult, type WiringReviewState } from './wiringReview';

/** Server-persisted dialogue metadata. Text remains a normal chat message. */
export interface WiringChatFlow {
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
  decision?: 'confirmed' | 'unsure' | 'needs_change';
  current: boolean;
  can_act: boolean;
  actions: WiringChatActionOp[];
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
    && review.component_id === flow.component_id && review.status !== 'stale' ? review : null;
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
