"""Newline-delimited JSON client for the UNO Q Debian serial proxy."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import serial
from serial.tools import list_ports

ARDUINO_VID = 0x2341
UNO_Q_PID = 0x0078


class SerialProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalogReading:
    pin: str
    raw: int
    minimum: int
    maximum: int
    full_scale: int
    sample_count: int


def find_uno_q_port() -> str:
    matches = [
        item.device
        for item in list_ports.comports()
        if item.vid == ARDUINO_VID and item.pid == UNO_Q_PID
    ]
    if not matches:
        raise SerialProtocolError(
            "UNO Q USB Serial not found (expected VID 2341, PID 0078)"
        )
    if len(matches) > 1:
        raise SerialProtocolError(
            "multiple UNO Q serial ports found; configure one explicitly: "
            + ", ".join(matches)
        )
    return matches[0]


class UnoQSerialLink:
    """One request at a time; safe for a background worker and diagnostics."""

    def __init__(self, port: str | None = None, *, timeout_s: float = 2.0) -> None:
        self._configured_port = port
        self._timeout_s = max(0.2, float(timeout_s))
        self._serial: serial.Serial | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    @property
    def port(self) -> str | None:
        if self._serial is not None:
            return str(self._serial.port)
        return self._configured_port

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        port = self._configured_port or find_uno_q_port()
        connection = serial.Serial(
            port=port,
            baudrate=115200,
            timeout=0.10,
            write_timeout=1.0,
        )
        time.sleep(0.25)
        connection.reset_input_buffer()
        self._serial = connection

    def close(self) -> None:
        connection, self._serial = self._serial, None
        if connection is not None and connection.is_open:
            connection.close()

    def request(self, command: str) -> dict[str, Any]:
        with self._lock:
            self.open()
            assert self._serial is not None
            request_id = self._next_id
            self._next_id = 1 if request_id >= 2_000_000_000 else request_id + 1
            payload = json.dumps(
                {"id": request_id, "cmd": command}, separators=(",", ":")
            ).encode("ascii") + b"\n"
            try:
                self._serial.write(payload)
                self._serial.flush()
                deadline = time.monotonic() + self._timeout_s
                while time.monotonic() < deadline:
                    raw = self._serial.readline()
                    if not raw:
                        continue
                    try:
                        response = json.loads(raw.decode("utf-8", errors="strict"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if response.get("id") != request_id:
                        continue
                    if response.get("ok") is not True:
                        raise SerialProtocolError(
                            str(response.get("error") or f"{command} failed")
                        )
                    return response
            except Exception:
                self.close()
                raise
            self.close()
            raise TimeoutError(
                f"UNO Q did not reply to {command!r} within {self._timeout_s:.1f}s"
            )

    def hello(self) -> dict[str, Any]:
        response = self.request("hello")
        if response.get("device") != "arduino-uno-q":
            raise SerialProtocolError("serial peer is not an Arduino UNO Q")
        return response

    def read_a0(self) -> AnalogReading:
        response = self.request("analog_a0")
        try:
            reading = AnalogReading(
                pin=str(response["pin"]),
                raw=int(response["raw"]),
                minimum=int(response["min"]),
                maximum=int(response["max"]),
                full_scale=int(response["full_scale"]),
                sample_count=int(response["sample_count"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SerialProtocolError(f"invalid analog_a0 response: {exc}") from exc
        if (
            reading.pin != "A0"
            or reading.full_scale <= 0
            or reading.sample_count <= 0
            or not 0 <= reading.minimum <= reading.raw <= reading.maximum <= reading.full_scale
        ):
            raise SerialProtocolError("analog_a0 response is outside the ADC range")
        return reading

    def __enter__(self) -> "UnoQSerialLink":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
