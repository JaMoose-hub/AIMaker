import json
import threading
import time

from app.electrical import serial_link
from app.electrical.serial_link import AnalogReading, UnoQSerialLink
from app.verification.electrical_worker import (
    ElectricalVerificationWorker,
    analog_response_evidence,
    supports_a0_challenge,
)
from app.verification.state import VerificationState, VerificationTarget


def _reading(raw: int, full_scale: int = 1023) -> AnalogReading:
    return AnalogReading("A0", raw, max(0, raw - 2), min(full_scale, raw + 2), full_scale, 9)


def test_a0_challenge_is_scoped_to_the_photoresistor_signal_wire():
    assert supports_a0_challenge(VerificationTarget("s", "A0", "AO", "sensor"))
    assert not supports_a0_challenge(VerificationTarget("s", "3V3", "VCC", "sensor"))
    assert not supports_a0_challenge(VerificationTarget("s", "A0", "DO", "sensor"))
    assert not supports_a0_challenge(None)


def test_analog_response_requires_repeated_samples_and_real_adc_span():
    now = 10_000.0
    collecting = analog_response_evidence(
        [(now + i, _reading(500 + i)) for i in range(4)],
        now_ms=now + 10,
        min_delta_fraction=0.08,
        fresh_for_ms=1500,
    )
    assert collecting.status == "uncertain"
    assert collecting.reason == "collecting_a0_baseline"

    unchanged = analog_response_evidence(
        [(now + i, _reading(value)) for i, value in enumerate([500, 501, 500, 502, 501, 500, 900, 501])],
        now_ms=now + 20,
        min_delta_fraction=0.08,
        fresh_for_ms=1500,
    )
    assert unchanged.status == "uncertain"  # one outlier is discarded
    assert unchanged.reason == "awaiting_light_change"

    changed = analog_response_evidence(
        [(now + i, _reading(value)) for i, value in enumerate([120, 125, 123, 130, 820, 830, 825, 815])],
        now_ms=now + 30,
        min_delta_fraction=0.08,
        fresh_for_ms=1500,
    )
    assert changed.status == "pass"
    assert changed.reason == "a0_response_confirmed"
    assert changed.details["delta_fraction"] > 0.6


class _FakeSerial:
    def __init__(self):
        self.port = "COM9"
        self.is_open = True
        self._response = b""

    def reset_input_buffer(self):
        pass

    def write(self, payload):
        request = json.loads(payload.decode("ascii"))
        if request["cmd"] == "hello":
            response = {
                "id": request["id"],
                "ok": True,
                "device": "arduino-uno-q",
                "features": ["analog_a0"],
            }
        else:
            response = {
                "id": request["id"],
                "ok": True,
                "pin": "A0",
                "raw": 401,
                "min": 399,
                "max": 403,
                "full_scale": 1023,
                "sample_count": 9,
            }
        self._response = json.dumps(response).encode("utf-8") + b"\n"

    def flush(self):
        pass

    def readline(self):
        result, self._response = self._response, b""
        return result

    def close(self):
        self.is_open = False


def test_serial_link_parses_correlated_json_replies(monkeypatch):
    fake = _FakeSerial()
    monkeypatch.setattr(serial_link.serial, "Serial", lambda **_kwargs: fake)
    monkeypatch.setattr(serial_link.time, "sleep", lambda _seconds: None)
    link = UnoQSerialLink("COM9", timeout_s=0.2)

    assert link.hello()["device"] == "arduino-uno-q"
    reading = link.read_a0()
    assert reading.raw == 401
    assert reading.full_scale == 1023
    link.close()
    assert fake.is_open is False


class _SequenceLink:
    port = "COM-test"

    def __init__(self, values):
        self.values = list(values)
        self.index = 0
        self.closed = False

    def hello(self):
        return {"device": "arduino-uno-q", "features": ["analog_a0"]}

    def read_a0(self):
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return _reading(value)

    def close(self):
        self.closed = True


def test_worker_publishes_a0_pass_without_blocking_camera_threads():
    state = VerificationState()
    state.set_step("photoresistor-ao", "A0", "AO", "photoresistor-module", electrical_available=True)
    passed = threading.Event()
    messages = []

    def publish(message):
        messages.append(message)
        if message["evidence"]["electrical"]["status"] == "pass":
            passed.set()

    link = _SequenceLink([120, 125, 123, 130, 820, 830, 825, 815])
    worker = ElectricalVerificationWorker(
        state,
        "arduino-uno-q",
        link,
        publish=publish,
        sample_interval_s=0.05,
        window_s=2.0,
        min_delta_fraction=0.08,
    )
    worker.start()
    try:
        time.sleep(0.12)
        assert link.index == 0  # final electrical check is explicit, never automatic
        assert state.request_electrical("photoresistor-ao") is True
        assert passed.wait(1.5)
    finally:
        worker.stop()

    assert messages[-1]["type"] == "verification_update"
    assert messages[-1]["evidence"]["electrical"]["reason"] == "a0_response_confirmed"
    assert link.closed is True


def test_worker_latches_a0_pass_until_the_challenge_is_restarted():
    state = VerificationState()
    state.set_step("photoresistor-ao", "A0", "AO", "photoresistor-module", electrical_available=True)
    link = _SequenceLink([120, 125, 123, 130, 820, 830, 825, 815] + [120] * 30)
    worker = ElectricalVerificationWorker(
        state,
        "arduino-uno-q",
        link,
        sample_interval_s=0.03,
        window_s=0.30,
        min_delta_fraction=0.08,
    )
    worker.start()
    try:
        assert state.request_electrical("photoresistor-ao") is True
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            snapshot = state.snapshot()
            if snapshot["evidence"]["electrical"]["status"] == "pass":
                break
            time.sleep(0.03)
        time.sleep(0.6)  # the ADC window has now moved past the high readings
        snapshot = state.snapshot()
        assert snapshot["evidence"]["electrical"]["status"] == "pass"
        assert snapshot["evidence"]["electrical"]["details"]["latched"] is True

        assert state.request_electrical("photoresistor-ao") is True
        time.sleep(0.05)
        assert state.snapshot()["evidence"]["electrical"]["status"] != "pass"
    finally:
        worker.stop()
