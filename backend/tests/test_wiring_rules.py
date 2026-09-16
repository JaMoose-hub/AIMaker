import json
from pathlib import Path
from app.components.models import ComponentSpec

from app.components.resolver import resolve_assignment
from app.components.store import ComponentStore
from app.profiles.store import ProfileStore


ROOT = Path(__file__).resolve().parents[2]


def _stores():
    return (
        ProfileStore(ROOT / "profiles").profile("arduino-uno-q"),
        ComponentStore(ROOT / "profiles" / "components"),
    )


def test_hcsr04_valid_assignment_passes():
    profile, components = _stores()
    result = resolve_assignment(profile, components.get("hc-sr04"), {
        "VCC": "5V", "GND": "GND_D", "TRIG": "D7", "ECHO": "D8",
    })
    assert result["ok"] is True
    assert result["status"] == "valid"
    assert result["issues"] == []


def test_hcsr04_5v_echo_to_non_tolerant_pin_is_danger():
    profile, components = _stores()
    result = resolve_assignment(profile, components.get("hc-sr04"), {
        "VCC": "5V", "GND": "GND_D", "TRIG": "D7", "ECHO": "D3",
    })
    assert result["ok"] is False
    assert any(issue["code"] == "voltage_risk" for issue in result["issues"])


def test_hw123_pi5_i2c_assignment_passes_and_sda_scl_swap_fails():
    profile = ProfileStore(ROOT / "profiles").profile("raspberry-pi-5")
    components = ComponentStore(ROOT / "profiles" / "components")
    # Archived fixture keeps generic I2C rule coverage; the live store rejects this retired part.
    sensor = ComponentSpec.model_validate(json.loads((ROOT / "profiles/components/hw-123/component.json").read_text(encoding="utf-8")))

    valid = resolve_assignment(profile, sensor, {
        "VCC": "3V3_P1",
        "GND": "GND_P6",
        "SCL": "GPIO3",
        "SDA": "GPIO2",
    })
    assert valid["ok"] is True
    assert valid["status"] == "valid"

    swapped = resolve_assignment(profile, sensor, {
        "VCC": "3V3_P1",
        "GND": "GND_P6",
        "SCL": "GPIO2",
        "SDA": "GPIO3",
    })
    assert swapped["ok"] is False
    assert any(issue["code"] == "i2c_role_mismatch" for issue in swapped["issues"])


def test_common_power_and_ground_errors_are_explicit():
    profile, components = _stores()
    result = resolve_assignment(profile, components.get("sg90-servo"), {
        "VCC": "GND_D", "GND": "5V", "SIGNAL": "D9",
    })
    codes = {issue["code"] for issue in result["issues"]}
    assert result["ok"] is False
    assert {"vcc_to_gnd", "gnd_to_power"}.issubset(codes)


def test_uart_direction_and_i2c_swap_are_rejected():
    profile, components = _stores()
    servo = components.get("sg90-servo")
    # A small local spec-like object is unnecessary: use the real board
    # capabilities through the component model constructor.
    from app.components.models import ComponentPin, ComponentSpec

    uart = ComponentSpec(
        schema_version="1.0", id="uart-test", version="1.0.0", name={},
        pins=[
            ComponentPin(id="TX", role="uart_tx", direction="output"),
            ComponentPin(id="RX", role="uart_rx", direction="input"),
        ],
    )
    result = resolve_assignment(profile, uart, {"TX": "D1", "RX": "D0"})
    assert result["ok"] is False
    assert any(issue["code"] == "uart_direction_mismatch" for issue in result["issues"])

    i2c = ComponentSpec(
        schema_version="1.0", id="i2c-test", version="1.0.0", name={},
        pins=[
            ComponentPin(id="SDA", role="i2c_sda", direction="bidirectional"),
            ComponentPin(id="SCL", role="i2c_scl", direction="bidirectional"),
        ],
    )
    result = resolve_assignment(profile, i2c, {"SDA": "SCL", "SCL": "SDA"})
    assert result["ok"] is False
    assert any(issue["code"] == "i2c_role_mismatch" for issue in result["issues"])
