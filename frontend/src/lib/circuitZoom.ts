export const MIN_CIRCUIT_ZOOM = 0.4;
export const MAX_CIRCUIT_ZOOM = 6;

export function clampCircuitZoom(zoom: number) {
  return Math.min(MAX_CIRCUIT_ZOOM, Math.max(MIN_CIRCUIT_ZOOM, zoom));
}

/** Leave a small margin, and fit both axes rather than stretching to page width. */
export function fitCircuitScale(width: number, height: number, drawingWidth: number, drawingHeight: number) {
  return Math.max(0.001, Math.min((width - 16) / drawingWidth, (height - 16) / drawingHeight, 0.8));
}

export function wheelCircuitZoom(current: number, deltaY: number, deltaMode: number) {
  const pixels = deltaY * (deltaMode === 1 ? 16 : deltaMode === 2 ? 300 : 1);
  return clampCircuitZoom(current * Math.exp(-Math.max(-150, Math.min(150, pixels)) * 0.002));
}

/** Keep the same drawing point under the cursor, including centered small drawings. */
export function anchoredCircuitScroll(scroll: number, cursor: number, viewport: number, before: number, after: number) {
  const oldInset = Math.max(0, (viewport - before) / 2);
  const newInset = Math.max(0, (viewport - after) / 2);
  const point = Math.max(0, Math.min(1, (scroll + cursor - oldInset) / before));
  return Math.max(0, Math.min(Math.max(0, after - viewport), newInset + point * after - cursor));
}

/** A native non-passive listener is required to suppress browser Ctrl+wheel zoom. */
export function bindCircuitWheel(element: HTMLElement, onZoom: (event: WheelEvent) => void) {
  const listener = (event: WheelEvent) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.deltaY) onZoom(event);
  };
  element.addEventListener("wheel", listener, { passive: false });
  return () => element.removeEventListener("wheel", listener);
}
