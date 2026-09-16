import { useEffect, useState, type RefObject } from "react";

/**
 * Letterbox transform (api-contract.md §3).
 *
 * The <img> shows a video of `video_size = [vw, vh]` with object-fit: contain
 * inside an element of size [ew, eh]:
 *   scale = min(ew/vw, eh/vh)
 *   offx  = (ew - vw*scale) / 2
 *   offy  = (eh - vh*scale) / 2
 *   display_x = x * scale + offx
 *   display_y = y * scale + offy
 */

export interface Letterbox {
  scale: number;
  offx: number;
  offy: number;
  /** Full CSS width of the containing viewport, used as the mirror axis. */
  elementWidth: number;
  /** Full CSS height of the containing viewport, used as the vertical mirror axis. */
  elementHeight: number;
  mirrorX: boolean;
  mirrorY: boolean;
  /** Optional source-pixel -> display-pixel projective mapping for optical HUDs. */
  sourceToDisplay?: HomographyMatrix;
  /** Exact inverse of `sourceToDisplay`, used by display-space editing tools. */
  displayToSource?: HomographyMatrix;
}

export type HomographyMatrix = readonly [
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
];

export const IDENTITY_LETTERBOX: Letterbox = {
  scale: 1,
  offx: 0,
  offy: 0,
  elementWidth: 0,
  elementHeight: 0,
  mirrorX: false,
  mirrorY: false,
};

export function computeLetterbox(
  videoSize: readonly [number, number],
  elementWidth: number,
  elementHeight: number,
  mirrorX = false,
  mirrorY = false,
): Letterbox {
  const [vw, vh] = videoSize;
  if (vw <= 0 || vh <= 0 || elementWidth <= 0 || elementHeight <= 0) {
    return { ...IDENTITY_LETTERBOX, elementWidth, elementHeight, mirrorX, mirrorY };
  }
  const scale = Math.min(elementWidth / vw, elementHeight / vh);
  return {
    scale,
    offx: (elementWidth - vw * scale) / 2,
    offy: (elementHeight - vh * scale) / 2,
    elementWidth,
    elementHeight,
    mirrorX,
    mirrorY,
  };
}

export interface DisplayPoint {
  x: number;
  y: number;
}

/** Apply a 3x3 homogeneous transform. Returns null at a projective horizon. */
export function applyHomography(
  matrix: HomographyMatrix,
  x: number,
  y: number,
): DisplayPoint | null {
  const denominator = matrix[6] * x + matrix[7] * y + matrix[8];
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-10) return null;
  const mappedX = (matrix[0] * x + matrix[1] * y + matrix[2]) / denominator;
  const mappedY = (matrix[3] * x + matrix[4] * y + matrix[5]) / denominator;
  if (!Number.isFinite(mappedX) || !Number.isFinite(mappedY)) return null;
  return { x: mappedX, y: mappedY };
}

/** Source-pixel coordinates -> display (CSS px) coordinates. */
export function toDisplay(t: Letterbox, x: number, y: number): DisplayPoint {
  if (t.sourceToDisplay) {
    const projected = applyHomography(t.sourceToDisplay, x, y);
    if (projected) return projected;
  }
  const displayX = x * t.scale + t.offx;
  const displayY = y * t.scale + t.offy;
  return {
    x: t.mirrorX ? t.elementWidth - displayX : displayX,
    y: t.mirrorY ? t.elementHeight - displayY : displayY,
  };
}

/**
 * Display (CSS px) coordinates -> source-pixel coordinates. Exact inverse of
 * `toDisplay`, used when a UI element is drawn in display space (e.g. the
 * calibration guide rectangle) but must be reported back in source-video
 * pixel space (api-contract.md — same space as WS detection coords).
 */
export function toSource(t: Letterbox, x: number, y: number): DisplayPoint {
  if (t.displayToSource) {
    const projected = applyHomography(t.displayToSource, x, y);
    if (projected) return projected;
  }
  const scale = t.scale === 0 ? 1 : t.scale;
  const displayX = t.mirrorX ? t.elementWidth - x : x;
  const displayY = t.mirrorY ? t.elementHeight - y : y;
  return { x: (displayX - t.offx) / scale, y: (displayY - t.offy) / scale };
}

export interface ElementSize {
  width: number;
  height: number;
}

/** Track an element's rendered size with a ResizeObserver. */
export function useElementSize(ref: RefObject<HTMLElement | null>): ElementSize {
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      // Children positioned with `inset: 0` use the element's padding box.
      // clientWidth/clientHeight therefore match the MJPEG image and SVG
      // mirror axes exactly; getBoundingClientRect also included the border
      // and introduced a small but visible mirrored GPIO offset.
      const width = element.clientWidth;
      const height = element.clientHeight;
      setSize((prev) =>
        prev.width === width && prev.height === height
          ? prev
          : { width, height },
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return size;
}
