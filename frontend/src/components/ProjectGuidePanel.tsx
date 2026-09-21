import { useEffect, useMemo } from "react";
import { guideFor, type ActiveGuideTarget } from "../lib/componentWiringGuides";
import { startProjectGuide, restartProjectGuide, confirmProjectWire, wireSignature, type ProjectDesign, type ProjectGuideState, type ProjectWire } from "../lib/maker";
import { useMakerText } from "../lib/useMaker";
import { useI18n } from "../lib/i18n";
import { CompactGuide } from "./CompactGuide";
import { useComponentTests } from "../lib/useComponentTests";
import { componentComplete, componentTestKey, selectTestModule } from "../lib/componentTests";
import { ComponentTestCard } from "./ComponentTestCard";
import { PiRowLocator } from "./PiRowLocator";
import { ComponentRowLocator } from "./ComponentRowLocator";
import { componentHeaderGuideText, componentModelName } from "../lib/componentHeaderGuide";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import type { Pin } from "../lib/types";

interface Props {
  design: ProjectDesign; session: ProjectGuideState; visible: boolean; disabled: boolean;
  pinsById: ReadonlyMap<string, Pin>;
  onChange: (session: ProjectGuideState) => void;
  onTargetChange: (target: ActiveGuideTarget | null) => void;
  onVisibleChange: (visible: boolean) => void;
  onDeploy: () => void;
}
export function ProjectGuidePanel({ design, session, visible, disabled, pinsById, onChange, onTargetChange, onVisibleChange, onDeploy }: Props) {
  const tr = useMakerText();
  const { t, tx } = useI18n();
  const tests = useComponentTests(design, session);
  const cid = design.component_ids[session.componentIndex];
  const guide = guideFor(cid);
  const steps = design.wiring.filter(w => w.componentId === cid);
  const step = steps[session.index] ?? steps[0];
  const target = useMemo<ActiveGuideTarget | null>(() => session.mode !== "camera" ? null : ({
    componentId: cid, boardPinId: step.boardPin, componentPinId: step.componentPin,
    connectionKind: step.connectionKind, manualOnly: true,
  }), [cid, step.boardPin, step.componentPin, step.connectionKind, session.mode]);
  const active = session.phase === "active";
  const complete = componentComplete(design, session, cid);
  const reviewing = session.phase === "review" || (session.phase === "prepare" && complete);
  const lastTest = tests.status.results.filter(r => r.component_id === cid).at(-1);
  const passed = lastTest?.outcome === "passed" && !lastTest.invalidated && lastTest.guide_key === componentTestKey(design, session, cid);
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
    void tests.invalidate();
    const index = session.phase === "prepare" && complete ? steps.length - 1
      : session.phase === "review" ? session.index : Math.max(0, session.index - 1);
    const next = { ...session.confirmed };
    const globalIndex = design.wiring.findIndex(w => w.id === steps[index].id);
    for (const w of design.wiring.slice(globalIndex)) delete next[w.id];
    onChange({ ...session, phase: "active", index, confirmed: next });
  }
  const [boardPhysical, ...boardSignals] = step.boardLabel.split(" · ");
  const boardPin = pinsById.get(step.boardPin);
  const piGuide = piHeaderGuideText(boardPin, t);
  const componentGuide = componentHeaderGuideText(cid, step.componentPin, t);
  return <CompactGuide contextKey={`${design.id}:${design.revision}:${cid}:${session.phase}:${session.index}:${session.run ?? 0}`} phase={reviewing ? "review" : session.phase}
    headerActions={<button type="button" className="guide-restart-action"
      title={tr("清除本輪接線紀錄，回到第一個零件的第一步；保留作品與程式", "Clear this wiring run and return to the first step; keep the project and code")}
      disabled={tests.pending} onClick={() => { void tests.invalidate(); onChange(restartProjectGuide(session)); }}>
      <span aria-hidden="true">↻</span>{tr("重新開始", "Restart")}
    </button>}
    visible={visible} title={componentGuide?.name ?? tx(guide.name)} progress={<>
      <div className="guide-progress-label"><span>{tr("作品人工紀錄", "Project manual records")}</span><strong>{count}<span> / {design.wiring.length}</span></strong></div>
      <progress max={design.wiring.length} value={count} aria-label={tr("作品人工接線進度", "Project manual wiring progress")} />
      <div className="guide-module-track">{design.component_ids.map((id, i) => <button type="button" key={id} disabled={tests.pending} aria-current={i === session.componentIndex ? "step" : undefined}
        onClick={() => onChange(selectTestModule(design, session, i))}>
        <span className="guide-module-dot" aria-hidden="true">{i + 1}</span>{componentModelName(id, t) ?? id.toUpperCase()}
      </button>)}</div>
    </>}
    targetId={active ? `${cid}:${step.componentPin}` : undefined} onClose={() => onVisibleChange(false)}
    actions={<><div className="guide-navigation">{session.phase === "prepare" && !complete ? <button type="button" className="guide-primary-action" onClick={start}>{tr("開始接線 →", "Start wiring →")}</button>
      : active ? <>
        <button type="button" className="guide-back-action" disabled={session.index === 0 || tests.pending} onClick={previous}>{tr("上一步", "Back")}</button>
        <button type="button" className="guide-primary-action" onClick={confirm}>{tr("我已接好，下一步 →", "Connected · Next →")}</button>
      </> : <>
        <button type="button" className="guide-back-action" disabled={tests.pending} onClick={previous}>{tr("回看", "Review")}</button>
        {session.componentIndex < design.component_ids.length - 1
          ? <button type="button" className={complete && !passed ? "guide-back-action" : "guide-primary-action"} onClick={() => onChange({ ...session, componentIndex: session.componentIndex + 1, index: 0, phase: "prepare", checks: [] })}>{complete && !passed ? tr("稍後測試，繼續 →", "Test later · Continue →") : tr("下一模組 →", "Next module →")}</button>
          : <button type="button" className={complete && !passed ? "guide-back-action" : "guide-primary-action"} onClick={onDeploy}>{complete && !passed ? tr("稍後測試，前往部署 →", "Test later · Deploy →") : tr("前往部署 →", "Deploy →")}</button>}
      </>}</div><small>{tr("接線由你逐腳確認；略過測試不會記錄為通過。", "Confirm each wire yourself; skipping a test never records a pass.")}</small></>}
    details={<>
    {active ? <p>{tx(step.hint)}</p> : null}
    <div className="maker-module-progress">{design.component_ids.map((id, i) => <span key={id} className={i === session.componentIndex ? "active" : ""}>{i + 1}. {id} · {design.wiring.filter(w => w.componentId === id && confirmed(w)).length}/{design.wiring.filter(w => w.componentId === id).length}</span>)}</div>
    {session.mode !== "camera" ? <button onClick={() => onChange({ ...session, mode: "camera" })}>{tr("返回鏡頭 Pin 引導", "Return to camera Pin guide")}</button> : null}
    <p className="wiring-safety">{tx(guide.safety)}</p>
    {session.restored ? <small className="maker-warning">{tr("含先前保存的人工紀錄；不是目前接線證據。", "Includes saved manual records, not evidence of current wiring.")}</small> : null}
    {active ? <button type="button" onClick={() => onChange({ ...session, phase: "review" })}>{tr("暫停並看總覽", "Pause & review")}</button> : null}
    <p className="wiring-status">{tr("功能測試透過 Pi 執行，不需要鏡頭定位。", "Function tests run on Pi and do not require camera tracking.")}</p>
    <p className="wiring-status">{tr("人工確認不代表導通、電壓或硬體功能通過。", "Manual confirmation does not verify continuity, voltage or functionality.")}</p>
    <details className="wiring-summary" open={session.phase === "review" ? true : undefined}><summary>{tr("接線總覽", "Wiring summary")} · {count}/{design.wiring.length}</summary>
      <table><tbody>{design.wiring.map(w => <tr key={w.id}><td>{w.componentId} · {w.componentPin}</td><td>{w.boardLabel}</td><td>{confirmed(w) ? `${tr("人工確認", "Manual")} (${session.confirmed[w.id].mode})` : tr("未確認", "Not confirmed")}</td></tr>)}</tbody></table></details>
    </>}>
    {tests.status.results.some(r => r.program_stopped) ? <p className="guide-caution">{tr("原作品已停止，測試結束不會自動重啟。原程式保留。", "Original project stopped; it will not restart automatically. Its code is preserved.")}</p> : null}
    {tests.status.results.some(r => r.program_stop_requested && !r.program_stopped) ? <p className="guide-caution">{tr("已送出停止原作品要求，狀態待確認；請重新連線核對。", "A stop request was sent to the original project; reconnect to confirm its state.")}</p> : null}
    {session.phase === "prepare" && !complete ? <div className="guide-prepare-message">
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
    </> : reviewing ? <section className="guide-module-review"><span>{tr("本模組人工紀錄", "MODULE MANUAL RECORDS")}</span>
      <strong>{moduleCount} / {steps.length}</strong><p>{complete ? tr("本零件必要接線已逐腳確認，現在可以測試。", "All required wires confirmed. You can now test this component.") : tr("這是暫停總覽；請繼續完成剩餘接線。", "Paused overview; finish the remaining wires first.")}</p></section> : null}
    {guide.unresolved.map(item => <p key={item.pin} className="guide-caution">{item.pin} · {tx(item.reason)}</p>)}
    {session.phase === "review" && session.componentIndex === design.component_ids.length - 1
      ? <p className="guide-caution">{tr("核對接線與供電規格後，接上 Pi USB-C 電源；開機後前往部署。", "After checking wiring and supply ratings, connect Pi USB-C power; deploy after boot.")}</p> : null}
    {disabled ? <p role="status">{tr("本機服務未連線；接線紀錄保留。", "Local service offline; wiring records are kept.")}</p> : null}
    <ComponentTestCard design={design} session={session} tests={tests} onViewWiring={() => { void tests.invalidate(cid); onChange({ ...session, phase: "active", index: 0 }); }} />
  </CompactGuide>;
}
