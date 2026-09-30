import { useCallback, useEffect, useRef, useState, type CSSProperties, type MutableRefObject, type PointerEvent, type ReactNode } from "react";
import { dragGuideRatio, GUIDE_SPLIT_STORAGE_KEY, guideRatioForRight, guideSplitGeometry, keyGuideRatio, parseSplitRatio } from "../lib/studioSplit";
import { useMakerText } from "../lib/useMaker";

function readRatio() {
  try { return parseSplitRatio(localStorage.getItem(GUIDE_SPLIT_STORAGE_KEY)); }
  catch { return null; }
}

/** Only the sibling grid changes size; VideoView and its overlay remain mounted. */
export function GuidePaneLayout({ stageRef, className, visible, resizable, children }: {
  stageRef: MutableRefObject<HTMLDivElement | null>; className: string; visible: boolean;
  resizable: boolean; children: ReactNode;
}) {
  const tr = useMakerText();
  const root = useRef<HTMLDivElement | null>(null);
  const handle = useRef<HTMLDivElement | null>(null);
  const frame = useRef(0);
  const drag = useRef<{ pointerId: number; startX: number; startRight: number; original: number | null; latest: number } | null>(null);
  const [ratio, setRatio] = useState(readRatio);
  const [width, setWidth] = useState(0);
  const [dragging, setDragging] = useState(false);
  const bindRoot = useCallback((node: HTMLDivElement | null) => { root.current = node; stageRef.current = node; }, [stageRef]);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    setWidth(element.clientWidth);
    observer.observe(element);
    return () => { observer.disconnect(); cancelAnimationFrame(frame.current); };
  }, []);

  function save(next: number | null) {
    setRatio(next);
    try {
      if (next === null) localStorage.removeItem(GUIDE_SPLIT_STORAGE_KEY);
      else localStorage.setItem(GUIDE_SPLIT_STORAGE_KEY, String(next));
    } catch { /* A blocked preference store must not prevent resizing. */ }
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || event.pointerId !== current.pointerId) return;
    current.latest = dragGuideRatio(current.startRight, current.startX, event.clientX, root.current?.clientWidth ?? width);
    if (!frame.current) frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      if (drag.current) setRatio(drag.current.latest);
    });
  }
  function finish(commit: boolean) {
    const current = drag.current;
    if (!current) return;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    drag.current = null;
    setDragging(false);
    if (commit) save(current.latest);
    else setRatio(current.original);
    if (handle.current?.hasPointerCapture(current.pointerId)) handle.current.releasePointerCapture(current.pointerId);
  }
  const geometry = guideSplitGeometry(width, ratio);
  const cameraPercent = geometry.available ? Math.round(geometry.left / geometry.available * 100) : 50;
  const cameraMin = geometry.available ? Math.round((geometry.available - geometry.maxRight) / geometry.available * 100) : 0;
  const cameraMax = geometry.available ? Math.round((geometry.available - geometry.minRight) / geometry.available * 100) : 100;
  const style = { ...(!visible ? { display: "none" } : {}), ...(width > 0 ? { "--guide-column-width": `${geometry.right}px` } : {}) } as CSSProperties;

  return <div ref={bindRoot} className={`${className}${resizable ? " guide-resizable" : ""}${dragging ? " is-resizing" : ""}`} style={style}>
    {children}
    {resizable ? <div ref={handle} className="guide-resize-handle" role="separator" tabIndex={0} aria-orientation="vertical"
      aria-label={tr("調整鏡頭與接線引導寬度", "Resize camera and wiring guide")}
      aria-valuemin={cameraMin} aria-valuemax={cameraMax} aria-valuenow={cameraPercent}
      aria-valuetext={`${tr("鏡頭", "Camera")} ${cameraPercent}% · ${tr("接線引導", "Wiring guide")} ${100 - cameraPercent}%`}
      title={tr("拖曳調整左右寬度；雙擊還原。方向鍵可微調。", "Drag to resize; double-click to reset. Arrow keys fine-tune.")}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary || drag.current) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { pointerId: event.pointerId, startX: event.clientX, startRight: geometry.right, original: ratio, latest: guideRatioForRight(geometry.right, width) };
        setDragging(true);
      }}
      onPointerMove={move}
      onPointerUp={event => { if (drag.current?.pointerId === event.pointerId) { move(event); finish(true); } }}
      onPointerCancel={() => finish(false)} onLostPointerCapture={() => finish(false)}
      onDoubleClick={() => { finish(false); save(null); }}
      onKeyDown={event => {
        if (event.key === "Escape" && drag.current) { event.preventDefault(); finish(false); return; }
        if (drag.current) return;
        if (event.key === "Enter") { event.preventDefault(); save(null); return; }
        const next = keyGuideRatio(event.key, event.shiftKey, geometry.right, width);
        if (next !== null) { event.preventDefault(); save(next); }
      }}><span aria-hidden="true" /></div> : null}
  </div>;
}
