import { useI18n } from "../lib/i18n";
import "../capture.css";

export function CaptureCountdown({ remaining, onCancel }: { remaining: number | null; onCancel: () => void }) {
  const { t } = useI18n();
  if (remaining === null) return null;
  return <div className="capture-countdown">
    <span className="capture-countdown-number" aria-hidden="true">{remaining}</span>
    <div role="status" aria-live="polite" aria-atomic="true"><strong>{t("capture.countdown", { seconds: remaining })}</strong><small>{t("capture.positionHint")}</small></div>
    <button type="button" onClick={onCancel}>{t("capture.cancel")}</button>
  </div>;
}
