"""Software contract tests, not physical supply/backlight/display validation."""
import copy
import sys
import types
from pathlib import Path

import pytest

from app.designs import demo_design, CATALOG, MODULES, render_code
from app.design_migration import migrate_maker_state


def test_v2_migration_preserves_old_ten_wires_but_requires_new_vcc_confirmation():
    old = demo_design()
    old.update(catalog_version="2", code="# old preview", summary="TFT 供電、背光與驅動未核實；禁止上電。")
    old["wiring"] = [w for w in old["wiring"] if w["id"] != "mrd-tf240-8p-cs:vcc"]
    signature = lambda w: "|".join(w[k] for k in ("componentId", "componentPin", "boardPin", "connectionKind"))
    state = dict(design=old, candidate=copy.deepcopy(old), selected=old["component_ids"], code=old["code"],
                 guide=dict(componentIndex=1, confirmed={w["id"]: {"signature": signature(w)} for w in old["wiring"]}))
    new = migrate_maker_state(state)
    assert len(new["guide"]["confirmed"]) == 10
    assert "mrd-tf240-8p-cs:vcc" not in new["guide"]["confirmed"]
    assert new["design"]["id"] == old["id"]
    assert new["candidate"]["catalog_version"] == CATALOG["version"]
    assert "禁止上電" not in new["design"]["summary"]
    assert "WiringDisplay" in new["code"]
    assert migrate_maker_state(new) == new


def test_catalog_display_contract_and_unresolved_hardware_still_prevents_initialization():
    project = demo_design()
    assert len(project["wiring"]) == 11
    assert project["requirements"]["devices"] == ["/dev/spidev0.0"]
    assert "luma.lcd" in project["requirements"]["imports"]
    assert all(w["componentPin"] != "BLK" for w in project["wiring"])
    assert "photographs" in MODULES["mrd-tf240-8p-cs"]["verification"]
    blocked = render_code(project["wiring"], project["parameters"], project["logic"], ["test unresolved hardware"])
    assert "from gpiozero" not in blocked
    with pytest.raises(RuntimeError, match="test unresolved"):
        exec(blocked, {})


