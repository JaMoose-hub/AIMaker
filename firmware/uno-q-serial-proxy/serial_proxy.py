#!/usr/bin/env python3
"""Bridge UNO Q USB Serial monitor bytes to STM32 wiring RPC methods.

This runs on the UNO Q Debian side and intentionally uses only Python's
standard library. The system's arduino-router-serial service already connects
/dev/ttyGS0 (Windows COM port) to the router monitor API.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Any


ROUTER_SOCKET = "/var/run/arduino-router.sock"


class NeedMoreData(Exception):
    pass


def pack(value: Any) -> bytes:
    if value is None:
        return b"\xc0"
    if value is False:
        return b"\xc2"
    if value is True:
        return b"\xc3"
    if isinstance(value, int):
        if 0 <= value <= 0x7F:
            return bytes((value,))
        if -32 <= value < 0:
            return bytes((value & 0xFF,))
        if 0 <= value <= 0xFF:
            return b"\xcc" + value.to_bytes(1, "big")
        if 0 <= value <= 0xFFFF:
            return b"\xcd" + value.to_bytes(2, "big")
        if 0 <= value <= 0xFFFFFFFF:
            return b"\xce" + value.to_bytes(4, "big")
        if -128 <= value < 0:
            return b"\xd0" + value.to_bytes(1, "big", signed=True)
        if -32768 <= value < 0:
            return b"\xd1" + value.to_bytes(2, "big", signed=True)
        return b"\xd2" + value.to_bytes(4, "big", signed=True)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        length = len(encoded)
        if length <= 31:
            return bytes((0xA0 | length,)) + encoded
        if length <= 0xFF:
            return b"\xd9" + bytes((length,)) + encoded
        return b"\xda" + length.to_bytes(2, "big") + encoded
    if isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
        length = len(encoded)
        if length <= 0xFF:
            return b"\xc4" + bytes((length,)) + encoded
        return b"\xc5" + length.to_bytes(2, "big") + encoded
    if isinstance(value, (list, tuple)):
        length = len(value)
        header = bytes((0x90 | length,)) if length <= 15 else b"\xdc" + length.to_bytes(2, "big")
        return header + b"".join(pack(item) for item in value)
    if isinstance(value, dict):
        length = len(value)
        header = bytes((0x80 | length,)) if length <= 15 else b"\xde" + length.to_bytes(2, "big")
        return header + b"".join(pack(item) for pair in value.items() for item in pair)
    raise TypeError(f"unsupported MessagePack value: {type(value).__name__}")


def _take(data: bytes, offset: int, size: int) -> tuple[bytes, int]:
    end = offset + size
    if end > len(data):
        raise NeedMoreData
    return data[offset:end], end


def unpack_one(data: bytes, offset: int = 0) -> tuple[Any, int]:
    if offset >= len(data):
        raise NeedMoreData
    marker = data[offset]
    offset += 1

    if marker <= 0x7F:
        return marker, offset
    if marker >= 0xE0:
        return marker - 256, offset
    if 0xA0 <= marker <= 0xBF:
        raw, offset = _take(data, offset, marker & 0x1F)
        return raw.decode("utf-8"), offset
    if 0x90 <= marker <= 0x9F:
        length = marker & 0x0F
        items = []
        for _ in range(length):
            item, offset = unpack_one(data, offset)
            items.append(item)
        return items, offset
    if 0x80 <= marker <= 0x8F:
        length = marker & 0x0F
        result = {}
        for _ in range(length):
            key, offset = unpack_one(data, offset)
            value, offset = unpack_one(data, offset)
            result[key] = value
        return result, offset
    if marker == 0xC0:
        return None, offset
    if marker == 0xC2:
        return False, offset
    if marker == 0xC3:
        return True, offset

    sized_binary = {0xC4: 1, 0xC5: 2, 0xC6: 4}
    sized_string = {0xD9: 1, 0xDA: 2, 0xDB: 4}
    sized_array = {0xDC: 2, 0xDD: 4}
    sized_map = {0xDE: 2, 0xDF: 4}
    integer_types = {
        0xCC: (1, False),
        0xCD: (2, False),
        0xCE: (4, False),
        0xCF: (8, False),
        0xD0: (1, True),
        0xD1: (2, True),
        0xD2: (4, True),
        0xD3: (8, True),
    }

    if marker in integer_types:
        size, signed = integer_types[marker]
        raw, offset = _take(data, offset, size)
        return int.from_bytes(raw, "big", signed=signed), offset
    if marker in sized_binary:
        size_bytes, offset = _take(data, offset, sized_binary[marker])
        length = int.from_bytes(size_bytes, "big")
        return _take(data, offset, length)
    if marker in sized_string:
        size_bytes, offset = _take(data, offset, sized_string[marker])
        length = int.from_bytes(size_bytes, "big")
        raw, offset = _take(data, offset, length)
        return raw.decode("utf-8"), offset
    if marker in sized_array:
        size_bytes, offset = _take(data, offset, sized_array[marker])
        length = int.from_bytes(size_bytes, "big")
        items = []
        for _ in range(length):
            item, offset = unpack_one(data, offset)
            items.append(item)
        return items, offset
    if marker in sized_map:
        size_bytes, offset = _take(data, offset, sized_map[marker])
        length = int.from_bytes(size_bytes, "big")
        result = {}
        for _ in range(length):
            key, offset = unpack_one(data, offset)
            value, offset = unpack_one(data, offset)
            result[key] = value
        return result, offset
    raise ValueError(f"unsupported MessagePack marker 0x{marker:02x}")


class RouterClient:
    def __init__(self, path: str = ROUTER_SOCKET) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(3.0)
        self._socket.connect(path)
        self._buffer = b""
        self._request_id = 1

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, *params: Any) -> Any:
        request_id = self._request_id
        self._request_id = 1 if request_id >= 0x7F else request_id + 1
        self._socket.sendall(pack([0, request_id, method, list(params)]))

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                message, used = unpack_one(self._buffer)
            except NeedMoreData:
                chunk = self._socket.recv(4096)
                if not chunk:
                    raise ConnectionError("arduino-router closed the connection")
                self._buffer += chunk
                continue
            self._buffer = self._buffer[used:]
            if not isinstance(message, list) or len(message) != 4:
                continue
            kind, response_id, error, result = message
            if kind != 1 or response_id != request_id:
                continue
            if error is not None:
                raise RuntimeError(f"RPC {method} failed: {error!r}")
            return result
        raise TimeoutError(f"RPC {method} timed out")

    def __enter__(self) -> "RouterClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def add_request_id(payload: str, request_id: Any) -> str:
    response = json.loads(payload)
    response["id"] = request_id
    return json.dumps(response, separators=(",", ":")) + "\n"


def serve() -> None:
    line_buffer = bytearray()
    with RouterClient() as router:
        # Discard bytes left by a previous serial terminal/session. Without
        # this, an old partial line can prefix the first JSON request.
        for _ in range(32):
            if not router.call("mon/read", 512):
                break
        print("board-vision serial proxy ready", flush=True)
        while True:
            incoming = router.call("mon/read", 512)
            if incoming:
                if isinstance(incoming, str):
                    incoming = incoming.encode("utf-8")
                line_buffer.extend(incoming)

            while b"\n" in line_buffer:
                raw_line, _, remaining = line_buffer.partition(b"\n")
                line_buffer = bytearray(remaining)
                try:
                    request = json.loads(raw_line.decode("utf-8"))
                    command = request.get("cmd")
                    request_id = request.get("id", 0)
                    if command == "hello":
                        output = add_request_id(router.call("wiring/hello"), request_id)
                    elif command == "scan":
                        output = add_request_id(router.call("wiring/scan"), request_id)
                    elif command == "analog_a0":
                        output = add_request_id(
                            router.call("wiring/analog_a0"), request_id
                        )
                    elif command == "idle":
                        router.call("wiring/idle")
                        output = json.dumps(
                            {"id": request_id, "ok": True, "mode": "input_pullup_gnd"},
                            separators=(",", ":"),
                        ) + "\n"
                    else:
                        output = json.dumps(
                            {"id": request_id, "ok": False, "error": "unknown_command"},
                            separators=(",", ":"),
                        ) + "\n"
                except Exception as exc:
                    output = json.dumps(
                        {"id": 0, "ok": False, "error": str(exc)},
                        separators=(",", ":"),
                    ) + "\n"
                router.call("mon/write", output)

            if not incoming:
                time.sleep(0.02)


def self_test() -> None:
    with RouterClient() as router:
        print(router.call("wiring/hello"))
        print(router.call("wiring/scan"))
        print(router.call("wiring/analog_a0"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        self_test() if args.self_test else serve()
        return 0
    except Exception as exc:
        print(f"serial proxy error: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
