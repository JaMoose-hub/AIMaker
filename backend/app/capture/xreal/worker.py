"""A separately terminable process owns the Windows R1 Media Foundation reader."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from queue import Full
import subprocess
import sys
import time

# Set before importing cv2 in the spawned process as well as its parent.
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

import cv2
import numpy as np

from .control import R1_USB_ID

MAX_BYTES = 2048 * 1920 * 3


def find_r1():
    from cv2_enumerate_cameras import enumerate_cameras

    devices = [device for device in enumerate_cameras(cv2.CAP_MSMF)
               if (device.vid, device.pid) == R1_USB_ID]
    if len(devices) > 1:
        raise RuntimeError("More than one R1 is connected")
    return devices[0] if devices else None


def _enable_with_timeout(stopped) -> None:
    """Bound HID calls too, and retire the helper when capture is cancelled."""
    process = subprocess.Popen(
        [sys.executable, "-u", str(Path(__file__).with_name("control.py"))],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 15
    try:
        while process.poll() is None:
            if stopped.wait(0.1):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("R1 HID enable timed out")
        _, error = process.communicate(timeout=1)
        if process.returncode:
            raise RuntimeError(error.decode(errors="replace").strip()[-1000:]
                               or "R1 HID enable failed")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)


def camera_worker(settings, pixels, metadata, frame_lock, stopped, messages,
                  reinitialize: bool = False) -> None:
    cv2.setNumThreads(1)
    cap = None
    com_result = None

    def report(**values):
        try:
            messages.put_nowait(values)
        except Full:
            pass

    try:
        if sys.platform != "win32":
            raise RuntimeError("R1 capture requires Windows Media Foundation")
        com_result = ctypes.windll.ole32.CoInitializeEx(None, 0)
        camera = find_r1()
        if camera is None or reinitialize:
            report(stage="enabling")
            _enable_with_timeout(stopped)
            if reinitialize:
                stopped.wait(0.8)
            camera = find_r1()
            deadline = time.monotonic() + 10
            while camera is None and time.monotonic() < deadline and not stopped.wait(0.5):
                camera = find_r1()
        if stopped.is_set():
            return
        if camera is None:
            raise RuntimeError("R1 camera missing; reconnect USB-C with Eye attached")
        report(stage="opening", device=str(camera))
        # Do not force MJPEG/HEVC or apply the main webcam's exposure/focus controls.
        cap = cv2.VideoCapture(camera.index, cv2.CAP_MSMF)
        if not cap.isOpened():
            raise RuntimeError("Windows could not open the R1 camera")
        accepted = {}
        for key, prop in (("width", cv2.CAP_PROP_FRAME_WIDTH),
                          ("height", cv2.CAP_PROP_FRAME_HEIGHT),
                          ("fps", cv2.CAP_PROP_FPS)):
            accepted[key] = bool(cap.set(prop, settings[key]))
        report(stage="waiting", property_accepted=accepted,
               driver_reported={"width": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                                "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
                                "fps": cap.get(cv2.CAP_PROP_FPS)})
        shared = np.frombuffer(pixels, dtype=np.uint8)
        count = 0
        while not stopped.is_set():
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Camera stopped delivering frames; reconnect USB-C")
            if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
                raise RuntimeError(f"Expected color uint8 image; received {frame.shape}")
            if frame.nbytes > MAX_BYTES:
                raise RuntimeError(f"R1 image exceeds capture buffer: {frame.shape}")
            count += 1
            stamp = time.monotonic_ns()
            if frame_lock.acquire(timeout=0.005):
                try:
                    shared[:frame.nbytes] = frame.reshape(-1)
                    metadata[:] = (count, frame.shape[1], frame.shape[0], stamp)
                finally:
                    frame_lock.release()
    except Exception as exc:
        report(error=str(exc))
    finally:
        if cap is not None:
            cap.release()
        if com_result in (0, 1):
            ctypes.windll.ole32.CoUninitialize()
