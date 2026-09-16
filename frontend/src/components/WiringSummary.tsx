import { useMemo } from "react";
import { isWireTraceFresh } from "../lib/traceFreshness";
import { useDetections, useGuidance, useWireTrace } from "../lib/wsClient";
import { useI18n } from "../lib/i18n";
import { useHeldStatusReason } from "../lib/useHeldStatusReason";
import { pinIdDisplayName } from "../lib/capabilities";
import type { WireInstance } from "../lib/types";

/**
 * Compact, honest wiring state. It deliberately says "candidate" rather
 * than "verified": electrical Rule Engine results are a separate layer.
 */

function wireSortKey(wire: WireInstance): string {
  const pins = wire.connection?.pin_ids.length
    ? [...wire.connection.pin_ids].sort().join("~")
    : "zz-floating";
  const attachment = wire.attachment ?? "unknown";
  return `${pins}|${wire.color}|${attachment}|${wire.wire_id}`;
}

export function WiringSummary() {
  const { t } = useI18n();
  const rawTrace = useWireTrace();
  const { detection } = useDetections();
  const trace = isWireTraceFresh(rawTrace, detection) ? rawTrace : null;
  const guidance = useHeldStatusReason(useGuidance());
  const wires = useMemo(
    () => [...(trace?.wires ?? [])].sort((a, b) => wireSortKey(a).localeCompare(wireSortKey(b))),
    [trace?.wires],
  );
  const hasRows = Boolean(guidance || trace?.suppressed_reason || wires.length > 0);

  return (
    <section className={`wiring-summary${hasRows ? "" : " empty"}`} aria-live="polite">
      <div className="wiring-summary-head">
        <span>{t("wiring.title")}</span>
        <span className="wiring-summary-note">{t("wiring.geometricOnly")}</span>
      </div>
      <div className="wiring-summary-body">
        {guidance && (
          <div className={`wiring-row guidance-${guidance.status}`}>
            <span className="wiring-row-label">{t("wiring.guidance")}</span>
            <span>{pinIdDisplayName(guidance.expected_pin_id)}</span>
            <strong>{guidance.status}</strong>
            {guidance.reason && (
              <small>{t(`wiring.reason.${guidance.reason}`)}</small>
            )}
          </div>
        )}
        {trace?.suppressed_reason === "scale_below_minimum" && (
          <div className="wiring-row uncertain">
            <span className="wiring-pins">{t("wiring.scalePaused")}</span>
            <span className="wiring-status">uncertain</span>
          </div>
        )}
        {wires.map((wire) => {
          const connection = wire.connection;
          const pins = connection?.pin_ids.map(pinIdDisplayName).join(" -> ") || "-";
          const status = connection?.status ?? "uncertain";
          const attachment = wire.attachment
            ? t("wiring.attachment." + wire.attachment)
            : null;
          return (
            <div className={`wiring-row ${status}`} key={wire.wire_id}>
              <span
                className="wiring-color"
                style={{ background: `var(--wire-${wire.color}, var(--wire-other))` }}
              />
              <span className="wiring-pins">{pins}</span>
              <span className="wiring-status">{status}</span>
              {attachment && <span className="wiring-attachment">{attachment}</span>}
              <span className="wiring-confidence">{Math.round(wire.confidence * 100)}%</span>
            </div>
          );
        })}
        {!hasRows && (
          <div className="wiring-row wiring-row-empty">
            <span>{t("wiring.empty")}</span>
          </div>
        )}
      </div>
    </section>
  );
}
