import { useCallback, useEffect, useRef, useState, type CSSProperties, type MutableRefObject, type PointerEvent, type ReactNode } from "react";
import { dragGuideRatio, GUIDE_SPLIT_STORAGE_KEY, guideRatioForRight, guideSplitGeometry, keyGuideRatio, parseSplitRatio,
  dragGuideHeightRatio, GUIDE_HEIGHT_STORAGE_KEY, guideHeightGeometry, guideRatioForTop, keyGuideHeightRatio } from "../lib/studioSplit";
import { useMakerText } from "../lib/useMaker";

function readRatio(key: string) {
  try { return parseSplitRatio(localStorage.getItem(key)); }
  catch { return null; }
}

/** Measure intrinsic content, not scrollHeight (which includes surplus pane space). */
function stackHeight(element: HTMLElement, nested?: HTMLElement | null): number {
  const css = getComputedStyle(element);
  const px = (value: string) => Number.parseFloat(value) || 0;
  const children = Array.from(element.children).filter((child): child is HTMLElement =>
    child instanceof HTMLElement && getComputedStyle(child).display !== "none");
  return px(css.paddingTop) + px(css.paddingBottom) + px(css.borderTopWidth) + px(css.borderBottomWidth)
    + Math.max(0, children.length - 1) * px(css.rowGap)
    + children.reduce((total, child) => {
      const style = getComputedStyle(child);
      return total + (child === nested ? stackHeight(child) : child.getBoundingClientRect().height)
        + px(style.marginTop) + px(style.marginBottom);
    }, 0);
}

