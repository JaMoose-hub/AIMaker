import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/realtimeFrame.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { acceptTrackingFrame, trackingCursor, trackingDisplayFrame, isSynchronizedPose, trackingNotices, currentBodyOutline, currentBodyRecognitions, bodyRecognitionStatus } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const packet = () => ({ seq: 2, frame_id: 7, runtime_revision: 1, board_id: "raspberry-pi-5",
  image: "data:image/jpeg;base64,test", detection: { frame_id: 7, board_id: "raspberry-pi-5", runtime_revision: 1 },
  components: [{ component_id: "hc-sr04", frame_id: 7 }], });
const accept = (p) => acceptTrackingFrame(p, "raspberry-pi-5", 1, 1);

test("body identity is independent of pin pose; mismatched or expired body cannot revive it", () => {
  const p = packet();
  p.detection.tracking = "searching";
  p.detection.pins = [];
  p.detection.outline = null;
  p.detection.body = { frame_id: 7, display_only: true, age_ms: 100,
    outline: [[1,1],[20,1],[20,20],[1,20]] };
  assert.ok(currentBodyOutline(p.detection));
  assert.deepEqual(bodyRecognitionStatus(p).map(s => s.found), [true, false, false]);
  assert.equal(p.detection.tracking, "searching");
  assert.deepEqual(p.detection.pins, []);
  assert.deepEqual(trackingNotices(p), []); // Body-only data no longer substitutes GPIO status.
  for (const change of [{frame_id: 6}, {age_ms: 651}, {age_ms: -1}, {age_ms: NaN}, {display_only: false}, {outline: [[NaN,0]]}]) {
    assert.equal(currentBodyOutline({...p.detection, body: {...p.detection.body, ...change}}), null);
  }
  assert.deepEqual(bodyRecognitionStatus(null), []);
});

test("shared recognition uses existing same-frame body geometry without filling pins or changing tracking", () => {
  const p=packet();
  Object.assign(p.detection,{tracking:"searching",pins:[],outline:null,body:{frame_id:7,display_only:true,age_ms:25,confidence:.9,outline:[[1,1],[20,1],[20,20],[1,20]]}});
  p.components=[];
  assert.deepEqual(currentBodyRecognitions(p),[{id:"raspberry-pi-5",outline:p.detection.body.outline,pinsLocated:false,drawOutline:true}]);
  assert.equal(p.detection.tracking,"searching");
  assert.deepEqual(p.detection.pins,[]);
  for (const changed of [{...p,frame_id:8},{...p,runtime_revision:2},{...p,board_id:"arduino-uno-q"}])
    assert.deepEqual(currentBodyRecognitions(changed),[]);
  const component={component_id:"mrd-tf240-8p-cs",frame_id:6,tracking:"searching",pins:[],outline:null,body:{...p.detection.body,frame_id:6,outline:[[30,1],[50,1],[50,20],[30,20]]}};
  p.components=[component];
  assert.equal(currentBodyRecognitions(p).length,1); // Reject old component even if its own body/pose match.
  component.frame_id=7;component.body.frame_id=7;
  assert.equal(currentBodyRecognitions(p).length,2);
  component.body.age_ms=651;
  assert.equal(currentBodyRecognitions(p).length,1);
});

test("independent body models cannot show a weak or duplicate HW label over an HC-SR04", () => {
  const p=packet();
  Object.assign(p.detection,{tracking:"searching",pins:[],outline:null});
  const body=(component_id,confidence,box)=>({component_id,frame_id:7,tracking:"searching",pins:[],outline:null,
    body:{frame_id:7,display_only:true,age_ms:20,confidence,outline:[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]}});
  const hc=body("hc-sr04",.49,[0,0,100,100]);
  const hw=body("mrd-tf240-8p-cs",.23,[3,3,103,103]);
  p.components=[hw,hc];
  assert.deepEqual(currentBodyRecognitions(p).map(item=>item.id),["hc-sr04"]);
  hw.body.confidence=.42; // Both pass the display threshold; higher confidence wins high IoU.
  assert.deepEqual(currentBodyRecognitions(p).map(item=>item.id),["hc-sr04"]);
  p.components=[hc,body("mrd-tf240-8p-cs",.42,[130,0,180,50])];
  assert.deepEqual(currentBodyRecognitions(p).map(item=>item.id),["hc-sr04","mrd-tf240-8p-cs"]);
  p.components=[hc,body("mrd-tf240-8p-cs",.42,[10,10,35,35])]; // A small wired module inside a big body has low IoU.
  assert.deepEqual(currentBodyRecognitions(p).map(item=>item.id),["hc-sr04","mrd-tf240-8p-cs"]);
  p.components=[body("mrd-tf240-8p-cs",.29,[130,0,180,50])];
  assert.deepEqual(currentBodyRecognitions(p),[]);
});

