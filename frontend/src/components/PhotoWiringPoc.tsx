import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import board from "../../../profiles/boards/raspberry-pi-5/board.json";
import { useI18n } from "../lib/i18n";
import type { ProjectDesign } from "../lib/maker";
import { componentHeaderLocation } from "../lib/componentHeaderGuide";
import { anchoredCircuitScroll } from "../lib/circuitZoom";
import { pinColorVar } from "../lib/capabilities";
import { componentPinColor, guideConnectionColor } from "../lib/recognitionStyle";
import type { Pin } from "../lib/types";
import { acceptPhotoCapture, acceptPhotoCheck, acceptPhotoImageSize, acceptPhotoPlan, locatedPhotoPin,
  mergePhotoResults, openPhotoSession, photoFitScale, photoFocusBox, photoFocusView, photoLocalizationFor, photoModelConfidence,
  photoOverlayObjects, reliablePhotoPose, photoPlanBinding, photoPlanForProject, photoVerdictLabel, photoWiringRequest,
  type PhotoCapture, type PhotoCheckJob, type PhotoFocusBox, type PhotoOverlayMode,
  type PhotoPlan, type PhotoResultsRecord, type PhotoWire } from "../lib/photoWiring";
import "../photoWiring.css";

const HEARTBEAT_MS = 10000;
const CHECK_POLL_MS = 1000;
const MAX_CHECK_POLLS = 180;
// JSON widens tuple/union fields; only profile identity and capabilities are used here.
const BOARD_PINS = new Map((board.pins as unknown as Pin[]).map(pin => [pin.id, pin]));

function boardPinName(id: string) {
  const pin = BOARD_PINS.get(id);
  return pin ? `${id} · Pin ${pin.index}` : id;
}
function componentName(id: string) { return id === "hc-sr04" ? "HC-SR04+" : id === "mrd-tf240-8p-cs" ? "MRD-TFT240" : id; }
function captureTime(value: string | number, locale: string) {
  const date = new Date(typeof value === "number" ? value < 1e12 ? value * 1000 : value : value);
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString(locale) : String(value);
}
function errorText(error: unknown) { return error instanceof Error ? error.message : String(error); }

function localizationText(value: string, locale: string) {
  const labels: Record<string, [string, string]> = {
    model_only: ["模型原始預測", "Original model prediction"], localization_not_validated: ["這份資料尚未驗證座標", "Coordinates have not been validated"],
    sift_reference: ["同張照片的 SIFT 參考特徵比對", "SIFT reference matching in this photo"],
    sift_pcb_j8: ["同張照片特徵、板框與 J8 排針校正", "Photo features, board and J8 header refinement"],
    tft_mounting_holes: ["同張照片的四個固定孔校正", "Four mounting holes in this photo"],
    profile_projection: ["依板卡 profile 投影（未獨立校正接點）", "Profile projection (contacts not independently refined)"],
    j8_contacts: ["J8 接點列校正", "J8 contact-row refinement"],
    reference_sift_j8: ["同張照片特徵比對與 J8 排針列檢查", "Photo feature matching and J8 row checks"],
    pcb_reference_j8: ["同張照片板框、參考方向與排針列檢查", "Photo board boundary, reference orientation and header rows"],
    tft_rings_lcd_header: ["四個固定孔、螢幕邊界與排針方向校正", "Mounting holes, display boundary and header orientation"],
    hc_reference_sift: ["同張照片超音波模組參考特徵校正", "Ultrasonic reference features in this photo"],
    yolo_candidate: ["模型候選框（幾何未確認）", "Model candidate (geometry unconfirmed)"],
    j8_rows_unverified: ["板框已校正，但 J8 兩排接點的影像支持仍不明確", "Board refined, but the two J8 contact rows remain ambiguous"],
    ambiguous_rows: ["兩排接點不明確", "Contact rows are ambiguous"],
    board_and_j8_supported: ["板框與排針行列得到同張照片支持", "Board and header rows supported by this photo"],
    four_rings_lcd_and_header: ["四個固定孔、螢幕與排針方向互相符合", "Four holes, display and header direction agree"],
    distributed_reference_supported: ["分布在模組上的參考特徵互相符合", "Distributed module reference features agree"],
    geometry_unverified: ["外框幾何尚未得到同張照片支持", "Outline geometry is not supported by this photo yet"],
    board_geometry_unverified: ["板框幾何尚未確認", "Board geometry is unconfirmed"],
    tft_geometry_unverified: ["TFT 固定孔或方向尚未確認", "TFT mounting holes or orientation are unconfirmed"],
    hc_geometry_unverified: ["超音波模組參考特徵不足", "Insufficient ultrasonic reference features"],
    component_reference_unverified: ["元件的參考特徵不足，尚未確認腳位方向", "Module reference features are insufficient to confirm pin orientation"],
    weak_distributed_support: ["有效特徵過少或集中在局部，尚不足以確認整片板面", "Too few or too localized reference features to confirm the entire board"],
    invalid_or_clipped_geometry: ["物件外框不完整或超出照片，請調整取景", "The object geometry is incomplete or clipped; adjust the view"],
    model_missing: ["這張照片尚未辨識到物件", "The object was not recognized in this photo"],
    local_geometry_error: ["局部定位未完成，請重新拍照", "Local refinement could not finish; capture again"],
    four_visible_pcb_rings_required: ["需要清楚看見四個固定孔", "Four visible mounting holes are required"],
    ring_layout_or_header_unverified: ["固定孔排列或排針方向尚未確認", "Mounting-hole layout or header direction is unconfirmed"],
    reference_missing: ["缺少可比對的參考特徵", "Reference features are unavailable"],
    matched_reference: ["參考特徵一致", "Reference features agree"],
    profile_projection_current_anchors: ["依同張照片校正板框投影標準腳位", "Canonical pins projected from photo-refined anchors"],
    profile_projection_j8_rows: ["依同張照片的 J8 行列校正標準腳位", "Canonical pins refined using photo-supported J8 rows"],
    profile_projection_j8_unverified: ["板框 profile 預估；J8 行列未確認", "Board-profile estimate; J8 rows are unconfirmed"],
    profile_projection_from_current_image_anchors: ["同張照片校正錨點的 profile 投影", "Profile projection from photo-refined anchors"],
    profile_projection_with_current_image_alignment: ["同張照片校正板框的 profile 預估", "Profile estimate from the photo-refined board"],
  };
  return labels[value]?.[locale === "en" ? 1 : 0] ?? value;
}

