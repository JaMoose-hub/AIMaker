import type { DisplayPoint } from "./geometry";

export interface LabelRect { x: number; y: number; width: number; height: number }
export const WIRING_LABEL_WIDTH = 228;
export const WIRING_LABEL_HEIGHT = 32;
export type WiringLabel = NonNullable<ReturnType<typeof placeWiringLabel>>;
export interface LabelAnchor { target: DisplayPoint | null; bounds: LabelRect | null }
type LabelLine = { from: DisplayPoint; to: DisplayPoint };

export function pointBounds(points: readonly DisplayPoint[]): LabelRect | null {
  const valid = points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!valid.length) return null;
  const xs = valid.map(p => p.x), ys = valid.map(p => p.y);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y };
}

function expand(rect: LabelRect, padding: number): LabelRect {
  return { x: rect.x - padding, y: rect.y - padding, width: rect.width + padding * 2, height: rect.height + padding * 2 };
}
function overlaps(a: LabelRect, b: LabelRect): boolean {
  return a.x <= b.x + b.width && a.x + a.width >= b.x && a.y <= b.y + b.height && a.y + a.height >= b.y;
}

/** Segment/rectangle clipping, also covers horizontal, vertical and zero-length links. */
export function linkIntersectsLabel(from: DisplayPoint, to: DisplayPoint, rect: LabelRect, padding = 18): boolean {
  const box = expand(rect, padding);
  let low = 0, high = 1;
  for (const [origin, delta, min, max] of [
    [from.x, to.x - from.x, box.x, box.x + box.width],
    [from.y, to.y - from.y, box.y, box.y + box.height],
  ]) {
    if (Math.abs(delta) < 1e-9) { if (origin < min || origin > max) return false; }
    else {
      const a = (min - origin) / delta, b = (max - origin) / delta;
      low = Math.max(low, Math.min(a, b)); high = Math.min(high, Math.max(a, b));
      if (low > high) return false;
    }
  }
  return true;
}

/** Display-only placement. Never cover the rendered wiring link, either endpoint,
 * the board/module, or the module's own callout. Prefer the side away from the
 * other endpoint. If a close-up leaves no space, the existing corner target
 * badge and side-panel row/ordinal remain visible; do not cover the link.
 */
export function placeWiringLabel(target: DisplayPoint, peer: DisplayPoint | null, board: LabelRect | null,
  obstacles: readonly LabelRect[], width: number, height: number,
  avoidLines: readonly LabelLine[] = [], avoidLeaderBoxes: readonly LabelRect[] = []) {
  const w = Math.min(WIRING_LABEL_WIDTH, width - 16), h = WIRING_LABEL_HEIGHT;
  if (w < 180 || height < 156) return null;
  const limits = { left: 8, right: width - w - 8, top: 112, bottom: height - h - 8 };
  const anchor = board ?? { x: target.x - 12, y: target.y - 12, width: 24, height: 24 };
  const sides = {
    right: [anchor.x + anchor.width + 12, target.y - h / 2],
    left: [anchor.x - w - 12, target.y - h / 2],
    bottom: [target.x - w / 2, anchor.y + anchor.height + 12],
    top: [target.x - w / 2, anchor.y - h - 12],
  };
  const dx = target.x - (peer?.x ?? width / 2), dy = target.y - (peer?.y ?? height / 2);
  const preferred = Math.abs(dx) >= Math.abs(dy) ? dx >= 0 ? "right" : "left" : dy >= 0 ? "bottom" : "top";
  const candidates = [sides[preferred], ...Object.values(sides)];
  // Stable scan order gives edge/crowded scenes alternatives without DOM measurement.
  for (let y = limits.top; y <= limits.bottom; y += h + 12) {
    candidates.push([limits.left, y], [limits.right, y]);
  }
  const blocks = [board, ...obstacles].filter((r): r is LabelRect => r !== null);
  for (const [x, y] of candidates) {
    const box = { x: Math.max(limits.left, Math.min(limits.right, x)), y: Math.max(limits.top, Math.min(limits.bottom, y)), width: w, height: h };
    if (blocks.some(r => overlaps(box, expand(r, 10)))) continue;
    if (linkIntersectsLabel(target, peer ?? target, box)) continue;
    if (avoidLines.some(line => linkIntersectsLabel(line.from, line.to, box, 8))) continue;
    // Nearest point on the box is the leader origin; keep the tip off the actual hole.
    const startX = Math.max(box.x, Math.min(box.x + w, target.x));
    const startY = Math.max(box.y, Math.min(box.y + h, target.y));
    if (avoidLeaderBoxes.some(rect => linkIntersectsLabel({ x: startX, y: startY }, target, rect, 8))) continue;
    const distance = Math.max(1, Math.hypot(target.x - startX, target.y - startY));
    return { ...box, startX, startY,
      endX: target.x + (startX - target.x) / distance * 8,
      endY: target.y + (startY - target.y) / distance * 8 };
  }
  return null;
}

/** One joint layout for both overlays. Reserve the actual peer label/leader,
 * not a guess at where another component might independently put its label. */
export function placeWiringLabelPair(board: LabelAnchor, component: LabelAnchor, width: number, height: number) {
  function attempt(first: LabelAnchor, second: LabelAnchor) {
    const firstLabel = first.target ? placeWiringLabel(first.target, second.target, first.bounds,
      second.bounds ? [second.bounds] : [], width, height) : null;
    const blocks = [first.bounds, firstLabel].filter((r): r is LabelRect => r !== null);
    const lines = firstLabel ? [{ from: { x: firstLabel.startX, y: firstLabel.startY }, to: { x: firstLabel.endX, y: firstLabel.endY } }] : [];
    const secondLabel = second.target ? placeWiringLabel(second.target, first.target, second.bounds,
      blocks, width, height, lines, firstLabel ? [firstLabel] : []) : null;
    return [firstLabel, secondLabel] as const;
  }
  const [boardLabel, componentLabel] = attempt(board, component);
  if (board.target && component.target && (!boardLabel || !componentLabel)) {
    const [otherComponent, otherBoard] = attempt(component, board);
    if (Number(Boolean(otherComponent)) + Number(Boolean(otherBoard)) > Number(Boolean(boardLabel)) + Number(Boolean(componentLabel))) {
      return { board: otherBoard, component: otherComponent };
    }
  }
  return { board: boardLabel, component: componentLabel };
}
