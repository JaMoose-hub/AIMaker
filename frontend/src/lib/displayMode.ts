export type DisplayMode =
  | "standard"
  | "smart-glasses-demo"
  | "optical-hud-calibration"
  | "optical-hud-demo";

export function isDisplayOnlyMode(mode: DisplayMode): boolean {
  return mode !== "standard";
}

export function isOpticalHudMode(mode: DisplayMode): boolean {
  return mode === "optical-hud-calibration" || mode === "optical-hud-demo";
}
