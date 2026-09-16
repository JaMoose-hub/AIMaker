import type { I18nText } from "./types";

export type GuideComponentPinId = "VCC" | "GND" | "AO";
export type GuideWireClass = "power" | "ground" | "signal";
export type GuideElectricalVerification = "none" | "serial-a0";

export interface WiringGuideStepProfile {
  id: string;
  board_pin_id: string;
  board_label: string;
  component_pin_id: GuideComponentPinId;
  wire_class: GuideWireClass;
  instruction: I18nText;
  hint: I18nText;
  electrical_verification?: GuideElectricalVerification;
}

/**
 * A wiring-guide profile controls lesson copy and Pin mappings only. It does
 * not replace the active board vision profile, reference image, or detector.
 */
export interface WiringGuideProfile {
  schema_version: "1.0";
  kind: "boardvision-wiring-guide";
  id: string;
  board_id: string;
  name: I18nText;
  controller_label: I18nText;
  component_id: "photoresistor-module";
  component_label: I18nText;
  intro: I18nText;
  safety: I18nText;
  complete_hint: I18nText;
  steps: WiringGuideStepProfile[];
}

export class WiringGuideProfileError extends Error {
  constructor(
    public readonly code: string,
    public readonly params: Record<string, string | number> = {},
  ) {
    super(code);
    this.name = "WiringGuideProfileError";
  }
}

function invalid(code: string, params: Record<string, string | number> = {}): never {
  throw new WiringGuideProfileError(code, params);
}

const UNO_Q_PHOTORESISTOR_GUIDE: WiringGuideProfile = {
  schema_version: "1.0",
  kind: "boardvision-wiring-guide",
  id: "photoresistor-uno-q-analog",
  board_id: "arduino-uno-q",
  name: { "zh-TW": "UNO Q 類比光敏電阻", en: "UNO Q analog photoresistor" },
  controller_label: { "zh-TW": "UNO Q", en: "UNO Q" },
  component_id: "photoresistor-module",
  component_label: { "zh-TW": "Sensor", en: "Sensor" },
  intro: {
    "zh-TW": "逐步完成 UNO Q 與光敏模組的三條接線；每一步只高亮目前要接的腳位。",
    en: "Connect the UNO Q to the light sensor in three steps. Only the current target Pin stays highlighted.",
  },
  safety: {
    "zh-TW": "請使用 3.3V，不要將 5V 或 5.5V 接到 A0。",
    en: "Use 3.3V. Never feed 5V or 5.5V into A0.",
  },
  complete_hint: {
    "zh-TW": "三條接線引導已結束；可在 AO 步驟以 Serial 確認 A0 是否隨光照改變。",
    en: "The three wiring steps are complete. Use Serial on the AO step to confirm that A0 responds to light.",
  },
  steps: [
    {
      id: "photoresistor-vcc",
      board_pin_id: "3V3",
      board_label: "3.3V",
      component_pin_id: "VCC",
      wire_class: "power",
      instruction: {
        "zh-TW": "將 UNO Q 3.3V 接到 Sensor VCC",
        en: "Connect UNO Q 3.3V to Sensor VCC",
      },
      hint: {
        "zh-TW": "畫面只會高亮 UNO Q 的 3V3 腳位；Sensor 端請插入 VCC。",
        en: "Only the UNO Q 3V3 Pin is highlighted; connect the sensor end to VCC.",
      },
    },
    {
      id: "photoresistor-gnd",
      board_pin_id: "GND_P1",
      board_label: "GND",
      component_pin_id: "GND",
      wire_class: "ground",
      instruction: {
        "zh-TW": "將 UNO Q GND 接到 Sensor GND",
        en: "Connect UNO Q GND to Sensor GND",
      },
      hint: {
        "zh-TW": "使用電源排上、緊鄰 5V 的第一個 GND 腳位。",
        en: "Use the first power-header GND Pin next to 5V.",
      },
    },
    {
      id: "photoresistor-ao",
      board_pin_id: "A0",
      board_label: "A0",
      component_pin_id: "AO",
      wire_class: "signal",
      instruction: {
        "zh-TW": "將 UNO Q A0 接到 Sensor AO",
        en: "Connect UNO Q A0 to Sensor AO",
      },
      hint: {
        "zh-TW": "AO 是類比訊號；A0 不可輸入高於 3.3V 的電壓。",
        en: "AO is analog. Never apply more than 3.3V to A0.",
      },
      electrical_verification: "serial-a0",
    },
  ],
};