/** A photo-only renderer: no live pose subscriptions, freshness timer or interpolation. */
export function PhotoPins({ capture, wire, mode = "corrected", labels = false, estimates = false, scale = 1 }: {
  capture: PhotoCapture; wire?: PhotoWire; mode?: PhotoOverlayMode; labels?: boolean; estimates?: boolean; scale?: number;
}) {
  const { locale } = useI18n();
  const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const arrowId = `photo-connection-${useId().replace(/:/g, "")}`;
  const [width, height] = capture.video_size;
  const boardTarget = mode === "corrected" && wire ? locatedPhotoPin(reliablePhotoPose(capture, "raspberry-pi-5"), wire.board_pin) : null;
  const moduleTarget = mode === "corrected" && wire ? locatedPhotoPin(reliablePhotoPose(capture, wire.component_id), wire.component_pin) : null;
  const radius = Math.min(4.6 / scale, Math.max(3, 1.65 / scale));
  const textSize = Math.max(13, 12 / scale);
  // Leave the exact contacts unobstructed, just like the live guide line.
  const dx = boardTarget && moduleTarget ? moduleTarget.x - boardTarget.x : 0;
  const dy = boardTarget && moduleTarget ? moduleTarget.y - boardTarget.y : 0;
  const distance = Math.hypot(dx, dy);
  const inset = Math.min(8 / scale, distance / 3) / (distance || 1);
  return <svg className="photo-poc-pin-overlay" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet"
    style={{ "--guide-connection-color": guideConnectionColor(wire?.component_pin ?? "") } as CSSProperties}
    role="img" aria-label={tr("固定照片 GPIO 與零件腳位；高亮目前接線的兩端", "GPIO and module pins on the frozen photo; the current wire endpoints are highlighted")}>
    {photoOverlayObjects(capture, mode).map(({ objectId, localization, outline, pins, candidatePins }) => <g key={objectId}
      className={`${objectId === "raspberry-pi-5" ? "photo-poc-board-pins" : "photo-poc-component-pins"} ${mode === "raw" ? "photo-poc-raw-outline" : localization.status !== "located" ? "photo-poc-uncertain-outline" : ""}`}>
      {outline ? <><polygon className="board-outline" points={outline.map(point => point.join(",")).join(" ")} />
        <text className="photo-poc-object-label object-recognition-label" x={Math.max(12, Math.min(width - 280, Math.min(...outline.map(point => point[0]))))}
          y={Math.max(25, Math.min(height - 10, Math.min(...outline.map(point => point[1])) - 12))} style={{ fontSize: textSize }}>
          {objectId === "raspberry-pi-5" ? "Pi 5" : componentName(objectId)} · {mode === "raw" ? tr("模型原框", "Model outline") : localization.status === "located" ? tr("座標可靠", "Reliable geometry") : tr("座標待確認", "Geometry uncertain")}</text></> : null}
      {pins.map(pin => <g key={pin.id} style={{ "--mk": objectId === "raspberry-pi-5"
        ? BOARD_PINS.has(pin.id) ? pinColorVar(BOARD_PINS.get(pin.id)!) : "var(--cap-other)"
        : componentPinColor(pin.id) } as CSSProperties}><circle className="pin-dot" cx={pin.x} cy={pin.y} r={radius}>
        <title>{objectId === "raspberry-pi-5" ? boardPinName(pin.id) : `${componentName(objectId)} · ${pin.id}`}</title></circle>
        {labels ? <text className="photo-poc-all-pin-label" x={pin.x + radius * 1.5} y={pin.y - radius} fontSize={textSize * .75}>
          {objectId === "raspberry-pi-5" ? BOARD_PINS.get(pin.id)?.index ?? pin.id : pin.id}</text> : null}</g>)}
      {estimates ? candidatePins.map(pin => { const selected = wire && (objectId === "raspberry-pi-5" ? wire.board_pin : wire.component_id === objectId ? wire.component_pin : "") === pin.id;
        return <g className={`photo-poc-estimated-pin${selected ? " selected" : ""}`} key={`candidate:${pin.id}`}><circle cx={pin.x} cy={pin.y} r={selected ? radius * 2.4 : radius}>
        <title>{tr("未驗證腳位預估", "Unverified pin estimate")}: {pin.id}</title></circle>
        {selected ? <text x={Math.max(12, Math.min(width - 420, pin.x + radius * 3))} y={Math.max(textSize * 1.3, pin.y - radius * 3)} fontSize={textSize}>
          {objectId === "raspberry-pi-5" ? boardPinName(pin.id) : pin.id} · {tr("預估，未驗證", "estimate, unverified")}</text>
          : labels ? <text x={pin.x + radius * 1.5} y={pin.y - radius} fontSize={textSize * .75}>{objectId === "raspberry-pi-5" ? board.pins.find(value => value.id === pin.id)?.index ?? pin.id : pin.id}</text> : null}</g>;
      }) : null}
    </g>)}
    {boardTarget && moduleTarget && wire?.connection_kind === "direct" ? <g>
      <defs><marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse"
        markerWidth={9 / scale} markerHeight={9 / scale} orient="auto">
        <path className="guide-connection-arrowhead" d="M 1 1 L 9 5 L 1 9" />
      </marker></defs>
      <line className="guide-connection-glow" x1={boardTarget.x + dx * inset} y1={boardTarget.y + dy * inset}
        x2={moduleTarget.x - dx * inset} y2={moduleTarget.y - dy * inset} />
      <line className="photo-poc-target-link guide-connection-line" markerEnd={`url(#${arrowId})`}
        x1={boardTarget.x + dx * inset} y1={boardTarget.y + dy * inset}
        x2={moduleTarget.x - dx * inset} y2={moduleTarget.y - dy * inset} />
    </g> : null}
    {[boardTarget ? { pin: boardTarget, label: boardPinName(wire!.board_pin) } : null,
      moduleTarget ? { pin: moduleTarget, label: `${componentName(wire!.component_id)} · ${wire!.component_pin}` } : null]
      .map((target, index) => target ? <g key={index} className="photo-poc-active-pin">
        <circle className="guidance-halo guidance-halo-outer" cx={target.pin.x} cy={target.pin.y} r={17 / scale} />
        <circle className="guidance-halo guidance-halo-inner" cx={target.pin.x} cy={target.pin.y} r={11 / scale} />
        <g className="pin-marker guidance-target"><circle className="pin-dot" cx={target.pin.x} cy={target.pin.y} r={3 / scale} /></g>
        <text x={Math.max(12, Math.min(width - textSize * Math.min(target.label.length, 24) * 0.58, target.pin.x + 22 / scale))}
          y={Math.max(textSize * 1.3, Math.min(height - 10, target.pin.y - 15 / scale))} fontSize={textSize}>{target.label}</text>
      </g> : null)}
  </svg>;
}

