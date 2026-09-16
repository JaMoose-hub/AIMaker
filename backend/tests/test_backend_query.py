"""Query-service routing / label / ordering regressions against the REAL
arduino-uno-q profile: two-pass intent matching (explicit protocol keywords
beat other intents' generic terms), silkscreen label dedupe, and natural
pin-id sorting.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.profiles.store import ProfileStore
from app.query.service import QueryService, _natural_key

PROFILES = Path(__file__).resolve().parents[2] / "profiles"


@pytest.fixture(scope="module")
def unoq() -> QueryService:
    profile = ProfileStore(PROFILES).profile("arduino-uno-q")
    return QueryService(profile, default_locale="zh-TW")


# -- two-pass intent matching ------------------------------------------------

def test_spi_with_generic_sensor_word_routes_to_spi(unoq):
    # Regression (verified live): used to misroute to i2c0 because the
    # generic 感測器模組 keyword on the i2c intent outranked the explicit SPI.
    res = unoq.answer("SPI 感測器模組要接哪裡?", "zh-TW")
    assert res["matched"] is True
    assert res["group"] == "spi0"
    assert res["pin_ids"] == ["D10", "D11", "D12", "D13"]


def test_uart_with_generic_sensor_word_routes_to_uart(unoq):
    # Regression: same misroute class for UART + generic sensor-module term.
    res = unoq.answer("UART 感測器模組要接哪裡?", "zh-TW")
    assert res["matched"] is True
    assert res["group"] == "uart0"
    assert res["pin_ids"] == ["D0", "D1"]


def test_plain_generic_sensor_query_still_routes_to_i2c(unoq):
    res = unoq.answer("溫濕度感測器模組要接哪裡?", "zh-TW")
    assert res["matched"] is True
    assert res["group"] == "i2c0"


def test_plain_spi_query(unoq):
    res = unoq.answer("SPI 要接哪裡?", "zh-TW")
    assert res["matched"] is True
    assert res["group"] == "spi0"


def test_spi_sensor_module_en(unoq):
    res = unoq.answer("Where do I connect an SPI sensor module?", "en")
    assert res["group"] == "spi0"


# -- answer label dedupe -------------------------------------------------------

def test_i2c_labels_deduped(unoq):
    res = unoq.answer("I2C 接哪裡?", "zh-TW")
    assert res["group"] == "i2c0"
    assert res["pin_ids"] == ["SDA", "SCL", "A4", "A5"]  # curated bus order
    # silkscreen == pin id (SDA/SCL/A4/A5) -> printed once, no "(SDA)" echo
    assert "SDA (SDA)" not in res["answer"]
    assert "SCL (SCL)" not in res["answer"]
    assert "SDA、SCL、A4、A5" in res["answer"]


def test_uart_labels_show_silkscreen_only_when_it_differs(unoq):
    res = unoq.answer("UART 接哪裡?", "zh-TW")
    assert res["group"] == "uart0"
    assert res["pin_ids"] == ["D0", "D1"]
    # silkscreen "0"/"1" differs from the ids -> kept in parens
    assert "D0 (0)" in res["answer"] and "D1 (1)" in res["answer"]


# -- natural pin sort ----------------------------------------------------------

def test_natural_key_ordering():
    ids = ["D10", "D3", "GND_P2", "D11", "A5", "D5", "GND_P1", "A4", "D9", "D6"]
    assert sorted(ids, key=_natural_key) == [
        "A4", "A5", "D3", "D5", "D6", "D9", "D10", "D11", "GND_P1", "GND_P2",
    ]


def test_pwm_pins_natural_sorted_in_ids_and_answer(unoq):
    res = unoq.answer("哪些腳支援 PWM?", "zh-TW")
    assert res["pin_ids"] == ["D3", "D5", "D6", "D9", "D10", "D11"]
    assert "D3、D5、D6、D9、D10、D11" in res["answer"]


def test_power_pins_natural_sorted(unoq):
    res = unoq.answer("電源腳位在哪?", "zh-TW")
    assert res["group"] == "power_rails"
    assert res["pin_ids"] == ["3V3", "5V", "GND_D", "GND_P1", "GND_P2", "IOREF", "VIN"]
