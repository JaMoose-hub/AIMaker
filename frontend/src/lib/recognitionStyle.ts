/** Presentation only. Shared by live recognition and frozen-photo overlays. */
const CONNECTION_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff6a00", GND: "#60728c", AO: "#00a86b",
};

const COMPONENT_PIN_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff7777", GND: "#aab4c4", AO: "#65d6a0", TRIG: "#ffb45f",
  ECHO: "#c891ff", SCL: "#6fb9ff", SDA: "#65d6a0", XDA: "#8fe3bd",
  XCL: "#8fc8ff", AD0: "#ffd166", INT: "#c891ff", RES: "#ff9d66",
  DC: "#f4c95d", CS: "#c891ff", BLK: "#8f9bad",
};

export function guideConnectionColor(pinId: string): string {
  return CONNECTION_COLORS[pinId] ?? "#007bff";
}

interface GuidePoint { x: number; y: number }
interface GuideTarget {
  /** Semantic TL/TR/BR/BL corners in the same coordinate space as the contacts. */
  outline: readonly GuidePoint[];
  headerAtTop: boolean;
}

function headerRoutePoints(from: GuidePoint, to: GuidePoint, gap: number, target: GuideTarget): GuidePoint[] | null {
  const quad = target.outline;
  if (quad.length !== 4 || !quad.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))) return null;
  const a = quad[target.headerAtTop ? 0 : 3], b = quad[target.headerAtTop ? 1 : 2];
  const edgeX = b.x - a.x, edgeY = b.y - a.y, edgeLength = Math.hypot(edgeX, edgeY);
  if (edgeLength < 1e-6) return null;
  const normal = { x: -edgeY / edgeLength, y: edgeX / edgeLength };
  const centre = quad.reduce((sum, p) => ({ x: sum.x + p.x / 4, y: sum.y + p.y / 4 }), { x: 0, y: 0 });
  const facing = ((a.x + b.x) / 2 - centre.x) * normal.x + ((a.y + b.y) / 2 - centre.y) * normal.y;
  if (Math.abs(facing) < 1e-6) return null;
  if (facing < 0) { normal.x *= -1; normal.y *= -1; }
  const tangent = { x: normal.y, y: -normal.x };
  const local = (p: GuidePoint) => ({ x: (p.x - to.x) * tangent.x + (p.y - to.y) * tangent.y,
    y: (p.x - to.x) * normal.x + (p.y - to.y) * normal.y });
  const point = (x: number, y: number) => ({ x: to.x + tangent.x * x + normal.x * y,
    y: to.y + tangent.y * x + normal.y * y });
  const start = local(from), body = quad.map(local), margin = Math.max(gap * 1.5, 1e-3);
  // Enter from outside the actual board edge, even when the projected contact
  // sits slightly inside the board. All bends are in the header's local axes.
  const entry = Math.max(gap * 2.5, Math.max(...body.map(p => p.y)) + gap);
  const end = point(0, gap);
  let points: GuidePoint[];
  if (Math.abs(start.x) < 1e-6 && start.y >= entry + gap) {
    points = [from, end];
  } else {
    const left = Math.min(...body.map(p => p.x)) - margin, right = Math.max(...body.map(p => p.x)) + margin;
    let lane = start.x / 2;
    // Keep the turn out of the module body rather than taking a shortcut over it.
    if ((lane >= left && lane <= right) || Math.abs(lane) < margin) {
      lane = Math.abs(start.x - left) < Math.abs(start.x - right) ? left : right;
      if (Math.abs(lane) < margin) lane = start.x < 0 ? -margin : margin;
    }
    points = [from, point(lane, start.y), point(lane, entry), point(0, entry), end];
  }
  points = points.filter((p, i) => i === 0 || Math.hypot(p.x - points[i - 1].x, p.y - points[i - 1].y) > 1e-6);
  const first = points[0], next = points[1];
  if (next) {
    const length = Math.hypot(next.x - first.x, next.y - first.y), inset = Math.min(gap, length / 3) / length;
    points[0] = { x: first.x + (next.x - first.x) * inset, y: first.y + (next.y - first.y) * inset };
  }
  return points;
}

/** Display-only control points, not a detected wire or electrical evidence. */
export function guideConnectionPoints(
  from: GuidePoint,
  to: GuidePoint,
  clearance = 8,
  target?: GuideTarget,
): GuidePoint[] {
  if (![from.x, from.y, to.x, to.y, clearance].every(Number.isFinite)) return [];
  const dx = to.x - from.x, dy = to.y - from.y;
  const routed = target && (dx !== 0 || dy !== 0) ? headerRoutePoints(from, to, Math.max(0, clearance), target) : null;
  if (routed) return routed;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  // Shorten along the actual first/last leg, leaving the pin centres clear.
  const gap = Math.min(Math.max(0, clearance), Math.abs(horizontal ? dx : dy) / 3);
  const points = horizontal
    ? [
      { x: from.x + Math.sign(dx) * gap, y: from.y },
      { x: (from.x + to.x) / 2, y: from.y },
      { x: (from.x + to.x) / 2, y: to.y },
      { x: to.x - Math.sign(dx) * gap, y: to.y },
    ]
    : [
      { x: from.x, y: from.y + Math.sign(dy) * gap },
      { x: from.x, y: (from.y + to.y) / 2 },
      { x: to.x, y: (from.y + to.y) / 2 },
      { x: to.x, y: to.y - Math.sign(dy) * gap },
    ];
  return points.filter((point, index) => index === 0
    || point.x !== points[index - 1].x || point.y !== points[index - 1].y);
}

/** Soft wire-like bends while keeping the original contacts and approach direction. */
export function guideConnectionPath(from: GuidePoint, to: GuidePoint, clearance = 8, target?: GuideTarget): string {
  const points = guideConnectionPoints(from, to, clearance, target);
  if (!points.length) return "";
  const coordinate = (p: GuidePoint) => `${p.x} ${p.y}`;
  let path = `M ${coordinate(points[0])}`;
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1], b = points[i], c = points[i + 1];
    const incoming = Math.hypot(b.x - a.x, b.y - a.y), outgoing = Math.hypot(c.x - b.x, c.y - b.y);
    const cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    const radius = Math.min(Math.max(0, clearance) * 2.25, incoming * .4, outgoing * .4);
    if (radius < 1e-6 || Math.abs(cross) < 1e-6) {
      path += ` L ${coordinate(b)}`;
      continue;
    }
    const before = { x: b.x + (a.x - b.x) * radius / incoming, y: b.y + (a.y - b.y) * radius / incoming };
    const after = { x: b.x + (c.x - b.x) * radius / outgoing, y: b.y + (c.y - b.y) * radius / outgoing };
    path += ` L ${coordinate(before)} Q ${coordinate(b)} ${coordinate(after)}`;
  }
  if (points.length > 1) path += ` L ${coordinate(points.at(-1)!)}`;
  return path;
}

export function componentPinColor(pinId: string): string {
  return COMPONENT_PIN_COLORS[pinId] ?? "#61dafb";
}
