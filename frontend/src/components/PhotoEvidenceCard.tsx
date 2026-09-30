import { useState } from "react";
import type { DebugEvidence } from "../lib/debugSessions";
import { debugEvidenceUrl } from "../lib/debugEvidence";
import { useMakerText } from "../lib/useMaker";

export function PhotoEvidenceCard({ evidence, sessionId }: { evidence?: DebugEvidence; sessionId?: string }) {
  const tr = useMakerText();
  const [selected, setSelected] = useState<string | null>(null);
  const [failedViews, setFailedViews] = useState<string[]>([]);
  if (!evidence || !sessionId || evidence.available === false) return <small className="ai-evidence-expired">{tr("此輪照片已過期", "This turn's photo has expired")}</small>;
  const views = evidence.views?.length ? evidence.views : [{ name: "overview" }];
  const view = views.find(item => item.name === selected) ?? views[0];
  const names: Record<string, string> = {
    overview: tr("全景", "Overview"), pi_overview: tr("原始全景", "Original overview"),
    component_overview: tr("零件全景", "Module overview"), pi_pins: tr("Pi Pin 特寫", "Pi pin close-up"),
    component_pins: tr("零件 Pin 特寫", "Module pin close-up"), pi_reading: tr("Pi 旋正放大", "Pi reading view"),
    component_reading: tr("零件旋正放大", "Module reading view"), pi_contact: tr("Pi 接合處", "Pi contact"),
    component_contact: tr("零件接合處", "Module contact"),
  };
  const unavailable = view.available === false || failedViews.includes(view.name);
  const url = debugEvidenceUrl(sessionId, evidence.id, view.name);
  const capturedAt = new Date(typeof evidence.captured_at === "number" && evidence.captured_at < 1e12 ? evidence.captured_at * 1000 : evidence.captured_at).toLocaleTimeString(tr("zh-TW", "en"));
  return <div className="ai-photo-card">
    <div className="ai-evidence-heading"><strong>{tr("本次實拍", "Captured photo")}</strong><time>{capturedAt}</time></div>
    {views.length > 1 ? <div className="ai-evidence-tabs" role="group" aria-label={tr("切換照片視角", "Select photo view")}>{views.map(item => <button type="button" key={item.name} aria-pressed={item.name === view.name} onClick={() => setSelected(item.name)}>{names[item.name] ?? item.name}</button>)}</div> : null}
    {unavailable ? <p className="ai-evidence-expired">{tr("此張照片已無法取得；其他視角與對話紀錄仍可查看。", "This image is unavailable. Other views and the conversation remain readable.")}</p>
      : <a href={url} target="_blank" rel="noreferrer" title={tr("開啟原圖", "Open original image")}><img src={url} loading="lazy" alt={`${tr("AI 本次查看的鏡頭照片", "Camera image reviewed for this reply")} · ${names[view.name] ?? view.name}`} onError={() => setFailedViews(old => old.includes(view.name) ? old : [...old, view.name])} /></a>}
    <small>{names[view.name] ?? view.name} · frame {view.frame_id ?? evidence.frame_id}{view.source_view ? ` · ${tr("同張照片的閱讀圖", "Reading view of the same photo")}` : ""}</small>
    {evidence.same_frame === false ? <small>{tr("兩端來源影格不同", "Endpoints use different source frames")} · {evidence.capture_skew_ms ?? "—"} ms</small> : null}
    {evidence.mode === "overview" && !views.some(item => item.name.includes("pins")) ? <small>{tr("本次為全景，尚無 Pin 特寫。", "Overview only; no pin close-up in this capture.")}</small> : null}
  </div>;
}
