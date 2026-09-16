"""Rule-based bilingual (zh-TW / en) natural-language pin query service.

Intents are keyed by keyword/synonym sets. Pin lists are always DERIVED from
the loaded BoardProfile (pins_with_capability / bus / groups lookups), never
hardcoded. Response shape (docs/api-contract.md §1 POST /api/query):

    { "answer": str, "pin_ids": [str], "group": str | None, "matched": bool }

Every I/O intent answer appends the 3.3V-logic reminder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.profiles.models import BoardProfile

_ASCII_WORD = re.compile(r"^[a-z0-9]+$")


def _keyword_hit(text_lower: str, keyword: str) -> bool:
    """ASCII keywords match on word boundaries; CJK keywords by substring."""
    if _ASCII_WORD.match(keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text_lower) is not None
    return keyword in text_lower


@dataclass(frozen=True)
class Intent:
    id: str  # "pwm" | "i2c" | "spi" | "uart" | "adc" | "power" | "interrupt"
    keywords: tuple[str, ...]  # pass 1: explicit protocol/bus/electrical terms
    generic: tuple[str, ...]   # pass 2: generic use-case terms (only when pass 1 misses)
    is_io: bool  # True -> append 3.3V logic reminder


# Priority order within a pass: first match wins. Bus intents first so e.g.
# "i2c 溫濕度感測器要接哪裡跟電源?" resolves to i2c, not power.
#
# Matching is two-pass: pass 1 checks only EXPLICIT protocol/bus keywords
# (i2c/sda/scl..., spi/mosi/miso..., uart/tx/rx...); only when no intent has
# an explicit hit does pass 2 consider generic terms (溫濕度/感測器模組/servo/
# button/...). This keeps e.g. "SPI 感測器模組要接哪裡?" on spi instead of
# misrouting to i2c via the generic 感測器模組.
_INTENTS: tuple[Intent, ...] = (
    Intent("i2c", ("i2c", "iic", "i²c", "qwiic", "sda", "scl", "wire"),
           ("溫濕度", "溫溼度", "感測器模組", "感應器模組"), True),
    Intent("spi", ("spi", "mosi", "miso", "sck", "sclk", "cipo", "copi"),
           (), True),
    Intent("uart", ("uart", "serial", "序列", "串列", "串口", "tx", "rx"),
           (), True),
    Intent("interrupt", ("interrupt", "irq", "中斷"),
           ("button", "按鈕", "按鍵"), True),
    Intent("power", ("power", "gnd", "ground", "5v", "3v3", "3.3v", "vin", "vcc",
                     "電源", "供電", "接地", "地線"),
           (), False),
    Intent("adc", ("adc", "analog", "analogue", "類比", "類比輸入"),
           ("potentiometer", "ldr", "光敏", "電位器", "可變電阻"), True),
    Intent("pwm", ("pwm",),
           ("servo", "sg90", "led", "dim", "fade", "brightness", "motor",
            "伺服", "舵機", "呼吸燈", "亮度", "調光", "馬達"), True),
)


def _natural_key(pin_id: str) -> tuple:
    """Natural-sort key: letters compare as text, digit runs as numbers,
    so D3 < D5 < D9 < D10 < D11 and GND_P1 < GND_P2 sort sanely."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.upper())
        for part in re.split(r"(\d+)", pin_id)
        if part
    )

_EXAMPLES = {
    "zh-TW": "「哪支腳可以接 servo?」、「I2C 接哪裡?」、「哪些是電源腳位?」",
    "en": '"Which pin can drive a servo?", "Where do I connect I2C?", "Which pins are power pins?"',
}


