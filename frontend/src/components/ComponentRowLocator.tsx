import { useI18n } from "../lib/i18n";
import { componentHeaderGuideText } from "../lib/componentHeaderGuide";

/** Physical single-row order, including unused pins (e.g. TFT BLK). */
export function ComponentRowLocator({ componentId, pinId }: { componentId: string; pinId: string }) {
  const { t } = useI18n();
  const location = componentHeaderGuideText(componentId, pinId, t);
  if (!location) return null;
  return <div className="component-row-locator">
    <p><strong>{location.name}</strong><span>{location.countFrom}</span></p>
    <ol className="component-row-count" aria-label={location.title}>
      {location.pins.map((pin, index) => <li key={pin} aria-current={pin === pinId ? "step" : undefined}>
        <span className="component-row-number">{index + 1}</span>
        <strong>{pin}</strong>
      </li>)}
    </ol>
  </div>;
}