test("display identity filtering leaves existing located pins and pose thresholds untouched", () => {
  const p=packet();
  const outline=[[0,0],[100,0],[100,100],[0,100]];
  Object.assign(p.detection,{tracking:"locked",pins:[{id:"GPIO17",v:true}],outline,
    body:{frame_id:7,display_only:true,age_ms:20,confidence:.2,outline}});
  p.components=[{component_id:"mrd-tf240-8p-cs",frame_id:7,tracking:"searching",pins:[],outline:null,
    body:{frame_id:7,display_only:true,age_ms:20,confidence:.8,outline}}];
  const before=structuredClone(p);
  assert.deepEqual(currentBodyRecognitions(p).map(item=>item.id),["raspberry-pi-5"]);
  assert.deepEqual(p,before);
});

test("Eye labels follow the located same-frame pose without replacing raw body geometry or Webcam placement", () => {
  const p=packet();
  Object.assign(p.detection,{tracking:"searching",pins:[],outline:null});
  const outline=[[650,810],[870,805],[875,900],[648,906]];
  const bodyOutline=[[613,707],[899,707],[899,990],[613,990]];
  p.components=[{component_id:"hc-sr04",frame_id:7,tracking:"locked",pins:[{id:"TRIG",v:true}],outline,
    body:{frame_id:7,display_only:true,age_ms:0,confidence:.29,outline:bodyOutline}}];
  const before=structuredClone(p);
  const normal=currentBodyRecognitions(p);
  const eye=currentBodyRecognitions(p,true);
  assert.deepEqual(normal,[{id:"hc-sr04",outline:bodyOutline,pinsLocated:true,drawOutline:false}]);
  assert.deepEqual(eye,[{...normal[0],labelAnchorOutline:outline}]);
  assert.equal(eye[0].outline,p.components[0].body.outline);
  assert.equal(eye[0].labelAnchorOutline,p.components[0].outline);
  assert.deepEqual(p,before); // No new pose, confidence, visibility, or body geometry.
});

test("Eye label anchors fall back to body for missing pins or invalid pose and reject old frame data", () => {
  const p=packet();
  Object.assign(p.detection,{tracking:"searching",pins:[],outline:null});
  const component={component_id:"hc-sr04",frame_id:7,tracking:"locked",pins:[{id:"TRIG",v:true}],
    outline:[[10,10],[30,10],[30,20],[10,20]],
    body:{frame_id:7,display_only:true,age_ms:0,confidence:.8,outline:[[0,0],[40,0],[40,30],[0,30]]}};
  for (const changed of [{tracking:"searching"},{pins:[]},{pins:[{id:"TRIG",v:false}]},
    {outline:null},{outline:[[10,10],[30,10],[30,20]]},{outline:[[NaN,10],[30,10],[30,20],[10,20]]}]) {
    p.components=[{...component,...changed}];
    assert.equal(currentBodyRecognitions(p,true)[0].labelAnchorOutline,undefined);
    assert.deepEqual(currentBodyRecognitions(p,true)[0].outline,component.body.outline);
  }
  p.components=[{...component,frame_id:6,body:{...component.body,frame_id:6}}];
  assert.deepEqual(currentBodyRecognitions(p,true),[]);
  p.components=[component];
  assert.deepEqual(currentBodyRecognitions({...p,frame_id:8},true),[]);
});

