import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { renderWiringVideo } from "./glasses_wiring_fixture.mjs";

const { outputText } = ts.transpileModule(readFileSync(new URL("../src/lib/glasses.ts", import.meta.url), "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
});
const { glassesVideoReady, DEFAULT_GLASSES_SETTINGS, requestGlassesStream, createGlassesMutationQueue, createGlassesSessionSettings,
  denoiseUpdate, sameGlassesCamera, glassesRestoreError, glassesInferenceSummary } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

async function renderControls(props) {
  const messages = JSON.parse(readFileSync(new URL("../src/locales/zh-TW.json", import.meta.url), "utf8"));
  const dataUrl = text => `data:text/javascript;base64,${Buffer.from(text).toString("base64")}`;
  let js = ts.transpileModule(readFileSync(new URL("../src/components/GlassesControls.tsx", import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  for (const [name, url] of Object.entries({
    react: import.meta.resolve("react"), "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"),
    "../lib/glasses": dataUrl(outputText),
    "../lib/i18n": dataUrl(`export const useI18n=()=>({t:key=>(${JSON.stringify(messages)})[key]??key});`),
  })) js = js.replaceAll(JSON.stringify(name), JSON.stringify(url));
  const { GlassesControls } = await import(dataUrl(js));
  return renderToStaticMarkup(createElement(GlassesControls, { status: null, pending: false, error: null,
    displayFps: 0, onApply() { throw Error("Rendering cannot configure camera"); }, ...props }));
}

test("controls expose only resolution, FPS and denoise; startup disables apply and errors allow retry", async () => {
  const starting = await renderControls({ pending: true });
  assert.equal((starting.match(/<select/g) ?? []).length, 3);
  assert.match(starting, /<button[^>]*disabled/);
  assert.doesNotMatch(starting, /對焦|曝光|採樣率/);
  const failed = await renderControls({ error: "Camera unavailable" });
  assert.match(failed, /role="alert"[^>]*>Camera unavailable/);
  assert.doesNotMatch(failed, /<button[^>]*disabled/);
  const live = await renderControls({ status: {
    active: true, state: "running", requested: { width: 2048, height: 1512, fps: 60, denoise: "strong" },
    actual: { width: 1920, height: 1080 }, capture_fps: 29.9, processing_fps: 26.1,
    modes: { resolutions: [{ width: 1920, height: 1080 }, { width: 2048, height: 1512 }], fps: [30, 60], denoise: ["original", "clean", "strong"] },
  }, displayFps: 24 });
  assert.match(live, /value="2048x1512" selected/);
  assert.match(live, /實際 1920 × 1080/);
  assert.match(live, /接收 29.9 FPS/);
  assert.match(live, /降噪處理 26.1 FPS/);
  assert.match(live, /顯示 24 FPS/);
  assert.match(await renderControls({displayFps:null}), /顯示 — FPS/);
});

test("Eye preview remains hidden during switching, disconnect and restoration", () => {
  assert.equal(glassesVideoReady(null), false);
  for (const state of ["starting", "switching", "restoring", "error", "idle"])
    assert.equal(glassesVideoReady({ active: true, state }), false);
  assert.equal(glassesVideoReady({ active: false, state: "running" }), false);
  assert.equal(glassesVideoReady({ active: true, state: "running" }), true);
});

test("Eye reports actual loaded CUDA models and inference FPS independently of capture, denoise and display", async () => {
  const models=["raspberry-pi-5","hc-sr04","hw-123","mrd-tf240-8p-cs","raspberry-pi-5-roi"].map(id=>({
    id,actual_backend:"cuda",preprocessing_backend:"cuda",available:true,fallback_reason:null,
  }));
  const status={active:true,state:"running",requested:DEFAULT_GLASSES_SETTINGS,actual:{width:1920,height:1080},
    capture_fps:59.8,processing_fps:45.2,denoise_backend:"cuda",
    modes:{resolutions:[{width:1920,height:1080}],fps:[30,60],denoise:["original","clean","strong"]},
    inference:{processing_fps:12.3,processing_ms:81.2,models}};
  const gpu=await renderControls({status,displayFps:11});
  assert.match(gpu,/YOLO CUDA 5\/5/);
  assert.match(gpu,/推論 12.3 FPS · 81.2 ms/);
  assert.match(gpu,/接收 59.8 FPS/);
  assert.match(gpu,/降噪處理 45.2 FPS/);
  assert.match(gpu,/顯示 11 FPS/);
  assert.match(gpu,/降噪 CUDA/);
  assert.match(gpu,/raspberry-pi-5-roi: CUDA/);
  assert.equal((gpu.match(/<select/g)??[]).length,3);
  assert.equal((gpu.match(/<button/g)??[]).length,1);
  models[4]={...models[4],actual_backend:"opencv",preprocessing_backend:"opencv",fallback_reason:"CUDA unavailable"};
  const mixed=await renderControls({status});
  assert.match(mixed,/YOLO 混合 5\/5 · CUDA 4\/5/);
  assert.match(mixed,/前處理 opencv · CUDA unavailable/);
  for (const model of models) Object.assign(model,{actual_backend:"opencv",preprocessing_backend:"opencv"});
  assert.match(await renderControls({status}),/YOLO CPU 5\/5/);
  for (const model of models) Object.assign(model,{actual_backend:"cuda",available:false});
  const unavailable=await renderControls({status});
  assert.match(unavailable,/YOLO 未就緒 0\/5 · CUDA 0\/5/);
  assert.doesNotMatch(unavailable,/YOLO CUDA/);
  assert.equal(glassesInferenceSummary(undefined),null);
  assert.doesNotMatch(await renderControls({}),/YOLO|推論/);
});

test("Eye status read failures hide cached server rates and CUDA claims until a successful poll", async () => {
  const status={active:true,state:"running",requested:DEFAULT_GLASSES_SETTINGS,actual:{width:1920,height:1080},
    capture_fps:29.9,processing_fps:28.1,denoise_backend:"cuda",
    modes:{resolutions:[{width:1920,height:1080}],fps:[30,60],denoise:["original","clean","strong"]},
    inference:{processing_fps:17.2,processing_ms:58.1,models:[{
      id:"raspberry-pi-5",actual_backend:"cuda",preprocessing_backend:"cuda",available:true,fallback_reason:null,
    }]}};
  const failed=await renderControls({status,error:"Eye GET: HTTP 503",displayFps:0});
  assert.match(failed,/接收 — FPS/);
  assert.match(failed,/降噪處理 — FPS/);
  assert.match(failed,/Eye GET: HTTP 503/);
  assert.doesNotMatch(failed,/YOLO CUDA|降噪 CUDA|推論 17.2|接收 29.9|降噪處理 28.1/);
  const restored=await renderControls({status});
  assert.match(restored,/YOLO CUDA 1\/1/);
  assert.match(restored,/推論 17.2 FPS/);
  const pending=await renderControls({status:{...status,inference:null,denoise_backend:"pending"}});
  assert.match(pending,/降噪 初始化中/);
  assert.doesNotMatch(pending,/CUDA|PENDING|推論/);
  const fallback=await renderControls({status:{...status,inference:null,denoise_backend:"cpu",denoise_fallback_reason:"CUDA initialization failed"}});
  assert.match(fallback,/title="CUDA initialization failed">降噪 CPU/);
});

test("instant denoise changes preserve pending resolution and FPS without submitting them", () => {
  const applied = { width: 1920, height: 1080, fps: 30, denoise: "clean" };
  const draft = { width: 2048, height: 1512, fps: 60, denoise: "clean" };
  const next = denoiseUpdate(draft, applied, "strong");
  assert.deepEqual(next.request, { width: 1920, height: 1080, fps: 30, denoise: "strong" });
  assert.deepEqual(next.draft, { width: 2048, height: 1512, fps: 60, denoise: "strong" });
  assert.equal(sameGlassesCamera(applied, next.request), true); // keep the live preview
  assert.equal(sameGlassesCamera(applied, next.draft), false); // Apply changes camera format
  assert.deepEqual(applied, DEFAULT_GLASSES_SETTINGS);
  assert.equal(draft.denoise, "clean");
});

test("Eye reentry keeps confirmed 2048 settings after restoring the webcam, independently of a new page session", () => {
  const settings=createGlassesSessionSettings();
  assert.deepEqual(settings.forStart(),DEFAULT_GLASSES_SETTINGS);
  const high={width:2048,height:1512,fps:30,denoise:"strong"};
  settings.observe({active:true,state:"starting",error:null,requested:high});
  assert.deepEqual(settings.forStart(),DEFAULT_GLASSES_SETTINGS); // async acceptance is not a working stream
  settings.observe({active:true,state:"running",error:null,requested:high});
  settings.observe({active:false,state:"stopped",error:null,requested:DEFAULT_GLASSES_SETTINGS});
  assert.deepEqual(settings.forStart(),high);
  const draft=settings.forStart();draft.width=720;
  assert.deepEqual(settings.forStart(),high);
  assert.deepEqual(createGlassesSessionSettings().forStart(),DEFAULT_GLASSES_SETTINGS);
});

test("failed Eye applies cannot replace the last working format or denoise choice", () => {
  const settings=createGlassesSessionSettings();
  const high={width:2048,height:1512,fps:30,denoise:"clean"};
  const failed={width:720,height:1280,fps:60,denoise:"original"};
  settings.observe({active:true,state:"running",error:null,requested:high});
  for (const update of [
    {active:true,state:"switching",error:null},
    {active:true,state:"error",error:"Format rejected"},
    {active:true,state:"running",error:"Apply failed"},
    {active:false,state:"stopped",error:null},
  ]) settings.observe({...update,requested:failed});
  assert.deepEqual(settings.forStart(),high);
  settings.observe({active:true,state:"running",error:null,requested:{...high,denoise:"strong"}});
  assert.deepEqual(settings.forStart(),{...high,denoise:"strong"});
});

test("restore retry is shown only after an actual failed exit and disappears on success", () => {
  const failed = { state: "error", error: "Previous camera unavailable" };
  assert.equal(glassesRestoreError(false, false, failed, null), null); // Eye startup error
  assert.equal(glassesRestoreError(true, true, failed, null), null); // restore is still pending
  assert.equal(glassesRestoreError(true, false, failed, null), "Previous camera unavailable");
  assert.equal(glassesRestoreError(true, false, { state: "restoring" }, "HTTP 503"), "HTTP 503");
  assert.equal(glassesRestoreError(true, false, { state: "stopped", error: null }, null), null);
});

test("Eye uses the same real wiring overlays, guide target and highlighted pins as the normal camera", async () => {
  for (const realtimeEnabled of [true, false]) {
    const normal = await renderWiringVideo({ realtimeEnabled });
    const eye = await renderWiringVideo({ displayMode:"smart-glasses-demo", realtimeEnabled });
    for (const rendered of [normal, eye]) {
      assert.match(rendered.html, /data-guide-connection="GPIO17:TRIG"/);
      assert.match(rendered.html, /data-component-id="hc-sr04"/);
      assert.match(rendered.html, /data-target-pin="TRIG"/);
      assert.match(rendered.html, /class="board-outline/);
      assert.match(rendered.html, /Selected target/);
      assert.doesNotMatch(rendered.html, /glasses-recognition|data-recognized-object/);
      assert.equal(rendered.pin.guidePinId, "GPIO17");
      assert.equal(rendered.pin.selectedPinId, "GPIO17");
      assert.deepEqual([...rendered.pin.highlightIds], ["GPIO17"]);
      assert.equal(rendered.pin.localGuidanceOnly, false);
    }
    assert.deepEqual(eye.target, normal.target);
    assert.equal(eye.tracking[0], true);
    assert.equal(normal.tracking[0], realtimeEnabled);
    assert.equal(eye.tracking[1], normal.tracking[1]);
    assert.equal(eye.tracking[4], "eye");
    assert.equal(normal.tracking[4], "standard");
    assert.deepEqual(eye.pin.displayOffsetPx,{x:0,y:0});
  }
});

test("Eye exit hides its image and GPIO while restore or config refresh is pending, including non-realtime webcam mode", async () => {
  for (const realtimeEnabled of [true,false]) {
    for (const context of [
      {eyeActive:true,state:"restoring",cameraSource:"xreal"},
      {eyeActive:true,state:"error",cameraSource:"device"},
      {eyeActive:false,state:"stopped",cameraSource:"xreal"},
    ]) {
      const leaving=await renderWiringVideo({displayMode:"standard",realtimeEnabled,bodyEvidence:"current",...context});
      assert.equal(leaving.tracking[0],false);
      assert.equal(leaving.tracking[4],"standard");
      assert.match(leaving.html,/video-img hidden/);
      assert.doesNotMatch(leaving.html,/src=|data-component-id=|data-guide-connection=|data-body-component=/);
    }
    const restored=await renderWiringVideo({displayMode:"standard",realtimeEnabled,eyeActive:false,state:"stopped",cameraSource:"device"});
    assert.equal(restored.tracking[0],realtimeEnabled);
    assert.doesNotMatch(restored.html,/video-img hidden/);
    assert.match(restored.html,/data-component-id="hc-sr04"/);
    assert.match(restored.html,realtimeEnabled?/src="data:image\/jpeg;base64,fixture"/:/src="\/video"/);
  }
});

test("Eye keeps the selected board but always pairs YOLO GPIO with its image independently of normal camera settings", async () => {
  const uno = await renderWiringVideo({displayMode:"smart-glasses-demo",boardId:"arduino-uno-q"});
  assert.equal(uno.tracking[0],true);
  assert.equal(uno.tracking[1],"arduino-uno-q");
  assert.match(uno.html, /src="data:image\/jpeg;base64,fixture"/);
  assert.match(uno.html, /data-tracking-frame="77"/);
  assert.doesNotMatch(uno.html, /video-img hidden/);
  const normalUno=await renderWiringVideo({boardId:"arduino-uno-q"});
  assert.equal(normalUno.tracking[0],false);
  assert.match(normalUno.html,/src="\/video"/);
  const eyeWithoutNormalTracking=await renderWiringVideo({displayMode:"smart-glasses-demo",realtimeEnabled:false});
  assert.equal(eyeWithoutNormalTracking.tracking[0],true);
  for (const state of ["starting","error"]) {
    const inactive = await renderWiringVideo({displayMode:"smart-glasses-demo",boardId:"arduino-uno-q",state});
    assert.match(inactive.html, /video-img hidden/);
    assert.doesNotMatch(inactive.html,/src="\/video"|data-component-id|data-guide-connection/);
  }
  const searching = await renderWiringVideo({displayMode:"smart-glasses-demo",searching:true,hasTarget:false});
  assert.doesNotMatch(searching.html,/data-component-id|data-recognized-object|glasses-recognition/);
});

test("manual-only semantics are identical in both views, while remote guidance remains available otherwise", async () => {
  for (const displayMode of ["standard","smart-glasses-demo"]) {
    const manual = await renderWiringVideo({displayMode,manualOnly:true});
    assert.equal(manual.pin.localGuidanceOnly,true);
    const remote = await renderWiringVideo({displayMode,hasTarget:false});
    assert.equal(remote.pin.localGuidanceOnly,false);
    assert.match(remote.html,/board-guidance-arrowhead/);
  }
});

test("only Eye shows body-only recognition; Webcam retains original GPIO and wiring overlays", async () => {
  for (const displayMode of ["standard","smart-glasses-demo"]) {
    const searching = await renderWiringVideo({displayMode,searching:true,hasTarget:false,bodyEvidence:"current"});
    if (displayMode === "smart-glasses-demo") {
      assert.match(searching.html,/HC-SR04 · 腳位定位中/);
      assert.match(searching.html,/Raspberry Pi 5 · 腳位定位中/);
      assert.equal((searching.html.match(/data-body-component=/g)??[]).length,2);
    } else {
      assert.doesNotMatch(searching.html,/腳位定位中|object-recognition-overlay|data-body-component=/);
      // The central placement prompt was already removed from Webcam.
      assert.doesNotMatch(searching.html, /<div class="video-hint">/);
    }
    assert.doesNotMatch(searching.html,/data-component-id=|data-guide-connection=/);
    const located = await renderWiringVideo({displayMode,bodyEvidence:"current"});
    if (displayMode === "smart-glasses-demo")
      assert.match(located.html,/data-body-component="hc-sr04" data-pins-located="true"/);
    else
      assert.doesNotMatch(located.html,/object-recognition-overlay|data-body-component=/);
    assert.match(located.html,/data-component-id="hc-sr04"/);
    assert.match(located.html,/data-guide-connection="GPIO17:TRIG"/);
    assert.doesNotMatch(located.html,/腳位定位中|object-recognition-outline/);
  }
});

test("Eye body metadata cannot change Webcam rendering in either tracking mode", async () => {
  for (const realtimeEnabled of [true,false]) for (const searching of [true,false]) {
    const props={displayMode:"standard",realtimeEnabled,searching,hasTarget:!searching};
    const original=await renderWiringVideo(props);
    const withEyeBodies=await renderWiringVideo({...props,bodyEvidence:"current",boardBodyPartial:true,
      componentBodyBox:[600,50,1100,650]});
    assert.equal(withEyeBodies.html,original.html);
    assert.deepEqual(withEyeBodies.tracking,original.tracking);
    // Body metadata and callback identities differ by construction; the
    // rendered GPIOs and all remaining pin-overlay inputs must not change.
    const {detection: originalDetection,onSelectPin: originalSelect,...originalPin}=original.pin;
    const {detection: eyeDetection,onSelectPin: eyeSelect,...eyePin}=withEyeBodies.pin;
    assert.deepEqual(eyePin,originalPin);
    assert.deepEqual(withEyeBodies.target,original.target);
  }
});

test("body labels never come from old-frame evidence or unpaired MJPEG/WS packets", async () => {
  for (const props of [{bodyEvidence:"old"},{bodyEvidence:"current",displayMode:"standard",realtimeEnabled:false}]) {
    const rendered=await renderWiringVideo({displayMode:"smart-glasses-demo",searching:true,hasTarget:false,...props});
    assert.doesNotMatch(rendered.html,/data-body-component=|object-recognition-label/);
  }
});

test("Eye clipped-body hints never leak into Webcam", async () => {
  const props={searching:true,hasTarget:false,bodyEvidence:"current",boardBodyPartial:true};
  const normal=await renderWiringVideo(props);
  const eye=await renderWiringVideo({...props,displayMode:"smart-glasses-demo"});
  assert.match(eye.html,/Raspberry Pi 5 · 請完整入鏡/);
  assert.match(eye.html,/HC-SR04 · 腳位定位中/); // Other complete bodies keep their existing explanation.
  assert.doesNotMatch(eye.html,/Raspberry Pi 5 · 腳位定位中|data-guide-connection=/);
  assert.doesNotMatch(normal.html,/腳位定位中|請完整入鏡|data-body-component=/);
  const complete=await renderWiringVideo({...props,displayMode:"smart-glasses-demo",boardBodyPartial:false});
  assert.match(complete.html,/Raspberry Pi 5 · 腳位定位中/);
  assert.doesNotMatch(complete.html,/請完整入鏡/);
});

test("only Eye anchors a located component label to its displayed pose when its raw body box is oversized", async () => {
  const props={bodyEvidence:"current",componentBodyBox:[600,50,1100,650]};
  const normal=await renderWiringVideo(props);
  const eye=await renderWiringVideo({...props,displayMode:"smart-glasses-demo"});
  const labelY=html=>Number(html.match(/data-body-component="hc-sr04"[^>]*><text[^>]* y="([^"]+)"/)?.[1]);
  assert.doesNotMatch(normal.html,/data-body-component=|object-recognition-label/);
  assert.ok(Math.abs(labelY(eye.html)-(200*2/3-8))<.001);
  for (const result of [normal,eye]) {
    assert.match(result.html,/data-component-id="hc-sr04"/);
    assert.match(result.html,/data-guide-connection="GPIO17:TRIG"/);
    assert.doesNotMatch(result.html,/object-recognition-outline/);
  }
});

test("three settings reach the real stream endpoint; restore follows a pending start even after failure", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  let release;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    if (options.method === "PUT") await new Promise(resolve => { release = resolve; });
    return { ok: options.method !== "PUT", status: options.method === "PUT" ? 503 : 200,
      json: async () => ({ state: "idle", active: false }) };
  };
  try {
    const mutate = createGlassesMutationQueue();
    const start = mutate("PUT", DEFAULT_GLASSES_SETTINGS);
    const rejected = assert.rejects(start, /HTTP 503/);
    const stop = mutate("DELETE");
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/glasses/stream");
    assert.deepEqual(JSON.parse(calls[0].body), { width: 1920, height: 1080, fps: 30, denoise: "clean" });
    release();
    await rejected;
    assert.equal((await stop).state, "idle");
    assert.deepEqual(calls.map(call => call.method), ["PUT", "DELETE"]);
    assert.equal(calls[1].body, undefined);
    await requestGlassesStream("GET");
    assert.equal(calls[2].cache, "no-store");
  } finally { globalThis.fetch = originalFetch; }
});
