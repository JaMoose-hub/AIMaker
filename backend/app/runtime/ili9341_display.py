"""Embedded verbatim into generated Pi programs; no BoardVision installation on Pi.

Uses luma.lcd's ILI9341 driver and an explicit gpiozero/lgpio adapter for Pi 5.
BLK is deliberately unconnected: never let the library claim its default GPIO18
(which this project's HC-SR04+ uses for ECHO).
"""
from PIL import Image, ImageDraw, ImageFont
from gpiozero import DigitalOutputDevice
from luma.core.interface.serial import spi
from luma.lcd.device import ili9341


class DisplayGPIO:
    LOW, HIGH, OUT = 0, 1, 1

    def __init__(self, factory, allowed):
        self.factory, self.allowed, self.outputs = factory, set(allowed), {}

    def setup(self, pin, direction, initial=0):
        if pin not in self.allowed or direction != self.OUT:
            raise ValueError("Display may control only its catalog DC and RES pins")
        self.outputs[pin] = DigitalOutputDevice(pin, initial_value=initial, pin_factory=self.factory)

    def output(self, pin, value):
        self.outputs[pin].value = bool(value)

    def close(self):
        for output in self.outputs.values():
            output.close()
        self.outputs.clear()


class WiringDisplay:
    def __init__(self, pins, factory):
        if (pins["SCL"], pins["SDA"], pins["CS"]) != (11, 10, 8):
            raise ValueError("ILI9341 runtime requires catalog SPI0 / CE0 wiring")
        self.gpio = DisplayGPIO(factory, (pins["DC"], pins["RES"]))
        self.serial = self.device = None
        try:
            self.serial = spi(port=0, device=0, gpio=self.gpio,
                              gpio_DC=pins["DC"], gpio_RST=pins["RES"],
                              bus_speed_hz=8000000, spi_mode=0,
                              reset_hold_time=0.02, reset_release_time=0.15)
            # luma's native ILI9341 mode is landscape. Rotation exposes the
            # photographed panel's portrait 240x320 surface to Pillow.
            self.device = ili9341(self.serial, width=320, height=240, rotate=1,
                                   backlight=lambda enabled: None)
            self.device.persist = True
        except Exception:
            self.close()
            raise

    @staticmethod
    def text(draw, position, text, color="white", size=20):
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            font = ImageFont.load_default()
        draw.text(position, text, fill=color, font=font)

    def test_card(self):
        image = Image.new("RGB", self.device.size, "#101820")
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(("red", "lime", "blue")):
            draw.rectangle((index * 80, 0, index * 80 + 79, 90), fill=color)
        self.text(draw, (12, 110), "ILI9341", size=30)
        self.text(draw, (12, 160), "240 x 320")
        self.text(draw, (12, 200), "VISUAL TEST", "#ffd166")
        self.text(draw, (12, 240), "R / G / B + text", size=18)
        self.device.display(image)

    def show_distance(self, distance, threshold):
        image = Image.new("RGB", self.device.size, "#101820")
        draw = ImageDraw.Draw(image)
        state = "NO ECHO" if distance is None else "WARNING" if distance < threshold else "OK"
        color = "#ffd166" if distance is None else "#ff5c65" if state == "WARNING" else "#44d6ac"
        self.text(draw, (12, 20), "DISTANCE")
        self.text(draw, (12, 88), "--" if distance is None else f"{distance:.1f}", size=42)
        self.text(draw, (180, 140), "cm")
        self.text(draw, (12, 200), state, color, size=30)
        self.text(draw, (12, 265), f"Limit: {threshold:g} cm", size=18)
        self.device.display(image)

    def close(self):
        # The luma device registers its own exit handler; persist avoids a
        # second clear over a closed SPI bus. Closing again is harmless.
        try:
            if self.serial is not None:
                self.serial.cleanup()
                self.serial = None
        finally:
            self.gpio.close()
