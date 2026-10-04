import { Children, useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { DEPLOY_SPLIT_STORAGE_KEY, deploySplitGeometry, dragDeploySplitRatio, keyDeploySplitRatio } from "../lib/deploySplit";
import { parseSplitRatio } from "../lib/studioSplit";
import { useMakerText } from "../lib/useMaker";
import "./deploySplit.css";

function initialRatio() {
  try { return parseSplitRatio(localStorage.getItem(DEPLOY_SPLIT_STORAGE_KEY)); }
  catch { return null; }
}

/** Only layout preferences change; the editor and output keep their mounted nodes. */
export function DeploySplitLayout({ children, editorHeight }: { children: ReactNode; editorHeight: number }) {
  const tr = useMakerText();
  const root = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const drag = useRef<{ pointerId: number; startX: number; startLeft: number; original: number | null; latest: number } | null>(null);
  const [ratio, setRatio] = useState(initialRatio);
  const [width, setWidth] = useState(0);
  const [dragging, setDragging] = useState(false);
  const geometry = deploySplitGeometry(width, ratio);
  const columns = Children.toArray(children);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    setWidth(element.clientWidth);
    observer.observe(element);
    return () => { observer.disconnect(); cancelAnimationFrame(frame.current); drag.current = null; };
  }, []);

  function saveRatio(next: number | null) {
    setRatio(next);
    try {
      if (next === null) localStorage.removeItem(DEPLOY_SPLIT_STORAGE_KEY);
      else localStorage.setItem(DEPLOY_SPLIT_STORAGE_KEY, String(next));
    } catch { /* Keep resizing usable if preference storage is blocked. */ }
  }
  function finishDrag(commit: boolean) {
    const current = drag.current;
    if (!current) return;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    drag.current = null;
    setDragging(false);
    if (commit) saveRatio(current.latest);
    else setRatio(current.original);
    if (handle.current?.hasPointerCapture(current.pointerId)) handle.current.releasePointerCapture(current.pointerId);
  }
  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    current.latest = dragDeploySplitRatio(current.startLeft, current.startX, event.clientX, root.current?.clientWidth ?? width);
    if (!frame.current) frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      if (drag.current) setRatio(drag.current.latest);
    });
  }
  const percent = (value: number) => geometry.available ? Math.round(value / geometry.available * 100) : 50;

  return <div ref={root} className={`deploy-workspace deploy-resizable${dragging ? " is-resizing" : ""}`}
    data-columns={width ? geometry.sideBySide ? "split" : "stacked" : "auto"}
    style={{ "--editor-height": `${editorHeight}px`, "--deploy-code-width": `${geometry.left}px` } as CSSProperties}>
    {columns[0]}
    <div ref={handle} className="deploy-splitter" role="separator" aria-orientation="vertical" tabIndex={0}
      aria-label={tr("調整程式碼與輸出結果寬度", "Resize code and output panels")}
      aria-valuemin={percent(geometry.min)} aria-valuemax={percent(geometry.max)} aria-valuenow={percent(geometry.left)}
      aria-valuetext={`${tr("程式碼", "Code")} ${percent(geometry.left)}%`}
      title={tr("拖曳調整寬度；雙擊還原。方向鍵可微調。", "Drag to resize; double-click to reset. Arrow keys fine-tune.")}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary || drag.current || !geometry.sideBySide) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { pointerId: event.pointerId, startX: event.clientX, startLeft: geometry.left, original: ratio, latest: geometry.left / geometry.available };
        setDragging(true);
      }}
      onPointerMove={moveDrag}
      onPointerUp={event => { if (drag.current?.pointerId === event.pointerId) { moveDrag(event); finishDrag(true); } }}
      onPointerCancel={event => { if (drag.current?.pointerId === event.pointerId) finishDrag(false); }}
      onLostPointerCapture={event => { if (drag.current?.pointerId === event.pointerId) finishDrag(false); }}
      onDoubleClick={() => { finishDrag(false); saveRatio(null); }}
      onKeyDown={event => {
        if (event.key === "Escape" && drag.current) { event.preventDefault(); finishDrag(false); return; }
        if (drag.current) return;
        if (event.key === "Enter") { event.preventDefault(); saveRatio(null); return; }
        const next = keyDeploySplitRatio(event.key, event.shiftKey, geometry.left, width);
        if (next !== null) { event.preventDefault(); saveRatio(next); }
      }}><span aria-hidden="true" /></div>
    {columns[1]}
  </div>;
}