test("only Eye explains a current clipped body without changing pins, normal Webcam labels or stale-frame rules", () => {
  const p=packet();
  p.components=[];
  Object.assign(p.detection,{tracking:"searching",pins:[],outline:null,
    body:{frame_id:7,display_only:true,age_ms:0,confidence:.9,partial:true,outline:[[1,1],[20,1],[20,20],[1,20]]}});
  const before=structuredClone(p);
  const normal=currentBodyRecognitions(p);
  assert.equal(normal[0].clipped,undefined);
  assert.deepEqual(currentBodyRecognitions(p,true),[{...normal[0],clipped:true}]);
  assert.deepEqual(p,before);
  p.detection.body.partial=false;
  assert.equal(currentBodyRecognitions(p,true)[0].clipped,undefined);
  p.detection.body.partial=true;
  p.detection.body.frame_id=6;
  assert.deepEqual(currentBodyRecognitions(p,true),[]);
  p.detection.body.frame_id=7;
  p.detection.tracking="locked";p.detection.pins=[{id:"GPIO17",v:true}];
  assert.equal(currentBodyRecognitions(p,true)[0].clipped,undefined);
});

test("live image, Pi and both supported modules must describe the same frame", () => {
  assert.equal(accept(packet()), true);
  assert.equal(accept({ ...packet(), frame_id: 8 }), false);
  for (const component_id of ["hc-sr04", "mrd-tf240-8p-cs"]) {
    assert.equal(accept({ ...packet(), components: [{ component_id, frame_id: 6 }] }), false);
    assert.equal(accept({ ...packet(), components: [{ component_id, frame_id: 7 }] }), true);
  }
  assert.equal(accept({ ...packet(), components: [
    { component_id: "hc-sr04", frame_id: 7 },
    { component_id: "mrd-tf240-8p-cs", frame_id: 6 },
  ] }), false);
});
test("runtime switch and out-of-order responses cannot revive old overlays", () => {
  for (const change of [{ seq: 1 }, { seq: NaN }, { runtime_revision: 0 }, { board_id: "arduino-uno-q" }])
    assert.equal(accept({ ...packet(), ...change }), false);
  assert.equal(accept({ ...packet(), detection: { ...packet().detection, runtime_revision: 2 } }), false);
});
test("camera mode changes reject old images and GPIO synchronously even before the runtime revision changes", () => {
  const eye={...packet(),sourceKey:"eye"};
  const webcam={...packet(),sourceKey:"standard"};
  const current=(frame,enabled,sourceKey,revision=1)=>trackingDisplayFrame(frame,enabled,sourceKey,"raspberry-pi-5",revision);
  assert.equal(current(eye,true,"eye"),eye);
  assert.equal(current(eye,true,"standard"),null); // Exit render, before DELETE or effect cleanup.
  assert.equal(current(webcam,true,"eye"),null); // Reentry cannot reuse a webcam frame.
  assert.equal(current(webcam,true,"standard"),webcam);
  assert.equal(current(webcam,false,"standard"),null); // Camera restore still pending.
  assert.equal(current(webcam,true,"standard",2),null);
});
test("invalid image or component envelope is rejected", () => {
  for (const change of [{ image: "http://another-host/frame.jpg" }, { image: null }, { components: null }])
    assert.equal(accept({ ...packet(), ...change }), false);
});
test("camera restart resets the long-poll cursor only after a bounded freshness timeout", () => {
  assert.equal(trackingCursor(999, 1000, 1400), 999);
  assert.equal(trackingCursor(999, 1000, 1700), -1);
});

test("same-frame flow and loss bypass interpolation; legacy detections still smooth", () => {
  for (const stability of ["yolo_direct", "optical_flow", "optical_flow_partial", "flow_lost"])
    assert.equal(isSynchronizedPose({ pose_quality: { stability } }), true);
  for (const detection of [null, {}, { pose_quality: { stability: "deadband" } }, { pose_quality: { path: "track" } }])
    assert.equal(isSynchronizedPose(detection), false);
});

test("partial outlines and interrupted tracks have distinct notices; old notices never survive missing frames", () => {
  const p = packet();
  p.components = [
    { component_id: "hc-sr04", pose_quality: { outline_only: true, reason: "partial_support" } },
    { component_id: "mrd-tf240-8p-cs", pose_quality: { outline_only: true, reason: "awaiting_model_confirmation" } },
  ];
  assert.deepEqual(trackingNotices(p), [
    { id: "hc-sr04", key: "camera.trackingPartial" },
    { id: "mrd-tf240-8p-cs", key: "camera.trackingConfirming" },
  ]);
  assert.deepEqual(trackingNotices(null), []);
  assert.deepEqual(trackingNotices(packet()), []);
});

