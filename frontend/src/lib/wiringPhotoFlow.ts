import { wiringPhotoRoles, type WiringPhotoRole, type WiringPhotoSlot, type WiringReviewState } from './wiringReview';

/** These receipts approve a photo for analysis, never a physical connection. */
export interface WiringPhotoReceipts { key: string; accepted: Partial<Record<WiringPhotoRole, string>> }
export const wiringPhotoFlowKey = (review: WiringReviewState) => `${review.id}:${review.round}:${review.component_id}`;
const photoToken = (slot: WiringPhotoSlot) => `${slot.capture_id}:${slot.sha256}`;
export function acceptedWiringPhotos(review: WiringReviewState, receipts?: WiringPhotoReceipts, failed: string[] = []) {
    return wiringPhotoRoles.filter(role => {
        const slot = review.slots[role];
        if (!slot || slot.available === false || failed.includes(slot.capture_id) || review.status === 'stale') return false;
        const accepted = slot.photo_acceptance;
        const shared = accepted?.source === 'human' && accepted.round === review.round
            && accepted.capture_id === slot.capture_id && accepted.sha256 === slot.sha256;
        return shared || ((review.photo_flow_version ?? 1) < 2 && receipts?.key === wiringPhotoFlowKey(review)
            && receipts.accepted[role] === photoToken(slot));
    });
}
export function acceptWiringPhoto(review: WiringReviewState, receipts: WiringPhotoReceipts, role: WiringPhotoRole): WiringPhotoReceipts {
    const key = wiringPhotoFlowKey(review), slot = review.slots[role];
    if (!slot || slot.available === false) return receipts;
    return { key, accepted: { ...(receipts.key === key ? receipts.accepted : {}), [role]: photoToken(slot) } };
}
export function loadWiringPhotoReceipts(review: WiringReviewState, storage?: Pick<Storage, 'getItem'>): WiringPhotoReceipts {
    const empty = { key: wiringPhotoFlowKey(review), accepted: {} };
    try {
        const saved = JSON.parse(storage?.getItem(`boardvision.wiring-photo-flow.v1.${review.id}`) ?? 'null');
        if (saved?.key !== empty.key || !saved.accepted || typeof saved.accepted !== 'object') return empty;
        return { key: empty.key, accepted: Object.fromEntries(wiringPhotoRoles
            .filter(role => typeof saved.accepted[role] === 'string').map(role => [role, saved.accepted[role]])) };
    } catch { return empty; }
}
