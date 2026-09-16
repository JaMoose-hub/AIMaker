import { useI18n } from "../lib/i18n";
import { piHeaderGuideText } from "../lib/piHeaderGuide";
import type { Pin } from "../lib/types";

/** A single-row count, not the alternating physical pin numbering. */
export function PiRowLocator({ pin }: { pin: Pin | undefined }) {
  const { t } = useI18n();
  const location = piHeaderGuideText(pin, t);
  if (!location) return null;
  return <div className="pi-row-locator">
    <p><span>{location.countFromLabel}</span></p>
    <div className="pi-row-caption">{t("boardGuide.pi.diagram")}</div>
    <ol className="pi-row-count" aria-label={location.title}>
      {Array.from({ length: 20 }, (_, i) => i + 1).map(number => <li key={number}
        aria-current={number === location.number ? "step" : undefined}>
        <span className="pi-row-dot" aria-hidden="true" />{number}
      </li>)}
    </ol>
  </div>;
}
