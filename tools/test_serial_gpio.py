"""Exercise the UNO Q GPIO-to-GND verifier over USB Serial."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any

import serial
from serial.tools import list_ports


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ARDUINO_VID = 0x2341
UNO_Q_PID = 0x0078


def find_uno_q_port() -> str:
    matches = [
        port.device
        for port in list_ports.comports()
        if port.vid == ARDUINO_VID and port.pid == UNO_Q_PID
    ]
    if not matches:
        raise RuntimeError("找不到 Arduino UNO Q USB Serial Port (VID 2341, PID 0078)")
    if len(matches) > 1:
        raise RuntimeError(f"找到多個 UNO Q Serial Port，請用 --port 指定：{', '.join(matches)}")
    return matches[0]


class GpioVerifier:
    def __init__(self, port: str, timeout: float = 2.0) -> None:
        self._port = port
        self._timeout = timeout
        self._next_id = 1
        self._serial = serial.Serial(
            port=port,
            baudrate=115200,
            timeout=0.1,
            write_timeout=1.0,
        )
        time.sleep(0.25)
        self._serial.reset_input_buffer()

    def close(self) -> None:
        if self._serial.is_open:
            self._serial.close()

    def request(self, command: str) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps(
            {"id": request_id, "cmd": command}, separators=(",", ":")
        ).encode("ascii") + b"\n"
        self._serial.write(payload)
        self._serial.flush()

        deadline = time.monotonic() + self._timeout
        seen_lines: list[str] = []
        while time.monotonic() < deadline:
            raw = self._serial.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            seen_lines.append(line)
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                return response

        detail = f"；收到：{' | '.join(seen_lines)}" if seen_lines else ""
        raise TimeoutError(f"UNO Q 未在 {self._timeout:.1f} 秒內回覆 {command}{detail}")

    def __enter__(self) -> "GpioVerifier":
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.request("idle")
        except (OSError, TimeoutError, serial.SerialException):
            pass
        self.close()


def print_scan(response: dict[str, Any], *, raw_json: bool) -> None:
    if raw_json:
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
        return

    timestamp = datetime.now().strftime("%H:%M:%S")
    connected = response.get("connected_to_gnd", [])
    if connected:
        print(f"[{timestamp}] 接到 GND：{', '.join(connected)}", flush=True)
    else:
        print(f"[{timestamp}] 未偵測到接地腳位", flush=True)


def print_analog(response: dict[str, Any], *, raw_json: bool) -> None:
    if raw_json:
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    raw = response.get("raw", "?")
    full_scale = response.get("full_scale", "?")
    minimum = response.get("min", "?")
    maximum = response.get("max", "?")
    print(
        f"[{timestamp}] A0={raw}/{full_scale} (firmware samples {minimum}..{maximum})",
        flush=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="透過 UNO Q USB Serial 掃描接到 GND 的 GPIO"
    )
    parser.add_argument("--port", help="例如 COM3；省略時自動偵測 UNO Q")
    parser.add_argument("--once", action="store_true", help="只掃描一次後結束")
    parser.add_argument("--interval", type=float, default=0.4, help="連續掃描間隔秒數")
    parser.add_argument("--timeout", type=float, default=2.0, help="每次命令逾時秒數")
    parser.add_argument("--json", action="store_true", help="輸出原始 JSON")
    parser.add_argument(
        "--analog-a0",
        action="store_true",
        help="read A0 continuously instead of scanning D2-to-GND",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        port = args.port or find_uno_q_port()
        with GpioVerifier(port, timeout=args.timeout) as verifier:
            hello = verifier.request("hello")
            if not hello.get("ok"):
                raise RuntimeError(f"韌體 hello 失敗：{hello}")
            print(
                f"已連接 {port}：{hello.get('firmware')} v{hello.get('version')}，"
                f"安全模式={hello.get('mode')}，腳位數={hello.get('pin_count')}",
                file=sys.stderr,
                flush=True,
            )

            while True:
                command = "analog_a0" if args.analog_a0 else "scan"
                response = verifier.request(command)
                if not response.get("ok"):
                    raise RuntimeError(f"掃描失敗：{response}")
                if args.analog_a0:
                    print_analog(response, raw_json=args.json)
                else:
                    print_scan(response, raw_json=args.json)
                if args.once:
                    return 0
                time.sleep(max(args.interval, 0.05))
    except KeyboardInterrupt:
        print("\n測試已停止", file=sys.stderr)
        return 0
    except (OSError, RuntimeError, TimeoutError, serial.SerialException) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
