import { useI18n } from "../lib/i18n";
import type {
  VerificationEvidenceMessage,
  VerificationUpdateMessage,
} from "../lib/types";
import { useHeldStatusReason } from "../lib/useHeldStatusReason";

interface VerificationPanelProps {
  verification: VerificationUpdateMessage;
  showElectrical: boolean;
}

const CAMERA_LAYERS = ["visual"] as const;
const ALL_LAYERS = ["visual", "electrical"] as const;

function statusMark(evidence: VerificationEvidenceMessage): string {
  if (evidence.status === "pass") return "\u2713";
  if (evidence.status === "fail") return "\u00d7";
  if (evidence.status === "unavailable") return "\u2014";
  return "\u2026";
}

export function VerificationPanel({
  verification,
  showElectrical,
}: VerificationPanelProps) {
  const { t } = useI18n();
  const { fusion, evidence } = verification;
  const visual = useHeldStatusReason(evidence.visual);
  const electrical = useHeldStatusReason(evidence.electrical);
  const displayedEvidence = { visual, electrical };
  const layers = showElectrical ? ALL_LAYERS : CAMERA_LAYERS;

  return (
    <section className={`verification-panel ${fusion.verdict}`} aria-live="polite">
      <div className="verification-overall">
        <div>
          <small>{t("verification.overall")}</small>
          <strong>{fusion.overall_confidence}<span>/100</span></strong>
        </div>
        <div className="verification-overall-copy">
          <b>{t(`verification.verdict.${fusion.verdict}`)}</b>
          <span>{t("verification.scoreCap", { cap: fusion.score_cap })}</span>
        </div>
      </div>

      <div className="verification-layers">
        {layers.map((layer) => {
          const item = displayedEvidence[layer] ?? evidence[layer];
          const partialEvidence = item.status === "uncertain"
            && item.details?.partial === true;
          const score = item.status === "unavailable"
            ? "\u2014"
            : item.status === "uncertain" && !partialEvidence
              ? "0%"
              : `${Math.round(item.score * 100)}%`;
          const raw = layer === "electrical" && typeof item.details?.raw === "number"
            ? ` \u00b7 A0 ${item.details.raw}/${item.details.full_scale ?? "?"}`
            : "";
          const trackingHold = item.details?.tracking_hold === true
            ? ` | ${t("verification.trackingHold")}`
            : "";
          const reasonParams = [
            "endpoint_near_other_pin",
            "component_endpoint_near_other_pin",
          ].includes(item.reason)
            ? { pin: String(item.details?.actual_pin ?? "?") }
            : undefined;
          return (
            <div className={`verification-layer ${layer} ${item.status}`} key={layer}>
              <span className="verification-layer-mark" aria-hidden="true">
                {statusMark(item)}
              </span>
              <span className="verification-layer-name">{t(`verification.layer.${layer}`)}</span>
              <span className="verification-layer-reason">
                {t(`verification.reason.${item.reason}`, reasonParams)}{trackingHold}{raw}
              </span>
              <strong>{score}</strong>
            </div>
          );
        })}
      </div>
    </section>
  );
}
