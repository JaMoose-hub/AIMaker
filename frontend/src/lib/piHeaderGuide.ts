import type { I18nApi } from "./i18n";
import type { Pin } from "./types";

/** J8 profile indices are physical 1–40, not the ordinal within one row.
 * Odd pins face the board centre; even pins face the board edge. Both rows
 * start at the end away from the USB-A / Ethernet connectors. This is board-
 * relative, so rotating or mirroring the camera never changes the wording.
 * Derive from the loaded profile; never introduce a second GPIO pin map.
 */
export function piHeaderLocation(pin: Pin | undefined) {
  if (!pin || pin.header !== "J8" || !Number.isInteger(pin.index) || pin.index < 1 || pin.index > 40) return null;
  return {
    physical: pin.index,
    number: Math.ceil(pin.index / 2),
    row: pin.index % 2 ? "inner" as const : "outer" as const,
    signal: pin.id.replace(/_P\d+$/, "").replace(/^3V3$/, "3.3V"),
  };
}

export function piHeaderGuideText(pin: Pin | undefined, t: I18nApi["t"]) {
  const location = piHeaderLocation(pin);
  if (!location) return null;
  const rowLabel = t(`boardGuide.pi.${location.row}`);
  return {
    ...location,
    rowLabel,
    ordinalLabel: t("boardGuide.pi.ordinal", { number: location.number }),
    title: t("boardGuide.pi.target", { row: rowLabel, number: location.number }),
    countFromLabel: t("boardGuide.pi.countFrom"),
    instruction: t("boardGuide.pi.instruction", { number: location.number }),
    reference: t("boardGuide.pi.reference", { signal: location.signal, physical: location.physical }),
  };
}
