export type StudioStage = "design" | "blueprint";
export const SPLIT_HANDLE_WIDTH = 18;
// Blueprint now has the diagram on the left; don't reuse old chat-column widths.
export const splitStorageKey = (stage: StudioStage) => `boardvision.studio-split.${stage === "blueprint" ? "v2" : "v1"}.${stage}`;

export function parseSplitRatio(raw: string | null): number | null {
  if (!raw?.trim()) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 && value < 1 ? value : null;
}

export function studioSplitGeometry(width: number, stage: StudioStage, ratio: number | null) {
  const available = Math.max(0, (Number.isFinite(width) ? width : 0) - SPLIT_HANDLE_WIDTH);
  const min = Math.min(300, available / 2);
  const max = Math.max(min, available - 360);
  const fallback = stage === "design" ? Math.min(640, Math.max(360, available * .38)) : available - 380;
  const requested = ratio !== null && Number.isFinite(ratio) ? available * ratio : fallback;
  return { available, min, max, left: Math.min(max, Math.max(min, requested)) };
}

export function splitRatioForLeft(left: number, width: number): number {
  const { available, min, max } = studioSplitGeometry(width, "design", null);
  return available ? Math.min(max, Math.max(min, Number.isFinite(left) ? left : min)) / available : .5;
}

export function dragSplitRatio(startLeft: number, startX: number, clientX: number, width: number): number {
  return splitRatioForLeft(startLeft + clientX - startX, width);
}

export function keySplitRatio(key: string, shift: boolean, left: number, width: number): number | null {
  const { min, max } = studioSplitGeometry(width, "design", null);
  const step = shift ? 80 : 24;
  if (key === "Home") return splitRatioForLeft(min, width);
  if (key === "End") return splitRatioForLeft(max, width);
  if (key === "ArrowLeft") return splitRatioForLeft(left - step, width);
  if (key === "ArrowRight") return splitRatioForLeft(left + step, width);
  return null;
}

export const GUIDE_SPLIT_HANDLE_WIDTH = 18;
export const GUIDE_SPLIT_STORAGE_KEY = "boardvision.guide-split.v1";

/** Camera and guide share one grid; resizing the grid leaves the video/overlay tree intact. */
export function guideSplitGeometry(width: number, ratio: number | null) {
  const available = Math.max(0, (Number.isFinite(width) ? width : 0) - GUIDE_SPLIT_HANDLE_WIDTH);
  const minRight = Math.min(280, available / 2);
  const minCamera = available >= 760 ? 480 : available / 2;
  const maxRight = Math.min(700, Math.max(minRight, available - minCamera));
  const fallback = Math.min(400, Math.max(320, available * .3));
  const requested = ratio !== null && Number.isFinite(ratio) ? available * ratio : fallback;
  const right = Math.min(maxRight, Math.max(minRight, requested));
  return { available, minRight, maxRight, right, left: available - right };
}

export function guideRatioForRight(right: number, width: number) {
  const { available, minRight, maxRight } = guideSplitGeometry(width, null);
  return available ? Math.min(maxRight, Math.max(minRight, Number.isFinite(right) ? right : minRight)) / available : .5;
}

export function dragGuideRatio(startRight: number, startX: number, clientX: number, width: number) {
  return guideRatioForRight(startRight - (clientX - startX), width);
}

export function keyGuideRatio(key: string, shift: boolean, right: number, width: number): number | null {
  const { minRight, maxRight } = guideSplitGeometry(width, null);
  const step = shift ? 80 : 24;
  if (key === "Home") return guideRatioForRight(maxRight, width);
  if (key === "End") return guideRatioForRight(minRight, width);
  if (key === "ArrowLeft") return guideRatioForRight(right + step, width);
  if (key === "ArrowRight") return guideRatioForRight(right - step, width);
  return null;
}

// The stacked workspace must not reinterpret the old side-by-side preference.
// Preserve the old preference, but start the new stream-first layout at 70:30.
export const GUIDE_HEIGHT_STORAGE_KEY = "boardvision.guide-height.v2";
export const GUIDE_HEIGHT_HANDLE_SIZE = 18;

export function guideHeightGeometry(height: number, ratio: number | null, minimumGuideHeight = 160) {
  const available = Math.max(0, (Number.isFinite(height) ? height : 0) - GUIDE_HEIGHT_HANDLE_SIZE);
  const minTop = Math.min(180, available * .4);
  const guideMinimum = Number.isFinite(minimumGuideHeight) ? Math.max(160, minimumGuideHeight) : 160;
  const maxTop = Math.max(minTop, available - Math.min(guideMinimum, available - minTop));
  const fallback = available * .7;
  const requested = ratio !== null && Number.isFinite(ratio) ? available * ratio : fallback;
  const top = Math.min(maxTop, Math.max(minTop, requested));
  return { available, minTop, maxTop, top, bottom: available - top };
}

export function guideRatioForTop(top: number, height: number, minimumGuideHeight = 160) {
  const { available, minTop, maxTop } = guideHeightGeometry(height, null, minimumGuideHeight);
  return available ? Math.min(maxTop, Math.max(minTop, Number.isFinite(top) ? top : minTop)) / available : .5;
}

export function dragGuideHeightRatio(startTop: number, startY: number, clientY: number, height: number, minimumGuideHeight = 160) {
  return guideRatioForTop(startTop + clientY - startY, height, minimumGuideHeight);
}

export function keyGuideHeightRatio(key: string, shift: boolean, top: number, height: number, minimumGuideHeight = 160): number | null {
  const { minTop, maxTop } = guideHeightGeometry(height, null, minimumGuideHeight);
  const step = shift ? 80 : 24;
  if (key === "Home") return guideRatioForTop(minTop, height, minimumGuideHeight);
  if (key === "End") return guideRatioForTop(maxTop, height, minimumGuideHeight);
  if (key === "ArrowUp") return guideRatioForTop(top - step, height, minimumGuideHeight);
  if (key === "ArrowDown") return guideRatioForTop(top + step, height, minimumGuideHeight);
  return null;
}