@pytest.fixture
def hardware(monkeypatch):
    record = types.SimpleNamespace(pins=[], closed=[], frames=[], factory_closed=False, serial_closed=False,
                                   raw=.04, age=0, fail_display=False, sleeps=0)

    class StopLoop(Exception):
        pass

    class Factory:
        def close(self): record.factory_closed = True

    class Output:
        def __init__(self, pin, **kwargs):
            record.pins.append(pin)
            self.pin = pin
        def close(self): record.closed.append(self.pin)

    class Sensor:
        def __init__(self, **kwargs):
            record.sensor = kwargs
            self.max_distance = kwargs["max_distance"]
        def _read(self): return record.raw
        def __enter__(self):
            self._read()
            return self
        def __exit__(self, *args): record.sensor_closed = True

    class Serial:
        def __init__(self, **kwargs):
            record.serial = kwargs
            for key in ("gpio_DC", "gpio_RST"):
                kwargs["gpio"].setup(kwargs[key], 1)
                kwargs["gpio"].output(kwargs[key], 1)
        def cleanup(self): record.serial_closed = True

    class LCD:
        def __init__(self, serial, **kwargs):
            record.display = kwargs
            # Would claim GPIO18 in luma unless we explicitly disable backlight.
            assert callable(kwargs["backlight"])
            kwargs["backlight"](True)
            if record.fail_display:
                raise OSError("SPI initialization failed")
            assert (kwargs["width"], kwargs["height"], kwargs["rotate"]) == (320, 240, 1)
            self.size = (240, 320)
        def display(self, image): record.frames.append(image.copy())

    def sleep(seconds):
        record.sleeps += 1
        if record.sleeps >= 2:
            raise StopLoop()

    ticks = iter([10, 10])
    def monotonic():
        value = next(ticks)
        return value + (record.age if hasattr(record, "tick_seen") else 0)
    def ticking():
        value = monotonic()
        record.tick_seen = True
        return value

    for name, attrs in {
        "gpiozero": dict(DigitalOutputDevice=Output, DistanceSensor=Sensor),
        "gpiozero.pins": {}, "gpiozero.pins.lgpio": dict(LGPIOFactory=Factory),
        "luma": {}, "luma.core": {}, "luma.core.interface": {},
        "luma.core.interface.serial": dict(spi=Serial),
        "luma.lcd": {}, "luma.lcd.device": dict(ili9341=LCD),
        "time": dict(sleep=sleep, monotonic=ticking),
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    record.stop = StopLoop
    return record


@pytest.mark.parametrize("raw,age,expected", [(.04, 0, "16.0 WARNING"), (None, 0, "UNAVAILABLE"), (.04, 2, "UNAVAILABLE"), (1, 0, "UNAVAILABLE")])
def test_combined_generated_runtime_and_cleanup(hardware, capsys, raw, age, expected):
    hardware.raw, hardware.age = raw, age
    with pytest.raises(hardware.stop):
        exec(demo_design()["code"], {})
    assert expected in capsys.readouterr().out
    assert hardware.pins == [24, 25]  # not ECHO/GPIO18, CS or BLK
    assert hardware.sensor["echo"] == 18 and hardware.sensor["trigger"] == 17
    assert len(hardware.frames) == 2
    assert hardware.frames[0].getpixel((5, 5)) == (255, 0, 0)
    assert hardware.frames[0].getpixel((85, 5)) == (0, 255, 0)
    assert hardware.frames[0].getpixel((165, 5)) == (0, 0, 255)
    assert hardware.factory_closed and hardware.serial_closed and hardware.sensor_closed
    assert hardware.closed == [24, 25]


def test_display_only_keeps_test_card_without_fake_distance(hardware, capsys):
    with pytest.raises(hardware.stop):
        exec(demo_design(["mrd-tf240-8p-cs"])["code"], {})
    assert len(hardware.frames) == 1 and not hasattr(hardware, "sensor")
    assert "distance_cm=" not in capsys.readouterr().out


def test_display_initialization_failure_closes_resources_before_sensor(hardware):
    hardware.fail_display = True
    with pytest.raises(OSError, match="SPI initialization"):
        exec(demo_design()["code"], {})
    assert hardware.factory_closed and hardware.serial_closed
    assert hardware.closed == [24, 25] and not hasattr(hardware, "sensor")


def test_actual_luma_213_driver_sends_pixels_without_claiming_echo(monkeypatch):
    from luma.core.interface.serial import spi as real_spi
    created, closed, writes = [], [], []

    class Output:
        def __init__(self, pin, **kwargs): created.append(pin); self.pin = pin
        def close(self): closed.append(self.pin)

    class Bus:
        def open(self, port, device): assert (port, device) == (0, 0)
        def writebytes(self, data): writes.append(bytes(data))
        def close(self): pass

    module = types.ModuleType("gpiozero")
    module.DigitalOutputDevice = Output
    monkeypatch.setitem(sys.modules, "gpiozero", module)
    namespace = {}
    source = Path(__file__).resolve().parents[1] / "app/runtime/ili9341_display.py"
    exec(source.read_text(encoding="utf-8"), namespace)
    namespace["spi"] = lambda **kwargs: real_spi(spi=Bus(), **kwargs)
    display = namespace["WiringDisplay"]({"SCL": 11, "SDA": 10, "CS": 8, "DC": 24, "RES": 25}, None)
    try:
        assert display.device.size == (240, 320)
        writes.clear()
        display.test_card()
        assert sum(map(len, writes)) >= 240 * 320 * 3
        display.show_distance(None, 20)
        display.show_distance(15, 20)
        assert created == [24, 25]
    finally:
        display.close()
    assert closed == [24, 25]
