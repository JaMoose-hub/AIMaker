"""Background A0 response challenge for the photoresistor guide."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import replace
from typing import Callable, Protocol, Sequence

from app.electrical.serial_link import AnalogReading
from app.verification.models import VerificationEvidence
from app.verification.state import VerificationState, VerificationTarget

log = logging.getLogger(__name__)


class AnalogLink(Protocol):
    @property
    def port(self) -> str | None: ...

    def hello(self) -> dict: ...

    def read_a0(self) -> AnalogReading: ...

    def close(self) -> None: ...


def supports_a0_challenge(target: VerificationTarget | None) -> bool:
    return bool(
        target is not None
        and target.board_pin.upper() == "A0"
        and (target.component_pin or "").upper() == "AO"
    )


def analog_response_evidence(
    samples: Sequence[tuple[float, AnalogReading]],
    *,
    now_ms: float,
    min_delta_fraction: float,
    fresh_for_ms: float,
) -> VerificationEvidence:
    if not samples:
        return VerificationEvidence.uncertain(
            "electrical",
            "collecting_a0_baseline",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + fresh_for_ms,
            method="serial_a0_response",
        )
    latest = samples[-1][1]
    compatible = [item.raw for _, item in samples if item.full_scale == latest.full_scale]
    ordered = sorted(compatible)
    # Once enough samples exist, ignore one extreme at each edge. Firmware
    # already averages nine ADC conversions; this additional guard prevents a
    # single USB/ADC outlier from being called a real light response.
    robust = ordered[1:-1] if len(ordered) >= 8 else ordered
    minimum = min(robust)
    maximum = max(robust)
    delta = maximum - minimum
    delta_fraction = delta / latest.full_scale
    details = {
        "pin": "A0",
        "raw": latest.raw,
        "min_raw": minimum,
        "max_raw": maximum,
        "delta_raw": delta,
        "delta_fraction": round(delta_fraction, 4),
        "full_scale": latest.full_scale,
        "sample_count": len(compatible),
    }
    if len(compatible) < 6:
        return VerificationEvidence.uncertain(
            "electrical",
            "collecting_a0_baseline",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + fresh_for_ms,
            method="serial_a0_response",
            quality=min(len(compatible) / 6.0, 1.0),
            details=details,
        )
    if delta_fraction < min_delta_fraction:
        return VerificationEvidence.uncertain(
            "electrical",
            "awaiting_light_change",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + fresh_for_ms,
            method="serial_a0_response",
            quality=min(len(compatible) / 12.0, 1.0),
            details=details,
        )
    margin = min(delta_fraction / max(min_delta_fraction, 1e-6) - 1.0, 1.0)
    return VerificationEvidence(
        source="electrical",
        status="pass",
        score=0.88 + 0.08 * max(0.0, margin),
        quality=min(len(compatible) / 12.0, 1.0),
        reason="a0_response_confirmed",
        as_of_ms=now_ms,
        fresh_until_ms=now_ms + fresh_for_ms,
        method="serial_a0_response",
        details=details,
    )


class ElectricalVerificationWorker:
    """Polls only while the active guide target is Sensor AO -> UNO Q A0."""

    def __init__(
        self,
        state: VerificationState,
        board_id: str,
        link: AnalogLink,
        *,
        publish: Callable[[dict], None] | None = None,
        sample_interval_s: float = 0.25,
        window_s: float = 6.0,
        min_delta_fraction: float = 0.08,
    ) -> None:
        self._state = state
        self._board_id = board_id
        self._link = link
        self._publish = publish
        self._sample_interval_s = max(0.05, float(sample_interval_s))
        self._window_ms = max(1.0, float(window_s)) * 1000.0
        self._min_delta_fraction = max(0.001, min(float(min_delta_fraction), 1.0))
        self._fresh_for_ms = max(1_500.0, self._sample_interval_s * 4_000.0)
        self._samples: deque[tuple[float, AnalogReading]] = deque()
        self._challenge_key: tuple[str, int] | None = None
        # A successful light-change challenge is an explicit user action. Keep
        # that result latched until the user starts a new generation or moves
        # to another guide step; otherwise the normal sliding ADC window makes
        # a valid pass disappear again a few seconds later.
        self._latched_pass_key: tuple[str, int] | None = None
        self._hello_checked = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="electrical-verification-worker", daemon=True
        )
        self._thread.start()

    def set_board_id(self, board_id: str) -> None:
        self._board_id = str(board_id)
        self._samples.clear()
        self._challenge_key = None
        self._latched_pass_key = None

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        try:
            self._link.close()
        except Exception:
            log.exception("could not close UNO Q serial link")

    def _publish_evidence(
        self, step_id: str, evidence: VerificationEvidence, now_ms: float
    ) -> None:
        if not self._state.update(step_id, [evidence], now_ms=now_ms):
            return
        if self._publish is not None:
            message = self._state.message(self._board_id, 0, now_ms)
            if message is not None:
                self._publish(message)

    def _serial_unavailable(self, step_id: str, exc: Exception, now_ms: float) -> None:
        message = str(exc).replace("\r", " ").replace("\n", " ")[:240]
        evidence = VerificationEvidence(
            source="electrical",
            status="unavailable",
            reason="serial_unavailable",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + self._fresh_for_ms,
            method="serial_a0_response",
            details={
                "port": self._link.port,
                "error_type": type(exc).__name__,
                "error": message,
            },
        )
        self._publish_evidence(step_id, evidence, now_ms)

    def _run(self) -> None:
        while not self._stop.is_set():
            target = self._state.target()
            if (
                not supports_a0_challenge(target)
                or target is None
                or not target.electrical_requested
            ):
                self._challenge_key = None
                self._latched_pass_key = None
                self._samples.clear()
                self._stop.wait(self._sample_interval_s)
                continue
            assert target is not None
            challenge_key = (target.step_id, target.electrical_generation)
            if self._challenge_key != challenge_key:
                self._challenge_key = challenge_key
                self._latched_pass_key = None
                self._samples.clear()
            if self._latched_pass_key == challenge_key:
                self._stop.wait(self._sample_interval_s)
                continue
            now_ms = time.monotonic() * 1000.0
            try:
                if not self._hello_checked:
                    hello = self._link.hello()
                    if "analog_a0" not in hello.get("features", []):
                        raise RuntimeError(
                            "UNO Q firmware does not advertise analog_a0; flash v0.3.0+"
                        )
                    self._hello_checked = True
                reading = self._link.read_a0()
                now_ms = time.monotonic() * 1000.0
                self._samples.append((now_ms, reading))
                while self._samples and now_ms - self._samples[0][0] > self._window_ms:
                    self._samples.popleft()
                evidence = analog_response_evidence(
                    tuple(self._samples),
                    now_ms=now_ms,
                    min_delta_fraction=self._min_delta_fraction,
                    fresh_for_ms=self._fresh_for_ms,
                )
                if evidence.status == "pass":
                    # A latched pass has no expiry. It is cleared only by a
                    # new electrical generation (the retry button) or a new
                    # guidance step, so the fusion score remains observable.
                    evidence = replace(
                        evidence,
                        fresh_until_ms=0.0,
                        details={**evidence.details, "latched": True},
                    )
                    self._latched_pass_key = challenge_key
                self._publish_evidence(target.step_id, evidence, now_ms)
            except Exception as exc:
                log.warning("UNO Q A0 verification unavailable: %s", exc)
                self._samples.clear()
                self._hello_checked = False
                try:
                    self._link.close()
                except Exception:
                    pass
                self._serial_unavailable(target.step_id, exc, now_ms)
                self._stop.wait(max(1.0, self._sample_interval_s))
                continue
            self._stop.wait(self._sample_interval_s)
