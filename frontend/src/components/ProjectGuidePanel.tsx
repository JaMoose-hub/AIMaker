import { useEffect, useMemo } from "react";
import { guideFor, type ActiveGuideTarget } from "../lib/componentWiringGuides";
import { startProjectGuide, restartProjectGuide, confirmProjectWire, wireSignature, type ProjectDesign, type ProjectGuideState, type ProjectWire } from "../lib/maker";
import { useGuidedPose } from "../lib/useGuidedPose";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { CompactGuide } from "./CompactGuide";
import { cloudWiringRequest, type CloudAISelection } from "../lib/cloudWiring";
import { useCloudWiringCheck } from "../lib/useCloudWiringCheck";
import { CloudWiringDetails } from "./CloudWiringDetails";
import { PiRowLocator } from "./PiRowLocator";
import { ComponentRowLocator } from "./ComponentRowLocator";
import { componentHeaderGuideText, componentModelName } from "../lib/componentHeaderGuide";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import type { Pin } from "../lib/types";

interface Props {
  design: ProjectDesign; session: ProjectGuideState; visible: boolean; disabled: boolean;
  cloudAI: CloudAISelection;
  pinsById: ReadonlyMap<string, Pin>;
  onChange: (session: ProjectGuideState) => void;
  onTargetChange: (target: ActiveGuideTarget | null) => void;
  onVisibleChange: (visible: boolean) => void;
  onDeploy: () => void;
}
export function ProjectGuidePanel({ design, session, visible, disabled, cloudAI, pinsById, onChange, onTargetChange, onVisibleChange, onDeploy }: Props) {
  const tr = useMakerText();
  const { t, tx, locale } = useI18n();
  const cid = design.component_ids[session.componentIndex];
  const guide = guideFor(cid);
  const steps = design.wiring.filter(w => w.componentId === cid);
  const step = steps[session.index] ?? steps[0];
  const target = useMemo<ActiveGuideTarget | null>(() => session.mode !== "camera" ? null : ({
    componentId: cid, boardPinId: step.boardPin, componentPinId: step.componentPin,
    connectionKind: step.connectionKind, manualOnly: true,
  }), [cid, step.boardPin, step.componentPin, step.connectionKind, session.mode]);
  const pose = useGuidedPose(target);
  const active = session.phase === "active";
  const cloudReady = active && !disabled && cloudAI.available && !cloudAI.busy && cloudAI.supportsImages;
  const check = useCloudWiringCheck(cloudWiringRequest(design, step, cloudAI, locale), cloudReady,
    pose.strictReady, `${session.mode}:${session.phase}:${session.run ?? 0}`);
  const cloudHint = !cloudAI.available ? tr("請先在上方登入 ChatGPT", "Sign in to ChatGPT above")
    : !cloudAI.supportsImages ? tr("請在上方選擇支援圖片的模型", "Select an image-capable model above")
      : cloudAI.busy ? tr("雲端設計處理中，請稍後", "Cloud design is busy; try later")
        : !pose.strictReady ? tr("未定位也能檢查：雲端從全景尋找端點，再裁切特寫", "Check without tracking: cloud locates endpoints in the overview for close-ups")
          : tr("擷取原始照片與特寫送至雲端；不會自動確認接線", "Send original photos and crops to the cloud; does not confirm wiring automatically");
  useEffect(() => {
    onTargetChange(active ? target : null);
    return () => onTargetChange(null);
  }, [active, target, onTargetChange]);
  const confirmed = (wire: ProjectWire) => session.confirmed[wire.id]?.signature === wireSignature(wire);
  const count = design.wiring.filter(confirmed).length;
  const moduleCount = steps.filter(confirmed).length;
  function start() {
    onChange(startProjectGuide(session));
  }
  function confirm() {
    onChange(confirmProjectWire(design, session));
  }
  function previous() {
    const index = session.phase === "review" ? session.index : Math.max(0, session.index - 1);
    const next = { ...session.confirmed };
    const globalIndex = design.wiring.findIndex(w => w.id === steps[index].id);
    for (const w of design.wiring.slice(globalIndex)) delete next[w.id];
    onChange({ ...session, phase: "active", index, confirmed: next });
  }
  const [boardPhysical, ...boardSignals] = step.boardLabel.split(" · ");
  const boardPin = pinsById.get(step.boardPin);
  const piGuide = piHeaderGuideText(boardPin, t);
  const componentGuide = componentHeaderGuideText(cid, step.componentPin, t);
  return <CompactGuide contextKey={`${design.id}:${design.revision}:${cid}:${session.phase}:${session.index}:${session.run ?? 0}`} phase={session.phase}
    headerActions={<button type="button" className="guide-restart-action"
      title={tr("清除本輪接線紀錄，回到第一個零件的第一步；保留作品與程式", "Clear this wiring run and return to the first step; keep the project and code")}
      onClick={() => onChange(restartProjectGuide(session))}>
      <span aria-hidden="true">↻</span>{tr("重新開始", "Restart")}
    </button>}
    visible={visible} title={componentGuide?.name ?? tx(guide.name)} progress={<>
      <div className="guide-progress-label"><span>{tr("作品人工紀錄", "Project manual records")}</span><strong>{count}<span> / {design.wiring.length}</span></strong></div>
      <progress max={design.wiring.length} value={count} aria-label={tr("作品人工接線進度", "Project manual wiring progress")} />
      <div className="guide-module-track">{design.component_ids.map((id, i) => <span key={id} aria-current={i === session.componentIndex ? "step" : undefined}>
        <span className="guide-module-dot" aria-hidden="true">{i + 1}</span>{componentModelName(id, t) ?? id.toUpperCase()}
      </span>)}</div>
    </>}
    targetId={active ? `${cid}:${step.componentPin}` : undefined} onClose={() => onVisibleChange(false)}
    actions={<><div className="guide-navigation">{session.phase === "prepare" ? <button type="button" className="guide-primary-action" onClick={start}>{tr("開始接線 →", "Start wiring →")}</button>
      : active ? <>
        <button type="button" className="guide-back-action" disabled={session.index === 0} onClick={previous}>{tr("上一步", "Back")}</button>
        <button type="button" className="guide-primary-action" onClick={confirm}>{tr("我已接好，下一步 →", "Connected · Next →")}</button>
      </> : <>
        <button type="button" className="guide-back-action" onClick={previous}>{tr("回看", "Review")}</button>
        {session.componentIndex < design.component_ids.length - 1
          ? <button type="button" className="guide-primary-action" onClick={() => onChange({ ...session, componentIndex: session.componentIndex + 1, index: 0, phase: "prepare", checks: [] })}>{tr("下一模組 →", "Next module →")}</button>
          : <button type="button" className="guide-primary-action" onClick={onDeploy}>{tr("前往部署 →", "Deploy →")}</button>}
      </>}</div><small>{tr("進度由你確認，AI 不會自動跳步。", "You confirm progress; AI never advances steps.")}</small></>}
    details={<>
    {active ? <p>{tx(step.hint)}</p> : null}
    <div className="maker-module-progress">{design.component_ids.map((id, i) => <span key={id} className={i === session.componentIndex ? "active" : ""}>{i + 1}. {id} · {design.wiring.filter(w => w.componentId === id && confirmed(w)).length}/{design.wiring.filter(w => w.componentId === id).length}</span>)}</div>
    {session.mode !== "camera" ? <button onClick={() => onChange({ ...session, mode: "camera" })}>{tr("返回鏡頭 Pin 引導", "Return to camera Pin guide")}</button> : null}
    <p className="wiring-safety">{tx(guide.safety)}</p>
    {session.restored ? <small className="maker-warning">{tr("含先前保存的人工紀錄；不是目前接線證據。", "Includes saved manual records, not evidence of current wiring.")}</small> : null}
    {active ? <button type="button" onClick={() => onChange({ ...session, phase: "review" })}>{tr("暫停並看總覽", "Pause & review")}</button> : null}
    {!pose.strictReady ? <p className="wiring-status" role="status">{tr("未定位不影響手動步驟；AI 檢查會使用相機全景。", "You can continue manually without tracking; AI checks use the camera overview.")}</p> : null}
    <p className="wiring-status">{tr("人工確認不代表導通、電壓或硬體功能通過。", "Manual confirmation does not verify continuity, voltage or functionality.")}</p>
    <details className="wiring-summary" open={session.phase === "review" ? true : undefined}><summary>{tr("接線總覽", "Wiring summary")} · {count}/{design.wiring.length}</summary>
      <table><tbody>{design.wiring.map(w => <tr key={w.id}><td>{w.componentId} · {w.componentPin}</td><td>{w.boardLabel}</td><td>{confirmed(w) ? `${tr("人工確認", "Manual")} (${session.confirmed[w.id].mode})` : tr("未確認", "Not confirmed")}</td></tr>)}</tbody></table></details>
    </>}>
    {session.phase === "prepare" ? <div className="guide-prepare-message">
      <strong>{tr("準備開始接線", "Ready to start wiring")}</strong>
      <p>{tr("按下方「開始接線」，再跟著腳位指引操作。", "Press Start wiring below to see the pin instructions.")}</p>
    </div> : null}
    {active ? <>
      <section className={`guide-connection-card ${step.connectionKind}`} aria-label={tr("本步接線", "Current connection")}>
        <div className="guide-step-label"><span>{tr("這一步", "THIS STEP")}</span><strong>{session.index + 1}<span> / {steps.length}</span></strong></div>
        <div className="guide-pin-pair">
          <div><span>{componentGuide?.name ?? cid.toUpperCase()}</span><strong>{step.componentPin}</strong>
            <small>{componentGuide ? t("componentGuide.ordinal", { number: componentGuide.number }) : tr("零件端", "Module pin")}</small></div>
          <span className="guide-pin-link" aria-hidden="true">{step.connectionKind === "divider" ? "⇢" : "→"}</span>
          <div><span>Raspberry Pi 5</span><strong>{piGuide?.ordinalLabel ?? boardPhysical}</strong>
            {piGuide ? <span className="guide-pi-row-label">{piGuide.rowLabel}</span> : null}
            <small>{piGuide?.reference ?? (boardSignals.join(" · ") || tr("實體腳位", "Physical pin"))}</small></div>
        </div>
        {piGuide ? <PiRowLocator pin={boardPin} /> : <p className="guide-step-instruction">{tx(step.instruction)}</p>}
        <ComponentRowLocator componentId={cid} pinId={step.componentPin} />
      </section>
      {step.connectionKind === "divider" ? <div className="guide-caution"><strong>{tr("ECHO 需分壓，不可直連 GPIO", "ECHO needs a divider, not a direct GPIO wire")}</strong>
        <div className="wiring-divider"><code>ECHO ─ 330Ω ─ ● ─ GPIO18</code><code>● ─ 470Ω ─ GND</code></div></div> : null}
    </> : session.phase === "review" ? <section className="guide-module-review"><span>{tr("本模組人工紀錄", "MODULE MANUAL RECORDS")}</span>
      <strong>{moduleCount} / {steps.length}</strong><p>{tx(guide.functionalTest)}</p></section> : null}
    {guide.unresolved.length ? <p className="guide-caution">{tr("此模組規格待確認，勿上電。", "Module specifications are unconfirmed. Do not power on.")}</p> : null}
    {active ? <CloudWiringDetails variant="guide" job={check.job} error={check.error} stale={check.stale} busy={check.busy} readAgain={check.readAgain}
      onCheck={() => void check.start()} checkDisabled={!check.readAgain && !cloudReady} checkHint={cloudHint}
      captureHint={!cloudReady ? cloudHint : !pose.strictReady ? tr("未定位時從全景尋找端點、準備特寫", "Locates endpoint close-ups from the overview when tracking is unavailable") : undefined} /> : null}
  </CompactGuide>;
}
