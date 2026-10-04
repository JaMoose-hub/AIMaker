import { useEffect, useId, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { useMakerText } from "../lib/useMaker";
import { boundWiringAction, cropFromPoints, imagePointFromClient, validWiringCrop, wiringPhotoRoles,
  type WiringCrop, type WiringEndpoint, type WiringHumanDecision, type WiringPhotoRole, type WiringPhotoSlot,
  type WiringReviewAction, type WiringReviewState } from "../lib/wiringReview";
import "./wiringReview.css";
import { WiringPhotoSequence } from './WiringPhotoSequence';

export interface WiringReviewCardProps {
  review?: WiringReviewState | null;
  components: { id: string; label: string }[];
  componentId?: string;
  busy?: boolean;
  captureReady?: boolean;
  stale?: boolean;
  error?: string | null;
  onAction: (action: WiringReviewAction) => void | Promise<unknown>;
  onReview: (wireId: string, decision: WiringHumanDecision) => void | Promise<unknown>;
  onSelectComponent?: (componentId: string) => void;
  onRetest?: (componentId: string) => void;
  onInspectWire?: (wireId: string) => void;
}

type Translate = (zh: string, en: string) => string;
const roleLabel = (role: WiringPhotoRole, tr: Translate) => role === "pi_side_a" ? tr("Pi 第一側", "Pi first side")
  : role === "pi_side_b" ? tr("Pi 另一側", "Pi other side") : tr("零件接頭", "Module header");
const colorLabel = (color: string | null, tr: Translate) => {
  const names: Record<string, [string, string]> = { red: ["紅色", "red"], orange: ["橘色", "orange"], yellow: ["黃色", "yellow"],
    green: ["綠色", "green"], blue: ["藍色", "blue"], purple: ["紫色", "purple"], black: ["黑色", "black"], white: ["白色", "white"],
    brown: ["棕色", "brown"], gray: ["灰色", "gray"], grey: ["灰色", "gray"], pink: ["粉紅色", "pink"], teal: ["藍綠色", "teal"],
    unknown: ["線色不明", "unknown color"], none: ["未見線色", "no visible wire color"] };
  return color && names[color] ? tr(...names[color]) : color || tr("線色不明", "unknown color");
};

export function FramingGuide({ role }: { role: WiringPhotoRole }) {
  const tr = useMakerText();
  return <svg className="wr-framing" viewBox="0 0 220 106" role="img" aria-label={tr("取景示意：排針、接頭及露出的線一起入鏡，不代表實際腳號", "Framing example: include header, connectors and wire exits; this is not a pin map")}>
    <rect x="18" y="71" width="184" height="19" rx="4" fill="#527b68" />
    <rect x="43" y="61" width="132" height="12" fill="#35424b" />
    {[0, 1, 2, 3, 4, 5, 6, 7].map(n => <g key={n}>
      <path d={`M${51 + n * 16} 62v-12`} stroke="#8c9aa2" strokeWidth="3" />
      {n < 5 ? <><rect x={47 + n * 16} y="32" width="10" height="25" rx="2" fill="#263444" />
        <path d={`M${52 + n * 16} 32v-18`} stroke={["#d56b62", "#dcb64c", "#739ab6", "#82976c", "#9b7ea6"][n]} strokeWidth="5" /></> : null}
    </g>)}
    <rect x="35" y="8" width="147" height="74" rx="8" fill="none" stroke="#407a9c" strokeWidth="2" strokeDasharray="5 4" />
    {role === "component_header" ? <text x="110" y="101" textAnchor="middle" fontSize="10" fill="currentColor">{tr("保留 pin 文字", "Keep pin labels visible")}</text>
      : <text x="110" y="101" textAnchor="middle" fontSize="10" fill="currentColor">{tr("保留板緣與插接底部", "Keep board edge and insertion points")}</text>}
  </svg>;
}

function CropDialog({ slot, initialCrop, disabled, onClose, onSave }: {
  slot: WiringPhotoSlot; initialCrop?: WiringCrop | null; disabled: boolean;
  onClose: () => void; onSave: (crop: WiringCrop | null) => Promise<void>;
}) {
  const tr = useMakerText();
  const dialog = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const image = useRef<HTMLImageElement>(null);
  const drag = useRef<[number, number] | null>(null);
  const [crop, setCrop] = useState<WiringCrop | null>(validWiringCrop(initialCrop) ? initialCrop : slot.crop);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current;
    const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (element && !element.open) element.showModal();
    return () => { element?.close(); if (active?.isConnected) active.focus(); };
  }, []);
  const input = crop ?? [0, 0, 1, 1];
  const point = (event: PointerEvent<HTMLDivElement>, clamp = false) => image.current
    ? imagePointFromClient(event.clientX, event.clientY, image.current.getBoundingClientRect(), slot.size, clamp) : null;
  function begin(event: PointerEvent<HTMLDivElement>) {
    if (disabled || saving || failed || !loaded || event.button !== 0) return;
    const start = point(event);
    if (!start) return;
    drag.current = start;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const end = point(event, true);
    if (!drag.current || !end) return;
    setCrop(cropFromPoints(drag.current, end));
  }
  function end(event: PointerEvent<HTMLDivElement>) {
    if (drag.current) move(event);
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  async function save(value: WiringCrop | null) {
    setError(""); setSaving(true);
    try { await onSave(value); } catch (cause) { setError(cause instanceof Error ? cause.message : tr("儲存失敗，請再試一次。", "Save failed. Try again.")); }
    finally { setSaving(false); }
  }
  // The SVG uses the same aspect ratio and contain behavior as the original image.
  return <dialog ref={dialog} className="wr-dialog" aria-labelledby={headingId} onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="wr-dialog-heading"><h3 id={headingId}>{roleLabel(slot.role, tr)} · {tr("查看原圖與框選", "Original photo and crop")}</h3>
      <button type="button" autoFocus disabled={saving} onClick={onClose}>{tr("關閉", "Close")}</button></div>
    <p>{tr("框入排針、插接底部、完整接頭與露出的線色。框選只指定分析區域，不代表腳號已確認。", "Include the header, insertion points, connectors and visible wire colors. A crop selects an area; it does not confirm pin identity.")}</p>
    <div className="wr-crop-stage" onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={() => { drag.current = null; }}>
      {!failed ? <><img ref={image} src={slot.image_url} draggable={false} alt={tr("供框選的原始接線照片", "Original wiring photo for cropping")}
        onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
        <svg className="wr-crop-overlay" viewBox={`0 0 ${slot.size[0]} ${slot.size[1]}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
          {crop ? <rect x={crop[0] * slot.size[0]} y={crop[1] * slot.size[1]} width={(crop[2] - crop[0]) * slot.size[0]} height={(crop[3] - crop[1]) * slot.size[1]}
            fill="#2cb5dc22" stroke="#00d2ff" strokeWidth="3" vectorEffect="non-scaling-stroke" /> : null}
        </svg></> : <p role="alert">{tr("原圖無法取得，請關閉後重拍此視角。", "Original photo unavailable. Close this view and retake the photo.")}</p>}
    </div>
    <fieldset className="wr-crop-inputs" disabled={disabled || saving || failed}>
      <legend>{tr("拖曳框選，或輸入邊界百分比", "Drag a crop, or enter boundary percentages")}</legend>
      {([tr("左", "Left"), tr("上", "Top"), tr("右", "Right"), tr("下", "Bottom")] as string[]).map((label, index) => <label key={index}>{label}
        <input type="number" min={0} max={100} step={0.1} value={Math.round(input[index] * 1000) / 10} onChange={event => {
          if (event.target.value === "") return;
          const next = [...input] as WiringCrop;
          next[index] = Math.max(0, Math.min(1, Number(event.target.value) / 100));
          if (validWiringCrop(next)) setCrop(next);
        }} /></label>)}
    </fieldset>
    {error ? <p role="alert">{error}</p> : null}
    <div className="wr-actions"><button type="button" disabled={disabled || saving || failed} onClick={() => void save(null)}>{tr("使用完整原圖", "Use full original")}</button>
      {validWiringCrop(slot.suggested_crop) ? <button type="button" disabled={disabled || saving || failed} onClick={() => setCrop(slot.suggested_crop!)}>{tr("預覽建議範圍", "Preview suggested crop")}</button> : null}
      <button type="button" disabled={disabled || saving || failed || !validWiringCrop(crop)} onClick={() => void save(crop)}>{saving ? tr("儲存中…", "Saving…") : tr("儲存框選範圍", "Save crop")}</button></div>
    <small>{slot.size[0]} × {slot.size[1]} · {tr("保留原始照片，框選不會修改原圖。", "The original photo is preserved.")}</small>
  </dialog>;
}

function EndpointList({ candidates, slots, onPhoto }: { candidates: WiringEndpoint[]; slots: WiringReviewState["slots"]; onPhoto: (slot: WiringPhotoSlot, box?: WiringCrop | null) => void }) {
  const tr = useMakerText();
  if (!candidates.length) return <p className="wr-muted">{tr("尚無可用觀察，不能視為未接線。", "No usable observation; this does not mean unplugged.")}</p>;
  return <ul className="wr-candidates">{candidates.map((candidate, index) => {
    const slot = Object.values(slots).find(item => item?.capture_id === candidate.capture_id);
    return <li key={`${candidate.capture_id}:${candidate.id}:${index}`}><strong>{candidate.physical_pin !== null ? `${tr("實體 Pin", "Physical pin")} ${candidate.physical_pin}`
      : candidate.pin_label || `${tr("接頭", "Connector")} ${candidate.id}`}</strong> · {colorLabel(candidate.color, tr)}
      {candidate.physical_pin === null && !candidate.pin_label ? <small>{tr("腳號待確認", "Pin identity unconfirmed")}</small> : null}
      {candidate.color_visibility && candidate.color_visibility !== "clear" ? <small>{tr("線色部分遮擋或不可見", "Wire color partially hidden or not visible")}</small> : null}
      <p>{candidate.evidence}</p>
      {slot ? <button type="button" className="wr-photo-link" onClick={() => onPhoto(slot, candidate.box)}>{roleLabel(slot.role, tr)} · {tr("查看照片依據", "View photo evidence")}</button>
        : <small>{tr("此觀察的照片已不在本輪，請重新核對。", "This observation's photo is no longer in this round. Review it again.")}</small>}
    </li>;
  })}</ul>;
}

export function WiringReviewCard({ review, components, componentId, busy = false, captureReady = false, stale = false, error,
  onAction, onReview, onSelectComponent, onRetest, onInspectWire }: WiringReviewCardProps) {
  const tr = useMakerText();
  const [selectedId, setSelectedId] = useState(componentId ?? review?.component_id ?? components[0]?.id ?? "");
  const [opened, setOpened] = useState<{ slot: WiringPhotoSlot; crop?: WiringCrop | null; revision: number } | null>(null);
  const [pending, setPending] = useState(false);
  const [localError, setLocalError] = useState("");
  const [failedCaptures, setFailedCaptures] = useState<string[]>([]);
  const [wireChoice, setWireChoice] = useState<{ key: string; id: string } | null>(null);
  const lock = useRef(false);
  useEffect(() => { if (componentId) setSelectedId(componentId); }, [componentId]);
  const selected = components.some(component => component.id === selectedId) ? selectedId : components[0]?.id ?? "";
  const inactive = stale || review?.status === "stale";
  const waiting = busy || pending || review?.status === "analysing";
  const disabled = waiting || inactive;
  const sameComponent = Boolean(review && review.component_id === selected);
  const usable = sameComponent ? review : null;
  const humanOnly = Boolean(usable && (usable.status === "needs_human" || usable.no_progress_count >= 2));
  async function perform(work: () => void | Promise<unknown>) {
    if (lock.current || busy) return false;
    lock.current = true; setPending(true); setLocalError("");
    try { return await work(); } catch (cause) { setLocalError(cause instanceof Error ? cause.message : tr("操作失敗，請再試一次。", "Action failed. Try again.")); return false; }
    finally { lock.current = false; setPending(false); }
  }
  function act(action: Omit<WiringReviewAction, "review_id" | "revision">) {
    return perform(() => onAction(review ? boundWiringAction(review, action) : action));
  }
  const photo = (slot: WiringPhotoSlot, crop?: WiringCrop | null) => setOpened({ slot, crop, revision: review?.revision ?? 0 });
  const canReview = Boolean(usable && ["ready", "needs_human"].includes(usable.status) && !disabled);
  const allConfirmed = Boolean(canReview && usable?.results.length && usable.results.every(row => usable.reviews[row.wire_id]?.decision === "confirmed"
    && !usable.reviews[row.wire_id]?.evidence_stale));
  const resultKey = usable ? `${usable.id}:${usable.round}:${usable.component_id}:${usable.analysis_revision ?? ''}` : '';
  const currentRow = usable?.results.find(row => wireChoice?.key === resultKey && row.wire_id === wireChoice.id)
    ?? usable?.results.find(row => usable.reviews[row.wire_id]?.decision !== 'confirmed' || usable.reviews[row.wire_id]?.evidence_stale)
    ?? usable?.results[0];
  const rowIndex = usable?.results.findIndex(row => row.wire_id === currentRow?.wire_id) ?? -1;
  const collectingPhotos = Boolean(usable && (!usable.results.length || ['collecting', 'analysing', 'error'].includes(usable.status)));
  const statusLabel = review?.status === "analysing" ? tr("正在分析照片", "Analysing photos")
    : inactive ? tr("本輪已過期", "This round is stale") : review?.status === "needs_human" ? tr("需要人工沿線核對", "Human wire tracing needed")
    : usable?.results.length ? tr("請逐線核對", "Review each wire") : tr("收集接線照片", "Collect wiring photos");
  const componentPicker = <label className="wr-component">{tr("檢查零件", "Module to inspect")}<select value={selected} disabled={waiting || !components.length} onChange={event => {
    setSelectedId(event.target.value); onSelectComponent?.(event.target.value); setOpened(null);
  }}>{components.map(component => <option key={component.id} value={component.id}>{component.label}</option>)}</select></label>;
  return <section className="wiring-review-card" data-dialogue={collectingPhotos && !inactive} aria-label={tr("接線照片輔助核對", "Guided wiring photo review")} aria-busy={waiting}>
    {!collectingPhotos || inactive ? <><header className="wr-heading"><div><strong>{tr("接線照片輔助核對", "Guided wiring photo review")}</strong><p>{tr("AI 整理照片依據，由你親自確認接線。", "AI organises photo evidence; you confirm the actual wiring.")}</p></div>
      {usable ? <span className="wr-round">{tr("第", "Round")} {usable.round} {tr("輪", "")}</span> : null}</header>
      {componentPicker}<p className="wr-status" role="status">{statusLabel}</p></> : <details className="wr-dialogue-context">
      <summary>{components.find(component => component.id === selected)?.label} · {tr("第", "Round")} {usable?.round} {tr("輪", "")}</summary>{componentPicker}
      <small>{tr("同一輪保持接線不變，選用照片不代表確認接線。", "Keep this round’s wiring unchanged. Selecting photos does not confirm wiring.")}</small>
    </details>}
    {error || localError || usable?.error ? <p className="wr-error" role="alert">{error || localError || usable?.error}</p> : null}
    {!usable || inactive ? <div className="wr-actions"><button type="button" disabled={waiting || !selected} onClick={() => void act({ op: "start", component_id: selected })}>
      {inactive ? tr("重新開始本輪核對", "Start a fresh review") : tr("開始接線照片核對", "Start photo review")}</button></div> : <>
      {collectingPhotos ? <WiringPhotoSequence key={`${usable.id}:${usable.round}:${usable.component_id}`} review={usable} disabled={disabled} waiting={waiting}
          captureReady={captureReady} humanOnly={humanOnly} failedCaptures={failedCaptures}
          onAccept={(usable.photo_flow_version ?? 1) >= 2 ? (role, slot) => act({ op: 'accept_photo', role, capture_id: slot.capture_id, sha256: slot.sha256 }) : undefined}
          onCapture={role => void act({ op: 'capture', role })} onAnalyse={() => void act({ op: 'analyse' })} onPhoto={slot => photo(slot)}
          onImageError={id => setFailedCaptures(previous => previous.includes(id) ? previous : [...previous, id])} framing={role => <FramingGuide role={role} />} />
       : <details className="wr-photo-archive"><summary>{tr("查看三張照片／補拍", "View three photos / retake")}</summary>
      <div className="wr-photo-slots">{wiringPhotoRoles.map(role => {
        const slot = usable.slots[role];
        const unavailable = slot?.available === false || Boolean(slot && failedCaptures.includes(slot.capture_id));
        return <article className="wr-slot" key={role}><h4>{roleLabel(role, tr)}</h4>
          {slot && !unavailable ? <button className="wr-thumbnail" type="button" onClick={() => photo(slot)} aria-label={tr(`查看${roleLabel(role, tr)}原圖與框選`, `View ${roleLabel(role, tr)} original and crop`)}>
            <img src={slot.image_url} alt={roleLabel(role, tr)} loading="lazy" onError={() => setFailedCaptures(previous => [...previous, slot.capture_id])} />
            {slot.crop ? <svg viewBox={`0 0 ${slot.size[0]} ${slot.size[1]}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true"><rect x={slot.crop[0] * slot.size[0]} y={slot.crop[1] * slot.size[1]}
              width={(slot.crop[2] - slot.crop[0]) * slot.size[0]} height={(slot.crop[3] - slot.crop[1]) * slot.size[1]} fill="#2cb5dc22" stroke="#00d2ff" strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg> : null}
          </button> : <FramingGuide role={role} />}
          <p>{role === "component_header" ? tr("pin 文字、接頭與線色一起入鏡。", "Include pin labels, connectors and wire colors.")
            : role === "pi_side_b" ? tr("從另一側露出被遮住的插接底部。", "Reveal hidden insertion points from the other side.")
            : tr("保留板子方向、排針與接頭底部。", "Include board orientation, header and connector bases.")}</p>
          {unavailable ? <small role="alert">{tr("照片無法取得，請重拍。", "Photo unavailable. Please retake it.")}</small> : null}
          {slot ? <small>{slot.crop ? tr("已選局部範圍，原圖仍保留", "Crop selected; original retained") : tr("使用全景，可手動框選接線區", "Full view; optionally select the wiring area")}</small> : null}
          <div className="wr-actions"><button type="button" disabled={disabled || humanOnly || !captureReady} onClick={() => void act({ op: "capture", role })}>{slot ? tr("重拍此視角", "Retake this view") : tr("拍攝此視角", "Capture this view")}</button>
            {slot && !unavailable ? <button type="button" disabled={waiting} onClick={() => photo(slot)}>{tr("查看／框選", "View / crop")}</button> : null}</div>
        </article>;
      })}</div>
      </details>}
      <details className="wr-wiring-changes"><summary>{tr("我已改動接線，重新核對", "I changed the wiring; review again")}</summary>
      <div className="wr-actions">
        <button type="button" disabled={disabled} onClick={() => void act({ op: "changed", component_id: usable.component_id })}>{tr("我已改動此零件接線，建立新一輪", "I changed this module's wiring — new round")}</button>
        <button type="button" disabled={disabled} onClick={() => void act({ op: "changed" })}>{tr("改動範圍不確定，全部重新核對", "Change scope unclear — review all wiring")}</button></div></details>
      {usable.no_progress_count >= 2 || usable.status === "needs_human" ? <p className="wr-note">{tr("補查仍沒有足夠的新證據。請沿著同一條線親自核對兩端，必要時貼上相同編號。", "Follow the same wire and inspect both ends yourself. Further photo checks have not added enough evidence; matching labels can help.")}</p> : null}
      {!collectingPhotos && usable.results.length ? <div className="wr-results">
        <div className="wr-step-heading"><strong>{allConfirmed ? tr('本零件接線已由你核對', 'You reviewed this module’s wiring') : tr('接著，一次核對一條線', 'Next, review one wire at a time')}</strong>
          <small>{rowIndex + 1} / {usable.results.length}</small></div>
        <div className="wr-wire-progress" role="group" aria-label={tr('選擇核對的線路', 'Choose a wire to review')}>{usable.results.map(row =>
          <button type="button" key={row.wire_id} disabled={waiting} aria-current={row === currentRow ? 'step' : undefined}
            data-confirmed={usable.reviews[row.wire_id]?.decision === 'confirmed' && !usable.reviews[row.wire_id]?.evidence_stale}
            onClick={() => setWireChoice({ key: resultKey, id: row.wire_id })}>{row.expected.component_pin}</button>)}</div>
        {usable.results.filter(row => row === currentRow).map(row => {
        const humanReview = usable.reviews[row.wire_id];
        const decision = humanReview?.decision;
        const comparison = row.comparison === "similar" ? tr("線色相符", "Similar colors") : row.comparison === "different" ? tr("線色不同", "Different colors")
          : row.comparison === "ambiguous" ? tr("多個候選", "Multiple candidates") : tr("資訊不足", "Insufficient evidence");
        return <article className="wr-wire" key={row.wire_id}><header><h4>{row.expected.component_pin}</h4><span className={`wr-comparison wr-${row.comparison}`}>{comparison}</span></header>
          <div className="wr-expected"><strong>{tr("預期接法", "Expected connection")}</strong><p>{row.expected.physical_pin !== null ? `${tr("Pi 實體 Pin", "Pi physical pin")} ${row.expected.physical_pin}` : row.expected.board_pin || tr("Pi 腳位待確認", "Pi pin unconfirmed")}
            {row.expected.bcm !== null ? ` · BCM ${row.expected.bcm}` : ""} → {row.expected.component_pin}</p></div>
          <div className="wr-observations"><div><h5>{tr("Pi 端照片觀察", "Pi photo observations")}</h5><EndpointList candidates={row.pi_candidates} slots={usable.slots} onPhoto={photo} /></div>
            <div><h5>{tr("零件端照片觀察", "Module photo observations")}</h5><EndpointList candidates={row.component_candidates} slots={usable.slots} onPhoto={photo} /></div></div>
          {row.evidence ? <p>{row.evidence}</p> : null}
          {row.comparison === "similar" ? <small>{tr("線色相符只提供線索，請確認兩端是否為同一條線。", "Matching colors are a clue. Check that both ends belong to the same wire.")}</small> : null}
          {row.expected.connection_kind && row.expected.connection_kind !== "direct" ? <small>{tr("此接法含中間連接，兩端線色可能不同。", "This connection has an intermediate link; end colors may differ.")}</small> : null}
          <p className="wr-next"><strong>{tr("下一步：", "Next: ")}</strong>{row.next_step}</p>
          {onInspectWire ? <button type="button" onClick={() => onInspectWire(row.wire_id)}>{tr("查看預期腳位圖", "View expected pin diagram")}</button> : null}
          <fieldset className="wr-human" disabled={!canReview}><legend>{tr("你的實際核對", "Your physical check")}</legend>
            <p>{humanReview?.evidence_stale ? tr("保留先前的人工決定；照片已更新，請對照新證據再確認。", "Your earlier decision is retained; photos changed. Review the new evidence and confirm again.")
              : decision === "confirmed" ? tr("你已親自確認接對", "You confirmed the wiring") : decision === "needs_change" ? tr("你指出需要修正", "You reported a needed change") : tr("尚未確認接對", "Not yet confirmed")}</p>
            <div className="wr-actions"><button type="button" aria-pressed={decision === "confirmed" && !humanReview?.evidence_stale} onClick={() => void perform(() => onReview(row.wire_id, "confirmed"))}>{tr("我已親自確認接對", "I checked: connected correctly")}</button>
              <button type="button" aria-pressed={decision === "needs_change"} onClick={() => void perform(() => onReview(row.wire_id, "needs_change"))}>{tr("我發現接錯，準備修正", "I found an error; prepare a fix")}</button>
              <button type="button" aria-pressed={decision === "unsure"} onClick={() => void perform(() => onReview(row.wire_id, "unsure"))}>{tr("仍無法確定", "Still unsure")}</button></div>
          </fieldset>
        </article>;
      })}<div className="wr-wire-navigation">
        <button type="button" disabled={waiting || rowIndex <= 0} onClick={() => setWireChoice({ key: resultKey, id: usable.results[rowIndex - 1].wire_id })}>{tr('上一條', 'Previous wire')}</button>
        <button type="button" disabled={waiting || rowIndex >= usable.results.length - 1} onClick={() => setWireChoice({ key: resultKey, id: usable.results[rowIndex + 1].wire_id })}>{tr('下一條', 'Next wire')}</button>
      </div></div> : null}
      {usable.observations.length ? <details className="wr-inventory"><summary>{tr("查看全部接頭候選（含腳號未知）", "All connector candidates, including unknown pins")}</summary>
        <EndpointList candidates={usable.observations} slots={usable.slots} onPhoto={photo} /></details> : null}
      {allConfirmed ? <div className="wr-retest"><p>{tr("你已確認本零件的接線；功能測試結果另行記錄。", "You confirmed this module's wiring. Functional test results are recorded separately.")}</p>
        {onRetest ? <button type="button" disabled={disabled} onClick={() => onRetest(usable.component_id)}>{tr("重新測試這個零件", "Retest this module")}</button> : null}</div> : null}
    </>}
    {opened && review && opened.revision === review.revision && Object.values(review.slots).some(slot => slot?.capture_id === opened.slot.capture_id) ? <CropDialog
      key={`${opened.slot.capture_id}:${opened.revision}`} slot={opened.slot} initialCrop={opened.crop} disabled={disabled || humanOnly} onClose={() => setOpened(null)} onSave={async crop => {
        const result = await onAction(boundWiringAction(review, { op: "crop", role: opened.slot.role, crop }));
        if (result === null || result === false) throw new Error(tr("框選未儲存，請關閉並查看操作訊息後重試。", "Crop was not saved. Close this view, check the action message and try again."));
        setOpened(null);
      }} /> : null}
  </section>;
}
