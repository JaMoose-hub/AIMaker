import { useEffect, useReducer, useState } from "react";
import { deleteGuidanceStep } from "../lib/api";
import {
  COMPONENT_GUIDES, guideFor, guideReducer, initialGuideSession, prerequisitesMet,
  type ActiveGuideTarget, type GuidedComponentId,
} from "../lib/componentWiringGuides";
import { useI18n } from "../lib/i18n";
import { useGuidedPose } from "../lib/useGuidedPose";
import { clearGuidanceSnapshot } from "../lib/wsClient";
import { PhotoresistorGuide } from "./PhotoresistorGuide";
import { PiRowLocator } from "./PiRowLocator";
import { ComponentRowLocator } from "./ComponentRowLocator";
import { componentModelName } from "../lib/componentHeaderGuide";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import type { Pin } from "../lib/types";

interface Props {
  boardId: string;
  boardName: string;
  availablePinIds: ReadonlySet<string>;
  pinsById: ReadonlyMap<string, Pin>;
  disabled: boolean;
  visible: boolean;
  onVisibleChange: (visible: boolean) => void;
  onTargetChange: (target: ActiveGuideTarget | null) => void;
}

/** Keep the legacy imported profiles/colour/Serial flow intact. */
function LegacyGuide({ onTargetChange, ...props }: Props) {
  const [boardPinId, setBoardPinId] = useState<string | null>(null);
  const [componentPinId, setComponentPinId] = useState<string | null>(null);
  useEffect(() => {
    onTargetChange(boardPinId ? { componentId: "photoresistor-module", boardPinId, componentPinId, connectionKind: "direct", manualOnly: false } : null);
  }, [boardPinId, componentPinId, onTargetChange]);
  return <PhotoresistorGuide {...props} onTargetPinChange={setBoardPinId} onTargetSensorPinChange={setComponentPinId} />;
}

export function WiringGuidePanel(props: Props) {
  return props.boardId === "raspberry-pi-5" ? <ComponentGuidePanel {...props} /> : <LegacyGuide {...props} />;
}

function DividerDiagram() {
  const { t } = useI18n();
  return <div className="wiring-divider" role="note" aria-label={t("wiring.dividerTitle")}>
    <strong>{t("wiring.dividerTitle")}</strong>
    <code>ECHO ─ 330Ω ─ ● ─ GPIO18</code>
    <code>● ─ 470Ω ─ GND</code>
    <small>{t("wiring.dividerNote")}</small>
  </div>;
}

