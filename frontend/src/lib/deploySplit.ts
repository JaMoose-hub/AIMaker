export const DEPLOY_SPLIT_STORAGE_KEY = "boardvision.deploy-split.v1";
export const DEPLOY_SPLIT_HANDLE_WIDTH = 18;
export const DEPLOY_COLUMN_MIN_WIDTH = 360;

/** Measure the deployment pane itself, since resizing AI also changes its width. */
export function deploySplitGeometry(width: number, ratio: number | null) {
  const measured = Number.isFinite(width) ? Math.max(0, width) : 0;
  const available = Math.max(0, measured - DEPLOY_SPLIT_HANDLE_WIDTH);
  const sideBySide = measured >= DEPLOY_COLUMN_MIN_WIDTH * 2 + DEPLOY_SPLIT_HANDLE_WIDTH;
  const min = Math.min(DEPLOY_COLUMN_MIN_WIDTH, available / 2);
  const max = Math.max(min, available - min);
  const preferred = ratio !== null && Number.isFinite(ratio) ? ratio : .5;
  const left = Math.min(max, Math.max(min, available * preferred));
  return { available, min, max, left, sideBySide };
}

export function deploySplitRatioForLeft(left: number, width: number) {
  const { available, min, max } = deploySplitGeometry(width, null);
  const preferred = Number.isFinite(left) ? left : available / 2;
  return available ? Math.min(max, Math.max(min, preferred)) / available : .5;
}

export function dragDeploySplitRatio(startLeft: number, startX: number, clientX: number, width: number) {
  return deploySplitRatioForLeft(startLeft + clientX - startX, width);
}

export function keyDeploySplitRatio(key: string, shift: boolean, left: number, width: number): number | null {
  const { min, max, sideBySide } = deploySplitGeometry(width, null);
  if (!sideBySide) return null;
  const current = Number.isFinite(left) ? left : deploySplitGeometry(width, null).left;
  const step = shift ? 80 : 24;
  if (key === "Home") return deploySplitRatioForLeft(min, width);
  if (key === "End") return deploySplitRatioForLeft(max, width);
  if (key === "ArrowLeft") return deploySplitRatioForLeft(current - step, width);
  if (key === "ArrowRight") return deploySplitRatioForLeft(current + step, width);
  return null;
}
