import type { BoardProfile, Capability, CapabilityType, Pin } from "./types";

/**
 * Capability priority, filter definitions and category colors.
 * Marker color = category color of the pin's "primary" capability with
 * priority power > boot > pwm > i2c > spi > uart > adc > digital_io.
 * All knowledge here is generic — pin data itself comes from the profile.
 */

const CAP_PRIORITY: readonly CapabilityType[] = [
  "power",
  "boot",
  "pwm",
  "i2c",
  "spi",
  "uart",
  "adc",
  "digital_io",
  "interrupt",
  "reset",
  "aref",
  "nc",
];

export function capRank(type: CapabilityType): number {
  const rank = CAP_PRIORITY.indexOf(type);
  return rank === -1 ? CAP_PRIORITY.length : rank;
}

export function primaryCapability(pin: Pin): Capability {
  let best = pin.capabilities[0];
  let bestRank = Number.POSITIVE_INFINITY;
  for (const cap of pin.capabilities) {
    const rank = capRank(cap.type);
    if (rank < bestRank) {
      bestRank = rank;
      best = cap;
    }
  }
  return best;
}

/** Unique capability types of a pin, sorted by display priority. */
export function orderedCapabilityTypes(pin: Pin): CapabilityType[] {
  const types = [...new Set(pin.capabilities.map((cap) => cap.type))];
  types.sort((a, b) => capRank(a) - capRank(b));
  return types;
}

/** Sorted copy of a pin's capabilities (for chip rows). */
export function sortedCapabilities(pin: Pin): Capability[] {
  return [...pin.capabilities].sort((a, b) => capRank(a.type) - capRank(b.type));
}

function powerColorVar(pin: Pin | undefined, cap: Capability | undefined): string {
  const haystack = [cap?.rail, cap?.role, pin?.silkscreen, pin?.id]
    .filter((part): part is string => typeof part === "string")
    .join(" ")
    .toLowerCase();
  if (haystack.includes("gnd") || haystack.includes("ground")) return "var(--cap-gnd)";
  if (haystack.includes("3v3") || haystack.includes("3.3")) return "var(--cap-power-3v3)";
  return "var(--cap-power-5v)"; // 5V / VIN
}

/** CSS color for a capability type; `pin`/`cap` refine power rails. */
export function capColorVar(type: CapabilityType, pin?: Pin, cap?: Capability): string {
  switch (type) {
    case "power":
      return powerColorVar(pin, cap);
    case "boot":
      return "var(--cap-boot)";
    case "pwm":
      return "var(--cap-pwm)";
    case "i2c":
      return "var(--cap-i2c)";
    case "spi":
      return "var(--cap-spi)";
    case "uart":
      return "var(--cap-uart)";
    case "adc":
      return "var(--cap-adc)";
    case "digital_io":
      return "var(--cap-digital)";
    case "interrupt":
      return "var(--cap-interrupt)";
    default:
      return "var(--cap-other)";
  }
}

/**
 * Translated chip label for a capability type. Unknown types — e.g. a newer
 * profile vocabulary than this build knows (`t` returns the raw key when the
 * translation is missing) — fall back to the type name itself.
 */
export function capLabel(t: (key: string) => string, type: CapabilityType): string {
  const key = `cap.${type}`;
  const label = t(key);
  return label === key ? String(type).replace(/_/g, " ").toUpperCase() : label;
}

/** Marker color for a pin (primary capability's category color). */
export function pinColorVar(pin: Pin): string {
  const primary = primaryCapability(pin);
  return capColorVar(primary.type, pin, primary);
}

/** User-facing Raspberry Pi/board pin name, separate from the profile id. */
export function pinDisplayName(pin: Pin | undefined): string {
  if (!pin) return "";
  const id = pin.id.toUpperCase();
  if (/^3V3_P\d+$/.test(id)) return "3.3V";
  if (/^5V_P\d+$/.test(id)) return "5V";
  if (/^GND_P\d+$/.test(id)) return "GND";
  const gpioNumber = id.match(/^GPIO(\d+)$/);
  if (gpioNumber) return gpioNumber[1];

  const alternate = pin.capabilities
    .filter((cap) => ["i2c", "spi", "uart", "pwm"].includes(cap.type))
    .map((cap) => {
      if (cap.type === "pwm") return cap.channel?.toUpperCase() ?? "PWM";
      return cap.role?.toUpperCase() ?? cap.type.toUpperCase();
    })
    .filter((label, index, labels) => labels.indexOf(label) === index)
    .slice(0, 1)[0];

  return alternate ? `${pin.id} / ${alternate}` : pin.id;
}

/** Name plus the physical header number, useful in guidance and tooltips. */
export function pinDisplayNameWithNumber(pin: Pin | undefined): string {
  if (!pin) return "";
  return `${pinDisplayName(pin)} · Pin ${pin.silkscreen}`;
}

/** Compact overlay label: keep power-rail names, use numbers for GPIOs. */
export function pinOverlayLabel(pin: Pin | undefined): string {
  if (!pin) return "";
  const name = pinDisplayName(pin);
  return ["3.3V", "5V", "GND"].includes(name) ? name : pin.silkscreen;
}

/** Best-effort label when a component only has the wire/protocol pin id. */
export function pinIdDisplayName(pinId: string): string {
  const id = pinId.toUpperCase();
  if (/^3V3_P\d+$/.test(id)) return "3.3V";
  if (/^5V_P\d+$/.test(id)) return "5V";
  if (/^GND_P\d+$/.test(id)) return "GND";
  const gpioNumber = id.match(/^GPIO(\d+)$/);
  if (gpioNumber) return gpioNumber[1];
  return pinId;
}

/* ------------------------------------------------------------------ */
/* Filters                                                             */
/* ------------------------------------------------------------------ */

export type FilterId = "all" | "pwm" | "i2c" | "spi" | "uart" | "adc" | "power" | "interrupt";

export const FILTERS: readonly FilterId[] = [
  "all",
  "pwm",
  "i2c",
  "spi",
  "uart",
  "adc",
  "power",
  "interrupt",
];

export const FILTER_COLOR_VAR: Record<Exclude<FilterId, "all">, string> = {
  pwm: "--cap-pwm",
  i2c: "--cap-i2c",
  spi: "--cap-spi",
  uart: "--cap-uart",
  adc: "--cap-adc",
  power: "--cap-power-5v",
  interrupt: "--cap-interrupt",
};

/**
 * Pin ids matching a filter. For bus filters (i2c/spi/uart) the profile
 * `buses` pin lists are authoritative; capability scan is only a fallback
 * when the profile declares no bus of that type.
 */
export function pinIdsForFilter(
  profile: BoardProfile,
  filter: Exclude<FilterId, "all">,
): Set<string> {
  const ids = new Set<string>();
  if (filter === "i2c" || filter === "spi" || filter === "uart") {
    for (const bus of profile.buses ?? []) {
      if (bus.type === filter) {
        for (const pinId of bus.pins) ids.add(pinId);
      }
    }
    if (ids.size > 0) return ids;
  }
  for (const pin of profile.pins) {
    if (pin.capabilities.some((cap) => cap.type === filter)) ids.add(pin.id);
  }
  return ids;
}
