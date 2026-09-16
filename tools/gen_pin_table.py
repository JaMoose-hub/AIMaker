# -*- coding: utf-8 -*-
"""Generate profiles/boards/arduino-uno-q/board.json.

Geometry comes from uno_q_geometry.py (verified against the official UNO R3
Eagle board file — the UNO Q keeps the exact UNO form factor). Capabilities
and texts come from the structured table below, verified 2026-07-27 against:

  * Arduino UNO Q user manual (arduino/docs-content, official source of
    docs.arduino.cc/tutorials/uno-q/user-manual):
      - PWM on D3/D5/D6/D9/D10/D11, fixed 500 Hz
      - UART: D0 = USART1_RX (PB7), D1 = USART1_TX (PB6)
      - SPI carried by the header pins: D10 SS (PB9), D11 MOSI (PB15),
        D12 MISO (PB14), D13 SCK (PB13)
      - Wire (primary I2C) on the dedicated SDA/SCL header pins
        (D20 = PB11 SDA, D21 = PB10 SCL); A4 = PC1 "SDA2", A5 = PC0 "SCL2"
        (a second STM32 I2C — NOT the same MCU pins as SDA/SCL, unlike the
        classic UNO where A4/A5 are hard-wired to the SDA/SCL pins)
      - ADC: 6 channels, up to 14-bit via analogReadResolution(14)
        (0-16383); analogRead defaults to 10-bit (0-1023) on the UNO Q
        ArduinoCore-zephyr. Default reference 3.3 V, external reference via
        AREF (analogReference(AR_EXTERNAL))
      - A0/A1 also carry DAC outputs; A2/A3 carry OPAMP inputs;
        D4/D5 carry FDCAN TX/RX alternates; D3 carries the OPAMP output
      - MCU STM32U585 (Cortex-M33 @ 160 MHz, Zephyr OS),
        MPU Qualcomm QRB2210 (4x Cortex-A53 @ 2.0 GHz, Debian Linux)
      - 8x13 blue LED matrix driven by the STM32
  * etechnophiles UNO Q pinout guide: header names JDIGITAL (18 pin) /
    JANALOG (14 pin), "All digital GPIO pins work at 3.3 V logic"
  * 5 V tolerance (official datasheet §9.6 + full-pinout PDF + power-spec
    tutorial): all header digital I/O except D3 are STM32 FT-type pads —
    5 V tolerant as DIGITAL INPUTS ONLY (outputs are always 3.3 V).
    D3 (PB0) is a TT-type pad, absolute max 3.6 V in every mode.
    A0/A1 are direct ADC pins, NOT 5 V tolerant. A2-A5 are 5 V tolerant
    only when used as digital inputs, never in analog (ADC) mode.
    Encoded per pin via electrical.five_volt_tolerant + tailored warnings;
    the board-level five_volt_tolerant stays false (conservative headline).
  * A0/A1 (official power-spec tutorial): "JANALOG (A0/A1): ADC inputs
    only. Do not source or sink DC current into these pins." — encoded with
    no max_current_ma and a do-not-drive-loads warning.
  * CWTI-Ltd arduino_uno_q_knowledge_base: max current per pin 20 mA,
    total 200 mA, all I/O 3.3 V
  * Interrupts: STM32U5 EXTI — attachInterrupt is available on all header
    GPIOs (encoded on D0-D13; analog pins also usable as GPIO)
  * JANALOG position 1: BOOT (MCU_BOOT0) on the UNO Q — official ABX00162
    full-pinout PDF power block reads "BOOT IOREF RESET +3V3 +5V GND GND
    VIN"; datasheet JANALOG pin map: "1 | BOOT | MCU_BOOT0 | Boot strap |
    3.3 V". (The classic UNO R3 kept this position NC.) Sampled at reset;
    pulling it high during boot/reset drops the STM32 into the system
    bootloader.

Run:  .venv python tools/gen_pin_table.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from uno_q_geometry import (  # noqa: E402
    BOARD_H_MM,
    BOARD_W_MM,
    BOTTOM_ROW_PINS,
    HEADER_TOP_Z_MM,
    MM_TO_PX_SYNTHETIC,
    PROFILE_DIR,
    BOARD_JSON,
    REF_HEIGHT_PX,
    REF_IMAGE_NAME,
    REF_WIDTH_PX,
    TOP_ROW_PINS,
    pin_positions_mm,
    validate_board_json,
)

# ---------------------------------------------------------------------------
# Shared text fragments
# ---------------------------------------------------------------------------

# AREF only: the ADC reference input is not 5V tolerant in any mode.
DANGER_3V3 = {
    "severity": "danger",
    "text": {
        "zh-TW": "3.3V 邏輯 — 接上 5V 訊號會永久損壞板子",
        "en": "3.3V logic — connecting a 5V signal will permanently damage the board",
    },
}

# FT-type digital I/O (D0-D2, D4-D13, SDA, SCL): 5V tolerant as digital
# INPUTS only, per the official datasheet §9.6 / full-pinout PDF.
WARN_FT_5V = {
    "severity": "warning",
    "text": {
        "zh-TW": "3.3V 邏輯 — 輸出皆為 3.3V；官方標示數位輸入可耐 5V（僅輸入）。"
                 "與 5V 模組介接時建議仍用電平轉換，並絕不可將本板輸出接到需要 5V 準位的輸入",
        "en": "3.3V logic — all outputs are 3.3V; officially the pin is 5V tolerant as a "
              "digital INPUT only. Prefer a level shifter when interfacing 5V modules, and "
              "never feed this board's outputs into inputs that require 5V levels",
    },
}

# D3 (PB0) is a TT-type pad: absolute max 3.6V in EVERY mode.
DANGER_D3_TT = {
    "severity": "danger",
    "text": {
        "zh-TW": "任何模式下都不可接 5V — D3 為 TT 型 I/O，最高僅耐 3.6V，接 5V 會永久損壞",
        "en": "Never apply 5V in any mode — D3 is a TT-type I/O rated to 3.6V absolute "
              "maximum; 5V causes permanent damage",
    },
}

# A0/A1 are direct ADC pins: never 5V tolerant.
DANGER_ADC_DIRECT = {
    "severity": "danger",
    "text": {
        "zh-TW": "不耐 5V（Direct ADC 腳）— 高於 3.3V 的訊號請先分壓",
        "en": "Not 5V tolerant (direct ADC pin) — divide down any signal above 3.3V first",
    },
}

# A0/A1: ADC inputs only, must not source/sink DC current (official
# power-spec tutorial).
WARN_ADC_NO_CURRENT = {
    "severity": "warning",
    "text": {
        "zh-TW": "ADC 輸入專用 — 請勿拉/灌直流電流（不可直接驅動 LED 等負載）；"
                 "高電壓感測請用分壓電阻",
        "en": "ADC input only — do not source or sink DC current (do not drive LEDs or "
              "other loads directly); use a resistor divider for higher-voltage sensing",
    },
}

# A2-A5: headline use is analog — not 5V tolerant in ADC mode; the official
# docs mark them 5V tolerant only as plain digital inputs.
WARN_ANALOG_5V = {
    "severity": "warning",
    "text": {
        "zh-TW": "類比（ADC）模式下不耐 5V；官方文件標示僅作數位輸入時可耐 5V。"
                 "建議一律使用 3.3V 訊號",
        "en": "Not 5V tolerant in analog (ADC) mode; the official docs mark it 5V tolerant "
              "only as a digital input. Recommended: keep every signal at 3.3V",
    },
}

# FT-type digital I/O pins (5V tolerant as digital inputs only).
IO_ELECTRICAL = {"voltage": 3.3, "max_current_ma": 20.0, "five_volt_tolerant": True}
# D3 (TT-type, 3.6V abs max) and the analog-headline pins A2-A5.
IO_ELECTRICAL_NOT_5VT = {"voltage": 3.3, "max_current_ma": 20.0, "five_volt_tolerant": False}
# A0/A1: direct ADC pins — no DC current allowed, so no max_current_ma.
IO_ELECTRICAL_ADC_ONLY = {"voltage": 3.3, "five_volt_tolerant": False}


def t(zh: str, en: str) -> dict:
    return {"zh-TW": zh, "en": en}


def cap(type_: str, **kw) -> dict:
    d = {"type": type_}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


PWM_NOTE = t("PWM 頻率固定為 500 Hz", "PWM frequency is fixed at 500 Hz")
ADC_NOTE = t(
    "ADC 最高 14 位元（呼叫 analogReadResolution(14)，0–16383）；"
    "analogRead 預設 10 位元（0–1023）；預設參考電壓 3.3V",
    "ADC up to 14-bit (call analogReadResolution(14), 0-16383); analogRead "
    "defaults to 10-bit (0-1023); default reference 3.3V",
)
EXTI_NOTE = t(
    "STM32 EXTI 外部中斷（attachInterrupt）",
    "STM32 EXTI external interrupt (attachInterrupt)",
)

SERVO_EX = t("控制伺服馬達（Servo 函式庫）", "Drive a hobby servo (Servo library)")
LED_DIM_EX = t("LED 呼吸燈 / 調光（analogWrite）", "LED dimming / breathing (analogWrite)")
MOTOR_EX = t(
    "透過馬達驅動板控制直流馬達轉速",
    "DC motor speed control through a motor driver board",
)
BUTTON_EX = t(
    "按鈕輸入（搭配 INPUT_PULLUP 內部上拉）",
    "Push-button input (with INPUT_PULLUP)",
)
DIGITAL_SENSOR_EX = t(
    "讀取數位感測器輸出（PIR、傾斜開關等）",
    "Read a digital sensor output (PIR, tilt switch, ...)",
)

# ---------------------------------------------------------------------------
# Per-pin capability / text table (geometry is injected separately)
# ---------------------------------------------------------------------------
# fields: silkscreen, capabilities, electrical, description, usage_examples,
#         warnings, tags

PIN_TABLE: dict[str, dict] = {
    # ---- top row, 10-pin block --------------------------------------------
    "SCL": {
        "silkscreen": "SCL",
        "capabilities": [
            cap("i2c", role="scl", bus="i2c0", mcu_pin="PB10",
                note=t("主要 I2C 時脈（Wire，Arduino 編號 D21）",
                       "Primary I2C clock (Wire, Arduino pin D21)")),
            cap("digital_io", mcu_pin="PB10"),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "專用 I2C 時脈腳位 SCL（STM32 PB10，Arduino D21）。Wire 函式庫的預設 I2C 匯流排走這裡，"
            "與旁邊的 SDA 成對使用；匯流排上可掛多顆位址不同的 I2C 裝置。",
            "Dedicated I2C clock pin SCL (STM32 PB10, Arduino D21). The default Wire bus lives "
            "here, paired with the neighbouring SDA pin; multiple I2C devices with distinct "
            "addresses can share the bus.",
        ),
        "usage_examples": [
            t("連接 SSD1306 OLED 顯示器（I2C 位址 0x3C）", "Connect an SSD1306 OLED display (I2C address 0x3C)"),
            t("讀取 BME280 溫濕度氣壓感測器", "Read a BME280 temperature/humidity/pressure sensor"),
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["i2c", "digital"],
    },
    "SDA": {
        "silkscreen": "SDA",
        "capabilities": [
            cap("i2c", role="sda", bus="i2c0", mcu_pin="PB11",
                note=t("主要 I2C 資料（Wire，Arduino 編號 D20）",
                       "Primary I2C data (Wire, Arduino pin D20)")),
            cap("digital_io", mcu_pin="PB11"),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "專用 I2C 資料腳位 SDA（STM32 PB11，Arduino D20）。與 SCL 成對，為 Wire 函式庫預設匯流排；"
            "大多數 I2C 模組（感測器、OLED、RTC）接這兩支即可。",
            "Dedicated I2C data pin SDA (STM32 PB11, Arduino D20). Paired with SCL as the default "
            "Wire bus; most I2C modules (sensors, OLEDs, RTCs) connect to these two pins.",
        ),
        "usage_examples": [
            t("連接 I2C 感測器模組（如 MPU6050 六軸 IMU（加速度計＋陀螺儀））",
              "Connect I2C sensor modules (e.g. MPU6050 six-axis IMU, accelerometer + gyroscope)"),
            t("連接 DS3231 RTC 即時時鐘模組", "Connect a DS3231 real-time-clock module"),
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["i2c", "digital"],
    },
    "AREF": {
        "silkscreen": "AREF",
        "capabilities": [
            cap("aref",
                note=t("外部 ADC 參考電壓輸入：analogReference(AR_EXTERNAL)",
                       "External ADC reference input: analogReference(AR_EXTERNAL)")),
        ],
        "electrical": {"voltage": 3.3, "five_volt_tolerant": False},
        "description": t(
            "類比參考電壓輸入。預設 ADC 參考為 3.3V，呼叫 analogReference(AR_EXTERNAL) 後改用此腳位"
            "的外部參考電壓，可提高特定量測範圍的解析度。輸入電壓不得超過 3.3V。",
            "Analog reference voltage input. The default ADC reference is 3.3V; after calling "
            "analogReference(AR_EXTERNAL) the ADC uses the external reference supplied on this "
            "pin, improving resolution over a narrower range. Never exceed 3.3V.",
        ),
        "usage_examples": [
            t("以 2.5V 精密參考源提升 ADC 量測精度", "Use a 2.5V precision reference to improve ADC accuracy"),
        ],
        "warnings": [DANGER_3V3],
        "tags": ["analog", "reference"],
    },
    "GND_D": {
        "silkscreen": "GND",
        "capabilities": [cap("power", rail="gnd")],
        "description": t(
            "接地（數位排針側）。與板上其他 GND 腳位電氣相同，接線時選最靠近訊號線的一支即可。",
            "Ground (digital header side). Electrically identical to every other GND pin; use "
            "whichever GND is closest to your signal wiring.",
        ),
        "usage_examples": [
            t("感測器 / 模組共地", "Common ground for sensors and modules"),
        ],
        "warnings": [],
        "tags": ["power", "ground"],
    },
    "D13": {
        "silkscreen": "13",
        "capabilities": [
            cap("digital_io", mcu_pin="PB13"),
            cap("spi", role="sck", bus="spi0", mcu_pin="PB13"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D13（STM32 PB13），同時是 SPI 匯流排的 SCK 時脈腳位。使用 SPI 裝置"
            "（SD 卡、顯示器、無線模組）時由函式庫自動接管。",
            "Digital pin D13 (STM32 PB13), also the SPI bus SCK clock line. Taken over by the "
            "SPI library when talking to SPI devices (SD cards, displays, radios).",
        ),
        "usage_examples": [
            t("SPI 裝置的時脈線（SD 卡模組、TFT 顯示器）", "SPI clock line for SD-card modules or TFT displays"),
            DIGITAL_SENSOR_EX,
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "spi"],
    },
    "D12": {
        "silkscreen": "12",
        "capabilities": [
            cap("digital_io", mcu_pin="PB14"),
            cap("spi", role="miso", bus="spi0", mcu_pin="PB14"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D12（STM32 PB14），同時是 SPI 的 MISO（主入從出）資料腳位，SPI 裝置回傳資料走這裡。",
            "Digital pin D12 (STM32 PB14), also the SPI MISO (main-in, sub-out) line — data "
            "coming back from SPI devices arrives here.",
        ),
        "usage_examples": [
            t("讀取 SD 卡模組回傳的資料", "Read data returned by an SD-card module"),
            BUTTON_EX,
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "spi"],
    },
    "D11": {
        "silkscreen": "~11",
        "capabilities": [
            cap("digital_io", mcu_pin="PB15"),
            cap("pwm", mcu_pin="PB15", note=PWM_NOTE),
            cap("spi", role="mosi", bus="spi0", mcu_pin="PB15"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D11（STM32 PB15），支援 PWM 輸出，同時是 SPI 的 MOSI（主出從入）資料腳位。",
            "Digital pin D11 (STM32 PB15) with PWM output; also the SPI MOSI (main-out, sub-in) "
            "data line.",
        ),
        "usage_examples": [SERVO_EX, LED_DIM_EX,
                           t("SPI 傳送資料至 TFT 顯示器", "Send SPI data to a TFT display")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "pwm", "spi"],
    },
    "D10": {
        "silkscreen": "~10",
        "capabilities": [
            cap("digital_io", mcu_pin="PB9"),
            cap("pwm", mcu_pin="PB9", note=PWM_NOTE),
            cap("spi", role="cs", bus="spi0", mcu_pin="PB9",
                note=t("SPI 晶片選擇（SS）", "SPI chip select (SS)")),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D10（STM32 PB9），支援 PWM 輸出，同時是 SPI 的預設晶片選擇（SS/CS）腳位。"
            "多顆 SPI 裝置時，每顆裝置各用一支 GPIO 作 CS。",
            "Digital pin D10 (STM32 PB9) with PWM output; also the default SPI chip-select "
            "(SS/CS). With multiple SPI devices, give each one its own GPIO as CS.",
        ),
        "usage_examples": [SERVO_EX,
                           t("作為 SD 卡模組的 CS 腳位", "Chip-select for an SD-card module")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "pwm", "spi"],
    },
    "D9": {
        "silkscreen": "~9",
        "capabilities": [
            cap("digital_io", mcu_pin="PB8"),
            cap("pwm", mcu_pin="PB8", note=PWM_NOTE),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D9（STM32 PB8），支援 PWM 輸出，經典的伺服馬達 / LED 調光腳位。",
            "Digital pin D9 (STM32 PB8) with PWM output — a classic choice for servos and LED "
            "dimming.",
        ),
        "usage_examples": [SERVO_EX, LED_DIM_EX],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "pwm"],
    },
    "D8": {
        "silkscreen": "8",
        "capabilities": [
            cap("digital_io", mcu_pin="PB4"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "泛用數位 I/O 腳位 D8（STM32 PB4），可作輸入或輸出，適合按鈕、繼電器模組、指示燈等。",
            "General-purpose digital I/O pin D8 (STM32 PB4) for input or output — buttons, relay "
            "modules, indicator LEDs and similar.",
        ),
        "usage_examples": [BUTTON_EX,
                           t("驅動繼電器模組（經電晶體/模組輸入端）", "Drive a relay module input")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital"],
    },
    # ---- top row, 8-pin block ---------------------------------------------
    "D7": {
        "silkscreen": "7",
        "capabilities": [
            cap("digital_io", mcu_pin="PB2"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "泛用數位 I/O 腳位 D7（STM32 PB2），無特殊複用功能，最適合當單純的輸入/輸出使用。",
            "General-purpose digital I/O pin D7 (STM32 PB2) with no special alternate function — "
            "ideal as a plain input/output.",
        ),
        "usage_examples": [DIGITAL_SENSOR_EX,
                           t("超音波模組 HC-SR04 的 Trig/Echo 腳位", "Trig/Echo line for an HC-SR04 ultrasonic module")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital"],
    },
    "D6": {
        "silkscreen": "~6",
        "capabilities": [
            cap("digital_io", mcu_pin="PB1"),
            cap("pwm", mcu_pin="PB1", note=PWM_NOTE),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D6（STM32 PB1），支援 PWM 輸出，適合調光、馬達速度控制與伺服馬達。",
            "Digital pin D6 (STM32 PB1) with PWM output — good for dimming, motor speed control "
            "and servos.",
        ),
        "usage_examples": [SERVO_EX, MOTOR_EX],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "pwm"],
    },
    "D5": {
        "silkscreen": "~5",
        "capabilities": [
            cap("digital_io", mcu_pin="PA11"),
            cap("pwm", mcu_pin="PA11", note=PWM_NOTE),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D5（STM32 PA11），支援 PWM 輸出；亦為 FDCAN 匯流排 RX 的替代功能腳位"
            "（需外接 CAN 收發器）。",
            "Digital pin D5 (STM32 PA11) with PWM output; also the FDCAN bus RX alternate "
            "function (external CAN transceiver required).",
        ),
        "usage_examples": [SERVO_EX, LED_DIM_EX,
                           t("搭配 D4 與 CAN 收發器連接 CAN 匯流排", "CAN bus with D4 and a CAN transceiver")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "pwm", "can"],
    },
    "D4": {
        "silkscreen": "4",
        "capabilities": [
            cap("digital_io", mcu_pin="PA12",
                note=t("亦為 FDCAN 匯流排 TX 替代功能", "Also the FDCAN bus TX alternate function")),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "泛用數位 I/O 腳位 D4（STM32 PA12）；亦為 FDCAN 匯流排 TX 的替代功能腳位"
            "（需外接 CAN 收發器）。",
            "General-purpose digital I/O pin D4 (STM32 PA12); also the FDCAN bus TX alternate "
            "function (external CAN transceiver required).",
        ),
        "usage_examples": [BUTTON_EX,
                           t("搭配 D5 與 CAN 收發器連接 CAN 匯流排", "CAN bus with D5 and a CAN transceiver")],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "can"],
    },
    "D3": {
        "silkscreen": "~3",
        "capabilities": [
            cap("digital_io", mcu_pin="PB0",
                note=t("亦為運算放大器（OPAMP）輸出", "Also the operational-amplifier (OPAMP) output")),
            cap("pwm", mcu_pin="PB0", note=PWM_NOTE),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL_NOT_5VT,
        "description": t(
            "數位腳位 D3（STM32 PB0），支援 PWM 輸出，亦是內建運算放大器的輸出腳位。",
            "Digital pin D3 (STM32 PB0) with PWM output; also the output of the built-in "
            "operational amplifier.",
        ),
        "usage_examples": [SERVO_EX, LED_DIM_EX, MOTOR_EX],
        "warnings": [DANGER_D3_TT],
        "tags": ["digital", "pwm"],
    },
    "D2": {
        "silkscreen": "2",
        "capabilities": [
            cap("digital_io", mcu_pin="PB3"),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "泛用數位 I/O 腳位 D2（STM32 PB3），傳統上常用來接外部中斷訊號（按鈕、編碼器、感測器警報）。",
            "General-purpose digital I/O pin D2 (STM32 PB3), traditionally used for external "
            "interrupt sources (buttons, encoders, sensor alerts).",
        ),
        "usage_examples": [
            t("旋轉編碼器的 A 相中斷輸入", "Interrupt input for a rotary-encoder A phase"),
            BUTTON_EX,
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "interrupt"],
    },
    "D1": {
        "silkscreen": "1",
        "capabilities": [
            cap("digital_io", mcu_pin="PB6"),
            cap("uart", role="tx", bus="uart0", mcu_pin="PB6",
                note=t("USART1 傳送（TX）", "USART1 transmit (TX)")),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D1（STM32 PB6），同時是硬體 UART 的 TX（傳送）腳位。使用序列埠與外部裝置"
            "通訊時，避免把它當一般 GPIO。",
            "Digital pin D1 (STM32 PB6), also the hardware UART TX (transmit) line. Avoid using "
            "it as plain GPIO while the serial port is talking to an external device.",
        ),
        "usage_examples": [
            t("傳送指令給序列裝置（如 DFPlayer MP3 模組）", "Send commands to a serial device (e.g. DFPlayer MP3 module)"),
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "uart"],
    },
    "D0": {
        "silkscreen": "0",
        "capabilities": [
            cap("digital_io", mcu_pin="PB7"),
            cap("uart", role="rx", bus="uart0", mcu_pin="PB7",
                note=t("USART1 接收（RX）", "USART1 receive (RX)")),
            cap("interrupt", note=EXTI_NOTE),
        ],
        "electrical": IO_ELECTRICAL,
        "description": t(
            "數位腳位 D0（STM32 PB7），同時是硬體 UART 的 RX（接收）腳位。使用序列埠時避免"
            "把它當一般 GPIO。",
            "Digital pin D0 (STM32 PB7), also the hardware UART RX (receive) line. Avoid using it "
            "as plain GPIO while the serial port is in use.",
        ),
        "usage_examples": [
            t("接收 GPS 模組的 NMEA 序列資料", "Receive NMEA serial data from a GPS module"),
        ],
        "warnings": [WARN_FT_5V],
        "tags": ["digital", "uart"],
    },
    # ---- bottom row, power block ------------------------------------------
    "BOOT": {
        "silkscreen": "BOOT",
        "capabilities": [
            cap("boot",
                note=t(
                    "STM32 BOOT0 開機模式選腳（官方腳位圖標示 BOOT / MCU_BOOT0），"
                    "於 reset 時取樣以決定開機來源",
                    "STM32 BOOT0 boot-mode strap (official pinout: BOOT / MCU_BOOT0), "
                    "sampled at reset to select the boot source",
                )),
        ],
        "electrical": {"voltage": 3.3},
        "description": t(
            "STM32U585 開機模式選腳（MCU_BOOT0），reset 時取樣。平常保持不接或低電位即可正常開機；"
            "官方 ABX00162 完整腳位圖將此位置標示為 BOOT（傳統 UNO R3 此位置為 NC）。",
            "STM32U585 boot-mode strap pin (MCU_BOOT0), sampled at reset. Leave it unconnected "
            "or low for normal boot; the official ABX00162 full-pinout diagram labels this "
            "position BOOT (the classic UNO R3 kept it NC).",
        ),
        "usage_examples": [
            t("進階用途：reset 時拉高可強制 STM32 進入系統 bootloader（韌體救援）",
              "Advanced: hold high through reset to force the STM32 system bootloader "
              "(firmware recovery)"),
        ],
        "warnings": [
            {"severity": "danger",
             "text": t("開機/重置期間請勿拉高此腳，否則 MCU 會進入系統 bootloader 而不執行程式",
                       "Do not pull this pin high during boot/reset, or the MCU will enter the "
                       "system bootloader instead of running your program")},
        ],
        "tags": ["system", "boot"],
    },
    "IOREF": {
        "silkscreen": "IOREF",
        "capabilities": [
            cap("power", rail="ioref", direction="output",
                note=t("向擴充板宣告本板 I/O 邏輯電壓（3.3V）",
                       "Tells shields this board's I/O logic voltage (3.3V)")),
        ],
        "electrical": {"voltage": 3.3},
        "description": t(
            "I/O 參考電壓腳位。擴充板（shield）讀取此腳位得知主板邏輯電壓；UNO Q 為 3.3V"
            "（傳統 UNO R3 為 5V，選購擴充板時務必確認相容 3.3V）。",
            "I/O reference voltage pin. Shields read it to learn the host board's logic voltage; "
            "on the UNO Q it is 3.3V (the classic UNO R3 was 5V — check shield compatibility).",
        ),
        "usage_examples": [
            t("支援雙電壓的擴充板據此自動切換準位", "Dual-voltage shields use it to auto-select their level"),
        ],
        "warnings": [],
        "tags": ["power"],
    },
    "RESET": {
        "silkscreen": "RESET",
        "capabilities": [
            cap("reset",
                note=t("低電位觸發：拉到 GND 會重置 STM32", "Active-low: pulling to GND resets the STM32")),
        ],
        "electrical": {"voltage": 3.3},
        "description": t(
            "重置腳位（低電位有效）。把它接到 GND 會重置 STM32 微控制器；擴充板的 RESET 按鈕"
            "也是接到這裡。",
            "Reset pin (active low). Pulling it to GND resets the STM32 microcontroller; shield "
            "reset buttons connect here.",
        ),
        "usage_examples": [
            t("外接重置按鈕（按下時接地）", "External reset button (shorts to ground when pressed)"),
        ],
        "warnings": [],
        "tags": ["system"],
    },
    "3V3": {
        "silkscreen": "3V3",
        "capabilities": [
            cap("power", rail="3v3", direction="output"),
        ],
        "electrical": {"voltage": 3.3},
        "description": t(
            "3.3V 電源輸出，供感測器與模組使用。UNO Q 的邏輯電壓即為 3.3V，多數 3.3V 模組"
            "可直接由此供電。",
            "3.3V power output for sensors and modules. The UNO Q's logic level is 3.3V, so most "
            "3.3V modules can be powered directly from this pin.",
        ),
        "usage_examples": [
            t("供電給 3.3V 感測器模組（BME280、MPU6050）", "Power 3.3V sensor modules (BME280, MPU6050)"),
        ],
        "warnings": [
            {"severity": "info",
             "text": t("輸出電流能力有限，大負載（馬達、燈條）請用外部電源",
                       "Limited output current — power heavy loads (motors, LED strips) externally")},
        ],
        "tags": ["power"],
    },
    "5V": {
        "silkscreen": "5V",
        "capabilities": [
            cap("power", rail="5v", direction="bidirectional",
                note=t("USB-C 供電時輸出 5V；也可由穩壓 5V 電源反向供電給板子",
                       "Outputs 5V when USB-C powered; the board can also be powered by a "
                       "regulated 5V supply on this pin")),
        ],
        "electrical": {"voltage": 5.0},
        "description": t(
            "5V 電源腳位。這是「電源軌」而不是訊號腳位 — UNO Q 的 I/O 全部是 3.3V 邏輯。"
            "可為 5V 週邊（如部分 LED 條、繼電器模組電源端）供電，或以穩壓 5V 由此供電給板子。",
            "5V power rail — a supply pin, not a signal pin (all UNO Q I/O is 3.3V logic). Use it "
            "to feed 5V peripherals (some LED strips, relay module supply inputs) or to power the "
            "board from a regulated 5V source.",
        ),
        "usage_examples": [
            t("供電給 5V 繼電器模組的 VCC（控制訊號仍須 3.3V 相容）",
              "Power a 5V relay module's VCC (its control input must still accept 3.3V)"),
        ],
        "warnings": [
            {"severity": "warning",
             "text": t("電源腳位，切勿接到任何 I/O 訊號腳，否則會損壞板子",
                       "Power pin — never wire it to any I/O signal pin or the board will be damaged")},
        ],
        "tags": ["power"],
    },
    "GND_P1": {
        "silkscreen": "GND",
        "capabilities": [cap("power", rail="gnd")],
        "description": t(
            "接地（電源排針，第一支）。與板上其他 GND 電氣相同。",
            "Ground (power header, first of two). Electrically identical to every other GND.",
        ),
        "usage_examples": [t("電源與訊號共地", "Common ground for power and signals")],
        "warnings": [],
        "tags": ["power", "ground"],
    },
    "GND_P2": {
        "silkscreen": "GND",
        "capabilities": [cap("power", rail="gnd")],
        "description": t(
            "接地（電源排針，第二支）。與板上其他 GND 電氣相同。",
            "Ground (power header, second of two). Electrically identical to every other GND.",
        ),
        "usage_examples": [t("電源與訊號共地", "Common ground for power and signals")],
        "warnings": [],
        "tags": ["power", "ground"],
    },
    "VIN": {
        "silkscreen": "VIN",
        "capabilities": [
            cap("power", rail="vin", direction="input",
                note=t("外部電源輸入 7–24 VDC", "External supply input, 7-24 VDC")),
        ],
        "description": t(
            "外部電源輸入腳位，接受 7–24 VDC，經板上穩壓器供電給整塊板子。",
            "External power input pin accepting 7-24 VDC, feeding the whole board through the "
            "on-board regulator.",
        ),
        "usage_examples": [
            t("以 12V 電源供應器為專題供電", "Power a project from a 12V wall supply"),
        ],
        "warnings": [
            {"severity": "warning",
             "text": t("僅限 7–24V 輸入並注意極性；請勿由此腳位取電驅動大負載",
                       "7-24V input only, mind the polarity; do not use it as a high-current output")},
        ],
        "tags": ["power"],
    },
    # ---- bottom row, analog block -----------------------------------------
    "A0": {
        "silkscreen": "A0",
        "capabilities": [
            cap("adc", channel="A0", mcu_pin="PA4", note=ADC_NOTE),
            cap("digital_io", mcu_pin="PA4",
                note=t("亦支援 DAC 類比輸出", "Also supports DAC analog output")),
        ],
        "electrical": IO_ELECTRICAL_ADC_ONLY,
        "description": t(
            "類比輸入腳位 A0（STM32 PA4），analogRead 預設 10 位元（0–1023），可呼叫 "
            "analogReadResolution(14) 提升至 14 位元（0–16383），量測範圍 0–3.3V；"
            "同時是 DAC 類比輸出腳位，也可當一般數位 I/O。",
            "Analog input A0 (STM32 PA4); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(0-16383) via analogReadResolution(14), over 0-3.3V; also a DAC analog output and "
            "usable as plain digital I/O.",
        ),
        "usage_examples": [
            t("讀取可變電阻旋鈕位置", "Read a potentiometer knob position"),
            t("以 DAC 輸出產生類比波形", "Generate an analog waveform with the DAC"),
        ],
        "warnings": [DANGER_ADC_DIRECT, WARN_ADC_NO_CURRENT],
        "tags": ["analog", "adc", "dac"],
    },
    "A1": {
        "silkscreen": "A1",
        "capabilities": [
            cap("adc", channel="A1", mcu_pin="PA5", note=ADC_NOTE),
            cap("digital_io", mcu_pin="PA5",
                note=t("亦支援 DAC 類比輸出", "Also supports DAC analog output")),
        ],
        "electrical": IO_ELECTRICAL_ADC_ONLY,
        "description": t(
            "類比輸入腳位 A1（STM32 PA5），analogRead 預設 10 位元（0–1023），可呼叫 "
            "analogReadResolution(14) 提升至 14 位元（0–16383），量測 0–3.3V；同時是第二個 DAC "
            "類比輸出腳位，也可當一般數位 I/O。",
            "Analog input A1 (STM32 PA5); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(0-16383) via analogReadResolution(14), over 0-3.3V; also the second DAC analog "
            "output and usable as plain digital I/O.",
        ),
        "usage_examples": [
            t("讀取光敏電阻（LDR）分壓", "Read an LDR light-sensor voltage divider"),
        ],
        "warnings": [DANGER_ADC_DIRECT, WARN_ADC_NO_CURRENT],
        "tags": ["analog", "adc", "dac"],
    },
    "A2": {
        "silkscreen": "A2",
        "capabilities": [
            cap("adc", channel="A2", mcu_pin="PA6",
                note=t("亦為 OPAMP 同相輸入（IN+）", "Also the OPAMP non-inverting input (IN+)")),
            cap("digital_io", mcu_pin="PA6"),
        ],
        "electrical": IO_ELECTRICAL_NOT_5VT,
        "description": t(
            "類比輸入腳位 A2（STM32 PA6），analogRead 預設 10 位元（0–1023），最高 14 位元"
            "（analogReadResolution(14)，0–16383）；亦為內建運算放大器的同相輸入（IN+），"
            "可搭配 D3（輸出）與 A3（IN−）組成放大電路。",
            "Analog input A2 (STM32 PA6); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(analogReadResolution(14), 0-16383); also the built-in OPAMP non-inverting input "
            "(IN+), usable with D3 (output) and A3 (IN-) as an amplifier.",
        ),
        "usage_examples": [
            t("量測土壤濕度感測器輸出", "Measure a soil-moisture sensor output"),
        ],
        "warnings": [WARN_ANALOG_5V],
        "tags": ["analog", "adc"],
    },
    "A3": {
        "silkscreen": "A3",
        "capabilities": [
            cap("adc", channel="A3", mcu_pin="PA7",
                note=t("亦為 OPAMP 反相輸入（IN−）", "Also the OPAMP inverting input (IN-)")),
            cap("digital_io", mcu_pin="PA7"),
        ],
        "electrical": IO_ELECTRICAL_NOT_5VT,
        "description": t(
            "類比輸入腳位 A3（STM32 PA7），analogRead 預設 10 位元（0–1023），最高 14 位元"
            "（analogReadResolution(14)，0–16383）；亦為內建運算放大器的反相輸入（IN−）。",
            "Analog input A3 (STM32 PA7); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(analogReadResolution(14), 0-16383); also the built-in OPAMP inverting input (IN-).",
        ),
        "usage_examples": [
            t("量測電流感測模組（如 ACS712 的 3.3V 版本）輸出",
              "Measure a current-sensor module output (3.3V-compatible types)"),
        ],
        "warnings": [WARN_ANALOG_5V],
        "tags": ["analog", "adc"],
    },
    "A4": {
        "silkscreen": "A4",
        "capabilities": [
            cap("adc", channel="A4", mcu_pin="PC1", note=ADC_NOTE),
            cap("i2c", role="sda", bus="i2c0", mcu_pin="PC1",
                note=t(
                    "第二組 I2C 資料（SDA2）。優先使用專用 SDA/SCL；UNO Q 上 A4/A5 對應 STM32 "
                    "另一組 I2C 腳位（PC1/PC0），與專用 SDA/SCL（PB11/PB10）不是同一組 MCU 腳位",
                    "Secondary I2C data (SDA2). Prefer the dedicated SDA/SCL pins; on the UNO Q "
                    "A4/A5 map to a different STM32 I2C (PC1/PC0) than the dedicated SDA/SCL "
                    "(PB11/PB10)",
                )),
            cap("digital_io", mcu_pin="PC1"),
        ],
        "electrical": IO_ELECTRICAL_NOT_5VT,
        "description": t(
            "類比輸入腳位 A4（STM32 PC1），analogRead 預設 10 位元（0–1023），最高 14 位元"
            "（analogReadResolution(14)，0–16383）；亦標示為 SDA2 —— 第二組 I2C 的資料腳位。"
            "接 I2C 模組時建議優先使用專用 SDA/SCL 腳位。",
            "Analog input A4 (STM32 PC1); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(analogReadResolution(14), 0-16383); also labelled SDA2 — the data line of a "
            "secondary I2C. Prefer the dedicated SDA/SCL pins for I2C modules.",
        ),
        "usage_examples": [
            t("讀取搖桿模組的 X 軸電壓", "Read a joystick module's X-axis voltage"),
        ],
        "warnings": [WARN_ANALOG_5V],
        "tags": ["analog", "adc", "i2c"],
    },
    "A5": {
        "silkscreen": "A5",
        "capabilities": [
            cap("adc", channel="A5", mcu_pin="PC0", note=ADC_NOTE),
            cap("i2c", role="scl", bus="i2c0", mcu_pin="PC0",
                note=t(
                    "第二組 I2C 時脈（SCL2）。優先使用專用 SDA/SCL；UNO Q 上 A4/A5 對應 STM32 "
                    "另一組 I2C 腳位（PC1/PC0），與專用 SDA/SCL（PB11/PB10）不是同一組 MCU 腳位",
                    "Secondary I2C clock (SCL2). Prefer the dedicated SDA/SCL pins; on the UNO Q "
                    "A4/A5 map to a different STM32 I2C (PC1/PC0) than the dedicated SDA/SCL "
                    "(PB11/PB10)",
                )),
            cap("digital_io", mcu_pin="PC0"),
        ],
        "electrical": IO_ELECTRICAL_NOT_5VT,
        "description": t(
            "類比輸入腳位 A5（STM32 PC0），analogRead 預設 10 位元（0–1023），最高 14 位元"
            "（analogReadResolution(14)，0–16383）；亦標示為 SCL2 —— 第二組 I2C 的時脈腳位。"
            "接 I2C 模組時建議優先使用專用 SDA/SCL 腳位。",
            "Analog input A5 (STM32 PC0); analogRead defaults to 10-bit (0-1023), up to 14-bit "
            "(analogReadResolution(14), 0-16383); also labelled SCL2 — the clock line of a "
            "secondary I2C. Prefer the dedicated SDA/SCL pins for I2C modules.",
        ),
        "usage_examples": [
            t("讀取搖桿模組的 Y 軸電壓", "Read a joystick module's Y-axis voltage"),
        ],
        "warnings": [WARN_ANALOG_5V],
        "tags": ["analog", "adc", "i2c"],
    },
}

# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------


def build_profile() -> dict:
    positions = pin_positions_mm()

    pins: list[dict] = []
    for header_id, row in (("JDIGITAL", TOP_ROW_PINS), ("JANALOG", BOTTOM_ROW_PINS)):
        for index, (pin_id, _x) in enumerate(row):
            meta = PIN_TABLE[pin_id]
            x, y, z = positions[pin_id]
            pin = {
                "id": pin_id,
                "silkscreen": meta["silkscreen"],
                "header": header_id,
                "index": index,
                "pos_mm": [x, y, z],
                "capabilities": meta["capabilities"],
                "description": meta["description"],
                "usage_examples": meta["usage_examples"],
                "warnings": meta["warnings"],
                "tags": meta["tags"],
            }
            if meta.get("electrical") is not None:
                pin["electrical"] = meta["electrical"]
            pins.append(pin)

    profile = {
        "schema_version": "1.0",
        "board": {
            "id": "arduino-uno-q",
            "name": t("Arduino UNO Q", "Arduino UNO Q"),
            "vendor": "Arduino",
            "revision": "ABX00162",
            "mcu": {
                "part": "STM32U585",
                "core": "Arm Cortex-M33",
                "max_clock_mhz": 160.0,
                "os": "Zephyr OS",
                "role_note": t(
                    "即時控制器：所有排針 I/O 都由 STM32 控制，Arduino sketch 在 Zephyr OS 上執行",
                    "Real-time controller: every header I/O is driven by the STM32; Arduino "
                    "sketches run on Zephyr OS",
                ),
            },
            "mpu": {
                "part": "Qualcomm QRB2210",
                "core": "4x Arm Cortex-A53",
                "max_clock_mhz": 2000.0,
                "os": "Debian Linux",
                "role_note": t(
                    "應用處理器：執行 Debian Linux（App Lab、Python 等），經內部匯流排與 STM32 溝通，"
                    "不直接控制排針",
                    "Application processor running Debian Linux (App Lab, Python, ...); talks to "
                    "the STM32 over an internal bus and does not drive the headers directly",
                ),
            },
            "logic_voltage": 3.3,
            "five_volt_tolerant": False,
            "form_factor": "arduino-uno-r3",
            "outline_mm": [BOARD_W_MM, BOARD_H_MM],
            "header_top_z_mm": HEADER_TOP_Z_MM,
            "docs_url": "https://docs.arduino.cc/hardware/uno-q/",
        },
        "reference": {
            "image": REF_IMAGE_NAME,
            "width_px": REF_WIDTH_PX,
            "height_px": REF_HEIGHT_PX,
            "mm_to_px": MM_TO_PX_SYNTHETIC,
        },
        "headers": [
            {
                "id": "JDIGITAL",
                "name": t("數位排針（上排）", "Digital header (top row)"),
                "side": "top",
            },
            {
                "id": "JANALOG",
                "name": t("電源與類比排針（下排）", "Power & analog header (bottom row)"),
                "side": "bottom",
            },
        ],
        "buses": [
            {
                "id": "i2c0",
                "type": "i2c",
                "pins": ["SDA", "SCL", "A4", "A5"],
                "note": t(
                    "優先使用專用 SDA/SCL。注意：UNO Q 上 A4/A5 對應 STM32 第二組 I2C"
                    "（SDA2/SCL2，PC1/PC0），與專用 SDA/SCL（PB11/PB10）並非同一組 MCU 腳位"
                    "（與傳統 UNO 不同）；官方 Wire 函式庫使用專用 SDA/SCL",
                    "Prefer the dedicated SDA/SCL pins. Note: on the UNO Q, A4/A5 map to a second "
                    "STM32 I2C (SDA2/SCL2 on PC1/PC0) — not the same MCU pins as the dedicated "
                    "SDA/SCL (PB11/PB10), unlike the classic UNO; the stock Wire library uses the "
                    "dedicated pins",
                ),
            },
            {
                "id": "spi0",
                "type": "spi",
                "pins": ["D10", "D11", "D12", "D13"],
                "note": t(
                    "SPI 直接由排針 D10–D13 提供（SS/MOSI/MISO/SCK = PB9/PB15/PB14/PB13）",
                    "SPI is carried by header pins D10-D13 (SS/MOSI/MISO/SCK = "
                    "PB9/PB15/PB14/PB13)",
                ),
            },
            {
                "id": "uart0",
                "type": "uart",
                "pins": ["D0", "D1"],
                "note": t(
                    "硬體序列埠 USART1：D0 = RX（PB7）、D1 = TX（PB6），3.3V 準位",
                    "Hardware serial USART1: D0 = RX (PB7), D1 = TX (PB6), 3.3V levels",
                ),
            },
        ],
        "groups": {
            "power_rails": ["3V3", "5V", "GND_D", "GND_P1", "GND_P2", "VIN", "IOREF"],
            "pwm_all": ["D3", "D5", "D6", "D9", "D10", "D11"],
        },
        "pins": pins,
    }
    return profile


def main() -> None:
    profile = build_profile()

    assert len(profile["pins"]) == 32, f"expected 32 pins, got {len(profile['pins'])}"
    ids = [p["id"] for p in profile["pins"]]
    assert len(set(ids)) == 32, "duplicate pin ids"
    # Every bus/group member must exist.
    for bus in profile["buses"]:
        for pid in bus["pins"]:
            assert pid in ids, f"bus {bus['id']} references unknown pin {pid}"
    for gname, members in profile["groups"].items():
        for pid in members:
            assert pid in ids, f"group {gname} references unknown pin {pid}"
    # Every I/O-capable pin carries a voltage-tolerance warning (severity
    # warning/danger, mentioning 5V or 3.3V). Pins that are NOT 5V tolerant
    # even as inputs (TT-type D3, direct-ADC A0/A1, and AREF) must carry a
    # danger-severity warning and five_volt_tolerant=False.
    io_types = {"digital_io", "adc", "pwm", "i2c", "spi", "uart", "aref"}
    hard_danger = {"D3", "A0", "A1", "AREF"}
    for p in profile["pins"]:
        if not any(c["type"] in io_types for c in p["capabilities"]):
            continue
        assert any(
            w["severity"] in ("warning", "danger")
            and ("5V" in w["text"]["zh-TW"] or "3.3V" in w["text"]["zh-TW"])
            for w in p["warnings"]
        ), f"pin {p['id']} is I/O-capable but lacks a voltage-tolerance warning"
        assert p["electrical"].get("five_volt_tolerant") is not None, \
            f"pin {p['id']} is I/O-capable but electrical.five_volt_tolerant is unset"
        if p["id"] in hard_danger:
            assert any(w["severity"] == "danger" for w in p["warnings"]), \
                f"pin {p['id']} must carry a danger-severity 5V warning"
            assert p["electrical"]["five_volt_tolerant"] is False
    # A0/A1: ADC inputs only — no DC current rating, explicit no-load warning.
    for pid in ("A0", "A1"):
        pin = next(p for p in profile["pins"] if p["id"] == pid)
        assert "max_current_ma" not in pin["electrical"], \
            f"pin {pid} must not advertise a DC current rating"
        assert any("直流電流" in w["text"]["zh-TW"] for w in pin["warnings"]), \
            f"pin {pid} lacks the do-not-source/sink-DC-current warning"

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    BOARD_JSON.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[gen_pin_table] wrote {BOARD_JSON} ({len(profile['pins'])} pins)")

    validate_board_json(BOARD_JSON)


if __name__ == "__main__":
    main()
