import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Test the actual pure TypeScript module without adding a browser/test dependency.
const catalog = readFileSync(new URL("../../profiles/component-catalog.json", import.meta.url), "utf8");
const source = readFileSync(new URL("../src/lib/componentWiringGuides.ts", import.meta.url), "utf8").replace(/import catalog from [^;]+;/, `const catalog = ${catalog};`);
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const { COMPONENT_GUIDES, initialGuideSession, guideReducer, guideFor, prerequisitesMet, guidePoseReady, guidePoseVisible } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const board = JSON.parse(readFileSync(new URL("../../profiles/boards/raspberry-pi-5/board.json", import.meta.url), "utf8"));
function prepare(id = "hc-sr04") {
  let state = initialGuideSession(id);
  for (const item of guideFor(id).prerequisites) state = guideReducer(state, { type: "check", id: item.id, checked: true });
  return state;
}
test("both lessons use existing pins, correct bus roles and bilingual instructions", () => {
  assert.deepEqual(COMPONENT_GUIDES.map((g) => g.id), ["hc-sr04", "mrd-tf240-8p-cs"]);
  for (const guide of COMPONENT_GUIDES) {
    const component = JSON.parse(readFileSync(new URL(`../../profiles/components/${guide.id}/component.json`, import.meta.url), "utf8"));
    for (const step of guide.steps) {
      assert(board.pins.some((pin) => pin.id === step.boardPin));
      assert(component.pins.some((pin) => pin.id === step.componentPin));
      assert(step.instruction["zh-TW"] && step.instruction.en && step.hint["zh-TW"] && step.hint.en);
    }
    assert.equal(guide.steps[0].componentPin, "GND");
    assert.equal(new Set(guide.steps.map((s) => s.boardPin)).size, guide.steps.length);
  }
  assert.equal(guideFor("mrd-tf240-8p-cs").steps.find((s) => s.componentPin === "SDA").boardPin, "GPIO10");
  assert.equal(guideFor("mrd-tf240-8p-cs").steps.find((s) => s.componentPin === "SCL").boardPin, "GPIO11");
});
test("HC-SR04 ECHO is protected and display supply/backlight have no wiring target", () => {
  const hc = guideFor("hc-sr04");
  assert.equal(hc.steps.find((s) => s.componentPin === "ECHO").connectionKind, "divider");
  assert(hc.prerequisites.some((p) => p.id === "divider-ready"));
  assert.equal(hc.steps.at(-1).componentPin, "VCC");
  const display = guideFor("mrd-tf240-8p-cs");
  assert(!display.steps.some((s) => ["VCC", "BLK"].includes(s.componentPin)));
  assert.deepEqual(display.unresolved.map((p) => p.pin), ["VCC", "BLK"]);
});
test("prepare checks are mandatory and never carry to another module", () => {
  let state = initialGuideSession();
  assert.equal(guideReducer(state, { type: "start" }), state);
  state = prepare();
  assert(prerequisitesMet(state));
  state = guideReducer(state, { type: "select", id: "mrd-tf240-8p-cs" });
  assert.equal(prerequisitesMet(state), false);
  assert.deepEqual(state.confirmed, []);
});
test("only manual confirmation advances, and module selection is locked during wiring", () => {
  const state = guideReducer(prepare(), { type: "start" });
  assert.equal(state.phase, "active");
  assert.equal(guideReducer(state, { type: "confirm", ready: false }), state);
  assert.equal(guideReducer(state, { type: "select", id: "mrd-tf240-8p-cs" }), state);
  const next = guideReducer(state, { type: "confirm", ready: true });
  assert.equal(next.index, 1);
  assert.deepEqual(next.confirmed, ["gnd"]);
});
test("backtracking invalidates later confirmations; ending early is incomplete", () => {
  let state = guideReducer(prepare(), { type: "start" });
  state = guideReducer(state, { type: "confirm", ready: true });
  state = guideReducer(state, { type: "confirm", ready: true });
  state = guideReducer(state, { type: "previous" });
  assert.equal(state.index, 1);
  assert.deepEqual(state.confirmed, ["gnd"]);
  state = guideReducer(state, { type: "end" });
  assert.equal(state.phase, "review");
  assert.equal(state.confirmed.length, 1);
});
test("all lessons reach a manual-only review and reset clears progress", () => {
  for (const guide of COMPONENT_GUIDES) {
    let state = guideReducer(prepare(guide.id), { type: "start" });
    for (const _ of guide.steps) state = guideReducer(state, { type: "confirm", ready: true });
    assert.equal(state.phase, "review");
    assert.equal(state.confirmed.length, guide.steps.length);
    state = guideReducer(state, { type: "previous" });
    assert.equal(state.confirmed.length, guide.steps.length - 1);
    assert.deepEqual(guideReducer(state, { type: "reset" }), initialGuideSession(guide.id));
  }
});
test("target identity, visible pins and fresh locked poses are all required", () => {
  const detection = { tracking: "locked", pins: [{ id: "GND_P6", v: true }] };
  const pose = { component_id: "hc-sr04", tracking: "locked", pins: [{ id: "GND", v: true }] };
  const target = { componentId: "hc-sr04", boardPinId: "GND_P6", componentPinId: "GND" };
  assert(guidePoseReady(detection, pose, target, true));
  assert(!guidePoseReady(detection, { ...pose, component_id: "mrd-tf240-8p-cs" }, target, true));
  assert(!guidePoseReady(detection, { ...pose, tracking: "stale" }, target, true));
  assert(!guidePoseReady({ ...detection, tracking: "searching" }, pose, target, true));
  assert(!guidePoseReady(detection, pose, target, false));
  assert(!guidePoseReady(detection, { ...pose, pins: [{ id: "GND", v: false }] }, target, true));
  assert(guidePoseVisible({ ...detection, tracking: "stale" }, { ...pose, tracking: "stale" }, target, true));
  assert(!guidePoseVisible({ ...detection, tracking: "searching" }, pose, target, true));
  assert(!guidePoseVisible(detection, { ...pose, tracking: "searching" }, target, true));
  assert(!guidePoseVisible(detection, pose, target, false));
});
