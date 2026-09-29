export const CONTACT_ALIGNMENT_VERSION = "pi5-contact-rows-v1";

export interface PinCalibrationOffset {
  x: number;
  y: number;
  alignmentVersion?: string;
}

export interface PinAlignment {
  version: string;
  accepted: boolean;
  offset_px: [number, number];
}

/** Retain old nudges as a fallback, not an extra shift on observed contacts.
 * A board-corner projection can change after reacquisition, so subtracting
 * today's automatic delta from yesterday's nudge preserves the wrong anchor.
 * Reliable local rows take over; subsequent user nudges are new residuals.
 * Never erase the saved fallback merely because one camera frame arrived.
 */
export function resolvePinCalibration(
  saved: PinCalibrationOffset, boardId: string | null, alignment?: PinAlignment,
): PinCalibrationOffset {
  if (boardId !== "raspberry-pi-5" || saved.alignmentVersion === CONTACT_ALIGNMENT_VERSION
      || (saved.x === 0 && saved.y === 0) || !alignment?.accepted
      || alignment.version !== CONTACT_ALIGNMENT_VERSION
      || !Array.isArray(alignment.offset_px) || alignment.offset_px.length !== 2
      || !alignment.offset_px.every(Number.isFinite)) return saved;
  return { x: 0, y: 0 };
}
