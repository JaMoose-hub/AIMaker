import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/wiringGuideProfiles.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const { piPhotoresistorExample, builtinWiringGuideProfile } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

test("Pi example follows the wiring profile, including changed GPIO mappings", () => {
  const guide = structuredClone(builtinWiringGuideProfile("raspberry-pi-5"));
  assert.match(piPhotoresistorExample(), /GPIO17/);
  const signal = guide.steps.find((step) => step.component_pin_id === "AO");
  signal.board_pin_id = "GPIO22";
  signal.board_label = "GPIO22 · Pin 15";
  const code = piPhotoresistorExample(guide);
  assert.match(code, /22, pull_up=None/);
  assert.match(code, /GPIO22: /);
  assert.doesNotMatch(code, /GPIO17/);
  assert.match(code, /flush=True/);
});

test("Arduino analog mappings cannot silently generate a Pi GPIO example", () => {
  assert.throws(() => piPhotoresistorExample(builtinWiringGuideProfile("arduino-uno-q")));
});
