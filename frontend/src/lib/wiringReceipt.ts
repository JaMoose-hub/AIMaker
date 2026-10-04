import type { MakerState, ProjectGuideState } from './maker';
import type { DebugSession } from './debugSessions';
import type { DebugContext } from './debug';
import type { WiringReviewAction } from './wiringReview';

export interface WiringGuideReceipt {
  request_id: string; flow_id: string; context_epoch: number; project_id: string; project_revision: number;
  op: 'review' | 'changed'; wire_id?: string; decision?: string;
  before_binding: NonNullable<DebugSession['binding']>; after_binding: NonNullable<DebugSession['binding']>;
  guide_confirmations: ProjectGuideState['confirmed']; guide_run: number; test_keys: Record<string, string>;
  review_id: string; round: number; context_fingerprint: string;
}
export interface WiringActionOutbox {
  request_id: string; conversation_id: string; context_epoch: number; message_id: string; flow_id: string;
  action: WiringReviewAction; context: DebugContext; before_signature: string;
  before_binding?: NonNullable<DebugSession['binding']>;
}
/** Browsing and draft text do not change a wiring version; explicit confirmations do. */
export const wiringReceiptSignature = (state: MakerState) => JSON.stringify([
  state.design, state.code, state.guide.run ?? 0, state.guide.confirmed,
]);
const equalKeys = (left: Record<string, unknown> = {}, right: Record<string, unknown> = {}): boolean =>
  Object.keys(left).length === Object.keys(right).length && Object.entries(left).every(([key, value]) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? Boolean(right[key] && typeof right[key] === 'object' && equalKeys(value as Record<string, unknown>, right[key] as Record<string, unknown>))
      : right[key] === value);

/** Recover only this user's exact completed action, never observations or arbitrary server guide state. */
export function guideFromWiringReceipt(state: MakerState, outbox: WiringActionOutbox, receipt: WiringGuideReceipt | null | undefined,
  session: DebugSession, conversationId: string, epoch: number): ProjectGuideState | null {
  const design = state.design;
  if (!design || !receipt || outbox.before_signature !== wiringReceiptSignature(state)
    || outbox.conversation_id !== conversationId || outbox.context_epoch !== epoch || receipt.context_epoch !== epoch
    || receipt.request_id !== outbox.request_id || receipt.flow_id !== outbox.flow_id
    || receipt.project_id !== design.id || receipt.project_revision !== design.revision
    || receipt.op !== outbox.action.op || (receipt.wire_id ?? null) !== (outbox.action.wire_id ?? null) || (receipt.decision ?? null) !== (outbox.action.decision ?? null)
    || receipt.guide_run !== (state.guide.run ?? 0) || session.wiring_review?.id !== receipt.review_id
    || session.wiring_review.round !== receipt.round || session.wiring_review.status === 'stale'
    || !outbox.before_binding || !equalKeys(receipt.before_binding, outbox.before_binding)
    || !equalKeys(receipt.after_binding, session.binding) || !equalKeys(receipt.test_keys, session.binding?.test_keys)
    || !equalKeys(receipt.guide_confirmations, outbox.context.guide_confirmations)) return null;
  return { ...state.guide, confirmed: receipt.guide_confirmations,
    ...(receipt.op === 'changed' ? { checks: [] } : {}) };
}