function ComponentGuidePanel({ boardId, boardName, availablePinIds, pinsById, disabled, visible, onVisibleChange, onTargetChange }: Props) {
  const { t, tx } = useI18n();
  const [session, dispatch] = useReducer(guideReducer, undefined, () => initialGuideSession());
  const [legacy, setLegacy] = useState(false);
  const [legacyTarget, setLegacyTarget] = useState<ActiveGuideTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const guide = guideFor(session.componentId);
  const step = guide.steps[session.index];
  const boardPin = pinsById.get(step.boardPin);
  const piGuide = piHeaderGuideText(boardPin, t);
  const active = !legacy && session.phase === "active";
  const target: ActiveGuideTarget = {
    componentId: guide.id, boardPinId: active ? step.boardPin : null,
    componentPinId: active ? step.componentPin : null,
    connectionKind: active ? step.connectionKind : "direct", manualOnly: true,
  };
  const { ready, connected, componentPoses, componentReceivedAtMs } = useGuidedPose(target);
  const available = guide.boardId === boardId && guide.steps.every((item) => availablePinIds.has(item.boardPin));
  const canConfirm = ready && !disabled && !busy && available;
  // Synchronize the displayed target only; requests stay in event handlers.
  useEffect(() => {
    onTargetChange(legacy ? legacyTarget : active ? {
      componentId: guide.id, boardPinId: step.boardPin, componentPinId: step.componentPin,
      connectionKind: step.connectionKind, manualOnly: true,
    } : null);
  }, [legacy, legacyTarget, active, guide.id, step.boardPin, step.componentPin, step.connectionKind, onTargetChange]);

  async function start() {
    if (!prerequisitesMet(session) || !canConfirm) return;
    setBusy(true);
    setError(false);
    try {
      // Manual lessons never publish a fictitious direct connection (ECHO
      // uses an external divider). Clear any previous legacy evidence first.
      await deleteGuidanceStep();
      clearGuidanceSnapshot();
      dispatch({ type: "start" });
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function returnToComponents() {
    if (busy || legacyTarget) return;
    setBusy(true);
    setError(false);
    try {
      await deleteGuidanceStep();
      clearGuidanceSnapshot();
      setLegacy(false);
      dispatch({ type: "reset" });
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  if (legacy) return <>
    <LegacyGuide boardId={boardId} boardName={boardName} availablePinIds={availablePinIds} pinsById={pinsById} disabled={disabled}
      visible={visible} onVisibleChange={onVisibleChange} onTargetChange={setLegacyTarget} />
    {visible ? <button type="button" className="wiring-legacy-back" disabled={busy || legacyTarget !== null}
      onClick={() => void returnToComponents()}>{error ? t("wiring.networkError") : t("wiring.backToComponents")}</button> : null}
  </>;

  return <section className={`photo-guide component-guide ${session.phase}`} hidden={!visible} aria-label={t("wiring.title")}>
    <div className="wiring-head">
      <div><small>{t("wiring.kicker")}</small><h2>{active ? componentModelName(guide.id, t) ?? tx(guide.name) : t("wiring.title")}</h2></div>
      {active ? <span className="photo-guide-progress">{session.index + 1}/{guide.steps.length}</span> : null}
      <button type="button" className="photo-guide-close" onClick={() => onVisibleChange(false)} aria-label={t("photoGuide.hide")}>×</button>
    </div>
    {!active ? <label className="wiring-selector">
      <span>{t("wiring.selectComponent")}</span>
      <select value={guide.id} disabled={active || busy} onChange={(event) => { dispatch({ type: "select", id: event.currentTarget.value as GuidedComponentId }); setError(false); }}>
        {COMPONENT_GUIDES.map((item) => {
          const pose = componentPoses.find((value) => value.component_id === item.id);
          const detected = connected && pose?.tracking === "locked" && Date.now() - (componentReceivedAtMs[item.id] ?? 0) < 1500;
          return <option key={item.id} value={item.id}>{componentModelName(item.id, t) ?? tx(item.name)} · {t(detected ? "wiring.detected" : "wiring.notDetected")}</option>;
        })}
      </select>
    </label> : null}
    <p className="wiring-safety">{tx(guide.safety)}</p>
    {!available ? <p role="alert">{t("wiring.profileMismatch")}</p> : null}
    {session.phase === "prepare" ? <>
      <fieldset className="wiring-prerequisites" disabled={busy}>
        <legend>{t("wiring.prepare")}</legend>
        {guide.prerequisites.map((item) => <label key={`${guide.id}:${item.id}`}>
          <input type="checkbox" checked={session.checked.includes(item.id)} onChange={(event) => dispatch({ type: "check", id: item.id, checked: event.currentTarget.checked })} />
          <span>{tx(item.text)}</span>
        </label>)}
      </fieldset>
      {guide.id === "hc-sr04" ? <DividerDiagram /> : null}
      <div className="wiring-actions">
        <button className="photo-guide-primary" type="button" disabled={!prerequisitesMet(session) || !canConfirm} onClick={() => void start()}>
          {t(busy ? "photoGuide.loading" : guide.unresolved.length ? "wiring.startSignals" : "wiring.start")}
        </button>
        <button className="photo-guide-secondary" type="button" disabled={busy} onClick={() => setLegacy(true)}>{t("wiring.legacy")}</button>
      </div>
      {!ready || disabled ? <p className="wiring-status" role="status">{t("wiring.waiting")}</p> : null}
    </> : active ? <>
      <div className="wiring-step" aria-live="polite">
        <span className="photo-guide-step-dot signal">{session.index + 1}</span>
        <div><strong>{piGuide ? `${step.componentPin} → ${piGuide.title}` : tx(step.instruction)}</strong><p>{tx(step.hint)}</p></div>
      </div>
      <div className="wiring-route" data-wiring-target={`${guide.id}:${step.componentPin}`}>
        <span>{guide.id}<strong>{step.componentPin}</strong></span>
        <span>{step.connectionKind === "divider" ? t("wiring.viaDivider") : "↔"}</span>
        <span>Pi 5<strong>{piGuide?.title ?? step.boardLabel}</strong>{piGuide ? <small>{piGuide.reference}</small> : null}</span>
      </div>
      {piGuide ? <PiRowLocator pin={boardPin} /> : null}
      <ComponentRowLocator componentId={guide.id} pinId={step.componentPin} />
      {step.connectionKind === "divider" ? <DividerDiagram /> : null}
      <p className={`wiring-status ${canConfirm ? "ready" : "paused"}`} role="status">{t(canConfirm ? "wiring.manualNotice" : "wiring.paused")}</p>
      <div className="wiring-actions">
        <button type="button" className="photo-guide-secondary" disabled={session.index === 0 || busy} onClick={() => dispatch({ type: "previous" })}>{t("photoGuide.previous")}</button>
        <button type="button" className="photo-guide-primary" disabled={!canConfirm} onClick={() => dispatch({ type: "confirm", ready: canConfirm })}>{t("wiring.confirmNext")}</button>
        <button type="button" className="photo-guide-secondary" onClick={() => dispatch({ type: "end" })}>{t("wiring.end")}</button>
      </div>
    </> : <>
      <strong className="wiring-review-title">{t(guide.unresolved.length ? "wiring.reviewPending" : session.confirmed.length === guide.steps.length ? "wiring.reviewRecorded" : "wiring.reviewPartial")}</strong>
      <p className="wiring-status">{t("wiring.notVerified")}</p>
      <p className="photo-guide-copy">{tx(guide.functionalTest)}</p>
      <div className="wiring-actions">
        <button type="button" className="photo-guide-secondary" onClick={() => dispatch({ type: "previous" })}>{t("wiring.reviewStep")}</button>
        <button type="button" className="photo-guide-secondary" onClick={() => dispatch({ type: "reset" })}>{t("photoGuide.restart")}</button>
      </div>
    </>}
    <details className="wiring-summary" open={session.phase === "review" ? true : undefined}>
      <summary>{t("wiring.summary")} · {session.confirmed.length}/{guide.steps.length}</summary>
      <table><thead><tr><th>{t("wiring.componentPin")}</th><th>{t("wiring.piTarget")}</th><th>{t("wiring.status")}</th></tr></thead>
        <tbody>{guide.steps.map((item) => <tr key={item.id}>
          <td>{item.componentPin}</td><td>{item.boardLabel}{item.connectionKind === "divider" ? ` · ${t("wiring.viaDivider")}` : ""}</td>
          <td>{t(session.confirmed.includes(item.id) ? "wiring.manuallyRecorded" : "wiring.unconfirmed")}</td>
        </tr>)}{guide.unresolved.map((item) => <tr key={item.pin} className="wiring-unresolved">
          <td>{item.pin}</td><td>{tx(item.reason)}</td><td>{t("wiring.pending")}</td>
        </tr>)}</tbody></table>
      <p>{t("wiring.notVerified")}</p>
    </details>
    {error ? <p className="photo-guide-error" role="alert">{t("wiring.networkError")}</p> : null}
  </section>;
}