const PI5_PHOTORESISTOR_GUIDE: WiringGuideProfile = {
  schema_version: "1.0",
  kind: "boardvision-wiring-guide",
  id: "photoresistor-pi5-digital-threshold",
  board_id: "raspberry-pi-5",
  name: { "zh-TW": "Pi 5 光敏電阻（數位門檻）", en: "Pi 5 photoresistor (digital threshold)" },
  controller_label: { "zh-TW": "PI 5", en: "PI 5" },
  component_id: "photoresistor-module",
  component_label: { "zh-TW": "Sensor", en: "Sensor" },
  intro: {
    "zh-TW": "以 Pi 5 當控制器完成三條接線；第三步只能把 AO 當 HIGH／LOW 數位門檻訊號。",
    en: "Use the Pi 5 as the controller. The AO lead is treated only as a HIGH/LOW digital-threshold signal.",
  },
  safety: {
    "zh-TW": "Sensor 必須使用 3.3V。Pi 5 GPIO 不耐 5V，且 40-Pin 接頭沒有可用的類比輸入；要讀光照數值請加 ADS1115／MCP3008。",
    en: "Power the Sensor from 3.3V. Pi 5 GPIO is not 5V tolerant and its 40-Pin header has no analog input; add an ADS1115 or MCP3008 to read light intensity.",
  },
  complete_hint: {
    "zh-TW": "接線引導完成；GPIO17 只能讀 HIGH／LOW。若要取得連續光照數值，請改用含外接 ADC 的接線 Profile。",
    en: "The guide is complete. GPIO17 can only read HIGH/LOW. Import a guide with an external ADC for continuous light values.",
  },
  steps: [
    {
      id: "photoresistor-pi5-vcc",
      board_pin_id: "3V3_P1",
      board_label: "3.3V · Pin 1",
      component_pin_id: "VCC",
      wire_class: "power",
      instruction: {
        "zh-TW": "將 Pi 5 Pin 1（3.3V）接到 Sensor VCC",
        en: "Connect Pi 5 Pin 1 (3.3V) to Sensor VCC",
      },
      hint: {
        "zh-TW": "使用 Pin 1 的 3.3V；不要使用旁邊 Pin 2 的 5V。",
        en: "Use 3.3V on Pin 1; do not use the adjacent 5V Pin 2.",
      },
    },
    {
      id: "photoresistor-pi5-gnd",
      board_pin_id: "GND_P6",
      board_label: "GND · Pin 6",
      component_pin_id: "GND",
      wire_class: "ground",
      instruction: {
        "zh-TW": "將 Pi 5 Pin 6（GND）接到 Sensor GND",
        en: "Connect Pi 5 Pin 6 (GND) to Sensor GND",
      },
      hint: {
        "zh-TW": "畫面會高亮實體 Pin 6；其他 GND 雖然電氣等效，但本步以 Pin 6 為教學目標。",
        en: "The UI highlights physical Pin 6. Other GND Pins are equivalent, but this lesson targets Pin 6.",
      },
    },
    {
      id: "photoresistor-pi5-ao-digital",
      board_pin_id: "GPIO17",
      board_label: "GPIO17 · Pin 11",
      component_pin_id: "AO",
      wire_class: "signal",
      instruction: {
        "zh-TW": "將 Pi 5 Pin 11（GPIO17）接到 Sensor AO",
        en: "Connect Pi 5 Pin 11 (GPIO17) to Sensor AO",
      },
      hint: {
        "zh-TW": "此接法只把 0–3.3V AO 當數位 HIGH／LOW；Pi 5 無法直接量測類比數值。",
        en: "This uses the 0-3.3V AO signal only as digital HIGH/LOW; the Pi 5 cannot directly measure its analog value.",
      },
      electrical_verification: "none",
    },
  ],
};

const BUILTIN_GUIDES: Readonly<Record<string, WiringGuideProfile>> = {
  "arduino-uno-q": UNO_Q_PHOTORESISTOR_GUIDE,
  "raspberry-pi-5": PI5_PHOTORESISTOR_GUIDE,
};

export function builtinWiringGuideProfile(boardId: string): WiringGuideProfile | null {
  return BUILTIN_GUIDES[boardId] ?? null;
}

/** Generate from the lesson's GPIO mapping, never a separate pin constant. */
export function piPhotoresistorExample(profile: WiringGuideProfile = PI5_PHOTORESISTOR_GUIDE): string {
  const signal = profile.steps.find((step) => step.component_pin_id === "AO");
  const match = /^GPIO(\d+)$/.exec(signal?.board_pin_id ?? "");
  if (profile.board_id !== "raspberry-pi-5" || !match) {
    throw new Error("Pi photoresistor example requires a GPIO signal pin");
  }
  const gpio = Number(match[1]);
  const wiring = profile.steps.map((step) => `# ${step.component_pin_id} -> ${step.board_label}`).join("\n");
  return `${wiring}
# Digital HIGH/LOW only (not a light intensity measurement).
from time import sleep
from gpiozero import DigitalInputDevice
from gpiozero.pins.lgpio import LGPIOFactory

with DigitalInputDevice(
    ${gpio}, pull_up=None, active_state=True,
    pin_factory=LGPIOFactory(),
) as sensor:
    while True:
        value = int(sensor.value)
        level = "HIGH" if value else "LOW"
        print(f"GPIO${gpio}: {value} ({level})", flush=True)
        sleep(0.2)
`;
}

