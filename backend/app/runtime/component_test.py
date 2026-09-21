"""Fixed one-shot runner uploaded to Pi; no project/AI code is evaluated.

The systemd unit also has an independent hard lifetime. JSON progress and
commands belong to one run; terminal status is published only after cleanup.
"""
import contextlib
import json
import math
import os
from pathlib import Path
import statistics
import threading
import time


class ReaderError(RuntimeError):
    """A background reader failed, not an absence of physical echoes."""


class ReaderHealth:
    """Forward thread failures to the owner of this one-shot runner.

    lgpio dispatches callbacks outside DistanceSensor's sampling thread. An
    exception there otherwise kills only the callback thread, leaving the main
    program alive and incorrectly reporting no_echo. Install before importing
    the GPIO drivers and retain through cleanup; never retain traceback objects.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.error = None

    def __enter__(self):
        self.previous_hook = threading.excepthook
        threading.excepthook = self.on_exception
        return self

    def on_exception(self, args):
        with self.lock:
            if self.error is None:
                self.error = f"{args.thread.name}: {args.exc_type.__name__}: {args.exc_value}"[:2000]
        self.previous_hook(args)  # Keep the full traceback in the service journal.

    def check(self):
        with self.lock:
            error = self.error
        if error:
            raise ReaderError(error)

    def __exit__(self, exc_type, exc_value, traceback):
        threading.excepthook = self.previous_hook
        if exc_type is None:
            self.check()


def distance_result(near, far):
    if len(near) < 5 or len(far) < 5:
        return "inconclusive", "no_echo"
    if statistics.median(far) - statistics.median(near) < 5:
        return "inconclusive", "movement_not_confirmed"
    return "passed", None


def classify_error(error):
    text = str(error).lower()
    if isinstance(error, ReaderError):
        return "reader_error"
    if isinstance(error, (ImportError, ModuleNotFoundError)):
        return "missing_dependency"
    if isinstance(error, PermissionError):
        return "device_permission"
    if any(word in text for word in ("busy", "in use", "already allocated")):
        return "resource_busy"
    return "program_error"


class Reporter:
    def __init__(self, directory, run_id):
        self.directory, self.run_id = Path(directory), run_id
        self.lock = threading.Lock()
        self.state = dict(run_id=run_id, phase="starting", outcome="running", samples={}, latest=None)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.thread.start()

    def update(self, **values):
        with self.lock:
            if values:
                self.state["last_progress_at"] = time.time()
            self.state.update(values, heartbeat_at=time.time())
            pending = self.directory / "result.tmp"
            pending.write_text(json.dumps(self.state), encoding="utf-8")
            pending.replace(self.directory / "result.json")

    def heartbeat(self):
        while not self.done.is_set():
            self.update()
            self.done.wait(.5)

    def wait_ready(self, phase, deadline, check_health=lambda: None):
        self.update(phase="awaiting_" + phase, latest=None, latest_valid_at=None, sample_count=0)
        while time.monotonic() < deadline:
            check_health()
            try:
                command = json.loads((self.directory / "command.json").read_text())
                if command.get("run_id") == self.run_id and command.get("action") == phase:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        raise TimeoutError("User preparation deadline exceeded")

    def finish(self, **values):
        self.done.set()
        self.thread.join(1)
        if values.get("reason"):
            values["failed_phase"] = self.state["phase"]
        self.update(**values, phase="finished", latest=None)


def collect(sensor, reporter, phase, seconds=5, check_health=lambda: None):
    start = time.monotonic_ns()
    seen, values = set(), []
    reporter.update(phase="sampling_" + phase, latest=None, latest_valid_at=None, sample_count=0)
    while (time.monotonic_ns() - start) / 1e9 < seconds:
        check_health()
        sample = sensor.latest
        if sample and sample[0] >= start and sample[0] not in seen:
            seen.add(sample[0])
            value = sample[1] * sensor.max_distance * 100
            if math.isfinite(value) and 0 < value < 400:
                values.append(value)
                reporter.update(latest=dict(cm=round(value, 1), at=time.time()), latest_valid_at=time.time(),
                                sample_count=len(values))
        time.sleep(.05)
    check_health()
    return values


def sensor_test(config, reporter, deadline):
    with ReaderHealth() as health:
        return _sensor_test(config, reporter, deadline, health)


def _sensor_test(config, reporter, deadline, health):
    from gpiozero import DistanceSensor
    from gpiozero.pins.lgpio import LGPIOFactory

    class FreshSensor(DistanceSensor):
        def __init__(self, **kwargs):
            self.latest = None
            super().__init__(**kwargs)

        def _read(self):
            # Timestamp the trigger/read start, not its completion. A pulse
            # already in flight when the next phase starts is not fresh evidence.
            started_at = time.monotonic_ns()
            value = super()._read()
            self.latest = (started_at, value) if value is not None else None
            return value

    readings = {}
    reporter.wait_ready("near", deadline, health.check)
    # Keep one factory/sensor across both phases. Closing/reopening at the
    # boundary can dispatch a queued lgpio callback into an already closed pin.
    with contextlib.ExitStack() as stack:
        factory = LGPIOFactory()
        stack.callback(factory.close)
        sensor = stack.enter_context(FreshSensor(echo=config["pins"]["ECHO"],
            trigger=config["pins"]["TRIG"], queue_len=1, partial=True,
            max_distance=4, pin_factory=factory))
        for phase in ("near", "far"):
            if phase == "far":
                reporter.wait_ready(phase, deadline, health.check)
            readings[phase] = collect(sensor, reporter, phase, check_health=health.check)
            reporter.update(samples={key: dict(count=len(values), median_cm=round(statistics.median(values), 1)
                                              if values else None) for key, values in readings.items()})
    health.check()
    outcome, reason = distance_result(readings["near"], readings["far"])
    return dict(outcome=outcome, reason=reason)


def display_test(config, reporter):
    from gpiozero.pins.lgpio import LGPIOFactory
    from PIL import Image, ImageDraw
    from display import WiringDisplay
    # Detect other accessible processes using SPI; never terminate them.
    for process in Path('/proc').glob('[0-9]*'):
        if process.name == str(os.getpid()):
            continue
        try:
            for fd in (process / 'fd').iterdir():
                if os.readlink(fd) == '/dev/spidev0.0':
                    raise RuntimeError('SPI device is busy in another process')
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    with contextlib.ExitStack() as stack:
        factory = LGPIOFactory()
        stack.callback(factory.close)
        display = WiringDisplay(config["pins"], factory)
        stack.callback(display.close)
        for color in ("red", "lime", "blue"):
            reporter.update(phase="display_" + color)
            display.device.display(Image.new("RGB", display.device.size, color))
            time.sleep(1)
        image = Image.new("RGB", display.device.size, "#101820")
        draw = ImageDraw.Draw(image)
        display.text(draw, (12, 30), "MRD-TFT240", size=26)
        display.text(draw, (12, 110), config["visual_code"], size=48)
        display.text(draw, (12, 220), "R / G / B", size=24)
        display.device.display(image)
        # Keep an explicit viewing window before releasing hardware. RGB had
        # one second per frame but the code previously disappeared at cleanup.
        # Never wait indefinitely for browser confirmation while holding GPIO.
        for _ in range(15):
            reporter.update(phase="display_code")
            time.sleep(1)
    return dict(outcome="awaiting_confirmation", reason=None)


def main(directory):
    import fcntl
    directory = Path(directory)
    config = json.loads((directory / "config.json").read_text())
    reporter = Reporter(directory, config["run_id"])
    result = dict(outcome="failed", reason="program_error")
    try:
        with (directory.parent / "hardware.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another component test is busy")
            result = sensor_test(config, reporter, time.monotonic() + 165) if config["component_id"] == "hc-sr04" else display_test(config, reporter)
    except TimeoutError:
        result = dict(outcome="inconclusive", reason="timeout")
    except Exception as error:
        result = dict(outcome="failed", reason=classify_error(error), detail=str(error)[:2000])
    reporter.finish(**result)


if __name__ == "__main__":
    import sys
    main(sys.argv[1])
