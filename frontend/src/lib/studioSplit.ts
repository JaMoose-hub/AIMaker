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
