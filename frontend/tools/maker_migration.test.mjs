import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const dataURL = source => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText).toString("base64")}`;
const catalog = readFileSync(new URL("../../profiles/component-catalog.json", import.meta.url), "utf8");
const maker = dataURL(readFileSync(new URL("../src/lib/maker.ts", import.meta.url), "utf8")
  .replace(/import catalog from [^;]+;/, `const catalog = ${catalog};`));
const source = readFileSync(new URL("../src/lib/makerMigration.ts", import.meta.url), "utf8")
  .replace('from "./maker"', `from "${maker}"`);
const { MAKER_STORAGE, RETIREMENT_BACKUP, needsRetirementMigration, migrateStoredMaker } = await import(dataURL(source));
const { initialMaker } = await import(maker);
const legacy = () => JSON.stringify({ ...initialMaker(), selected: ["hc-sr04", "hw-123", "mrd-tf240-8p-cs"], code: "user's code" });
function storage(raw) {
  const map = new Map([[MAKER_STORAGE, raw]]);
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value) };
}

test("only active draft references trigger migration; historical conversation stays intact", () => {
  assert(needsRetirementMigration(legacy()));
  for (const raw of [null, "broken", JSON.stringify(initialMaker()), JSON.stringify({ conversation: [{text:"HW-123"}] })])
    assert(!needsRetirementMigration(raw));
  assert(needsRetirementMigration(JSON.stringify({ candidate: {component_ids:["hw-123"]} })));
});

test("backup precedes request, draft migration runs once, existing backup is not overwritten", async () => {
  const raw = legacy(), store = storage(raw);
  let calls = 0;
  const request = async (path, state) => {
    calls++;
    assert.equal(path, "design/migrate-retired");
    assert.equal(store.getItem(RETIREMENT_BACKUP), raw);
    return { ...state, selected: ["hc-sr04", "mrd-tf240-8p-cs"] };
  };
  await migrateStoredMaker(store, request);
  assert.equal(JSON.parse(store.getItem(RETIREMENT_BACKUP)).code, "user's code");
  await migrateStoredMaker(store, request);
  assert.equal(calls, 1);
  store.setItem(MAKER_STORAGE, legacy());
  await migrateStoredMaker(store, request);
  assert.equal(store.getItem(RETIREMENT_BACKUP), raw);
});

test("API/storage failures and malformed migrations cannot overwrite the active original", async () => {
  for (const request of [async () => { throw Error("offline"); }, async () => ({}), async () => JSON.parse(legacy())]) {
    const raw = legacy(), store = storage(raw);
    await assert.rejects(migrateStoredMaker(store, request));
    assert.equal(store.getItem(MAKER_STORAGE), raw);
  }
  let called = false;
  const store = storage(legacy());
  store.setItem = () => { throw Error("storage full"); };
  await assert.rejects(migrateStoredMaker(store, async () => { called = true; }));
  assert.equal(called, false);
});