test("Pi boundary rejection is not mislabeled as physical obstruction", () => {
  const p = packet();
  p.detection.pose_quality = { stability: "flow_lost", interrupted: true, reason: "pcb_boundary_unverified" };
  assert.deepEqual(trackingNotices(p), [{ id: "raspberry-pi-5", key: "camera.trackingBoundaryUnverified" }]);
  p.detection.pose_quality.reason = "awaiting_model_lock";
  assert.deepEqual(trackingNotices(p), [{ id: "raspberry-pi-5", key: "camera.trackingObstructed" }]);
  assert.deepEqual(trackingNotices(null), []);
});

test("shared display feed suspends cards on loss and old owners cannot revive frames", async () => {
  const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/motionDisplayStore.ts", import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  });
  const store = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
  assert.equal(store.getMotionDisplay(), undefined);
  let updates = 0;
  const off = store.subscribeMotionDisplay(() => updates++);
  const a = store.openMotionDisplay();
  assert.equal(store.getMotionDisplay(), null);
  const p = packet();
  a.update(p);
  assert.equal(store.getMotionDisplay(), p);
  a.update(null);
  assert.equal(store.getMotionDisplay(), null);
  const b = store.openMotionDisplay();
  a.update(p); a.close();
  assert.equal(store.getMotionDisplay(), null);
  b.update(p); b.close();
  assert.equal(store.getMotionDisplay(), undefined);
  assert.ok(updates >= 5);
  off();
});

test("supported pins can coexist with partial tracking without implying full visibility", () => {
  const p = packet();
  p.detection.pose_quality = { partial: true, outline_only: false, visible_pin_count: 1, hidden_pin_count: 1 };
  assert.deepEqual(trackingNotices(p), [{ id: "raspberry-pi-5", key: "camera.trackingPartial" }]);
  p.detection.pose_quality = { outline_only: true, reason: "pin_region_changed" };
  assert.deepEqual(trackingNotices(p), [{ id: "raspberry-pi-5", key: "camera.trackingPartial" }]);
});

