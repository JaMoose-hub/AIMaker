import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { anchoredCircuitScroll, bindCircuitWheel, clampCircuitZoom, fitCircuitScale, MAX_CIRCUIT_ZOOM, MIN_CIRCUIT_ZOOM, wheelCircuitZoom } from "../lib/circuitZoom";
import { useMakerText } from "../lib/useMaker";

export function CircuitViewport({ width, height, children }: { width: number; height: number; children: ReactNode }) {
  const tr = useMakerText();
  const viewport = useRef<HTMLDivElement>(null);
  const drawing = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(1);
  const pendingScroll = useRef<{ left: number; top: number }>();
  const scale = fitCircuitScale(size.width, size.height, width, height) * zoom;

  useEffect(() => {
    const element = viewport.current!;
    const observer = new ResizeObserver(() => {
      // A horizontal scrollbar must not alter the base zoom while enlarging.
      const next = { width: element.clientWidth, height: element.offsetHeight - element.clientTop * 2 };
      setSize(old => old.width === next.width && old.height === next.height ? old : next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  function changeZoom(nextValue: number, clientX?: number, clientY?: number) {
    const element = viewport.current;
    const art = drawing.current;
    if (!element || !art) return;
    const next = clampCircuitZoom(nextValue);
    const bounds = element.getBoundingClientRect();
    const x = clientX === undefined ? element.clientWidth / 2 : clientX - bounds.left - element.clientLeft;
    const y = clientY === undefined ? element.clientHeight / 2 : clientY - bounds.top - element.clientTop;
    const before = art.getBoundingClientRect();
    const ratio = next / Number(art.dataset.zoom);
    pendingScroll.current = {
      left: anchoredCircuitScroll(element.scrollLeft, x, element.clientWidth, before.width, before.width * ratio),
      top: anchoredCircuitScroll(element.scrollTop, y, element.clientHeight, before.height, before.height * ratio),
    };
    zoomRef.current = next;
    setZoom(next);
  }

  // The listener reads DOM dimensions and refs, not render state; it stays local to this viewport.
  useEffect(() => bindCircuitWheel(viewport.current!, event => {
    changeZoom(wheelCircuitZoom(zoomRef.current, event.deltaY, event.deltaMode), event.clientX, event.clientY);
  }), []);

  useLayoutEffect(() => {
    if (pendingScroll.current && viewport.current) {
      viewport.current.scrollLeft = pendingScroll.current.left;
      viewport.current.scrollTop = pendingScroll.current.top;
      pendingScroll.current = undefined;
    }
  }, [zoom]);

  function fit() {
    pendingScroll.current = undefined;
    zoomRef.current = 1;
    setZoom(1);
    if (viewport.current) viewport.current.scrollTo(0, 0);
  }

  return <div className="circuit-zoom">
    <div className="circuit-zoom-toolbar" role="group" aria-label={tr("接線圖縮放", "Diagram zoom")}>
      <button type="button" onClick={() => changeZoom(zoomRef.current / 1.25)} disabled={zoom <= MIN_CIRCUIT_ZOOM} aria-label={tr("縮小接線圖", "Zoom out diagram")}>−</button>
      <output aria-label={tr("接線圖比例", "Diagram scale")}>{size.width ? `${Math.round(scale * 100)}%` : "—"}</output>
      <button type="button" onClick={() => changeZoom(zoomRef.current * 1.25)} disabled={zoom >= MAX_CIRCUIT_ZOOM} aria-label={tr("放大接線圖", "Zoom in diagram")}>＋</button>
      <button type="button" onClick={fit} title={tr("重設縮放，顯示完整接線圖", "Reset zoom to show the entire diagram")}>↺ {tr("適合視窗", "Fit to view")}</button>
      <small>{tr("Ctrl＋滾輪縮放 · 放大後可捲動", "Ctrl + wheel to zoom · scroll when enlarged")}</small>
    </div>
    <div ref={viewport} className="circuit-viewport" tabIndex={0} role="region" aria-label={tr("可縮放接線圖", "Zoomable wiring diagram")}
      onKeyDown={event => {
        if (event.key === "+" || event.key === "=") { event.preventDefault(); changeZoom(zoomRef.current * 1.25); }
        else if (event.key === "-") { event.preventDefault(); changeZoom(zoomRef.current / 1.25); }
        else if (event.key === "0") { event.preventDefault(); fit(); }
      }}>
      <div className="circuit-zoom-stage" style={{ width: Math.max(size.width, width * scale), height: Math.max(size.height, height * scale) }}>
        <div ref={drawing} className="circuit-zoom-drawing" data-zoom={zoom} style={{ width: width * scale, height: height * scale }}>{children}</div>
      </div>
    </div>
  </div>;
}
