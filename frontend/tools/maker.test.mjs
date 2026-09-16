import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const catalog = JSON.parse(readFileSync(new URL("../../profiles/component-catalog.json", import.meta.url), "utf8"));
const source = readFileSync(new URL("../src/lib/maker.ts", import.meta.url), "utf8").replace(/import catalog from [^;]+;/, `const catalog = ${JSON.stringify(catalog)};`);
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const m = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const design = {
  id: "test", revision: 1, source: "demo", catalog_version: catalog.version, title: "test", summary: "test",
  component_ids: ["hc-sr04"], wiring: catalog.modules[0].steps.map(s => ({ ...s, id: `hc-sr04:${s.id}`, componentId: "hc-sr04" })),
  code: "old", tests: [], features: [], instructions: [], unresolved: [], bom: [],
};
test("image requests are explicit, safe image URLs survive restoration, failed images cannot confirm", () => {
  const state = m.initialMaker();
  assert.equal(m.designRequest(state, 'zh-TW', null).generate_image, true);
  assert.equal(m.designRequest({...state, aiIntent: 'ask'}, 'zh-TW', null).generate_image, false);
  const pending = {...design, image_required: true, image_error: 'quota'};
  const withCandidate = {...state, candidate: pending};
  assert.equal(m.confirmConcept(withCandidate), withCandidate);
  const id = 'a'.repeat(32);
  const image = {id, url: `/api/design/images/${id}`, width: 1024, height: 1024};
  const complete = {...pending, image};
  assert.equal(m.validDesign(complete), true);
  assert.equal(m.validDesign({...complete, image: {...image, url: 'https://external.invalid/image'}}), false);
  assert.equal(m.restoreMaker(JSON.stringify({...state, candidate: complete})).candidate.image.url, image.url);
  assert.equal(m.confirmConcept({...state, candidate: complete}).stage, 'blueprint');
  assert.equal(m.validDesign({...complete, assembly: {description:'cart', parts:[{kind:'motor', quantity:1, purpose:'drive'}]}}), false);
});
test("saved project is validated and restoration never revives camera evidence", () => {
  let state = m.applyDesign(m.initialMaker(), design, "guide");
  state.guide.phase = "active"; state.guide.checks = ["power-off"];
  state.code = "manual draft";
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.code, "manual draft");
  assert.equal(restored.guide.phase, "prepare");
  assert.equal(restored.guide.restored, true);
  assert.deepEqual(restored.guide.checks, []);
  assert.equal(m.restoreMaker("broken").design, null);
  assert.equal(m.restoreMaker(JSON.stringify({ ...state, design: { ...design, catalog_version: "bad" } })).design, null);
});
test("candidate does not overwrite manual code; applying revision preserves only matching wires", () => {
  let state = m.applyDesign(m.initialMaker(), design, "guide");
  state.code = "manual";
  for (const w of design.wiring) state.guide.confirmed[w.id] = { signature: m.wireSignature(w), mode: "camera", at: "test" };
  const revision = { ...design, revision: 2, code: "new" };
  state.guide.phase = "active"; state.guide.index = 2;
  state.candidate = revision;
  assert.equal(state.code, "manual");
  const applied = m.applyDesign(state, revision, "design");
  assert.equal(applied.code, "new");
  assert.equal(Object.keys(applied.guide.confirmed).length, 4);
  assert.equal(applied.guide.index, 2);
  assert.equal(applied.guide.phase, "active");
  const rewired = { ...revision, wiring: revision.wiring.map((w, i) => i ? w : { ...w, boardPin: "GND_P9" }) };
  assert.equal(Object.keys(m.applyDesign(state, rewired, "guide").guide.confirmed).length, 3);
  assert.equal(Object.keys(m.applyDesign(state, { ...revision, id: "different" }, "guide").guide.confirmed).length, 0);
});
test("unknown wires cannot be restored as authoritative project pins", () => {
  assert(m.validDesign(design));
  assert(!m.validDesign({ ...design, wiring: [{ ...design.wiring[0], boardPin: "GPIO99" }] }));
  assert(!m.validDesign({ ...design, component_ids: ["fake-module"] }));
  assert(!m.validDesign({ ...design, component_ids: ["hc-sr04", "hc-sr04"] }));
  const restored = m.restoreMaker(JSON.stringify({ ...m.initialMaker(), design, guide: { confirmed: null, componentIndex: "invalid", mode: "fake" }, conversation: [null] }));
  assert.equal(restored.guide.componentIndex, 0);
  assert.equal(restored.guide.mode, "camera");
  assert.deepEqual(restored.conversation, []);
});

test("AI choices persist without touching projects and older saved state migrates safely", () => {
  const state = { ...m.initialMaker(), design, code: "manual code", aiModel: "gpt-5.6-luna", aiEffort: "high", aiExpectedOutputTokens: 8000 };
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.aiModel, "gpt-5.6-luna");
  assert.equal(restored.aiEffort, "high");
  assert.equal(restored.aiExpectedOutputTokens, 8000);
  assert.equal(restored.code, "manual code");
  const legacy = { ...state }; delete legacy.aiModel; delete legacy.aiEffort; delete legacy.aiExpectedOutputTokens;
  assert.equal(m.restoreMaker(JSON.stringify(legacy)).aiEffort, "low");
  const invalid = m.restoreMaker(JSON.stringify({ ...state, aiModel: {}, aiEffort: "invented", aiExpectedOutputTokens: -20 }));
  assert.equal(invalid.aiModel, ""); assert.equal(invalid.aiEffort, "low"); assert.equal(invalid.aiExpectedOutputTokens, null);
  assert.equal(m.applyDesign(state, { ...design, revision: 2 }, "design").aiModel, state.aiModel);
});

