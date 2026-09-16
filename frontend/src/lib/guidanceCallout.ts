export const GUIDANCE_CALLOUT_WIDTH = 132;
export const GUIDANCE_CALLOUT_HEIGHT = 44;

const CALLOUT_GAP = 42;
const VIEWPORT_PADDING = 8;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(value, maximum));
}

/** Keep an arrow callout readable near every viewport edge. */
export function guidanceCalloutGeometry(
  targetX: number,
  targetY: number,
  width: number,
  height: number,
  boxWidth = GUIDANCE_CALLOUT_WIDTH,
  boxHeight = GUIDANCE_CALLOUT_HEIGHT,
) {
  boxWidth = Math.min(boxWidth, Math.max(1, width - VIEWPORT_PADDING * 2));
  boxHeight = Math.min(boxHeight, Math.max(1, height - VIEWPORT_PADDING * 2));
  const placeRight = targetX < width / 2;
  const placeBelow = targetY < boxHeight + VIEWPORT_PADDING + 18;
  const boxX = clamp(
    placeRight ? targetX + CALLOUT_GAP : targetX - CALLOUT_GAP - boxWidth,
    VIEWPORT_PADDING,
    Math.max(VIEWPORT_PADDING, width - boxWidth - VIEWPORT_PADDING),
  );
  const boxY = clamp(
    placeBelow ? targetY + 18 : targetY - boxHeight - 18,
    VIEWPORT_PADDING,
    Math.max(VIEWPORT_PADDING, height - boxHeight - VIEWPORT_PADDING),
  );
  const startX = placeRight ? boxX : boxX + boxWidth;
  const startY = clamp(targetY, boxY + 9, boxY + boxHeight - 9);
  const dx = targetX - startX;
  const dy = targetY - startY;
  const distance = Math.max(1, Math.hypot(dx, dy));

  return {
    boxWidth,
    boxHeight,
    boxX,
    boxY,
    startX,
    startY,
    endX: targetX - (dx / distance) * 8,
    endY: targetY - (dy / distance) * 8,
  };
}

/** Pi instructions live in the side panel. Keep only a short pointer near the
 * target so a floating text box never covers the connector or wire path.
 */
export function guidancePointerGeometry(targetX: number, targetY: number, width: number, height: number) {
  const anchor = guidanceCalloutGeometry(targetX, targetY, width, height);
  const dx = anchor.startX - targetX;
  const dy = anchor.startY - targetY;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const length = Math.min(38, distance);
  const tipGap = Math.min(8, length / 2);
  return {
    startX: targetX + dx / distance * length,
    startY: targetY + dy / distance * length,
    endX: targetX + dx / distance * tipGap,
    endY: targetY + dy / distance * tipGap,
  };
}
