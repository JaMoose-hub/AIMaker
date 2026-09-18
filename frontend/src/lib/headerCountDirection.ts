import type { I18nApi } from "./i18n";

type Point = { x: number; y: number };
const DIRECTIONS = ["right", "downRight", "down", "downLeft", "left", "upLeft", "up", "upRight"] as const;

/** Use semantic first/last pins AFTER the display mirror/projective transform.
 * Never sort by screen X: that would reverse physical ordinals on rotation.
 * Missing, collapsed or off-screen endpoints use the physical-reference text.
 */
export function headerCountDirection(start: Point | null | undefined, end: Point | null | undefined,
  width: number, height: number, t: I18nApi["t"]) {
  if (!start || !end || ![start.x, start.y, end.x, end.y].every(Number.isFinite)) return null;
  if ([start, end].some(p => p.x < 0 || p.y < 0 || p.x > width || p.y > height)) return null;
  const dx = end.x - start.x, dy = end.y - start.y;
  if (Math.hypot(dx, dy) < 12) return null;
  const index = (Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) + 8) % 8;
  return t(`headerCount.${DIRECTIONS[index]}`);
}
