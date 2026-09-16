import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/circuitZoom.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { fitCircuitScale, wheelCircuitZoom, anchoredCircuitScroll, bindCircuitWheel, clampCircuitZoom } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("default overview fits both axes in a sidebar or expanded dialog and stays compact", () => {
  for (const [w, h] of [[280, 300], [800, 500], [1400, 900]]) {
    for (const drawingHeight of [518, 624, 1360]) {
      const scale = fitCircuitScale(w, h, 840, drawingHeight);
      assert(scale * 840 <= w - 16);
      assert(scale * drawingHeight <= h - 16);
      assert(scale <= 0.8);
    }
  }
  assert(Number.isFinite(fitCircuitScale(0, 0, 840, 1300)), "hidden dialog remains finite until observed");
});

test("wheel direction, delta units and min/max zoom are bounded", () => {
  assert(wheelCircuitZoom(1, -100, 0) > 1);
  assert(wheelCircuitZoom(1, 100, 0) < 1);
  assert.equal(wheelCircuitZoom(1, 0, 0), 1);
  assert.equal(wheelCircuitZoom(1, 1, 1), wheelCircuitZoom(1, 16, 0));
  assert.equal(wheelCircuitZoom(1, 1, 2), wheelCircuitZoom(1, 300, 0));
  assert.equal(clampCircuitZoom(1000), 6);
  assert.equal(clampCircuitZoom(-1000), 0.4);
});

test("zoom anchors the cursor, handles centered drawings and clamps scroll at the edges", () => {
  assert.equal(anchoredCircuitScroll(100, 200, 500, 1000, 2000), 400);
  assert.equal(anchoredCircuitScroll(0, 250, 500, 300, 900), 200);
  assert.equal(anchoredCircuitScroll(400, 200, 500, 2000, 300), 0);
  assert.equal(anchoredCircuitScroll(0, 0, 500, 300, 900), 0);
  assert.equal(anchoredCircuitScroll(500, 500, 500, 1000, 2000), 1500);
});

test("only Ctrl/Meta wheel is intercepted, including bounds; plain scroll and cleanup work", () => {
  let listener;
  let zoomCalls = 0;
  const element = {
    addEventListener(type, callback, options) { assert.equal(type, "wheel"); assert.equal(options.passive, false); listener = callback; },
    removeEventListener(type, callback) { assert.equal(type, "wheel"); assert.equal(callback, listener); listener = undefined; },
  };
  const cleanup = bindCircuitWheel(element, () => zoomCalls++);
  const event = (extra = {}) => ({ ctrlKey: false, metaKey: false, deltaY: 100, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...extra });
  const plain = event(); listener(plain); assert.equal(plain.prevented, false); assert.equal(plain.stopped, false);
  for (const modifier of [{ ctrlKey: true }, { metaKey: true }]) {
    const e = event(modifier); listener(e); assert.equal(e.prevented, true); assert.equal(e.stopped, true);
  }
  assert.equal(zoomCalls, 2);
  const horizontal = event({ ctrlKey: true, deltaY: 0 }); listener(horizontal);
  assert.equal(horizontal.prevented, true); assert.equal(zoomCalls, 2);
  cleanup(); assert.equal(listener, undefined);
});