class QueryService:
    def __init__(self, profile: BoardProfile, default_locale: str = "zh-TW") -> None:
        self._profile = profile
        self._default_locale = default_locale

    # -- helpers ---------------------------------------------------------

    def _lang(self, locale: str | None) -> str:
        loc = (locale or self._default_locale or "zh-TW").lower()
        return "en" if loc.startswith("en") else "zh-TW"

    def _board_name(self, lang: str) -> str:
        name = self._profile.board.name
        return name.get(lang) or name.get("zh-TW") or self._profile.board.id

    def _reminder(self, lang: str) -> str:
        v = self._profile.board.logic_voltage
        board = self._board_name(lang)
        if lang == "en":
            return f" Note: {board} uses {v:g}V logic."
        return f"注意：{board} 為 {v:g}V 邏輯。"

    @staticmethod
    def _join(pin_ids: list[str], lang: str) -> str:
        return ("、" if lang == "zh-TW" else ", ").join(pin_ids)

    def _bus_pins(self, bus_type: str) -> tuple[str | None, list[str], list[str]]:
        """Return (bus_id, pin_ids, labels). Prefers bus '<type>0'.
        Bus pin order is the profile author's curated order (dedicated pins
        first); the capability-scan fallback is natural-sorted."""
        bus = self._profile.bus_by_id(f"{bus_type}0")
        if bus is None:
            bus = next((b for b in self._profile.buses if b.type == bus_type), None)
        if bus is None:
            # Fall back to capability scan when the profile has no bus entry.
            pin_ids = sorted(
                (p.id for p in self._profile.pins_with_capability(bus_type)),
                key=_natural_key,
            )
            return None, pin_ids, [self._pin_label(pid) for pid in pin_ids]
        return bus.id, list(bus.pins), [self._pin_label(pid) for pid in bus.pins]

    def _pin_label(self, pin_id: str) -> str:
        """Answer-text name for a pin: the id, with the silkscreen label in
        parens ONLY when it differs from the id (case-insensitive), e.g.
        'SDA' (silkscreen 'SDA') but 'GND_P1 (GND)'. Avoids 'SDA (SDA)'."""
        pin = self._profile.pin_by_id(pin_id)
        if pin is None:
            return pin_id
        silk = (pin.silkscreen or "").strip()
        if silk and silk.lower() != pin.id.lower():
            return f"{pin.id} ({silk})"
        return pin.id

    # -- public API ------------------------------------------------------

    def answer(self, text: str, locale: str | None = None) -> dict:
        lang = self._lang(locale)
        text_lower = (text or "").lower()

        # Pass 1: explicit protocol/bus keywords only.
        intent = next(
            (i for i in _INTENTS if any(_keyword_hit(text_lower, k) for k in i.keywords)),
            None,
        )
        # Pass 2 (only when no explicit keyword hit anywhere): generic terms.
        if intent is None:
            intent = next(
                (i for i in _INTENTS if any(_keyword_hit(text_lower, k) for k in i.generic)),
                None,
            )
        if intent is None:
            return self._no_match(lang)

        group: str | None = None
        labels: list[str]

        if intent.id in ("i2c", "spi", "uart"):
            group, pin_ids, labels = self._bus_pins(intent.id)
        elif intent.id == "power":
            group_pins = self._profile.groups.get("power_rails")
            if group_pins:
                group = "power_rails"
                pin_ids = sorted(group_pins, key=_natural_key)
            else:
                pin_ids = sorted(
                    (p.id for p in self._profile.pins_with_capability("power")),
                    key=_natural_key,
                )
            labels = pin_ids
        else:  # pwm / adc / interrupt -> capability scan
            pin_ids = sorted(
                (p.id for p in self._profile.pins_with_capability(intent.id)),
                key=_natural_key,
            )
            labels = pin_ids

        if not pin_ids:
            return self._none_available(lang, intent.id)

        answer = self._render(lang, intent.id, labels, group)
        if intent.is_io:
            answer += self._reminder(lang)
        return {"answer": answer, "pin_ids": pin_ids, "group": group, "matched": True}

    # -- answer templates --------------------------------------------------

    def _render(self, lang: str, intent_id: str, labels: list[str], group: str | None) -> str:
        pins = self._join(labels, lang)
        bus_part_zh = f"（匯流排 {group}）" if group and intent_id in ("i2c", "spi", "uart") else ""
        bus_part_en = f" (bus {group})" if group and intent_id in ("i2c", "spi", "uart") else ""
        zh = {
            "pwm": f"可以用 {pins}（支援 PWM）。",
            "i2c": f"I2C 請接 {pins}{bus_part_zh}。",
            "spi": f"SPI 請接 {pins}{bus_part_zh}。",
            "uart": f"UART/序列埠請接 {pins}{bus_part_zh}。",
            "adc": f"類比輸入請用 {pins}（ADC）。",
            "power": f"電源相關腳位：{pins}。",
            "interrupt": f"支援外部中斷：{pins}。",
        }
        en = {
            "pwm": f"Use {pins} (PWM capable).",
            "i2c": f"For I2C use {pins}{bus_part_en}.",
            "spi": f"For SPI use {pins}{bus_part_en}.",
            "uart": f"For UART/serial use {pins}{bus_part_en}.",
            "adc": f"For analog input use {pins} (ADC).",
            "power": f"Power-related pins: {pins}.",
            "interrupt": f"External-interrupt capable: {pins}.",
        }
        return (en if lang == "en" else zh)[intent_id]

    def _no_match(self, lang: str) -> dict:
        if lang == "en":
            answer = ("Sorry, I did not understand that. Try for example: "
                      f"{_EXAMPLES['en']}.")
        else:
            answer = f"抱歉，我沒聽懂。可以試試：{_EXAMPLES['zh-TW']}。"
        return {"answer": answer, "pin_ids": [], "group": None, "matched": False}

    def _none_available(self, lang: str, intent_id: str) -> dict:
        board = self._board_name(lang)
        if lang == "en":
            answer = f"No pins matching '{intent_id}' were found on {board}."
        else:
            answer = f"{board} 上找不到符合「{intent_id}」的腳位。"
        return {"answer": answer, "pin_ids": [], "group": None, "matched": True}
