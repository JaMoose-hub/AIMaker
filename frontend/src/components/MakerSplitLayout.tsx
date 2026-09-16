import { useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import { dragSplitRatio, keySplitRatio, parseSplitRatio, splitStorageKey, studioSplitGeometry, type StudioStage } from "../lib/studioSplit";
import { useMakerText } from "../lib/useMaker";

function readRatio(stage: StudioStage) {
  try { return parseSplitRatio(localStorage.getItem(splitStorageKey(stage))); } catch { return null; }
}

/** Resizing only updates this layout, never the shared project / AI request state. */
export function MakerSplitLayout({ stage, left, children }: { stage: StudioStage; left: ReactNode; children: ReactNode }) {
  const tr = useMakerText();
  const root = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const drag = useRef<{ pointerId: number; stage: StudioStage; startX: number; startLeft: number; original: number | null; latest: number } | null>(null);
  const [ratios, setRatios] = useState(() => ({ design: readRatio("design"), blueprint: readRatio("blueprint") }));
  const [width, setWidth] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    setWidth(element.clientWidth);
    observer.observe(element);
    return () => { observer.disconnect(); cancelAnimationFrame(frame.current); };
  }, []);

  function setRatio(value: number | null, save = false) {
    setRatios(previous => ({ ...previous, [stage]: value }));
    if (save) {
      try {
        if (value === null) localStorage.removeItem(splitStorageKey(stage));
        else localStorage.setItem(splitStorageKey(stage), String(value));
      } catch { /* A blocked preference store must not prevent resizing. */ }
    }
  }
  function finishDrag(commit: boolean) {
    const current = drag.current;
    if (!current) return;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    drag.current = null;
    setDragging(false);
    setRatio(commit ? current.latest : current.original, commit);
    if (handle.current?.hasPointerCapture(current.pointerId)) handle.current.releasePointerCapture(current.pointerId);
  }
  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    current.latest = dragSplitRatio(current.startLeft, current.startX, event.clientX, root.current?.clientWidth ?? width);
    if (!frame.current) frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const active = drag.current;
      if (active) setRatios(previous => ({ ...previous, [active.stage]: active.latest }));
    });
  }
  const geometry = studioSplitGeometry(width, stage, ratios[stage]);
  const percent = (value: number) => geometry.available ? Math.round(value / geometry.available * 100) : 50;

  return <div ref={root} className={`maker-design-container maker-studio maker-resizable maker-${stage}-layout${dragging ? " is-resizing" : ""}`}
    style={width ? { "--maker-left-width": `${geometry.left}px` } as CSSProperties : undefined}>
    {left}
    <div ref={handle} className="maker-splitter" role="separator" tabIndex={0} aria-orientation="vertical"
      aria-label={stage === "blueprint" ? tr("調整接線圖與製作側欄寬度", "Resize wiring diagram and build sidebar") : tr("調整對話與作品區寬度", "Resize conversation and project panels")}
      aria-valuemin={percent(geometry.min)} aria-valuemax={percent(geometry.max)} aria-valuenow={percent(geometry.left)}
      aria-valuetext={`${stage === "blueprint" ? tr("接線圖", "Wiring diagram") : tr("對話區", "Conversation")} ${percent(geometry.left)}%`}
      title={tr("拖曳調整左右寬度；雙擊還原。方向鍵可微調。", "Drag to resize; double-click to reset. Arrow keys fine-tune.")}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary || drag.current) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { pointerId: event.pointerId, stage, startX: event.clientX, startLeft: geometry.left, original: ratios[stage], latest: geometry.available ? geometry.left / geometry.available : .5 };
        setDragging(true);
      }}
      onPointerMove={moveDrag}
      onPointerUp={event => {
        if (drag.current?.pointerId !== event.pointerId) return;
        moveDrag(event);
        finishDrag(true);
      }}
      onPointerCancel={() => finishDrag(false)} onLostPointerCapture={() => finishDrag(false)}
      onDoubleClick={() => { finishDrag(false); setRatio(null, true); }}
      onKeyDown={event => {
        if (event.key === "Escape" && drag.current) { event.preventDefault(); finishDrag(false); return; }
        if (drag.current) return;
        if (event.key === "Enter") { event.preventDefault(); setRatio(null, true); return; }
        const ratio = keySplitRatio(event.key, event.shiftKey, geometry.left, width);
        if (ratio !== null) { event.preventDefault(); setRatio(ratio, true); }
      }}><span aria-hidden="true" /></div>
    {children}
  </div>;
}
