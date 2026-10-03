/** Presentation only. Shared by live recognition and frozen-photo overlays. */
const CONNECTION_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff9a56", GND: "#b4becd", AO: "#5ee0b2",
};

const COMPONENT_PIN_COLORS: Readonly<Record<string, string>> = {
  VCC: "#ff7777", GND: "#aab4c4", AO: "#65d6a0", TRIG: "#ffb45f",
  ECHO: "#c891ff", SCL: "#6fb9ff", SDA: "#65d6a0", XDA: "#8fe3bd",
  XCL: "#8fc8ff", AD0: "#ffd166", INT: "#c891ff", RES: "#ff9d66",
  DC: "#f4c95d", CS: "#c891ff", BLK: "#8f9bad",
};

export function guideConnectionColor(pinId: string): string {
  return CONNECTION_COLORS[pinId] ?? "#66dfff";
}

export function componentPinColor(pinId: string): string {
  return COMPONENT_PIN_COLORS[pinId] ?? "#61dafb";
}