/** Source-pixel canvas: the image and SVG always have identical dimensions and offsets. */
export function PhotoViewport({ capture, wire, imageAttempt, imageLoaded, onLoad, onError, compact = false }: {
  capture: PhotoCapture; wire?: PhotoWire; imageAttempt: number; imageLoaded: boolean;
  onLoad: (width: number, height: number) => void; onError: () => void;
  compact?: boolean;
}) {
  const { locale } = useI18n();
  const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const viewport = useRef<HTMLDivElement>(null);
  const drawing = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [scale, setScale] = useState<number | null>(null);
  const [mode, setMode] = useState<PhotoOverlayMode>("corrected");
  const [labels, setLabels] = useState(false);
  const [estimates, setEstimates] = useState(false);
  const pendingScroll = useRef<{ left: number; top: number } | null>(null);
  const [width, height] = capture.video_size;
  const fitScale = photoFitScale(capture.video_size, size.width, size.height);
  const currentScale = scale ?? fitScale;
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(element); return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    if (pendingScroll.current && viewport.current) { viewport.current.scrollTo(pendingScroll.current); pendingScroll.current = null; }
  }, [currentScale]);
  function zoom(next: number) {
    const element = viewport.current; const art = drawing.current;
    if (!element || !art) return;
    const clamped = Math.max(.05, Math.min(4, next));
    pendingScroll.current = {
      left: anchoredCircuitScroll(element.scrollLeft, element.clientWidth / 2, element.clientWidth, width * currentScale, width * clamped),
      top: anchoredCircuitScroll(element.scrollTop, element.clientHeight / 2, element.clientHeight, height * currentScale, height * clamped),
    };
    setScale(clamped);
  }
  function focus(box: PhotoFocusBox | null) {
    if (!box) return;
    const next = photoFocusView(box, size.width, size.height);
    pendingScroll.current = { left: next.left, top: next.top }; setScale(next.scale);
    // Focusing another object can retain the scale; scrolling still needs to run.
    requestAnimationFrame(() => { if (pendingScroll.current && viewport.current) { viewport.current.scrollTo(pendingScroll.current); pendingScroll.current = null; } });
  }
  const hasEstimates = capture.localization?.some(item => item.status !== "located" && Boolean(item.candidate_pins?.length));
  return <div className="photo-poc-viewer">
    <div className="photo-poc-view-tools"><div className="photo-poc-overlay-switch" role="group" aria-label={tr("照片圖層", "Photo overlays")}>
      {(compact ? ["corrected", "photo"] as const : ["corrected", "raw", "photo"] as const).map(value => <button type="button" key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>
        {value === "corrected" ? tr("校正結果", "Refined") : value === "raw" ? tr("原始模型框", "Original model") : tr("純照片", "Photo only")}</button>)}</div>
      <div className="photo-poc-zoom-tools"><button type="button" onClick={() => zoom(currentScale / 1.3)} aria-label={tr("縮小照片", "Zoom out photo")}>−</button>
        <output>{Math.round(currentScale * 100)}%</output><button type="button" onClick={() => zoom(currentScale * 1.3)} aria-label={tr("放大照片", "Zoom in photo")}>＋</button>
        <button type="button" onClick={() => { pendingScroll.current = null; setScale(null); viewport.current?.scrollTo(0, 0); }}>{tr("完整照片", "Fit photo")}</button>
        <button type="button" onClick={() => zoom(1)}>1:1</button></div></div>
    <div className="photo-poc-view-options"><label><input type="checkbox" checked={labels} disabled={mode === "photo"} onChange={event => setLabels(event.target.checked)} />{tr("顯示全部腳位標籤", "All pin labels")}</label>
      {hasEstimates ? <label className="photo-poc-estimate-option"><input type="checkbox" checked={estimates} disabled={mode !== "corrected"} onChange={event => setEstimates(event.target.checked)} />{tr("顯示未驗證腳位預估", "Show unverified pin estimates")}</label> : null}
      <span>{labels ? tr("密集腳位標籤請用 1:1 或聚焦後查看", "Use 1:1 or focus to read dense pin labels") : tr("放大後可捲動 · + / − 縮放，0 顯示完整照片", "Scroll when enlarged · + / − zoom, 0 fits the photo")}</span></div>
    <div ref={viewport} className="photo-poc-photo-viewport" data-fit={scale === null} tabIndex={0} role="region" aria-label={tr("可放大的固定照片", "Zoomable frozen photo")}
      onKeyDown={event => {
        if (event.key === "+" || event.key === "=") { event.preventDefault(); zoom(currentScale * 1.3); }
        else if (event.key === "-") { event.preventDefault(); zoom(currentScale / 1.3); }
        else if (event.key === "0") { event.preventDefault(); setScale(null); viewport.current?.scrollTo(0, 0); }
      }}><div className="photo-poc-source-stage" style={{ width: width * currentScale, height: height * currentScale }}>
        <div ref={drawing} className="photo-poc-source-canvas" style={{ width: width * currentScale, height: height * currentScale }}>
          <img key={`${capture.capture_id}:${imageAttempt}`} src={`${capture.image_url}${imageAttempt ? `?retry=${imageAttempt}` : ""}`}
            alt={tr("本次固定接線照片", "Frozen wiring photo")} onLoad={event => onLoad(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)} onError={onError} />
          {imageLoaded && mode !== "photo" ? <PhotoPins capture={capture} wire={wire} mode={mode} labels={labels} estimates={estimates} scale={currentScale} /> : null}
        </div></div></div>
    <div className="photo-poc-focus-tools"><span>{tr("快速查看", "Focus")}</span><button type="button" onClick={() => focus(photoFocusBox(capture, "raspberry-pi-5"))}>Pi 5</button>
      {capture.components.map(pose => <button type="button" key={pose.component_id} onClick={() => focus(photoFocusBox(capture, pose.component_id))}>{componentName(pose.component_id)}</button>)}
      <button type="button" disabled={!wire || !photoFocusBox(capture, undefined, wire)} onClick={() => focus(photoFocusBox(capture, undefined, wire))}>{tr("目前接線兩端", "Current endpoints")}</button></div>
    {mode === "raw" ? <p className="photo-poc-diagnostic-note">{tr("粉紅虛框是模型原始預測，用來比較偏差；不提供可信 GPIO 座標。", "Pink dashed outlines are original model predictions for comparison; they do not provide reliable GPIO coordinates.")}</p>
      : estimates && hasEstimates ? <p className="photo-poc-diagnostic-note">{tr("空心淡色腳位是未驗證的 profile 預估；排針接點仍待校正，不能作為接線通過依據。", "Faint hollow pins are unverified profile estimates; contacts still need refinement and cannot support a wiring pass.")}</p> : null}
  </div>;
}

