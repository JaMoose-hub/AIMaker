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
const { MAKER_STORAGE, RETIREMENT_BACKUP, CATALOG_BACKUP, needsCatalogMigration, needsRetirementMigration, migrateStoredMaker } = await import(dataURL(source));
const { initialMaker } = await import(maker);
const legacy = () => JSON.stringify({ ...initialMaker(), selected: ["hc-sr04", "hw-123", "mrd-tf240-8p-cs"], code: "user's code" });
function storage(raw) {
  const map = new Map([[MAKER_STORAGE, raw]]);
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value) };
}

const currentCatalog = JSON.parse(catalog);
function currentState() {
  const design = { id: 'supply-migration', revision: 2, source: 'demo', catalog_version: currentCatalog.version,
    title: 'My project', summary: 'My project', component_ids: ['hc-sr04'],
    wiring: currentCatalog.modules[0].steps.map(s => ({...s, id: `hc-sr04:${s.id}`, componentId: 'hc-sr04'})),
    code: '# new generated', tests: [], features: [], instructions: [], unresolved: [], bom: [] };
  return {...initialMaker(), design, code: design.code, stage: 'blueprint'};
}

test('3.3V migration backs up before request, preserves the project, and runs only once', async () => {
  const old = currentState();
  old.design.catalog_version = '1';
  old.design.wiring.find(w => w.componentPin === 'VCC').boardPin = '5V_P2';
  const raw = JSON.stringify(old), store = storage(raw);
  let calls = 0;
  await migrateStoredMaker(store, async (path, state) => {
    calls++;
    assert.equal(path, 'design/migrate-catalog');
    assert.equal(store.getItem(CATALOG_BACKUP), raw);
    assert.equal(state.design.id, old.design.id);
    return currentState();
  });
  assert.equal(JSON.parse(store.getItem(MAKER_STORAGE)).stage, 'blueprint');
  await migrateStoredMaker(store, async () => { calls++; });
  assert.equal(calls, 1);
  assert.equal(store.getItem(CATALOG_BACKUP), raw);
});

test('unknown versions and incomplete candidate migrations preserve the original draft', async () => {
  for (const version of ['1', 'unknown']) {
    const old = currentState();
    old.candidate = {...old.design, catalog_version: version};
    const raw = JSON.stringify(old);
    assert(needsCatalogMigration(raw));
    for (const request of [async () => { throw Error('offline'); }, async () => old,
      async () => ({...currentState(), candidate: {...currentState().design, wiring: []}})]) {
      const store = storage(raw);
      await assert.rejects(migrateStoredMaker(store, request));
      assert.equal(store.getItem(MAKER_STORAGE), raw);
    }
  }
});

test('TFT v2 upgrade creates a distinct backup without overwriting the earlier 3.3V backup', async () => {
  const old = currentState();
  old.design.catalog_version = '2';
  const raw = JSON.stringify(old), store = storage(raw);
  const earlier = 'boardvision.maker.v1.before-hcsr04-3v3';
  store.setItem(earlier, 'original 5V project');
  await migrateStoredMaker(store, async () => currentState());
  assert.equal(store.getItem(earlier), 'original 5V project');
  assert.equal(store.getItem(CATALOG_BACKUP), raw);
  assert.equal(needsCatalogMigration(store.getItem(MAKER_STORAGE)), false);
});

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
