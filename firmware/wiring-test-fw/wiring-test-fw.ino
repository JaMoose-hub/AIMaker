// Board Vision electrical verification firmware for Arduino UNO Q.
//
// The UNO Q routes the STM32 sketch to Debian through Arduino_RouterBridge.
// A small Debian proxy exposes these RPC methods as newline-delimited JSON on
// the board's USB Serial Port. Every operation is intentionally read-only:
// digital test pins remain INPUT_PULLUP, A0 remains INPUT, and no GPIO is
// ever driven. The photoresistor module must be powered from UNO Q 3.3V.

#include <Arduino_RouterBridge.h>

struct TestPin {
  int number;
  const char *name;
};

// Start with one physical pin for the first end-to-end hardware proof. More
// pins are enabled after the COM3/RPC path and a D2-to-GND jumper are verified.
const TestPin TEST_PINS[] = {
    {D2, "D2"},
};

const size_t TEST_PIN_COUNT = sizeof(TEST_PINS) / sizeof(TEST_PINS[0]);
const int SAMPLE_COUNT = 7;
const int ANALOG_SAMPLE_COUNT = 9;
const int ANALOG_FULL_SCALE = 1023;  // UNO Q analogRead default is 10-bit.

void configureSafeInputs() {
  for (size_t i = 0; i < TEST_PIN_COUNT; ++i) {
    pinMode(TEST_PINS[i].number, INPUT_PULLUP);
  }
}

bool isHeldLow(int pin) {
  int lowSamples = 0;
  for (int sample = 0; sample < SAMPLE_COUNT; ++sample) {
    if (digitalRead(pin) == LOW) {
      ++lowSamples;
    }
    delay(1);
  }
  return lowSamples > SAMPLE_COUNT / 2;
}

String wiringHello() {
  String payload;
  payload.reserve(180);
  payload += "{\"ok\":true,\"device\":\"arduino-uno-q\",";
  payload += "\"firmware\":\"board-vision-wiring-test\",";
  payload += "\"version\":\"0.3.0\",\"mode\":\"read_only\",";
  payload += "\"pin_count\":";
  payload += TEST_PIN_COUNT;
  payload += ",\"features\":[\"input_pullup_gnd\",\"analog_a0\"]}";
  return payload;
}

String wiringScan() {
  bool heldLow[TEST_PIN_COUNT];
  configureSafeInputs();

  for (size_t i = 0; i < TEST_PIN_COUNT; ++i) {
    heldLow[i] = isHeldLow(TEST_PINS[i].number);
  }

  String payload;
  payload.reserve(700);
  payload += "{\"ok\":true,\"mode\":\"input_pullup_gnd\",\"pins\":{";
  for (size_t i = 0; i < TEST_PIN_COUNT; ++i) {
    if (i > 0) {
      payload += ',';
    }
    payload += '"';
    payload += TEST_PINS[i].name;
    payload += "\":\"";
    payload += heldLow[i] ? "connected_to_gnd" : "floating";
    payload += '"';
  }
  payload += "},\"connected_to_gnd\":[";

  bool first = true;
  for (size_t i = 0; i < TEST_PIN_COUNT; ++i) {
    if (!heldLow[i]) {
      continue;
    }
    if (!first) {
      payload += ',';
    }
    payload += '"';
    payload += TEST_PINS[i].name;
    payload += '"';
    first = false;
  }
  payload += "]}";
  return payload;
}

String wiringAnalogA0() {
  // A0/A1 are direct 3.3V ADC inputs on UNO Q and are not 5V tolerant.
  // Keep this endpoint read-only and use the default 10-bit ADC range.
  pinMode(A0, INPUT);
  analogRead(A0);  // discard the first conversion after channel selection
  delay(2);

  long total = 0;
  int minimum = ANALOG_FULL_SCALE;
  int maximum = 0;
  for (int sample = 0; sample < ANALOG_SAMPLE_COUNT; ++sample) {
    const int value = analogRead(A0);
    total += value;
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
    delay(2);
  }
  const int average = static_cast<int>(
      (total + ANALOG_SAMPLE_COUNT / 2) / ANALOG_SAMPLE_COUNT);

  String payload;
  payload.reserve(180);
  payload += "{\"ok\":true,\"pin\":\"A0\",\"raw\":";
  payload += average;
  payload += ",\"min\":";
  payload += minimum;
  payload += ",\"max\":";
  payload += maximum;
  payload += ",\"full_scale\":";
  payload += ANALOG_FULL_SCALE;
  payload += ",\"sample_count\":";
  payload += ANALOG_SAMPLE_COUNT;
  payload += "}";
  return payload;
}

bool wiringIdle() {
  configureSafeInputs();
  pinMode(A0, INPUT);
  return true;
}

void setup() {
  if (!Bridge.begin()) {
    return;
  }

  Bridge.provide("wiring/hello", wiringHello);
  Bridge.provide("wiring/scan", wiringScan);
  Bridge.provide("wiring/analog_a0", wiringAnalogA0);
  Bridge.provide("wiring/idle", wiringIdle);
}

void loop() {
  delay(50);
}
