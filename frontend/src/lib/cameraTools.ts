/** Keep a non-modal camera tools panel inside the viewport, beside its trigger. */
export function cameraToolsPlacement(
  anchor: { top: number; bottom: number; right: number },
  viewport: { width: number; height: number },
) {
  const gutter = 12;
  const gap = 8;
  const top = Math.max(gutter, Math.min(anchor.top, viewport.height - gutter));
  const bottom = Math.max(gutter, Math.min(anchor.bottom, viewport.height - gutter));
  const width = Math.max(0, Math.min(640, viewport.width - gutter * 2));
  const below = Math.max(0, viewport.height - bottom - gap - gutter);
  const above = Math.max(0, top - gap - gutter);
  const opensBelow = below >= 280 || below >= above;
  const maxHeight = Math.min(560, opensBelow ? below : above);
  return {
    width,
    left: Math.max(gutter, Math.min(anchor.right - width, viewport.width - gutter - width)),
    top: opensBelow ? bottom + gap : top - gap - maxHeight,
    maxHeight,
  };
}