const { outputText: decodeText } = ts.transpileModule(readFileSync(new URL("../src/lib/trackingImageDecode.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { decodePhoneTrackingImage } = await import(`data:text/javascript;base64,${Buffer.from(decodeText).toString("base64")}`);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function fakeDecoder(t, outcomes) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "Image");
  const images = [];
  globalThis.Image = class {
    src = "";
    cleared = 0;
    calls = 0;
    constructor() { images.push(this); }
    decode() {
      this.calls++;
      const next = outcomes.shift();
      return typeof next === "function" ? next() : next;
    }
    removeAttribute(name) {
      assert.equal(name, "src");
      this.src = "";
      this.cleared++;
    }
  };
  t.after(() => {
    if (original) Object.defineProperty(globalThis, "Image", original);
    else delete globalThis.Image;
  });
  return images;
}
const turn = () => new Promise(resolve => setImmediate(resolve));

test("phone decode keeps the successful image cache and removes its abort listener", async (t) => {
  const images = fakeDecoder(t, [Promise.resolve()]);
  const controller = new AbortController();
  const remove = t.mock.method(controller.signal, "removeEventListener");
  await decodePhoneTrackingImage("data:image/jpeg;base64,current", controller.signal, 100);
  assert.equal(images[0].src, "data:image/jpeg;base64,current");
  assert.equal(images[0].cleared, 0);
  assert.equal(remove.mock.callCount(), 1);
  controller.abort();
  assert.equal(images[0].cleared, 0); // Completion has released cancellation ownership.
});

test("a hung phone decoder expires and the next fresh image can decode", async (t) => {
  const old = deferred();
  const images = fakeDecoder(t, [old.promise, Promise.resolve()]);
  await assert.rejects(decodePhoneTrackingImage("data:image/jpeg;base64,stuck", new AbortController().signal, 10),
    error => error.name === "TimeoutError");
  assert.equal(images[0].cleared, 1);
  await decodePhoneTrackingImage("data:image/jpeg;base64,recovered", new AbortController().signal, 100);
  old.resolve();
  await turn();
  assert.equal(images[0].src, "");
  assert.equal(images[1].src, "data:image/jpeg;base64,recovered");
});

test("phone decode cancellation settles immediately and handles a late decoder rejection", async (t) => {
  const pending = deferred();
  const images = fakeDecoder(t, [pending.promise]);
  const controller = new AbortController();
  const result = decodePhoneTrackingImage("data:image/jpeg;base64,old", controller.signal, 100);
  const rejected = assert.rejects(result, error => error.name === "AbortError");
  controller.abort();
  await rejected;
  pending.reject(new Error("decoder rejected after cancellation"));
  await turn(); // An unhandled late rejection fails the node test runner.
  assert.equal(images[0].src, "");
  assert.equal(images[0].cleared, 1);
});

test("an already-cancelled phone decode never starts the decoder", async (t) => {
  const images = fakeDecoder(t, []);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(decodePhoneTrackingImage("data:image/jpeg;base64,old", controller.signal),
    error => error.name === "AbortError");
  assert.equal(images[0].calls, 0);
  assert.equal(images[0].src, "");
});

test("phone decoder failures release the image and preserve the original error", async (t) => {
  const failed = new Error("corrupt JPEG");
  const images = fakeDecoder(t, [() => Promise.reject(failed), () => { throw failed; }]);
  for (let i = 0; i < 2; i++) {
    await assert.rejects(decodePhoneTrackingImage("data:image/jpeg;base64,bad", new AbortController().signal, 100),
      error => error === failed);
    assert.equal(images[i].cleared, 1);
  }
});

/** Run the actual hook's effect without mounting the full App or touching a camera. */
function trackingHookHarness(t, sourceKey, responses) {
  const globals = new Map(["window", "fetch"].map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const timers = new Set();
  const intervals = new Set();
  const updates = [];
  const stateWrites = [];
  let effect, requests = 0, closed = 0, cleanup;
  const delivered = deferred();
  globalThis.window = {
    setTimeout(callback, ms) {
      // Keep the real pipeline ordering while avoiding a 1-second test delay.
      const id = setTimeout(() => { timers.delete(id); callback(); }, ms === 1000 ? 20 : ms === 500 ? 1 : ms);
      timers.add(id);
      return id;
    },
    clearTimeout(id) { clearTimeout(id); timers.delete(id); },
    setInterval(callback, ms) { const id = setInterval(callback, ms); intervals.add(id); return id; },
    clearInterval(id) { clearInterval(id); intervals.delete(id); },
  };
  globalThis.fetch = async () => {
    requests++;
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return next ? { status: 200, ok: true, json: async () => next } : { status: 204, ok: true };
  };
  const compiled = ts.transpileModule(readFileSync(new URL("../src/lib/useRealtimeTracking.ts", import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  const dependencies = {
    react: {
      useEffect(callback) { effect = callback; },
      useState(initial) {
        let value = initial;
        return [value, next => { value = typeof next === "function" ? next(value) : next; stateWrites.push(value); }];
      },
    },
    "./realtimeFrame": { acceptTrackingFrame, trackingCursor, trackingDisplayFrame },
    "./trackingImageDecode": { decodePhoneTrackingImage },
    "./motionDisplayStore": { openMotionDisplay: () => ({
      update(next) { updates.push(next); if (next) delivered.resolve(next); },
      close() { closed++; },
    }) },
  };
  new Function("require", "exports", compiled)(name => {
    assert.ok(name in dependencies, `unexpected production dependency ${name}`);
    return dependencies[name];
  }, exports);
  exports.useRealtimeTracking(true, "raspberry-pi-5", 1, 30, sourceKey);
  cleanup = effect();
  const dispose = () => { if (cleanup) { const run = cleanup; cleanup = null; run(); } };
  t.after(() => {
    dispose();
    for (const id of timers) clearTimeout(id);
    for (const id of intervals) clearInterval(id);
    for (const [name, original] of globals) {
      if (original) Object.defineProperty(globalThis, name, original);
      else delete globalThis[name];
    }
  });
  return { updates, stateWrites, delivered: delivered.promise, dispose,
    get requests() { return requests; }, get closed() { return closed; },
    get timerCount() { return timers.size + intervals.size; } };
}

test("actual phone tracking loop retries a hung decode and publishes only the recovered frame", { timeout: 2000 }, async (t) => {
  const stale = deferred();
  const images = fakeDecoder(t, [stale.promise, Promise.resolve()]);
  const fresh = { ...packet(), seq: 3, image: "data:image/jpeg;base64,fresh" };
  const harness = trackingHookHarness(t, "phone:own-session", [packet(), fresh]);
  const shown = await harness.delivered;
  assert.equal(shown.seq, 3);
  assert.equal(shown.image, fresh.image);
  assert.equal(shown.sourceKey, "phone:own-session");
  assert.equal(harness.requests, 2);
  assert.equal(images[0].cleared, 1);
  assert.deepEqual(harness.updates.filter(Boolean).map(frame => frame.seq), [3]);
  stale.reject(new Error("late abandoned decode"));
  await turn();
  assert.deepEqual(harness.updates.filter(Boolean).map(frame => frame.seq), [3]);
  harness.dispose();
  assert.equal(harness.timerCount, 0);
});

test("a transient phone tracking request failure preserves the still-fresh synchronized frame", { timeout: 2000 }, async (t) => {
  const pending = deferred();
  fakeDecoder(t, [Promise.resolve(), pending.promise]);
  const next = { ...packet(), seq: 3, image: "data:image/jpeg;base64,next" };
  const harness = trackingHookHarness(t, "phone:own-session", [packet(), new Error("temporary network failure"), next]);
  try {
    const shown = await harness.delivered;
    for (let i = 0; i < 100 && harness.requests < 3; i++) await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(harness.requests, 3);
    assert.equal(harness.updates.at(-1), shown, "one failed poll must not blank valid pixels and synchronized poses");
    assert.equal(harness.stateWrites.filter(value => value === null).length, 1, "only the initial source reset may clear the fresh frame");
  } finally {
    harness.dispose();
    pending.resolve();
    await turn();
  }
  assert.equal(harness.timerCount, 0);
});

test("persistent phone tracking failures still expire pixels and overlays within the freshness bound", { timeout: 2500 }, async (t) => {
  fakeDecoder(t, [Promise.resolve()]);
  const failures = Array.from({ length: 20 }, () => new Error("network remains unavailable"));
  const harness = trackingHookHarness(t, "phone:own-session", [packet(), ...failures]);
  const shown = await harness.delivered;
  try {
    await new Promise(resolve => setTimeout(resolve, 850));
    assert.equal(harness.updates.at(-1), null);
    assert.ok(harness.stateWrites.filter(value => value && typeof value === "object").every(value => value === shown), "failed polls must never replace or refresh the frame timestamp");
  } finally { harness.dispose(); await turn(); }
  assert.equal(harness.timerCount, 0);
});

test("a transient phone decoder failure does not erase the previously decoded fresh pair", { timeout: 2000 }, async (t) => {
  const pending = deferred();
  const images = fakeDecoder(t, [Promise.resolve(), () => Promise.reject(new Error("temporary decode failure")), pending.promise]);
  const harness = trackingHookHarness(t, "phone:own-session", [packet(), { ...packet(), seq: 3 }, { ...packet(), seq: 4 }]);
  try {
    const shown = await harness.delivered;
    for (let i = 0; i < 100 && harness.requests < 3; i++) await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(harness.requests, 3);
    assert.equal(images[1].cleared, 1);
    assert.equal(harness.updates.at(-1), shown);
  } finally { harness.dispose(); pending.resolve(); await turn(); }
  assert.equal(harness.timerCount, 0);
});

test("actual phone tracking cleanup aborts pending decode without reviving state or polling", async (t) => {
  const old = deferred();
  const images = fakeDecoder(t, [old.promise]);
  const harness = trackingHookHarness(t, "phone:old-session", [packet()]);
  await turn();
  assert.equal(images[0].calls, 1);
  const before = harness.stateWrites.length;
  harness.dispose();
  old.resolve();
  await turn();
  assert.equal(harness.requests, 1);
  assert.equal(harness.closed, 1);
  assert.equal(harness.stateWrites.length, before);
  assert.deepEqual(harness.updates, []);
  assert.equal(harness.timerCount, 0);
  assert.equal(images[0].cleared, 1);
});

test("the standard webcam tracking branch retains its original decoder ownership", async (t) => {
  const pending = deferred();
  const images = fakeDecoder(t, [pending.promise]);
  const harness = trackingHookHarness(t, "standard", [packet()]);
  await turn();
  harness.dispose();
  pending.resolve();
  await turn();
  assert.equal(images[0].cleared, 0); // The phone-only cancellation helper was not called.
  assert.equal(harness.requests, 1);
  assert.deepEqual(harness.updates, []);
});
