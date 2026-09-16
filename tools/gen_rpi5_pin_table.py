# -*- coding: utf-8 -*-
"""Generate profiles/boards/raspberry-pi-5/board.json.

Geometry comes from rpi_40pin_geometry.py (shared by every 40-pin Pi - HAT
compatibility fixes the header position by specification). Pin functions,
electrical limits and warning texts are Pi 5 specific and were verified
against official Raspberry Pi documentation:

  * The 40-pin header keeps the SAME physical-pin -> BCM GPIO mapping as
    earlier 40-pin models (HAT compatibility), including I2C1 on GPIO2/3,
    UART0 on GPIO14/15, SPI0 on GPIO7-11, SPI1 on GPIO16/19/20/21 and the
    HAT ID EEPROM on GPIO0/1.
  * WHAT CHANGED vs the Pi 4: the GPIO are driven by the RP1 I/O controller,
    not directly by the SoC. RP1's PWM block has FOUR independent channels,
    one each on GPIO12, GPIO13, GPIO18 and GPIO19 - on the Pi 4 there were
    only two channels, each shared between a pair of pins, so a Pi 4 could
    not drive all four pins independently. This is a real capability
    difference, not a naming change.
  * SoC is BCM2712 (4x Cortex-A76 @ 2.4 GHz).
  * GPIO remain 3.3 V and are NOT 5 V tolerant; a 5 V signal damages RP1.

Run:  backend\\.venv\\Scripts\\python.exe tools\\gen_rpi5_pin_table.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpi_40pin_geometry as geo  # noqa: E402

BOARD_ID = "raspberry-pi-5"
OUT_DIR = Path(__file__).resolve().parent.parent / "profiles" / "boards" / BOARD_ID

# --- reusable i18n fragments -------------------------------------------------
W_NOT_5V = {
    "severity": "danger",
    "text": {
        "zh-TW": "3.3V 邏輯，不耐 5V — 接上 5V 訊號會損壞 RP1 I/O 控制晶片（沒有輸入保護，且 RP1 無法更換）",
        "en": "3.3V logic, NOT 5V tolerant - a 5V signal will damage the RP1 I/O controller (no input protection, and RP1 is not replaceable)",
    },
}
W_CURRENT = {
    "severity": "warning",
    "text": {
        "zh-TW": "單腳建議上限 16mA、所有 GPIO 合計約 50mA（沿用 Pi 系列慣用值；Raspberry Pi 未公布 RP1 專屬數字）— 驅動 LED 需串電阻，馬達/繼電器需外部驅動電路",
        "en": "Keep to roughly 16 mA per pin and ~50 mA across all GPIO (the conventional Pi figure; Raspberry Pi does not publish an RP1-specific number) - use a series resistor for LEDs and an external driver for motors or relays",
    },
}
W_POWER_RAIL = {
    "severity": "warning",
    "text": {
        "zh-TW": "電源腳位，切勿接到任何 GPIO 訊號腳，否則會損壞板子",
        "en": "Power pin - never wire it to a GPIO signal pin or the board will be damaged",
    },
}

# physical pin -> (id, extra_caps, tags, description_zh, description_en)
GPIO_PINS: dict[int, tuple[str, list, list[str], str, str]] = {
    3:  ("GPIO2",  [("i2c", {"bus": "i2c1", "role": "SDA"})], ["i2c"],
         "I2C1 資料線（SDA）。Pi 的預設 I2C 匯流排，板上已有上拉電阻到 3.3V。也可當一般 GPIO。",
         "I2C1 data (SDA). The Pi's default I2C bus, with pull-ups to 3.3V on board. Also usable as plain GPIO."),
    5:  ("GPIO3",  [("i2c", {"bus": "i2c1", "role": "SCL"})], ["i2c"],
         "I2C1 時脈線（SCL），板上已有上拉電阻。也可當一般 GPIO。",
         "I2C1 clock (SCL), with on-board pull-ups. Also usable as plain GPIO."),
    7:  ("GPIO4",  [], ["gpclk"],
         "一般 GPIO，另可輸出 GPCLK0 通用時脈訊號。常被 1-Wire（DS18B20 溫度感測器）的 overlay 預設佔用。",
         "Plain GPIO; can also output the GPCLK0 general-purpose clock. Commonly claimed by the 1-Wire overlay (DS18B20 sensors)."),
    8:  ("GPIO14", [("uart", {"bus": "uart0", "role": "TXD"})], ["uart"],
         "UART0 傳送腳（TXD）。預設為序列埠主控台輸出；要當一般 GPIO 需先在 raspi-config 關閉主控台。",
         "UART0 transmit (TXD). Serial console by default - disable the console in raspi-config before using it as plain GPIO."),
    10: ("GPIO15", [("uart", {"bus": "uart0", "role": "RXD"})], ["uart"],
         "UART0 接收腳（RXD）。預設為序列埠主控台輸入，同樣須先關閉主控台。",
         "UART0 receive (RXD). Serial console by default - disable the console first."),
    11: ("GPIO17", [], [], "一般 GPIO，無預設特殊功能，適合當數位輸入或輸出。",
         "Plain GPIO with no default alternate function - a good general-purpose input or output."),
    12: ("GPIO18", [("pwm", {"channel": "PWM2"})], ["pwm", "pcm"],
         "一般 GPIO，支援硬體 PWM（RP1 的第 3 個獨立通道），也是 PCM/I2S 的位元時脈（PCM_CLK）。驅動伺服馬達最常用的腳位。",
         "Plain GPIO with hardware PWM (RP1's third independent channel); also the PCM/I2S bit clock (PCM_CLK). The most commonly used pin for driving a servo."),
    13: ("GPIO27", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    15: ("GPIO22", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    16: ("GPIO23", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    18: ("GPIO24", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    19: ("GPIO10", [("spi", {"bus": "spi0", "role": "MOSI"})], ["spi"],
         "SPI0 主控輸出（MOSI）。也可當一般 GPIO（需先停用 SPI 介面）。",
         "SPI0 master out (MOSI). Usable as plain GPIO if the SPI interface is disabled."),
    21: ("GPIO9",  [("spi", {"bus": "spi0", "role": "MISO"})], ["spi"],
         "SPI0 主控輸入（MISO）。",
         "SPI0 master in (MISO)."),
    22: ("GPIO25", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    23: ("GPIO11", [("spi", {"bus": "spi0", "role": "SCLK"})], ["spi"],
         "SPI0 時脈（SCLK）。",
         "SPI0 clock (SCLK)."),
    24: ("GPIO8",  [("spi", {"bus": "spi0", "role": "CE0"})], ["spi"],
         "SPI0 晶片選擇 0（CE0）。",
         "SPI0 chip enable 0 (CE0)."),
    26: ("GPIO7",  [("spi", {"bus": "spi0", "role": "CE1"})], ["spi"],
         "SPI0 晶片選擇 1（CE1）。",
         "SPI0 chip enable 1 (CE1)."),
    27: ("GPIO0",  [("i2c", {"bus": "i2c0", "role": "ID_SD"})], ["reserved"],
         "HAT 辨識用 EEPROM 的 I2C 資料線（ID_SD）。開機時系統用它讀取 HAT 資訊，保留腳位，請勿當一般 GPIO 使用。",
         "HAT ID EEPROM I2C data (ID_SD). The system reads HAT information through it at boot - reserved, do not use as plain GPIO."),
    28: ("GPIO1",  [("i2c", {"bus": "i2c0", "role": "ID_SC"})], ["reserved"],
         "HAT 辨識用 EEPROM 的 I2C 時脈線（ID_SC），保留腳位，請勿當一般 GPIO 使用。",
         "HAT ID EEPROM I2C clock (ID_SC) - reserved, do not use as plain GPIO."),
    29: ("GPIO5",  [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    31: ("GPIO6",  [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    32: ("GPIO12", [("pwm", {"channel": "PWM0"})], ["pwm"],
         "一般 GPIO，支援硬體 PWM（RP1 的第 1 個獨立通道）。Pi 5 的四個 PWM 通道彼此獨立，可同時使用。",
         "Plain GPIO with hardware PWM (RP1's first independent channel). The Pi 5's four PWM channels are independent and can all be used at once."),
    33: ("GPIO13", [("pwm", {"channel": "PWM1"})], ["pwm"],
         "一般 GPIO，支援硬體 PWM（RP1 的第 2 個獨立通道）。",
         "Plain GPIO with hardware PWM (RP1's second independent channel)."),
    35: ("GPIO19", [("pwm", {"channel": "PWM3"}), ("spi", {"bus": "spi1", "role": "MISO"})], ["pwm", "spi", "pcm"],
         "一般 GPIO，支援硬體 PWM（RP1 的第 4 個獨立通道），亦為 SPI1 的 MISO 與 PCM/I2S 的框同步（PCM_FS）。",
         "Plain GPIO with hardware PWM (RP1's fourth independent channel); also SPI1 MISO and the PCM/I2S frame sync (PCM_FS)."),
    36: ("GPIO16", [("spi", {"bus": "spi1", "role": "CE0"})], ["spi"],
         "一般 GPIO，亦為 SPI1 的晶片選擇 0。",
         "Plain GPIO; also SPI1 chip enable 0."),
    37: ("GPIO26", [], [], "一般 GPIO，無預設特殊功能。",
         "Plain GPIO with no default alternate function."),
    38: ("GPIO20", [("spi", {"bus": "spi1", "role": "MOSI"})], ["spi", "pcm"],
         "一般 GPIO，亦為 SPI1 的 MOSI 與 PCM/I2S 資料輸入（PCM_DIN）。",
         "Plain GPIO; also SPI1 MOSI and PCM/I2S data in (PCM_DIN)."),
    40: ("GPIO21", [("spi", {"bus": "spi1", "role": "SCLK"})], ["spi", "pcm"],
         "一般 GPIO，亦為 SPI1 時脈與 PCM/I2S 資料輸出（PCM_DOUT）。",
         "Plain GPIO; also SPI1 clock and PCM/I2S data out (PCM_DOUT)."),
}

POWER_PINS = {1: "3v3", 17: "3v3", 2: "5v", 4: "5v"}
GND_PINS = [6, 9, 14, 20, 25, 30, 34, 39]


def _gpio_pin(physical: int) -> dict:
    pin_id, extra, tags, desc_zh, desc_en = GPIO_PINS[physical]
    caps: list[dict] = [{"type": "digital_io", "mcu_pin": pin_id}]
    for cap_type, kwargs in extra:
        caps.append({"type": cap_type, **kwargs})
    caps.append({"type": "interrupt", "note": {
        "zh-TW": "支援邊緣觸發中斷（任一 GPIO 皆可）",
        "en": "Supports edge-detection interrupts (available on any GPIO)",
    }})
    warnings = [W_NOT_5V, W_CURRENT]
    if "reserved" in tags:
        warnings.insert(0, {"severity": "warning", "text": {
            "zh-TW": "保留給 HAT 辨識 EEPROM（ID_SD/ID_SC），佔用會影響 HAT 偵測",
            "en": "Reserved for the HAT ID EEPROM (ID_SD/ID_SC); using it breaks HAT detection",
        }})
    x, y = geo.profile_pin_xy_mm(physical)
    examples = []
    if "pwm" in tags:
        examples.append({"zh-TW": "驅動伺服馬達的訊號線", "en": "Drive a servo signal line"})
        examples.append({"zh-TW": "LED 呼吸燈（漸亮漸暗）", "en": "LED breathing/fade effect"})
    elif "i2c" in tags:
        examples.append({"zh-TW": "連接 I2C 溫濕度感測器或 OLED 顯示器",
                         "en": "Connect an I2C temperature/humidity sensor or OLED display"})
    elif "spi" in tags:
        examples.append({"zh-TW": "連接 SPI 顯示模組或 ADC 晶片",
                         "en": "Connect an SPI display module or ADC chip"})
    elif "uart" in tags:
        examples.append({"zh-TW": "與 GPS 模組或另一塊開發板做序列通訊",
                         "en": "Serial link to a GPS module or another board"})
    else:
        examples.append({"zh-TW": "讀取按鈕狀態（配合上拉/下拉電阻）",
                         "en": "Read a push-button state (with a pull-up or pull-down)"})
    return {
        "id": pin_id,
        "silkscreen": str(physical),
        "header": geo.HEADER_ID,
        "index": physical,
        "pos_mm": [round(x, 3), round(y, 3), geo.HEADER_TOP_Z_MM],
        "capabilities": caps,
        "description": {"zh-TW": desc_zh, "en": desc_en},
        "usage_examples": examples,
        "warnings": warnings,
        "tags": ["gpio"] + tags,
        "electrical": {"voltage": 3.3, "max_current_ma": 16, "five_volt_tolerant": False},
    }


def _power_pin(physical: int, rail: str) -> dict:
    x, y = geo.profile_pin_xy_mm(physical)
    if rail == "3v3":
        pin_id = f"3V3_P{physical}"
        desc_zh = ("3.3V 電源輸出。與 GPIO 同一個邏輯電壓，可直接供電給 3.3V 感測器。"
                   "此電源軌由板上穩壓器提供，可用電流有限（不適合驅動較耗電的模組）。")
        desc_en = ("3.3V power output - the same logic voltage as the GPIO, so it can supply 3.3V "
                   "sensors directly. It comes from the on-board regulator and its available "
                   "current is limited (not for power-hungry modules).")
        volts = 3.3
        extra_warn = [{"severity": "warning", "text": {
            "zh-TW": "3.3V 電源軌可用電流有限，較耗電的模組請改用 5V 或外部電源",
            "en": "The 3.3V rail has limited available current - power hungry modules should use 5V or an external supply",
        }}]
    else:
        pin_id = f"5V_P{physical}"
        desc_zh = ("5V 電源輸出，來自板子的輸入電源（USB-C PD）。這是「電源軌」而不是訊號腳位。"
                   "可為 5V 週邊供電，但注意其訊號腳位仍必須是 3.3V 相容。")
        desc_en = ("5V power output from the board's input supply (USB-C PD). This is a power rail, "
                   "not a signal pin. It can feed 5V peripherals, but their signal lines must still "
                   "be 3.3V compatible.")
        volts = 5.0
        extra_warn = [{"severity": "danger", "text": {
            "zh-TW": "5V 直接來自輸入電源且未經保險絲 — 短路可能損壞 Pi 或電源；且 5V 訊號絕不可回接 GPIO",
            "en": "5V is unfused and comes straight from the input supply - a short can damage the Pi or the supply, and a 5V signal must never be fed back into a GPIO",
        }}]
    return {
        "id": pin_id,
        "silkscreen": str(physical),
        "header": geo.HEADER_ID,
        "index": physical,
        "pos_mm": [round(x, 3), round(y, 3), geo.HEADER_TOP_Z_MM],
        "capabilities": [{"type": "power", "rail": rail, "direction": "output"}],
        "description": {"zh-TW": desc_zh, "en": desc_en},
        "usage_examples": [{"zh-TW": "供電給感測器模組的 VCC", "en": "Power a sensor module's VCC"}],
        "warnings": extra_warn + [W_POWER_RAIL],
        "tags": ["power", rail],
        "electrical": {"voltage": volts},
    }


def _gnd_pin(physical: int) -> dict:
    x, y = geo.profile_pin_xy_mm(physical)
    return {
        "id": f"GND_P{physical}",
        "silkscreen": str(physical),
        "header": geo.HEADER_ID,
        "index": physical,
        "pos_mm": [round(x, 3), round(y, 3), geo.HEADER_TOP_Z_MM],
        "capabilities": [{"type": "power", "rail": "gnd", "direction": "output"}],
        "description": {
            "zh-TW": ("接地腳位。Pi 上有 8 個 GND（實體腳 6/9/14/20/25/30/34/39），電氣上全部相通，"
                      "接任何一個都可以 — 選離你的訊號線最近的那個，接線最整齊。"),
            "en": ("Ground. The Pi has 8 GND pins (physical 6/9/14/20/25/30/34/39), all electrically "
                   "common, so any of them works - pick the one nearest your signal wire for the "
                   "tidiest wiring."),
        },
        "usage_examples": [{"zh-TW": "感測器模組的 GND 共地", "en": "Common ground for a sensor module"}],
        "warnings": [{"severity": "info", "text": {
            "zh-TW": "所有 GND 電氣相通；與外部電路務必共地，否則訊號會不穩定",
            "en": "All GND pins are common; always share a ground with external circuitry or signals will be unreliable",
        }}],
        "tags": ["power", "gnd"],
        "electrical": {"voltage": 0.0},
    }


def build() -> dict:
    pins = []
    for physical in range(1, 41):
        if physical in GPIO_PINS:
            pins.append(_gpio_pin(physical))
        elif physical in POWER_PINS:
            pins.append(_power_pin(physical, POWER_PINS[physical]))
        elif physical in GND_PINS:
            pins.append(_gnd_pin(physical))
        else:
            raise AssertionError(f"physical pin {physical} unassigned")
    assert len(pins) == 40, len(pins)
    assert len({p["id"] for p in pins}) == 40, "duplicate pin id"

    return {
        "schema_version": "1.0",
        "board": {
            "id": BOARD_ID,
            "name": {"zh-TW": "Raspberry Pi 5", "en": "Raspberry Pi 5"},
            "vendor": "Raspberry Pi",
            "mcu": {
                "part": "BCM2712",
                "core": "4x Arm Cortex-A76",
                "max_clock_mhz": 2400,
                "os": "Raspberry Pi OS (Linux)",
                "role_note": {
                    "zh-TW": "SoC 執行 Linux；40 支 header 腳位由獨立的 RP1 I/O 控制晶片驅動（Pi 5 與 Pi 4 的關鍵架構差異），GPIO 仍由 Linux 直接控制",
                    "en": "The SoC runs Linux; the 40 header pins are driven by a separate RP1 I/O controller (the key architectural change from the Pi 4). GPIO are still controlled directly from Linux",
                },
            },
            "logic_voltage": 3.3,
            "five_volt_tolerant": False,
            "form_factor": "raspberry-pi-b-plus",
            "outline_mm": [geo.BOARD_W_MM, geo.BOARD_H_MM],
            "header_top_z_mm": geo.HEADER_TOP_Z_MM,
            "docs_url": "https://www.raspberrypi.com/documentation/computers/raspberry-pi.html",
        },
        # Canonical Pi-5 pose-model reference. The four source corners are
        # the observed pose rectangle in reference_captured.jpg; keeping this
        # registration with the generated profile lets appearance matching
        # recover semantic corner order at 90/180/270-degree rotations.
        "reference": {
            "image": "reference_captured.jpg",
            "width_px": 1280,
            "height_px": 720,
            "mm_to_px": [
                [4.281984176820758, -0.06180215560218967, 467.6387023925781],
                [0.06537366031332315, 4.048130750339494, 376.1624450683594],
                [-4.834721112655998e-11, 2.99382856855518e-09, 1.0],
            ],
        },
        "headers": [{
            "id": geo.HEADER_ID,
            "name": {"zh-TW": "40-pin GPIO 排針（J8）", "en": "40-pin GPIO header (J8)"},
            "side": "bottom",
        }],
        "buses": [
            {"id": "i2c1", "type": "i2c", "pins": ["GPIO2", "GPIO3"], "note": {
                "zh-TW": "預設 I2C 匯流排，板上已有上拉電阻；須先在 raspi-config 啟用 I2C。Pi 5 另有更多 I2C 匯流排可用 overlay 開啟",
                "en": "The default I2C bus with on-board pull-ups; enable I2C in raspi-config first. The Pi 5 exposes additional I2C buses via overlays"}},
            {"id": "i2c0", "type": "i2c", "pins": ["GPIO0", "GPIO1"], "note": {
                "zh-TW": "保留給 HAT 辨識 EEPROM，請勿佔用",
                "en": "Reserved for the HAT ID EEPROM - do not use"}},
            {"id": "spi0", "type": "spi", "pins": ["GPIO10", "GPIO9", "GPIO11", "GPIO8", "GPIO7"], "note": {
                "zh-TW": "主要 SPI 匯流排，兩個晶片選擇（CE0/CE1）；須先啟用 SPI",
                "en": "The primary SPI bus with two chip selects (CE0/CE1); enable SPI first"}},
            {"id": "spi1", "type": "spi", "pins": ["GPIO20", "GPIO19", "GPIO21", "GPIO16"], "note": {
                "zh-TW": "第二組 SPI，需以 device tree overlay 啟用",
                "en": "A second SPI bus; needs a device-tree overlay to enable"}},
            {"id": "uart0", "type": "uart", "pins": ["GPIO14", "GPIO15"], "note": {
                "zh-TW": "預設為序列埠主控台；當一般序列埠使用前須先關閉主控台。Pi 5 另有更多 UART 可用 overlay 開啟",
                "en": "Serial console by default; disable the console before using it as a general serial port. The Pi 5 exposes additional UARTs via overlays"}},
        ],
        "groups": {
            "power_rails": [p["id"] for p in pins if "power" in p["tags"]],
            "pwm_all": [p["id"] for p in pins if "pwm" in p["tags"]],
        },
        "pins": pins,
    }


def main() -> None:
    profile = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "board.json"
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}  ({len(profile['pins'])} pins)")
    print(f"PWM pins (4 independent RP1 channels): {profile['groups']['pwm_all']}")
    if not geo.GEOMETRY_VERIFIED:
        print("\n*** HEADER GEOMETRY IS UNVERIFIED ***")
        print("    pin 1 assumed at "
              f"({geo.HEADER_PIN1_X_MM}, {geo.HEADER_ROW_NEAR_EDGE_Y_MM}) mm, "
              f"odd row near edge = {geo.ODD_ROW_IS_NEAR_EDGE}")
        print("    Verify with a straight-on photo overlay before trusting pin positions")
        print("    (see rpi_40pin_geometry.py docstring).")


if __name__ == "__main__":
    main()
