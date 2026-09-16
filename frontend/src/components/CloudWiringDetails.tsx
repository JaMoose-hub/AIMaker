import { cloudContactLabel, cloudEndpointFinding, cloudEvidenceText, cloudPathLabel, cloudPinContactLabel, cloudTargetColorLabel, cloudWireColorLabel, cloudWiringCopy, type CloudCheckViewState } from "../lib/cloudWiring";
import { useMakerText } from "../lib/useMaker";

interface Props extends CloudCheckViewState {
  variant?: "card" | "guide";
  captureHint?: string;
  target?: { componentId: string; componentPin: string; boardLabel: string };
  onCheck?: () => void;
  checkDisabled?: boolean;
  checkHint?: string;
}

export function CloudWiringDetails({ job, error, stale, busy, readAgain, target, onCheck, checkDisabled, checkHint, variant = "card", captureHint }: Props) {
  const tr = useMakerText();
  const locale = tr("zh-TW", "en");
  const copy = cloudWiringCopy({ job, error, stale, busy, readAgain }, locale);
  const result = busy || error || job?.status === "failed" ? null : job?.result;
  const earlier = stale || job?.stale;
  const inline = variant === "guide";
  const idle = !job && !error && !busy;
  const text = (value: string) => cloudEvidenceText(value, locale);
  const names: Record<string, string> = { pi_overview: tr("原始全景", "Original overview"), pi_pins: tr("Pi 排針特寫", "Pi header close-up"),
    component_overview: tr("零件原始全景", "Module overview"), component_pins: tr("零件腳位特寫", "Module pin close-up"),
    pi_reading: tr("Pi 特寫旋正放大（同張照片）", "Pi rotated/enlarged (same photo)"),
    component_reading: tr("零件特寫旋正放大（同張照片）", "Module rotated/enlarged (same photo)"),
    pi_contact: tr("Pi 接合處裁切（同張照片）", "Pi contact crop (same photo)"),
    component_contact: tr("零件接合處裁切（同張照片）", "Module contact crop (same photo)") };
  const colors = result?.wire_colors;
  return <section className={`cloud-wiring-details cloud-result-card tone-${copy.tone}${inline ? " cloud-result-inline" : ""}`} aria-label={tr("雲端接線照片檢查", "Cloud wiring photo check")}>
    <header className="cloud-result-header">
      <span className="cloud-result-symbol" aria-hidden="true">{copy.symbol}</span>
      <div><span className="cloud-result-eyebrow">{tr("AI 接線檢查", "AI WIRING CHECK")}</span>
        <h3 role="status">{inline && idle ? tr("尚未檢查", "Not checked yet") : copy.title}</h3></div>
    </header>
    {target ? <div className="cloud-result-target"><span>{tr("本步目標", "Target connection")}</span>
      <strong>{target.componentId.toUpperCase()} · {target.componentPin}</strong><span aria-hidden="true">→</span><strong>Pi · {target.boardLabel}</strong>
    </div> : null}
    {result ? <div className="cloud-result-observation">
      <h4>{earlier ? tr("先前照片看到的內容", "What the earlier photo showed") : tr("看到什麼", "What the photo shows")}</h4>
      <dl className="cloud-result-findings">
        <div><dt>{tr("Pi 端", "Pi end")}</dt><dd>{cloudEndpointFinding(result.board_endpoint, colors?.board, result.visual_observations?.board, locale)}</dd></div>
        <div><dt>{tr("零件端", "Module end")}</dt><dd>{cloudEndpointFinding(result.component_endpoint, colors?.component, result.visual_observations?.component, locale)}</dd></div>
        <div><dt>{tr("線路", "Wire route")}</dt><dd>{cloudPathLabel(result, locale)}</dd></div>
      </dl>
      {result.consistency_issues?.length ? <p>{tr("AI 的接頭觀察與腳位結論不一致；有衝突的端點保留待確認。", "AI connector observations conflict with the pin conclusion; affected ends remain unconfirmed.")}</p> : null}
    </div> : null}
    <div className="cloud-result-next">{!inline ? <h4>{tr("下一步", "Next step")}</h4> : null}<p>{copy.next}</p></div>
    {inline && (error || job?.error) ? <p className="cloud-inline-error" role="alert">{error ?? job?.error}</p> : null}
    {onCheck ? <div className="cloud-result-actions"><button type="button" className="cloud-wiring-button" title={checkHint}
      disabled={busy || checkDisabled} onClick={onCheck}>{busy ? tr("檢查中…", "Checking…") : readAgain ? tr("再讀結果", "Read result")
        : job || error ? tr("重新檢查", "Check again") : tr("AI 檢查本步", "AI check step")}</button></div> : null}
    {captureHint ? <small className="cloud-capture-hint">{captureHint}</small> : null}
    {job?.images.length ? <details className="cloud-result-disclosure cloud-result-photos"><summary>{tr("查看檢查照片", "View inspection photos")} <span>({job.images.length})</span></summary>
      <div className="cloud-wiring-images">{job.images.map(view => <a key={view.name} href={view.url} target="_blank" rel="noreferrer">
        <img src={view.url} alt={names[view.name] ?? view.name} loading="lazy" /><span>{names[view.name] ?? view.name} ↗</span>
      </a>)}</div>
    </details> : null}
    {result || error || job?.error || job?.capture ? <details className="cloud-result-disclosure"><summary>{tr("詳細判讀與模型資訊", "Evidence and model details")}</summary>
      <div className="cloud-result-evidence">
        {!inline && (error || job?.error) ? <p className="cloud-result-error" role="alert">{error ?? job?.error}</p> : null}
        {result ? <section><h4>{tr("AI 補充說明", "AI explanation")}</h4><p>{text(result.summary)}</p></section> : null}
        {colors ? <section className="cloud-result-colors" aria-label={tr("雲端線色判讀", "Cloud wire colors")}>
          <h4>{tr("兩端線色", "Wire colors")}</h4>
          <dl className="cloud-color-pair"><div><dt>{tr("Pi 端", "Pi end")}</dt><dd>{result ? cloudTargetColorLabel(result.board_endpoint, colors.board, result.visual_observations?.board, locale) : null}</dd></div>
            <div><dt>{tr("零件端", "Module end")}</dt><dd>{result ? cloudTargetColorLabel(result.component_endpoint, colors.component, result.visual_observations?.component, locale) : null}</dd></div></dl>
          <p className="cloud-color-comparison">{colors.comparison === "similar" ? tr("顏色相近（不代表同一條線）", "Similar colors (not proof of the same wire)")
            : colors.comparison === "different" ? tr("顏色不同", "Different colors") : tr("色差待確認", "Color comparison uncertain")}</p>
          <p>{text(colors.evidence)}</p>
        </section> : null}
        {result?.visual_observations ? (["board", "component"] as const).map(side => {
          const observation = result.visual_observations![side];
          return <section key={side} className="cloud-connector-observations">
            <h4>{side === "board" ? tr("Pi 端接頭觀察", "Pi connector observations") : tr("零件端接頭觀察", "Module connector observations")}</h4>
            {result.pin_contacts?.[side]?.length ? <dl className="cloud-result-findings cloud-pin-inventory">
              {result.pin_contacts[side]!.map((pin, index) => <div key={index} title={pin.position}>
                <dt>{pin.pin_id ?? tr(`位置 ${index + 1}`, `Position ${index + 1}`)}</dt>
                <dd>{cloudPinContactLabel(pin.appearance, locale)}</dd>
              </div>)}
            </dl> : null}
            {observation.connectors.map((connector, index) => <div key={`${connector.id}-${index}`}>
              <strong>{cloudWireColorLabel(connector.wire_color, locale)} · {cloudContactLabel(connector.contact, locale)}</strong>
              <p>{text(connector.position)} — {text(connector.evidence)}</p>
              {connector.breadboard ? <p>{tr("麵包板孔位", "Breadboard holes")}: {connector.breadboard.pin_hole.column}{connector.breadboard.pin_hole.row}
                {" → "}{connector.breadboard.wire_hole.column}{connector.breadboard.wire_hole.row} · {text(connector.breadboard.evidence)}</p> : null}
            </div>)}
            <p>{text(observation.evidence)}</p>
          </section>;
        }) : null}
        {result ? <>
          <section><h4>{tr("Pi 端", "Pi end")}</h4><p>{text(result.board_endpoint.evidence)}</p>
            {colors ? <p className="cloud-color-note">{text(colors.board.evidence)}</p> : null}</section>
          <section><h4>{tr("零件端", "Module end")}</h4><p>{text(result.component_endpoint.evidence)}</p>
            {colors ? <p className="cloud-color-note">{text(colors.component.evidence)}</p> : null}</section>
          {result.wire_path ? <section><h4>{tr("線路追查", "Wire path")}</h4><p>{text(result.wire_path.evidence)}</p></section> : null}
          <section><h4>{tr("仍未確認", "What is not verified")}</h4><p>{text(result.limitations)}</p></section>
        </> : null}
        {job?.capture ? <dl className="cloud-result-meta"><div><dt>{tr("拍攝時間", "Captured")}</dt><dd>{new Date(job.capture.captured_at).toLocaleTimeString(locale)}</dd></div>
          <div><dt>{tr("模型", "Model")}</dt><dd>{job.model}</dd></div>
          {job.inspection ? <><div><dt>{tr("推理強度", "Reasoning effort")}</dt><dd>{job.inspection.effort}</dd></div>
            <div><dt>{tr("分段檢查", "Staged inspection")}</dt><dd>{job.inspection.stages.length} / {job.inspection.max_calls}</dd></div></> : null}
          <div><dt>{tr("取像方式", "Capture mode")}</dt><dd>{job.capture.mode === "overview" ? tr("原始全景", "Original overview")
            : job.capture.mode === "context_crops" ? tr("雲端圈選＋原圖裁切（非精準定位）", "Cloud regions + source crops (not precise pose)") : tr("全景與腳位特寫", "Overview and pin close-ups")}</dd></div>
          {!job.capture.same_frame ? <div><dt>{tr("原圖時間差", "Source frame gap")}</dt><dd>{job.capture.capture_skew_ms} ms</dd></div> : null}
        </dl> : null}
      </div>
    </details> : null}
    <small className="cloud-result-footnote">{inline ? tr("僅照片判讀，非導通測試。", "Photo review, not a continuity test.") : tr("僅檢查照片外觀，不代表導通或功能驗證。", "Photo inspection only — not continuity or functional verification.")}</small>
  </section>;
}
