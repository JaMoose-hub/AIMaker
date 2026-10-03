import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/studioSplit.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { parseSplitRatio, splitStorageKey, studioSplitGeometry, splitRatioForLeft, dragSplitRatio, keySplitRatio,
  GUIDE_SPLIT_STORAGE_KEY, guideSplitGeometry, guideRatioForRight, dragGuideRatio, keyGuideRatio,
  GUIDE_HEIGHT_STORAGE_KEY, guideHeightGeometry, guideRatioForTop, dragGuideHeightRatio, keyGuideHeightRatio } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

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

test("camera/guide resizing has a separate preference, stable defaults and safe bounds", () => {
  assert.notEqual(GUIDE_SPLIT_STORAGE_KEY, splitStorageKey("design"));
  const defaultLayout = guideSplitGeometry(1600, null);
  assert.equal(defaultLayout.right, 400);
  assert.equal(defaultLayout.left + defaultLayout.right + 18, 1600);
  for (const width of [0, 10, 600, 960, 1600, 3000, NaN]) {
    for (const ratio of [null, .01, .3, .9, NaN]) {
      const geometry = guideSplitGeometry(width, ratio);
      assert(Number.isFinite(geometry.right));
      assert(geometry.right >= geometry.minRight && geometry.right <= geometry.maxRight);
      assert(geometry.left >= 0);
      if (width >= 960) { assert(geometry.right >= 280); assert(geometry.left >= 480); }
    }
  }
});

test("camera/guide pointer and keyboard resizing clamp both sides", () => {
  const width = 1600;
  const original = guideSplitGeometry(width, null).right;
  assert.equal(guideSplitGeometry(width, dragGuideRatio(original, 700, 800, width)).right, 300);
  assert.equal(guideSplitGeometry(width, dragGuideRatio(original, 700, -5000, width)).right, 700);
  assert.equal(guideSplitGeometry(width, dragGuideRatio(original, 700, 9999, width)).right, 280);
  assert.equal(guideSplitGeometry(width, keyGuideRatio("ArrowLeft", false, original, width)).right, 424);
  assert.equal(guideSplitGeometry(width, keyGuideRatio("ArrowRight", true, original, width)).right, 320);
  assert.equal(guideSplitGeometry(width, keyGuideRatio("Home", false, original, width)).right, 700);
  assert.equal(guideSplitGeometry(width, keyGuideRatio("End", false, original, width)).right, 280);
  assert.equal(keyGuideRatio("Tab", false, original, width), null);
  assert.equal(guideRatioForRight(NaN, 0), .5);
});

test("stacked heights preserve separate preferences and keep both panes within the viewport", () => {
  assert.notEqual(GUIDE_HEIGHT_STORAGE_KEY, GUIDE_SPLIT_STORAGE_KEY);
  assert.equal(GUIDE_HEIGHT_STORAGE_KEY, 'boardvision.guide-height.v2');
  for (const height of [0, 10, 250, 420, 520, 760, 1200, NaN]) {
    for (const ratio of [null, .01, .55, .99, NaN]) {
      const g = guideHeightGeometry(height, ratio);
      assert(Number.isFinite(g.top) && Number.isFinite(g.bottom));
      assert(g.top >= g.minTop && g.top <= g.maxTop);
      assert(g.bottom >= 0);
      assert.equal(g.top + g.bottom, g.available);
      if (height >= 438) { assert(g.top >= 180); assert(g.bottom >= 160); }
    }
  }
  assert.equal(guideHeightGeometry(760, .5).top, 371);
  assert.equal(guideRatioForTop(NaN, 0), .5);
});

test("default stacked workspace assigns 70 percent to streaming and 30 percent to wiring", () => {
  for (const height of [600, 742, 760, 871, 1200]) {
    const layout = guideHeightGeometry(height, null);
    assert(Math.abs(layout.top / layout.available - .7) < 1e-9);
    assert(Math.abs(layout.bottom / layout.available - .3) < 1e-9);
  }
});

test("stacked pointer and keyboard resizing follow up/down motion and clamp at safe heights", () => {
  const height = 760;
  const topFor = ratio => guideHeightGeometry(height, ratio).top;
  const close = (actual, expected) => assert(Math.abs(actual - expected) < 1e-6, `${actual} != ${expected}`);
  close(topFor(dragGuideHeightRatio(350, 410, 460, height)), 400);
  assert.equal(topFor(dragGuideHeightRatio(350, 410, -9999, height)), 180);
  assert.equal(topFor(dragGuideHeightRatio(350, 410, 9999, height)), height - 18 - 160);
  close(topFor(keyGuideHeightRatio('ArrowUp', false, 350, height)), 326);
  close(topFor(keyGuideHeightRatio('ArrowDown', true, 350, height)), 430);
  assert.equal(topFor(keyGuideHeightRatio('Home', false, 350, height)), 180);
  assert.equal(topFor(keyGuideHeightRatio('End', false, 350, height)), 582);
  assert.equal(keyGuideHeightRatio('Tab', false, 350, height), null);
  assert.equal(keyGuideHeightRatio('ArrowLeft', false, 350, height), null);
});

test("test contents set the minimum height without changing the saved camera preference", () => {
  const height = 760, minimum = 410, preference = .95;
  const geometry = guideHeightGeometry(height, preference, minimum);
  assert.equal(geometry.bottom, minimum);
  assert(geometry.top >= 180);
  assert.equal(guideHeightGeometry(height, preference).bottom, 160);
  const end = keyGuideHeightRatio('End', false, geometry.top, height, minimum);
  assert.equal(guideHeightGeometry(height, end, minimum).bottom, minimum);
  const dragged = dragGuideHeightRatio(geometry.top, 400, 9999, height, minimum);
  assert.equal(guideHeightGeometry(height, dragged, minimum).bottom, minimum);
  assert.equal(guideRatioForTop(9999, height, minimum), end);
});

test("oversized test contents preserve camera space and invalid content bounds are safe", () => {
  for (const height of [0, 10, 250, 420, 760, NaN]) {
    for (const minimum of [-5, 0, 410, 9999, NaN, Infinity]) {
      const g = guideHeightGeometry(height, .9, minimum);
      assert(Number.isFinite(g.top) && Number.isFinite(g.bottom));
      assert(g.top >= g.minTop && g.top <= g.maxTop);
      assert(g.bottom >= 0);
      assert.equal(g.top + g.bottom, g.available);
      if (height >= 468) assert(g.top >= 180);
    }
  }
  assert.deepEqual(guideHeightGeometry(760, .9, NaN), guideHeightGeometry(760, .9));
});
