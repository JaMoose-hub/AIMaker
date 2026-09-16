// Execute the real App callbacks/effects with deterministic fullscreen events.
// No DOM camera, network endpoint, or classifier is opened by this harness.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = ts.createSourceFile("App.tsx", readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8"),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const callbacks = new Map();
const effects = new Map();
let exitButtonExpression;
function visit(node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer
    && ts.isCallExpression(node.initializer) && node.initializer.expression.getText(source) === "useCallback")
    callbacks.set(node.name.text, node.initializer.arguments[0]);
  if (ts.isCallExpression(node) && node.expression.getText(source) === "useEffect") {
    for (const event of ["fullscreenchange", "keydown"])
      if (node.arguments[0]?.getText(source).includes(`addEventListener("${event}"`)) effects.set(event, node.arguments[0]);
  }
  if (ts.isJsxOpeningElement(node) && node.tagName.getText(source) === "button") {
    const attrs = node.attributes.properties;
    if (attrs.some(attr => ts.isJsxAttribute(attr) && attr.name.getText(source) === "className"
      && attr.initializer?.getText(source) === '"smart-glasses-exit"')) {
      exitButtonExpression = attrs.find(attr => ts.isJsxAttribute(attr) && attr.name.getText(source) === "onClick")?.initializer?.expression;
    }
  }
  ts.forEachChild(node, visit);
}
visit(source);
function bind(node, env) {
  assert.ok(node, "Expected the real App event/callback binding");
  const js = ts.transpileModule(`const callback = ${node.getText(source)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText;
  return new Function(...Object.keys(env), `${js}\nreturn callback;`)(...Object.values(env));
}

function presentation({ nativeFullscreen = true } = {}) {
  const state = { mode: "standard", fallback: false, starts: 0, restores: 0, requests: 0, nativeExits: 0 };
  const documentEvents = new Map(), windowEvents = new Map(), timers = new Map();
  const eventTarget = listeners => ({
    addEventListener(name, fn) { listeners.set(name, fn); },
    removeEventListener(name, fn) { if (listeners.get(name) === fn) listeners.delete(name); },
  });
  const document = { ...eventTarget(documentEvents), fullscreenElement: null,
    exitFullscreen() { state.nativeExits++; this.fullscreenElement = null; return Promise.resolve(); } };
  const stage = nativeFullscreen ? { requestFullscreen() { state.requests++; return Promise.resolve(); } } : {};
  const window = { ...eventTarget(windowEvents), setTimeout(fn) { const id=timers.size+1;timers.set(id,fn);return id; },
    clearTimeout(id) { timers.delete(id); } };
  const env = {
    document, window, FULLSCREEN_REQUEST_TIMEOUT_MS: 2000,
    videoStageRef: { current: stage }, fullscreenRequestPendingRef: { current: false },
    fullscreenEnteredRef: { current: false }, fullscreenAttemptIdRef: { current: 0 },
    fullscreenFallbackTimerRef: { current: null }, glassesSessionRef: { current: false },
    displayModeDisabled: false,
    glasses: { pending: false, start() { state.starts++; }, stop() { state.restores++; } },
    setDisplayMode(mode) { state.mode=mode; }, setFullscreenFallback(value) { state.fallback=value; },
    setCameraPickerOpen() {}, setCalibrateOpen() {}, setOpticalHudCalibration() {}, setGlassesDisplayFps() {},
    handleGuideVisibilityChange() {}, setSelectedPinId() {},
    calibrateOpen: false, cameraPickerOpen: false, guideVisible: false,
  };
  let cleanup = [];
  function render() {
    cleanup.forEach(fn => fn());
    Object.assign(env, { displayMode: state.mode, displayModeActive: state.mode !== "standard", fullscreenFallback: state.fallback });
    for (const name of ["clearFullscreenFallbackTimer", "exitDisplayMode", "enterDisplayMode", "enterSmartGlassesDemo"])
      env[name] = bind(callbacks.get(name), env);
    cleanup = [...effects.values()].map(effect => bind(effect, env)());
  }
  render();
  return {
    state, env, timers, render,
    enterEye() { env.enterSmartGlassesDemo(); render(); },
    enterHud() { env.enterDisplayMode("optical-hud-calibration"); render(); },
    nativeChange(entered) { document.fullscreenElement=entered?stage:null; documentEvents.get("fullscreenchange")?.(); render(); },
    escape() { let prevented=false;windowEvents.get("keydown")?.({key:"Escape",preventDefault(){prevented=true;}});render();return prevented; },
    clickExit() { bind(exitButtonExpression, env)();render(); },
  };
}

test("Eye uses CSS fullscreen and survives browser fullscreen changes until Esc requests restoration", async () => {
  const ui=presentation();
  ui.enterEye();
  await Promise.resolve();
  assert.equal(ui.state.starts,1);
  assert.equal(ui.state.requests,0);
  assert.equal(ui.state.fallback,true);
  assert.equal(ui.timers.size,0);
  for (const entered of [true,false,true,false]) ui.nativeChange(entered);
  assert.equal(ui.state.mode,"smart-glasses-demo");
  assert.equal(ui.state.fallback,true);
  assert.equal(ui.state.restores,0);
  assert.equal(ui.escape(),true);
  assert.equal(ui.state.mode,"standard");
  assert.equal(ui.state.fallback,false);
  assert.equal(ui.state.restores,1);
  ui.escape();
  assert.equal(ui.state.restores,1); // The Eye session is restored only once.
});

test("the existing Exit button ends CSS Eye mode and invokes the same camera restoration callback", () => {
  const ui=presentation();
  ui.enterEye();
  ui.clickExit();
  assert.equal(ui.state.requests,0);
  assert.equal(ui.state.restores,1);
  assert.equal(ui.state.mode,"standard");
  assert.equal(ui.env.glassesSessionRef.current,false);
  assert.equal(ui.state.fallback,false);
});

test("optical HUD still requests native fullscreen and follows its exit without starting or restoring Eye", async () => {
  const ui=presentation();
  ui.enterHud();
  assert.equal(ui.state.requests,1);
  ui.nativeChange(true);
  await Promise.resolve();
  assert.equal(ui.state.fallback,false);
  ui.nativeChange(false);
  assert.equal(ui.state.mode,"standard");
  assert.equal(ui.state.starts,0);
  assert.equal(ui.state.restores,0);
});

test("unsupported HUD browsers retain CSS fallback until the existing Esc exit", () => {
  const ui=presentation({nativeFullscreen:false});
  ui.enterHud();
  ui.nativeChange(false);
  assert.equal(ui.state.mode,"optical-hud-calibration");
  assert.equal(ui.state.fallback,true);
  assert.equal(ui.escape(),true);
  assert.equal(ui.state.mode,"standard");
  assert.equal(ui.state.restores,0);
});
