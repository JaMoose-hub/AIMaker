import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/circuitZoom.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { fitCircuitScale, readableCircuitScale, wheelCircuitZoom, anchoredCircuitScroll, bindCircuitWheel, clampCircuitZoom } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

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

test("Blueprint starts at a readable width without horizontal clipping, and fit remains available", () => {
  const fit = fitCircuitScale(900, 175, 840, 800);
  assert(fit < .3);
  const readable = readableCircuitScale(fit, 900, 840, .65);
  assert.equal(readable, .65);
  assert(readable * 840 <= 900 - 16);
  assert(readable * 800 > 175, "the diagram can scroll vertically at a legible size");
  assert.equal(readableCircuitScale(fit, 280, 840, .65), (280 - 16) / 840);
  assert.equal(readableCircuitScale(fit, 0, 840, .65), fit);
});

test("full-frame step mode fills the limiting axis without the compact scale cap or cropping", () => {
  for (const [w,h] of [[350,360],[840,500],[1065,610],[1400,850]]) for (const drawingHeight of [518,648]) {
    const scale=fitCircuitScale(w,h,840,drawingHeight,Infinity);
    assert(scale*840<=w-16+1e-6);
    assert(scale*drawingHeight<=h-16+1e-6);
    assert(Math.abs(scale*840-(w-16))<1e-6 || Math.abs(scale*drawingHeight-(h-16))<1e-6);
  }
  assert(fitCircuitScale(1065,850,840,518,Infinity)>1,'large step canvas is no longer limited to 80 percent');
  assert.equal(fitCircuitScale(1065,850,840,518),0.8,'existing overview behavior is unchanged');
  assert(Number.isFinite(fitCircuitScale(0,0,840,518,Infinity)));
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
