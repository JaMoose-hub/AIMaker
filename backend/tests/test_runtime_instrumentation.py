"""Execute the deployed instrumentation without accessing GPIO or SPI."""
import ast
from types import SimpleNamespace

import pytest

from app.debug_support import observed_source
from app.designs import demo_design


@pytest.mark.parametrize("components", [["hc-sr04"], ["hc-sr04", "mrd-tf240-8p-cs"]])
def test_observed_sensor_method_uses_runner_global_during_construction_and_later_reads(components):
    observed, structured = observed_source(demo_design(components)["code"])
    assert structured
    tree = ast.parse(observed)
    sensor_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FreshDistanceSensor")
    samples = []
    reading = SimpleNamespace(value=.25, tick=10)

    class DistanceSensor:
        def __init__(self, **kwargs):
            # gpiozero starts its read queue in the base constructor. The first
            # callback must already see subclass state and the runner's hook.
            assert self.latest is None
            self._read()

        def _read(self):
            return reading.value

    namespace = {"DistanceSensor": DistanceSensor, "monotonic": lambda: reading.tick,
                 "_bv_emit": lambda kind, value: samples.append((kind, value))}
    exec(compile(ast.Module(body=[sensor_class], type_ignores=[]), "observed.py", "exec"), namespace)
    sensor = namespace["FreshDistanceSensor"]()
    assert sensor.latest == (10, .25)
    assert samples == [("sample", (10, .25))]
    # Missing and maximum-range returns remain explicit. Telemetry validates
    # them later; instrumentation must neither invent nor cache a valid echo.
    for value, tick in [(None, 11), (1, 12), (.1, 13)]:
        reading.value, reading.tick = value, tick
        assert sensor._read() == value
        assert sensor.latest == (tick, value)
        assert samples[-1] == ("sample", (tick, value))
    assert len(samples) == 4


def display_statements(tree):
    for parent in ast.walk(tree):
        for _field, statements in ast.iter_fields(parent):
            if not isinstance(statements, list):
                continue
            for index, node in enumerate(statements):
                if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and isinstance(node.value.func.value, ast.Name)
                        and node.value.func.value.id == "display"
                        and node.value.func.attr in {"test_card", "show_distance"}):
                    yield node.value.func.attr, statements[index:index+2]


@pytest.mark.parametrize("components,expected", [(["mrd-tf240-8p-cs"], {"test_card"}),
                                               (["hc-sr04", "mrd-tf240-8p-cs"], {"test_card", "show_distance"})])
def test_display_emits_only_after_the_real_display_call_returns(components, expected):
    observed, structured = observed_source(demo_design(components)["code"])
    assert structured
    instrumented = list(display_statements(ast.parse(observed)))
    assert {name for name, _nodes in instrumented} == expected
    for name, nodes in instrumented:
        calls = []

        def display_call(*args):
            calls.append(("display_call", name, args))

        namespace = {"display": SimpleNamespace(test_card=display_call, show_distance=display_call),
                     "distance": 42, "SETTINGS": {"distance_cm": 20},
                     "_bv_emit": lambda kind, value: calls.append(("telemetry", kind, value))}
        code = compile(ast.Module(body=nodes, type_ignores=[]), "observed.py", "exec")
        exec(code, namespace)
        assert calls == [("display_call", name, () if name == "test_card" else (42, 20)),
                         ("telemetry", "display", None)]

        def fail(*args):
            raise OSError("simulated SPI failure")

        calls.clear()
        namespace["display"] = SimpleNamespace(test_card=fail, show_distance=fail)
        with pytest.raises(OSError, match="simulated SPI failure"):
            exec(code, namespace)
        assert calls == [], "failed writes must not produce successful display telemetry"


@pytest.mark.parametrize("custom", [
    "_bv_emit = lambda *args: None\nprint('custom')",
    "def _bv_emit(kind, value):\n    pass\n_bv_emit('sample', (10, .2))",
    "class CustomSensor:\n    def _read(self):\n        self.latest = (10, .2)\n        return .2",
])
def test_custom_code_and_emitter_name_collisions_do_not_gain_structured_telemetry(custom):
    assert observed_source(custom) == (custom, False)


def test_changed_hardware_scaffold_is_never_silently_instrumented():
    custom = demo_design()["code"] + "\n_bv_emit = lambda *args: None\n"
    assert observed_source(custom) == (custom, False)