/** Only the sibling grid changes size; VideoView and its overlay remain mounted. */
export function GuidePaneLayout({ stageRef, className, visible, resizable, stacked = false, children }: {
  stageRef: MutableRefObject<HTMLDivElement | null>; className: string; visible: boolean;
  resizable: boolean; stacked?: boolean; children: ReactNode;
}) {
  const tr = useMakerText();
  const root = useRef<HTMLDivElement | null>(null);
  const handle = useRef<HTMLDivElement | null>(null);
  const frame = useRef(0);
  const drag = useRef<{ pointerId: number; startCoordinate: number; startSize: number; original: number | null; latest: number } | null>(null);
  const storageKey = stacked ? GUIDE_HEIGHT_STORAGE_KEY : GUIDE_SPLIT_STORAGE_KEY;
  const [ratio, setRatio] = useState(() => readRatio(storageKey));
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [minimumGuideHeight, setMinimumGuideHeight] = useState(160);
  const { width, height } = size;
  // On phones / very short windows keep the natural, scrollable layout instead.
  const enabled = resizable && visible && (!stacked || (width > 700 && height >= 420));
  const [dragging, setDragging] = useState(false);
  const bindRoot = useCallback((node: HTMLDivElement | null) => { root.current = node; stageRef.current = node; }, [stageRef]);

  useEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => setSize(previous => {
      const next = { width: element.clientWidth, height: element.clientHeight };
      return next.width === previous.width && next.height === previous.height ? previous : next;
    });
    const observer = new ResizeObserver(measure);
    measure();
    observer.observe(element);
    return () => { observer.disconnect(); cancelAnimationFrame(frame.current); };
  }, []);

  useEffect(() => {
    const element = root.current;
    if (!element || !stacked || !visible || !resizable) return;
    let pending = 0;
    const measure = () => {
      pending = 0;
      const guide = element.querySelector<HTMLElement>(".compact-guide.review");
      if (!guide || element.clientWidth <= 700) { setMinimumGuideHeight(160); return; }
      // Details are optional reading, not a reason to consume the whole camera.
      if (guide.querySelector("details[open]")) return;
      const body = guide.querySelector<HTMLElement>(".guide-panel-body");
      const footer = guide.querySelector<HTMLElement>(".guide-panel-footer");
      const workspace = guide.closest<HTMLElement>(".wiring-workspace");
      if (!body || !footer || !workspace) return;
      const overhead = workspace.getBoundingClientRect().height - body.getBoundingClientRect().height;
      const contentHeight = Math.ceil(overhead + Math.max(stackHeight(body),
        stackHeight(footer, footer.querySelector<HTMLElement>(".guide-test-controls"))) + 4);
      // Long test instructions must not take space from the preferred 70% stream.
      // Each guide column can scroll when its content exceeds the available 30%.
      const guideBudget = Math.max(160, (element.clientHeight - 18) * .3);
      const needed = Math.min(contentHeight, guideBudget);
      setMinimumGuideHeight(previous => previous === needed ? previous : needed);
    };
    const schedule = () => { if (!pending) pending = requestAnimationFrame(measure); };
    const observer = new ResizeObserver(schedule);
    const observeContent = () => {
      observer.disconnect();
      observer.observe(element);
      element.querySelectorAll(".guide-panel-body, .guide-panel-footer, .guide-panel-body > *, .guide-panel-footer > *, .guide-test-controls > *")
        .forEach(node => observer.observe(node));
      schedule();
    };
    const mutations = new MutationObserver(observeContent);
    const workspace = element.querySelector(".wiring-workspace");
    // Camera overlay updates are irrelevant to the guide's intrinsic height.
    if (workspace) mutations.observe(workspace, { childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ["open", "hidden", "class"] });
    observeContent();
    return () => { mutations.disconnect(); observer.disconnect(); cancelAnimationFrame(pending); };
  }, [stacked, visible, resizable]);

  useEffect(() => { if (!enabled) finish(false); }, [enabled]);
  useEffect(() => { setRatio(readRatio(storageKey)); }, [storageKey]);

  function save(next: number | null) {
    setRatio(next);
    try {
      if (next === null) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, String(next));
    } catch { /* A blocked preference store must not prevent resizing. */ }
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current || event.pointerId !== current.pointerId) return;
    current.latest = stacked
      ? dragGuideHeightRatio(current.startSize, current.startCoordinate, event.clientY, root.current?.clientHeight ?? height, minimumGuideHeight)
      : dragGuideRatio(current.startSize, current.startCoordinate, event.clientX, root.current?.clientWidth ?? width);
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
  const vertical = guideHeightGeometry(height, ratio, minimumGuideHeight);
  const available = stacked ? vertical.available : geometry.available;
  const cameraSize = stacked ? vertical.top : geometry.left;
  const minCamera = stacked ? vertical.minTop : geometry.available - geometry.maxRight;
  const maxCamera = stacked ? vertical.maxTop : geometry.available - geometry.minRight;
  const cameraPercent = available ? Math.round(cameraSize / available * 100) : 50;
  const cameraMin = available ? Math.round(minCamera / available * 100) : 0;
  const cameraMax = available ? Math.round(maxCamera / available * 100) : 100;
  const style = { ...(!visible ? { display: "none" } : {}), ...(stacked
    ? { "--guide-camera-height": `${vertical.top}px`, "--guide-panel-height": `${vertical.bottom}px` }
    : width > 0 ? { "--guide-column-width": `${geometry.right}px` } : {}) } as CSSProperties;

  return <div ref={bindRoot} className={`${className}${enabled ? stacked ? " guide-height-resizable" : " guide-resizable" : ""}${dragging ? " is-resizing" : ""}`} style={style}>
    {children}
    {enabled ? <div ref={handle} className="guide-resize-handle" role="separator" tabIndex={0} aria-orientation={stacked ? "horizontal" : "vertical"}
      aria-label={stacked ? tr("調整鏡頭與接線引導高度", "Resize camera and wiring guide height") : tr("調整鏡頭與接線引導寬度", "Resize camera and wiring guide")}
      aria-valuemin={cameraMin} aria-valuemax={cameraMax} aria-valuenow={cameraPercent}
      aria-valuetext={`${tr("鏡頭", "Camera")} ${cameraPercent}% · ${tr("接線引導", "Wiring guide")} ${100 - cameraPercent}%`}
      title={stacked ? tr("上下拖曳調整；雙擊還原。↑ ↓ 可微調。", "Drag up or down to resize; double-click to reset. ↑ ↓ fine-tune.") : tr("拖曳調整左右寬度；雙擊還原。方向鍵可微調。", "Drag to resize; double-click to reset. Arrow keys fine-tune.")}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary || drag.current) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { pointerId: event.pointerId, startCoordinate: stacked ? event.clientY : event.clientX,
          startSize: stacked ? vertical.top : geometry.right, original: ratio,
          latest: stacked ? guideRatioForTop(vertical.top, height, minimumGuideHeight) : guideRatioForRight(geometry.right, width) };
        setDragging(true);
      }}
      onPointerMove={move}
      onPointerUp={event => { if (drag.current?.pointerId === event.pointerId) { move(event); finish(true); } }}
      onPointerCancel={event => { if (drag.current?.pointerId === event.pointerId) finish(false); }}
      onLostPointerCapture={event => { if (drag.current?.pointerId === event.pointerId) finish(false); }}
      onDoubleClick={() => { finish(false); save(null); }}
      onKeyDown={event => {
        if (event.key === "Escape" && drag.current) { event.preventDefault(); event.stopPropagation(); finish(false); return; }
        if (drag.current) return;
        if (event.key === "Enter") { event.preventDefault(); save(null); return; }
        const next = stacked ? keyGuideHeightRatio(event.key, event.shiftKey, vertical.top, height, minimumGuideHeight)
          : keyGuideRatio(event.key, event.shiftKey, geometry.right, width);
        if (next !== null) { event.preventDefault(); save(next); }
      }}><span aria-hidden="true" /></div> : null}
  </div>;
}
