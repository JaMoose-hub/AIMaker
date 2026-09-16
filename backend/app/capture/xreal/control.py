"""R1 Eye-enable HID command, ported from nudou350/Xreal-tools.

Protocol portions are adapted from GlassesFrame.kt and GlassesCommands.kt
(Apache-2.0). See this package's licenses/ and NOTICE.md. The local Python
port and Windows R1 adaptation originated in the standalone Eye experiment.
"""
from __future__ import annotations

import struct
import time
import zlib

R1_USB_ID = (0x0B05, 0x1D9D)


def make_frame(command: int, payload: bytes = b"") -> bytes:
    if len(payload) > 233:
        raise ValueError("Control payload is too long")
    data = bytearray(22 + len(payload))
    data[0], data[5], data[15] = 0xFD, len(data) - 5, command
    data[22:] = payload
    struct.pack_into("<I", data, 1, zlib.crc32(data[5:]))
    return bytes(data)


def parse_frame(data: bytes) -> tuple[int, bytes]:
    if len(data) < 22 or data[0] != 0xFD:
        raise ValueError("Invalid XREAL control frame")
    total = data[5] + 5
    if not 22 <= total <= len(data):
        raise ValueError("Invalid XREAL control frame length")
    if zlib.crc32(data[5:total]) != int.from_bytes(data[1:5], "little"):
        raise ValueError("XREAL control response CRC mismatch")
    return data[15], data[22:total]


def enable_eye() -> None:
    """Enable only the known R1 RGB interface; no firmware or driver changes."""
    import hid

    devices = [device for device in hid.enumerate(*R1_USB_ID)
               if device["interface_number"] == 0]
    if len(devices) != 1:
        raise RuntimeError(f"Expected one R1 control interface; found {len(devices)}")
    device = hid.device()
    try:
        device.open_path(devices[0]["path"])

        def request(command: int, payload: bytes = b"") -> bytes:
            packet = make_frame(command, payload)
            # Report ID zero precedes the device's 1024-byte output report.
            written = device.write(b"\0" + packet.ljust(1024, b"\0"))
            if written != 1025:
                raise RuntimeError(f"Incomplete R1 HID write: {written}")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                raw = bytes(device.read(1024, 200))
                if not raw:
                    continue
                code, body = parse_frame(raw)
                if code != command:
                    continue
                if not body or body[0] != 0:
                    raise RuntimeError(f"R1 command {command:#x} failed: {body.hex()}")
                return body
            raise TimeoutError(f"No R1 response to {command:#x}")

        if request(0xD6, b"ro.bsp.app_prepare_done")[1:] != b"true":
            raise RuntimeError("R1 is still starting; apply the settings again")
        request(0xD3, bytes.fromhex("45100100"))
    finally:
        device.close()


if __name__ == "__main__":
    import sys
    try:
        enable_eye()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
