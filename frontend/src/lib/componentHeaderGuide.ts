import ultrasonic from "../../../profiles/components/hc-sr04/vision_profile.json";
import screen from "../../../profiles/components/mrd-tf240-8p-cs/vision_profile.json";
import type { I18nApi } from "./i18n";

// Both vision profiles define a single horizontal header in canonical board
// coordinates. Never use wiring-step order or screen/mirrored X to number it.
const headers = new Map([
  [ultrasonic.id, { nameKey: "componentGuide.ultrasonic", pins: [...ultrasonic.pins].sort((a, b) => a.x_norm - b.x_norm) }],
  [screen.id, { nameKey: "componentGuide.screen", pins: [...screen.pins].sort((a, b) => a.x_norm - b.x_norm) }],
]);

export function componentHeaderLocation(componentId: string, pinId: string | null) {
  const header = headers.get(componentId);
  if (!header || !pinId) return null;
  const index = header.pins.findIndex(pin => pin.id === pinId);
  if (index < 0) return null;
  return { nameKey: header.nameKey, pinId, number: index + 1,
    startPin: header.pins[0].id, pins: header.pins.map(pin => pin.id) };
}

export function componentModelName(componentId: string, t: I18nApi["t"]) {
  const header = headers.get(componentId);
  return header ? t(header.nameKey) : null;
}

export function componentHeaderGuideText(componentId: string, pinId: string | null, t: I18nApi["t"]) {
  const location = componentHeaderLocation(componentId, pinId);
  if (!location) return null;
  const name = t(location.nameKey);
  return { ...location, name,
    title: t("componentGuide.compactTarget", { name, number: location.number, pin: location.pinId }),
    countFrom: t(componentId === "hc-sr04" ? "componentGuide.countHc" : "componentGuide.countTft"),
  };
}