function requireObject(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    invalid("field_object", { field });
  }
  return value as Record<string, unknown>;
}

function requireShortString(value: unknown, field: string, maxLength = 180): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maxLength) {
    invalid("field_string", { field, max: maxLength });
  }
  return value.trim();
}

function requireI18n(value: unknown, field: string): I18nText {
  const object = requireObject(value, field);
  const result: I18nText = {};
  for (const [locale, text] of Object.entries(object)) {
    if (!/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(locale)) continue;
    result[locale] = requireShortString(text, `${field}.${locale}`, 500);
  }
  if (!result["zh-TW"] && !result.en) {
    invalid("i18n_missing", { field });
  }
  return result;
}

/** Validate an imported lesson against the board Profile currently in use. */
export function parseWiringGuideProfile(
  value: unknown,
  activeBoardId: string,
  availablePinIds: ReadonlySet<string>,
): WiringGuideProfile {
  const object = requireObject(value, "Profile");
  if (object.schema_version !== "1.0" || object.kind !== "boardvision-wiring-guide") {
    invalid("schema_unsupported");
  }
  const boardId = requireShortString(object.board_id, "board_id", 80);
  if (boardId !== activeBoardId) {
    invalid("board_mismatch", { board_id: boardId, active_board_id: activeBoardId });
  }
  if (object.component_id !== "photoresistor-module") {
    invalid("component_unsupported");
  }
  if (!Array.isArray(object.steps) || object.steps.length < 1 || object.steps.length > 12) {
    invalid("steps_range");
  }

  const seenStepIds = new Set<string>();
  const steps: WiringGuideStepProfile[] = object.steps.map((rawStep, index) => {
    const step = requireObject(rawStep, `steps[${index}]`);
    const id = requireShortString(step.id, `steps[${index}].id`, 80);
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id) || seenStepIds.has(id)) {
      invalid("step_id_invalid", { index });
    }
    seenStepIds.add(id);
    const boardPinId = requireShortString(step.board_pin_id, `steps[${index}].board_pin_id`, 80);
    if (!availablePinIds.has(boardPinId)) {
      invalid("pin_not_found", { board_id: activeBoardId, pin_id: boardPinId });
    }
    const componentPinId = requireShortString(
      step.component_pin_id,
      `steps[${index}].component_pin_id`,
      12,
    ) as GuideComponentPinId;
    if (!["VCC", "GND", "AO"].includes(componentPinId)) {
      invalid("component_pin_unsupported", { index });
    }
    const wireClass = requireShortString(step.wire_class, `steps[${index}].wire_class`, 12) as GuideWireClass;
    if (!["power", "ground", "signal"].includes(wireClass)) {
      invalid("wire_class_unsupported", { index });
    }
    const electrical = (step.electrical_verification ?? "none") as GuideElectricalVerification;
    if (!["none", "serial-a0"].includes(electrical)) {
      invalid("electrical_unsupported", { index, value: String(electrical) });
    }
    if (electrical === "serial-a0" && (boardPinId !== "A0" || componentPinId !== "AO")) {
      invalid("serial_target_invalid");
    }
    return {
      id,
      board_pin_id: boardPinId,
      board_label: requireShortString(step.board_label, `steps[${index}].board_label`, 80),
      component_pin_id: componentPinId,
      wire_class: wireClass,
      instruction: requireI18n(step.instruction, `steps[${index}].instruction`),
      hint: requireI18n(step.hint, `steps[${index}].hint`),
      electrical_verification: electrical,
    };
  });

  return {
    schema_version: "1.0",
    kind: "boardvision-wiring-guide",
    id: requireShortString(object.id, "id", 80),
    board_id: boardId,
    name: requireI18n(object.name, "name"),
    controller_label: requireI18n(object.controller_label, "controller_label"),
    component_id: "photoresistor-module",
    component_label: requireI18n(object.component_label, "component_label"),
    intro: requireI18n(object.intro, "intro"),
    safety: requireI18n(object.safety, "safety"),
    complete_hint: requireI18n(object.complete_hint, "complete_hint"),
    steps,
  };
}