test("blueprint confirmation preserves the part catalog and survives reload", () => {
  const state = m.applyDesign(m.initialMaker(), design, "blueprint");
  const restored = m.restoreMaker(JSON.stringify(state));
  assert.equal(restored.stage, "blueprint");
  assert.deepEqual(restored.design.wiring, design.wiring);
  assert.equal(m.restoreMaker(JSON.stringify({ ...m.initialMaker(), stage: "blueprint" })).stage, "design");
  assert.equal(m.restoreMaker(JSON.stringify({ ...state, aiJobId: "job-123", aiIntent: "ask" })).aiJobId, "job-123");
});

test("all stages send cloud context, while unapproved revisions never replace wiring or code", () => {
  let state = m.applyDesign(m.initialMaker(), design, "blueprint");
  state.candidate = { ...design, title: "new concept", revision: 2, code: "new" };
  state.code = "manual draft";
  state.conversation = [{ role: "user", text: "keep same modules" }];
  state.designMode = "fixed";
  const before = JSON.stringify(state);
  for (const stage of ["design", "blueprint", "guide", "deploy"]) {
    const request = m.designRequest({ ...state, stage }, "zh-TW", "model");
    assert.equal(request.workflow.stage, stage);
    assert.equal(request.current.title, "new concept");
    assert.equal(request.conversation[0].text, "keep same modules");
    assert.equal(request.workflow.code_draft, stage === "deploy" ? "manual draft" : "");
  }
  assert.equal(m.designRequest({ ...state, stage: "guide", aiIntent: "ask" }, "en", "model").current.title, "test");
  assert.equal(JSON.stringify(state), before);
});

test("malformed saved concept metadata cannot crash the preview renderer", () => {
  assert(!m.validDesign({ ...design, preview: { screen_lines: [123] } }));
  assert(m.validDesign({ ...design, preview: null }));
});

test("exhibition guide starts and records manual steps without power checks or detector state", () => {
  const before = m.emptyGuide();
  assert.deepEqual(before.checks, []);
  let session = m.startProjectGuide(before);
  assert.equal(session.phase, 'active');
  for (let i=0; i<design.wiring.length; i++) session = m.confirmProjectWire(design, session);
  assert.equal(session.phase, 'review');
  assert.equal(Object.keys(session.confirmed).length, design.wiring.length);
  assert.equal(Object.keys(before.confirmed).length, 0);
  assert.deepEqual(session.checks, []);
  assert.equal(m.confirmProjectWire(design, session), session);
});

test("restart works in every phase and invalidates a same-step cloud result without replacing design or code", () => {
  const state = {...m.initialMaker(), design, code:'hand-edited', conversation:[{role:'user',text:'keep'}]};
  for (const phase of ['prepare', 'active', 'review']) {
    const old = {...m.emptyGuide(), phase, run:3, componentIndex:2, index:3, checks:['power-off'], restored:true,
      confirmed:{old:{signature:'old', mode:'camera',at:'old'}}};
    const next = {...state,guide:m.restartProjectGuide(old)};
    assert.equal(next.guide.componentIndex, 0);
    assert.equal(next.guide.index, 0);
    assert.equal(next.guide.phase, 'prepare');
    assert.equal(next.guide.run, 4);
    assert.equal(next.guide.restored, false);
    assert.deepEqual(next.guide.confirmed, {});
    assert.deepEqual(next.guide.checks, []);
    assert.equal(next.design, state.design);
    assert.equal(next.code, 'hand-edited');
    assert.equal(next.conversation, state.conversation);
    assert.equal(m.restartProjectGuide(next.guide).run, 5);
  }
});

test("manual code requires separate consent before confirming a concept", () => {
  const state = { ...m.applyDesign(m.initialMaker(), design, "design"), code: "manual", candidate: { ...design, revision: 2, code: "new" } };
  assert(m.needsDraftConsent(state));
  assert.equal(m.confirmConcept(state), state);
  assert.equal(m.confirmConcept(state, true).stage, "blueprint");
  assert.equal(m.confirmConcept(state, true).code, "new");
  assert.equal(m.confirmConcept(m.initialMaker()).stage, "design");
});

test("fixed and free modes persist without replacing approved or working versions", () => {
  const candidate = { ...design, revision: 2, title: 'working preview' };
  const state = { ...m.initialMaker(), design, candidate, code: 'manual draft',
    conversation: [{role: 'user', text: 'old car'}] };
  for (const mode of ['fixed', 'free']) {
    const restored = m.restoreMaker(JSON.stringify({ ...state, designMode: mode }));
    assert.equal(restored.designMode, mode);
    assert.deepEqual(restored.design, design);
    assert.deepEqual(restored.candidate, candidate);
    assert.equal(restored.code, 'manual draft');
    assert.deepEqual(restored.conversation, state.conversation);
    const request = m.designRequest(restored, 'zh-TW', null);
    assert.equal(request.design_mode, mode);
    assert.deepEqual(request.component_ids, state.selected);
    assert.equal(request.current.revision, 2);
    assert.deepEqual(request.conversation, mode === 'free' ? [] : state.conversation);
    const ask = m.designRequest({ ...restored, aiIntent: 'ask' }, 'zh-TW', null);
    assert.deepEqual(ask.conversation, state.conversation);
    assert.equal(ask.generate_image, false);
  }
  const legacy = { ...state }; delete legacy.designMode;
  assert.equal(m.restoreMaker(JSON.stringify(legacy)).designMode, 'free');
  assert.equal(m.restoreMaker(JSON.stringify({...state, designMode: 'invalid'})).designMode, 'free');
});
