import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/studioSplit.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { parseSplitRatio, splitStorageKey, studioSplitGeometry, splitRatioForLeft, dragSplitRatio, keySplitRatio } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("split preferences are separate by stage and corrupted storage is ignored", () => {
  assert.notEqual(splitStorageKey("design"), splitStorageKey("blueprint"));
  assert.equal(splitStorageKey("design"), 'boardvision.studio-split.v1.design');
  assert.equal(splitStorageKey("blueprint"), 'boardvision.studio-split.v2.blueprint');
  for (const raw of [null, "", " ", "NaN", "Infinity", "{}", "null", "-1", "0", "1", "12"]) assert.equal(parseSplitRatio(raw), null);
  assert.equal(parseSplitRatio("0.42"), .42);
});
test("default widths preserve a large concept image and compact blueprint sidebar", () => {
  assert.equal(studioSplitGeometry(1700, "design", null).left, 639.16);
  assert.equal(studioSplitGeometry(1700, "blueprint", null).left, 1302);
  assert.equal(studioSplitGeometry(3000, "design", null).left, 640);
});
test("dragging in either direction clamps both panes and uses pointer deltas, not page coordinates", () => {
  const width = 1600;
  assert.equal(studioSplitGeometry(width, "design", dragSplitRatio(500, 700, 800, width)).left, 600);
  assert.equal(studioSplitGeometry(width, "design", dragSplitRatio(500, 700, -5000, width)).left, 300);
  assert.equal(studioSplitGeometry(width, "design", dragSplitRatio(500, 700, 9999, width)).left, width - 18 - 360);
});
test("viewport changes retain preferred ratios while preventing overflow, including hidden containers", () => {
  for (const width of [0, 10, 500, 721, 900, 1700, 3000, NaN]) {
    for (const ratio of [null, .01, .3, .9, NaN]) {
      const g = studioSplitGeometry(width, "design", ratio);
      assert(Number.isFinite(g.left));
      assert(g.left >= 0 && g.left <= g.available);
      if (width >= 721) { assert(g.left >= 300); assert(g.available - g.left >= 360); }
    }
  }
  assert.equal(studioSplitGeometry(1200, "design", .5).left, 591);
  assert.equal(splitRatioForLeft(NaN, 0), .5);
});
test("keyboard arrows, coarse adjustment and bounds do not consume unrelated keys", () => {
  const width = 1600;
  const leftFor = (key, shift = false) => studioSplitGeometry(width, "design", keySplitRatio(key, shift, 500, width)).left;
  assert(Math.abs(leftFor("ArrowLeft") - 476) < 1e-6);
  assert(Math.abs(leftFor("ArrowRight") - 524) < 1e-6);
  assert(Math.abs(leftFor("ArrowRight", true) - 580) < 1e-6);
  assert.equal(leftFor("Home"), 300);
  assert.equal(leftFor("End"), width - 18 - 360);
  assert.equal(keySplitRatio("Tab", false, 500, width), null);
});