function PhotoQuality({ capture, ids }: { capture: PhotoCapture; ids: string[] }) {
  const { locale } = useI18n(); const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const metric = (value: unknown, suffix = "") => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(value % 1 ? 2 : 0)}${suffix}` : null;
  return <section className="photo-poc-quality" aria-label={tr("同張照片的定位品質", "Localization quality in this photo")}>
    <header><strong>{tr("辨識與座標品質", "Recognition and coordinate quality")}</strong><small>{tr("辨識信心不是接線正確率", "Recognition confidence is not wiring correctness")}</small></header>
    {ids.map(id => { const item = photoLocalizationFor(capture, id); const confidence = photoModelConfidence(capture, id);
      const boardVerified = item.evidence.board_geometry_verified === true;
      const support = [
        { name: tr("參考特徵內點", "Feature inliers"), value: metric(item.evidence.inliers) },
        { name: tr("參考投影誤差", "Reference reprojection error"), value: metric(item.evidence.reprojection_px, " px") },
        { name: tr("固定孔支持", "Mounting-hole support"), value: metric(item.evidence.holes_supported) },
        { name: tr("已校正角點", "Refined corners"), value: metric(item.evidence.corrected_corner_count) },
        { name: tr("最大角點調整", "Largest corner adjustment"), value: metric(item.evidence.max_corner_delta_px, " px") },
      ].filter(value => value.value !== null);
      return <details key={id} className={`photo-poc-quality-row ${item.status}`} open={item.status !== "located"}><summary>
        <strong>{id === "raspberry-pi-5" ? "Raspberry Pi 5" : componentName(id)}</strong>
        <span className="photo-poc-recognition">{confidence !== null ? `${tr("模型辨識", "Model recognition")} ${Math.round(confidence * 100)}%` : tr("模型信心未提供", "Model confidence unavailable")}</span>
        <span className="photo-poc-geometry">{item.status === "located" ? tr("座標可靠", "Reliable geometry") : boardVerified ? tr("板框已校正 · 腳位待確認", "Board refined · pins uncertain") : item.status === "not_found" ? tr("未辨識到", "Not found") : tr("座標不可靠", "Unreliable geometry")}</span>
      </summary><div className="photo-poc-quality-body"><p><b>{tr("校正方式", "Method")}</b>{localizationText(item.method, locale)}</p>
        {item.reason ? <p><b>{tr("定位說明", "Reason")}</b>{localizationText(item.reason, locale)}</p> : null}
        <p><b>{tr("腳位來源", "Pin source")}</b>{item.evidence.pin_method === "profile_projection_j8_rows" ? tr("同張照片排針行列支持；每個插接點仍需核對", "Header rows supported by this photo; each plugged contact still needs checking")
          : item.status === "located" ? tr("依同張照片校正板框投影標準腳位；每個插接點仍需核對", "Canonical pins projected from the photo-refined board; each plugged contact still needs checking")
            : tr("不顯示可信 GPIO；可查看標準腳位圖引導", "No trusted GPIO shown; use the canonical pin reference")}</p>
        {support.length ? <dl>{support.map(value => <div key={value.name}><dt>{value.name}</dt><dd>{value.value}</dd></div>)}</dl> : null}
        <details className="photo-poc-raw-evidence"><summary>{tr("詳細定位證據", "Detailed localization evidence")}</summary>
          <pre>{JSON.stringify(item.evidence, null, 2)}</pre></details>
      </div></details>;
    })}</section>;
}

function PhotoEndpointCrop({ capture, wire, objectId }: { capture: PhotoCapture; wire: PhotoWire; objectId: string }) {
  const { locale } = useI18n(); const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const isBoard = objectId === "raspberry-pi-5"; const pinId = isBoard ? wire.board_pin : wire.component_pin;
  const pose = reliablePhotoPose(capture, objectId); const pin = locatedPhotoPin(pose, pinId);
  const [width, height] = capture.video_size;
  const cropWidth = Math.min(width, 240); const cropHeight = Math.min(height, 150);
  const x = pin ? Math.max(0, Math.min(width - cropWidth, pin.x - cropWidth / 2)) : 0;
  const y = pin ? Math.max(0, Math.min(height - cropHeight, pin.y - cropHeight / 2)) : 0;
  return <figure className="photo-poc-endpoint-crop"><figcaption>{isBoard ? boardPinName(pinId) : `${componentName(objectId)} · ${pinId}`}</figcaption>
    {pin ? <svg viewBox={`${x} ${y} ${cropWidth} ${cropHeight}`} role="img" aria-label={tr("固定照片接點放大", "Enlarged contact from the frozen photo")}>
      <image href={capture.image_url} width={width} height={height} />
      {pose?.pins.filter(item => item.v && item.x >= x && item.x <= x + cropWidth && item.y >= y && item.y <= y + cropHeight).map(item => <g key={item.id}>
        <circle cx={item.x} cy={item.y} r={item.id === pinId ? 9 : 3} className={item.id === pinId ? "active" : ""} />
        <text x={item.x + 8} y={item.y - 6}>{isBoard ? board.pins.find(value => value.id === item.id)?.index ?? item.id : item.id}</text></g>)}
    </svg> : <div className="photo-poc-crop-missing">{tr("照片腳位尚未可靠定位", "Photo pin position is not reliable yet")}</div>}</figure>;
}

function PhotoPinReference({ wire }: { wire: PhotoWire }) {
  const { locale } = useI18n(); const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const pins = [...board.pins].sort((a, b) => a.index - b.index);
  const module = componentHeaderLocation(wire.component_id, wire.component_pin);
  return <details className="photo-poc-pin-reference"><summary>{tr("完整標準腳位圖 · Pi 40腳與元件腳位", "Complete pin reference · Pi 40-pin and module header")}</summary>
    <p>{tr("標準順序圖與照片分開：由 Pin 1 端依實體腳位編號找位置；高亮目前接線。", "This canonical order is separate from the photo: count physical pin numbers from Pin 1; the current connection is highlighted.")}</p>
    <div className="photo-poc-header-reference" aria-label={tr("Raspberry Pi 5 40 腳排針", "Raspberry Pi 5 40-pin header")}>{pins.map(pin => <div key={pin.id} className={pin.id === wire.board_pin ? "active" : ""}>
      <b>{pin.index}</b><span>{pin.id}</span></div>)}</div>
    {module ? <div className="photo-poc-module-reference"><strong>{componentName(wire.component_id)} · {module.pins.length} {tr("腳", "pins")}</strong><ol>
      {module.pins.map((id, index) => <li key={id} className={id === wire.component_pin ? "active" : ""}><b>{index + 1}</b>{id}</li>)}</ol>
      <small>{tr("以元件標籤與 Pin 1 方向為準；這張圖不是照片座標。", "Use the module labels and Pin 1 orientation; this diagram is not photo coordinates.")}</small></div> : null}
  </details>;
}

export function PhotoWiringPoc({ project = null, model, effort, onClose }: {
  project?: ProjectDesign | null; model: string; effort: string; onClose: () => void;
}) {
  const { locale } = useI18n();
  const tr = (zh: string, en: string) => locale === "en" ? en : zh;
  const [defaultPlan, setDefaultPlan] = useState<PhotoPlan | null>(null);
  const [startupAttempt, setStartupAttempt] = useState(0);
  const [session, setSession] = useState<{ id?: string; starting?: boolean; error?: string }>({ starting: true });
  const [captureRecord, setCaptureRecord] = useState<{ binding: string; packet: PhotoCapture } | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [captureError, setCaptureError] = useState("");
  const [selectedWireId, setSelectedWireId] = useState<string | null>(null);
  const [resultsRecord, setResultsRecord] = useState<PhotoResultsRecord | null>(null);
  const [jobTask, setJobTask] = useState<{ id: string; capture: PhotoCapture; binding: string; wireId?: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [pollRetry, setPollRetry] = useState(0);
  const [summary, setSummary] = useState("");
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageAttempt, setImageAttempt] = useState(0);
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState("");
  const [widePhoto, setWidePhoto] = useState(false);
  const operation = useRef<AbortController | null>(null);
  const flight = useRef(false);
  const mounted = useRef(true);
  const sessionQueue = useRef<Promise<void>>(Promise.resolve());
  const closeSession = useRef<(() => Promise<void>) | null>(null);
  const plan = useMemo(() => project ? photoPlanForProject(project) : defaultPlan, [project, defaultPlan]);
  const binding = photoPlanBinding(plan, project);
  const latest = useRef({ binding, sessionId: session.id });
  latest.current = { binding, sessionId: session.id };
  const packet = captureRecord?.binding === binding ? captureRecord.packet : null;
  const results = resultsRecord?.binding === binding && resultsRecord.captureId === packet?.capture_id ? resultsRecord.values : {};
  const wires = plan?.wires ?? [];
  const currentIndex = Math.max(0, wires.findIndex(wire => wire.wire_id === selectedWireId));
  const currentWire = wires[currentIndex];
  const currentResult = currentWire ? results[currentWire.wire_id] : undefined;
  const boardLocated = Boolean(packet && currentWire && locatedPhotoPin(reliablePhotoPose(packet, "raspberry-pi-5"), currentWire.board_pin));
  const moduleLocated = Boolean(packet && currentWire && locatedPhotoPin(reliablePhotoPose(packet, currentWire.component_id), currentWire.component_pin));

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; operation.current?.abort(); };
  }, []);

  useEffect(() => {
    let disposed = false;
    let token: string | undefined;
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let heartbeatPending = false;
    const stopHeartbeat = () => { clearInterval(heartbeat); document.removeEventListener("visibilitychange", wakeHeartbeat); window.removeEventListener("pageshow", wakeHeartbeat); };
    const wakeHeartbeat = () => { if (document.visibilityState === "visible") void refreshLease(); };
    async function refreshLease() {
      if (disposed || heartbeatPending || !token) return;
      heartbeatPending = true;
      try {
        const response = await photoWiringRequest<{ continuous_inference: boolean }>(`sessions/${encodeURIComponent(token)}/heartbeat`, { method: "POST", timeoutMs: 12000 });
        if (response.continuous_inference !== false) throw new Error(tr("照片模式已中斷", "Photo mode was interrupted"));
      } catch (error) {
        if (disposed) return;
        disposed = true; stopHeartbeat(); operation.current?.abort();
        // Keep the immutable photograph and completed advice available for read-only inspection.
        setSession({ error: errorText(error) }); setJobTask(null);
        setChecking(false); setCapturing(false); flight.current = false;
        void owner.close().catch(resumeError => { if (mounted.current) setCloseError(errorText(resumeError)); });
      } finally { heartbeatPending = false; }
    }
    setSession({ starting: true });
    setCaptureRecord(null); setResultsRecord(null); setJobTask(null); setChecking(false); setSummary("");
    const release = async (id: string) => {
      const response = await photoWiringRequest<{ resumed: boolean; continuous_inference: boolean }>(`sessions/${encodeURIComponent(id)}`, { method: "DELETE", timeoutMs: 20000 });
      if (!response.resumed || !response.continuous_inference) throw new Error(tr("服務尚未恢復持續辨識", "The service has not resumed continuous inference"));
    };
    const owner = openPhotoSession(sessionQueue, async () => {
        // Do not abort session creation: a late token must still be released after cleanup.
        const response = await photoWiringRequest<{ session_id: string; continuous_inference: false }>("sessions", { method: "POST" });
        if (!response.session_id || response.continuous_inference !== false) {
          if (response.session_id) await release(response.session_id);
          throw new Error(tr("服務未暫停持續辨識", "The service did not pause continuous inference"));
        }
        return response.session_id;
      }, release, id => {
        token = id;
        setSession({ id: token });
        heartbeat = setInterval(() => void refreshLease(), HEARTBEAT_MS);
        document.addEventListener("visibilitychange", wakeHeartbeat);
        window.addEventListener("pageshow", wakeHeartbeat);
      }, error => { if (!disposed) setSession({ error: errorText(error) }); });
    const finish = () => { disposed = true; stopHeartbeat(); operation.current?.abort(); return owner.close(); };
    closeSession.current = finish;
    return () => { if (closeSession.current === finish) closeSession.current = null; void finish().catch(() => undefined); };
    // A session owns its lease independently of project navigation and locale.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startupAttempt]);

  useEffect(() => {
    if (project) return;
    const controller = new AbortController();
    void photoWiringRequest<PhotoPlan>("plan", { signal: controller.signal, timeoutMs: 15000 }).then(response => {
      if (!acceptPhotoPlan(response)) throw new Error(tr("接線清單格式不符", "Invalid wiring plan"));
      if (!controller.signal.aborted) setDefaultPlan(response);
    }).catch(error => { if (!controller.signal.aborted) setCaptureError(errorText(error)); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(project), startupAttempt]);

  useEffect(() => {
    operation.current?.abort(); flight.current = false;
    setCaptureRecord(null); setResultsRecord(null); setJobTask(null); setCapturing(false); setChecking(false);
    setCaptureError(""); setCheckError(""); setSummary(""); setImageLoaded(false); setSelectedWireId(null);
  }, [binding]);

  useEffect(() => {
    if (!jobTask || !packet || jobTask.capture.capture_id !== packet.capture_id || jobTask.binding !== binding) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    setChecking(true); setCheckError("");
    async function poll() {
      if (!jobTask) return;
      try {
        const job = await photoWiringRequest<PhotoCheckJob>(`checks/${encodeURIComponent(jobTask.id)}`, { signal: controller.signal, timeoutMs: 15000 });
        if (controller.signal.aborted || latest.current.binding !== jobTask.binding) return;
        if (!acceptPhotoCheck(job, jobTask.capture, jobTask.wireId, jobTask.id)) throw new Error(tr("核對結果與這張照片不符，請重新核對", "The result does not match this photo; check again"));
        if (job.status === "failed") throw new Error(job.error || tr("AI 核對失敗", "AI check failed"));
        if (job.status === "completed") {
          setResultsRecord(previous => mergePhotoResults(previous, jobTask.capture.capture_id, jobTask.binding, job.results));
          setSummary(job.summary ?? ""); setJobTask(null); setChecking(false); return;
        }
        if (++polls >= MAX_CHECK_POLLS) throw new Error(tr("等待已超過三分鐘，可重試讀取結果", "Waited over three minutes; retry reading the result"));
        timer = setTimeout(() => void poll(), CHECK_POLL_MS);
      } catch (error) {
        if (!controller.signal.aborted) { setCheckError(errorText(error)); setChecking(false); }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobTask, packet, binding, pollRetry, locale]);

  async function takePhoto() {
    if (!session.id || !plan || !acceptPhotoPlan(plan) || flight.current || checking) return;
    const controller = new AbortController(); operation.current?.abort(); operation.current = controller; flight.current = true;
    const sessionId = session.id;
    const requestBinding = binding;
    setCapturing(true); setCaptureError(""); setCheckError(""); setCaptureRecord(null); setResultsRecord(null);
    setJobTask(null); setSummary(""); setImageLoaded(false); setImageAttempt(0);
    try {
      const next = await photoWiringRequest<PhotoCapture>(`sessions/${encodeURIComponent(sessionId)}/captures`, {
        method: "POST", signal: controller.signal, body: { project_id: project?.id ?? "photo-wiring-poc",
          project_revision: project?.revision ?? 1, catalog_version: plan.catalog_version,
          profile_versions: plan.profile_versions ?? {}, wires: plan.wires },
      });
      if (controller.signal.aborted || latest.current.binding !== requestBinding || latest.current.sessionId !== sessionId) return;
      if (!acceptPhotoCapture(next, sessionId, plan)) throw new Error(tr("照片與 GPIO 定位資料不一致，請重拍", "The photo and GPIO positions are inconsistent; capture again"));
      setCaptureRecord({ binding: requestBinding, packet: next });
    } catch (error) { if (!controller.signal.aborted && mounted.current) setCaptureError(errorText(error)); }
    finally { if (operation.current === controller) { flight.current = false; if (mounted.current) setCapturing(false); } }
  }

  async function checkPhoto(wireId?: string) {
    if (!packet || !imageLoaded || !session.id || !model || flight.current || checking) return;
    const controller = new AbortController(); operation.current?.abort(); operation.current = controller; flight.current = true;
    const requestBinding = binding;
    setChecking(true); setCheckError(""); setJobTask(null);
    try {
      const response = await photoWiringRequest<{ job_id: string }>(`captures/${encodeURIComponent(packet.capture_id)}/checks`, {
        method: "POST", signal: controller.signal, body: { model, effort, locale, wire_id: wireId ?? null },
      });
      if (controller.signal.aborted || latest.current.binding !== requestBinding) return;
      if (!response.job_id) throw new Error(tr("服務未返回核對工作", "The service did not return a check job"));
      setJobTask({ id: response.job_id, capture: packet, binding: requestBinding, wireId });
    } catch (error) { if (!controller.signal.aborted && mounted.current) { setCheckError(errorText(error)); setChecking(false); } }
    finally { if (operation.current === controller) flight.current = false; }
  }

  async function closePoc() {
    if (closing) return;
    setClosing(true); setCloseError(""); setJobTask(null); setChecking(false);
    setSession(current => ({ ...current, id: undefined, starting: false }));
    try { await closeSession.current?.(); if (mounted.current) onClose(); }
    catch (error) { if (mounted.current) { setCloseError(errorText(error)); setClosing(false); } }
  }

  const ready = Boolean(!closing && !closeError && session.id && !session.error && plan && acceptPhotoPlan(plan));
  const canCheck = ready && Boolean(packet && imageLoaded && model) && !capturing && !checking;
  return <section className="photo-wiring-poc" aria-label={tr("照片接線 POC", "Photo wiring POC")}>
    <header className="photo-poc-header"><div><span className="photo-poc-eyebrow">POC</span><h2>{tr("照片接線辨識", "Photo wiring recognition")}</h2>
      <p>{project?.title ?? tr("Raspberry Pi 5 · HC-SR04+ · TFT 接線", "Raspberry Pi 5 · HC-SR04+ · TFT wiring")}</p></div>
      <button type="button" className="photo-poc-close" disabled={closing} onClick={() => void closePoc()}>{closing ? tr("正在恢復持續辨識…", "Resuming continuous inference…") : tr("關閉 POC", "Close POC")} <span aria-hidden="true">×</span></button></header>
    <div className="photo-poc-intro"><ol><li>{tr("拍照定位 GPIO", "Capture GPIO positions")}</li><li>{tr("在固定照片上逐線引導", "Follow wires on the frozen photo")}</li><li>{tr("需要時請 AI 核對", "Ask AI to check when needed")}</li></ol>
      <span className={`photo-poc-session ${session.id && !closing && !closeError ? "ready" : ""}`} role="status">{closing ? tr("正在恢復持續辨識…", "Resuming continuous inference…") : closeError ? tr("持續辨識恢復未完成", "Continuous inference has not fully resumed") : session.starting ? tr("正在啟動照片模式…", "Starting photo mode…")
        : session.id ? tr("持續辨識已暫停 · 僅拍照時辨識", "Continuous inference paused · Recognize on capture") : tr("照片模式未連線", "Photo mode disconnected")}</span></div>
    {session.error ? <div className="photo-poc-error" role="alert"><span>{session.error}</span>{!closeError ? <button type="button" disabled={closing} onClick={() => setStartupAttempt(value => value + 1)}>{tr("重新連線", "Reconnect")}</button> : null}</div> : null}
    {closeError ? <div className="photo-poc-error" role="alert"><span>{tr("恢復辨識時發生問題：", "Could not resume inference: ")}{closeError}</span><button type="button" disabled={closing} onClick={() => void closePoc()}>{tr("重試關閉", "Retry close")}</button></div> : null}
    {packet && session.error ? <p className="photo-poc-diagnostic-note">{tr("保留這張照片與已完成結果供查看；重新連線後請重新拍照再核對。", "This photo and completed results remain available to view; reconnect and retake before checking again.")}</p> : null}
    <div className={`photo-poc-workspace${widePhoto ? " photo-poc-wide-photo" : ""}`}>
      <section className="photo-poc-camera"><header><div><strong>{packet ? tr("固定照片", "Frozen photo") : tr("拍照取景", "Camera preview")}</strong>
        {packet ? <small>frame {packet.frame_id} · {packet.video_size.join(" × ")} · {captureTime(packet.captured_at, locale)}</small>
          : <small>{tr("取景不會執行 GPIO 辨識", "Preview does not run GPIO recognition")}</small>}</div>
        <button type="button" className="photo-poc-primary" disabled={!ready || capturing || checking} onClick={() => void takePhoto()}>
          {capturing ? tr("正在拍照與定位…", "Capturing and locating…") : packet ? tr("重新拍照", "Retake photo") : tr("拍照辨識 GPIO", "Capture and recognize GPIO")}</button></header>
        {packet ? <><div className="photo-poc-photo-layout"><button type="button" aria-pressed={widePhoto} onClick={() => setWidePhoto(value => !value)}>{widePhoto ? tr("恢復並排", "Side-by-side") : tr("展開大圖", "Expand photo")}</button></div>
          <PhotoViewport key={packet.capture_id} capture={packet} wire={currentWire} imageAttempt={imageAttempt} imageLoaded={imageLoaded}
            onLoad={(width, height) => {
              if (!acceptPhotoImageSize(packet, width, height)) {
                setCaptureError(tr("照片尺寸與腳位座標不符，請重拍", "Photo dimensions differ from the pin coordinates; capture again"));
                setCaptureRecord(null); setResultsRecord(null); setJobTask(null); return;
              }
              setImageLoaded(true); setCaptureError("");
            }} onError={() => { setImageLoaded(false); setCaptureError(tr("無法讀取照片，可重試載入或重新拍照", "Cannot load the photo; retry loading or capture again")); }} /></>
          : <div className="photo-poc-image-stage" aria-busy={capturing}>{session.id && !session.error ? <img src="/video" alt={tr("Webcam 拍照取景", "Webcam capture preview")} />
            : <div className="photo-poc-placeholder">{session.starting ? tr("正在準備相機…", "Preparing camera…") : tr("重新連線後即可拍照", "Reconnect to capture a photo")}</div>}
          {capturing ? <div className="photo-poc-capturing" role="status">{tr("正在辨識這張照片…", "Recognizing this photo…")}</div> : null}</div>}
        {captureError ? <div className="photo-poc-error" role="alert"><span>{captureError}</span>
          {packet ? <button type="button" onClick={() => { setImageAttempt(value => value + 1); setCaptureError(""); }}>{tr("重試載入照片", "Retry photo load")}</button>
            : !plan ? <button type="button" onClick={() => setStartupAttempt(value => value + 1)}>{tr("重試", "Retry")}</button> : null}</div> : null}
        {packet && currentWire ? <div className="photo-poc-endpoints"><span className={boardLocated ? "located" : "missing"}>{boardPinName(currentWire.board_pin)} · {boardLocated ? tr("已定位", "Located") : tr("未定位", "Not located")}</span>
          <span className={moduleLocated ? "located" : "missing"}>{componentName(currentWire.component_id)} · {currentWire.component_pin} · {moduleLocated ? tr("已定位", "Located") : tr("未定位", "Not located")}</span>
          {!boardLocated || !moduleLocated ? <p>{tr("未可靠定位的端點不畫可信 GPIO；可用標準腳位圖繼續引導，或調整取景後重拍。", "Unreliable endpoints do not show trusted GPIO; continue with the canonical pin reference or adjust the view and retake.")}</p> : null}</div> : null}
        <p className="photo-poc-photo-note">{tr("虛線表示預期接法。切換步驟只更換高亮；接線或移動板卡後，請重拍。", "The dashed line shows the intended connection. Changing steps only changes the highlight; retake after wiring or moving the boards.")}</p>
        {packet ? <PhotoQuality capture={packet} ids={["raspberry-pi-5", ...(plan?.component_ids ?? [])]} /> : null}
      </section>
      <aside className="photo-poc-review"><header><strong>{tr("接線清單", "Wiring list")}</strong><span>{wires.length} {tr("條線", "wires")}</span></header>
        {!project ? <small className="photo-poc-plan-note">{tr("使用目前標準接線清單；POC 不建立或儲存作品。", "Uses the current standard wiring plan; this POC does not create or save a project.")}</small> : null}
        <div className="photo-poc-check-actions"><button type="button" className="photo-poc-primary" disabled={!canCheck} onClick={() => void checkPhoto()}>{tr("AI 核對全部接線", "AI check all wires")}</button>
          <button type="button" disabled={!canCheck || !currentWire} onClick={() => void checkPhoto(currentWire?.wire_id)}>{tr("核對這條線", "Check this wire")}</button></div>
        {!model ? <p className="photo-poc-plan-note">{tr("請先在上方選擇 Codex 模型，再進行 AI 核對。", "Select a Codex model above before asking AI to check.")}</p> : null}
        {checking ? <p className="photo-poc-check-status" role="status">{tr("AI 正在核對這張固定照片…", "AI is checking this frozen photo…")}</p> : null}
        {checkError ? <div className="photo-poc-error" role="alert"><span>{checkError}</span>{jobTask ? <button type="button" onClick={() => setPollRetry(value => value + 1)}>{tr("重試讀取結果", "Retry reading result")}</button> : null}</div> : null}
        <ol className="photo-poc-wire-list">{wires.map((wire, index) => <li key={wire.wire_id}><button type="button" aria-pressed={currentWire?.wire_id === wire.wire_id}
          className={currentWire?.wire_id === wire.wire_id ? "selected" : ""} onClick={() => setSelectedWireId(wire.wire_id)}>
          <span className="photo-poc-wire-number">{index + 1}</span><span className="photo-poc-wire-name"><strong>{componentName(wire.component_id)} · {wire.component_pin}</strong><small>→ {boardPinName(wire.board_pin)}</small></span>
          <span className={`photo-poc-verdict ${results[wire.wire_id]?.verdict ?? "unchecked"}`}>{results[wire.wire_id] ? photoVerdictLabel(results[wire.wire_id].verdict, locale) : tr("尚未核對", "Unchecked")}</span>
        </button></li>)}</ol>
        {!wires.length ? <p>{tr("正在讀取接線清單…", "Loading the wiring plan…")}</p> : null}
        <nav className="photo-poc-step-nav" aria-label={tr("照片接線步驟", "Photo wiring steps")}><button type="button" disabled={!wires.length || currentIndex === 0} onClick={() => setSelectedWireId(wires[currentIndex - 1]?.wire_id ?? null)}>{tr("← 上一條", "← Previous")}</button>
          <span>{wires.length ? currentIndex + 1 : 0} / {wires.length}</span><button type="button" disabled={!wires.length || currentIndex >= wires.length - 1} onClick={() => setSelectedWireId(wires[currentIndex + 1]?.wire_id ?? null)}>{tr("下一條 →", "Next →")}</button></nav>
        {packet && imageLoaded && currentWire ? <section className="photo-poc-current-endpoints"><strong>{tr("目前接線 · 同張照片局部放大", "Current wire · photo contact details")}</strong><div>
          <PhotoEndpointCrop capture={packet} wire={currentWire} objectId="raspberry-pi-5" /><PhotoEndpointCrop capture={packet} wire={currentWire} objectId={currentWire.component_id} /></div></section> : null}
        {currentWire ? <PhotoPinReference wire={currentWire} /> : null}
        {currentResult ? <section className={`photo-poc-result ${currentResult.verdict}`} aria-label={tr("目前接線核對結果", "Current wire check result")}>
          <strong>{photoVerdictLabel(currentResult.verdict, locale)}</strong><dl><dt>{tr("Pi 端", "Pi endpoint")}</dt><dd>{currentResult.board_observation.evidence}{currentResult.board_observation.observed_pin ? <small className="photo-poc-observed">{tr("觀察腳位", "Observed pin")}: {currentResult.board_observation.observed_pin}</small> : null}</dd>
            <dt>{tr("零件端", "Module endpoint")}</dt><dd>{currentResult.component_observation.evidence}{currentResult.component_observation.observed_pin ? <small className="photo-poc-observed">{tr("觀察腳位", "Observed pin")}: {currentResult.component_observation.observed_pin}</small> : null}</dd><dt>{tr("線路", "Wire path")}</dt><dd>{currentResult.wire_observation.evidence}</dd></dl>
          {currentResult.note ? <p>{currentResult.note}</p> : null}</section> : null}
        {packet && summary ? <p className="photo-poc-summary">{summary}</p> : null}
      </aside>
    </div>
    <footer>{tr("核對照片可見的接點與線路；遮住的接點無法確認，也不代表導通或電壓已驗證。", "Checks the contacts and wires visible in the photo; hidden contacts cannot be confirmed, and continuity or voltage is not verified.")}</footer>
  </section>;
}
