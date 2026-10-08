import { validWiringCrop, wiringPhotoRoles, wiringPhotoRow, type WiringCrop, type WiringImageInput,
  type WiringPhotoRole, type WiringPhotoSlot, type WiringReviewState } from './wiringReview';

export interface WiringPhotoStatus {
  state: 'missing' | 'unaccepted' | 'pending' | 'analysing' | 'analysed' | 'reused' | 'unverified';
  images: WiringImageInput[];
  /** True only when a completed receipt verifies the current saved crop. */
  detail: boolean;
}

/** Compare saved and edited coordinates exactly; do not hide unsaved small changes. */
export function sameWiringCrop(a: WiringCrop | null | undefined, b: WiringCrop | null | undefined): boolean {
  if (a == null || b == null) return a === b;
  return validWiringCrop(a) && validWiringCrop(b) && a.every((value, index) => value === b[index]);
}

function acceptedPhoto(review: WiringReviewState, role: WiringPhotoRole): boolean {
  const slot = review.slots[role], acceptance = slot?.photo_acceptance;
  return Boolean(slot?.available === true && slot.role === role && slot.capture_id && slot.sha256
    && acceptance?.source === 'human' && acceptance.capture_id === slot.capture_id
    && acceptance.sha256 === slot.sha256 && acceptance.round === review.round);
}

/** Selection is explicit, including older records without a selection receipt. */
export function wiringPhotosReady(review: WiringReviewState | null | undefined): boolean {
  return Boolean(review && review.status !== 'stale' && wiringPhotoRoles.every(role => acceptedPhoto(review, role)));
}

function validSize(size: unknown): size is [number, number] {
  return Array.isArray(size) && size.length === 2 && size.every(value => Number.isInteger(value) && value > 0);
}

function sourceMatches(input: WiringImageInput, slot: WiringPhotoSlot, role: WiringPhotoRole): boolean {
  return input.role === role && input.capture_id === slot.capture_id && input.source_sha256 === slot.sha256
    && validSize(input.source_size) && validSize(slot.size) && validSize(input.size)
    && input.source_size.every((value, index) => value === slot.size[index]);
}

/** A retained receipt alone never proves that a newly edited crop was analysed. */
export function wiringPhotoStatus(review: WiringReviewState | null | undefined, role: WiringPhotoRole): WiringPhotoStatus {
  const status = (state: WiringPhotoStatus['state'], images: WiringImageInput[] = [], detail = false): WiringPhotoStatus => ({ state, images, detail });
  const slot = review?.slots[role];
  if (!review || !slot || slot.available !== true) return status('missing');
  if (review.status === 'stale') return status('unverified');
  if (!acceptedPhoto(review, role)) return status('unaccepted');
  if (review.status === 'analysing') return status('analysing');
  if (review.status === 'collecting' || review.status === 'error') return status('pending');
  const receipt = review.model_receipt;
  if (!['ready', 'needs_human'].includes(review.status) || !Number.isInteger(review.analysis_revision)
    || review.analysis_revision! < 0 || review.analysis_revision! > review.revision
    || !receipt || receipt.review_id !== review.id || receipt.wiring_round !== review.round) return status('unverified');
  const requestedRow = wiringPhotoRow(role, review.capture_plan);
  if (review.capture_plan === 'pi_rows_v1' && (receipt.capture_plan !== review.capture_plan
    || requestedRow && slot.target_row !== requestedRow)) return status('unverified');

  if (Array.isArray(receipt.reused_roles) && receipt.reused_roles.includes(role)) {
    const ids = receipt.capture_ids, hashes = receipt.capture_hashes;
    const index = Array.isArray(ids) ? ids.indexOf(slot.capture_id) : -1;
    return index >= 0 && ids!.lastIndexOf(slot.capture_id) === index && Array.isArray(hashes)
      && ids!.length === hashes.length && hashes[index] === slot.sha256 ? status('reused') : status('unverified');
  }

  const images = Array.isArray(receipt.image_inputs) ? receipt.image_inputs.filter(input => input?.role === role) : [];
  if (!images.length || images.some(input => !sourceMatches(input, slot, role))) return status('unverified');
  if (requestedRow && images.some(input => input.requested_row !== requestedRow)) return status('unverified');
  const overview = images.filter(input => input.view === 'overview' && input.crop === null);
  const details = images.filter(input => input.view === 'detail');
  if (overview.length !== 1 || images.length !== overview.length + details.length) return status('unverified');
  if (slot.crop === null) return details.length ? status('unverified') : status('analysed', overview);
  if (!validWiringCrop(slot.crop) || details.length !== 1) return status('unverified');
  const [left, top, right, bottom] = slot.crop, [width, height] = slot.size;
  const pixels = [Math.floor(left * width), Math.floor(top * height), Math.ceil(right * width), Math.ceil(bottom * height)];
  const crop = details[0].crop;
  if (!Array.isArray(crop) || crop.length !== 4 || !crop.every((value, index) => value === pixels[index])) return status('unverified');
  return status('analysed', images, true);
}
