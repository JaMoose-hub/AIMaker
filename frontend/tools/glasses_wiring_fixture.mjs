// Render the real video and wiring overlays with deterministic camera packets.
// Hooks supply fixtures only; this does not open cameras or run a classifier.
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import {componentHeaderUrl} from './component_header_fixture.mjs';

const dataUrl = js => `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`;
const react = import.meta.resolve("react");
function compile(path, replacements = {}) {
  let js = ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  for (const [name, url] of Object.entries({ react, "react/jsx-runtime": import.meta.resolve("react/jsx-runtime"), ...replacements }))
    js = js.replaceAll(JSON.stringify(name), JSON.stringify(url));
  return dataUrl(js);
}
const baseGeometry = compile("lib/geometry.ts");
const geometry = dataUrl(`export * from ${JSON.stringify(baseGeometry)}; export const useElementSize = () => ({width:1280,height:720});`);
const messages = JSON.parse(readFileSync(new URL("../src/locales/zh-TW.json", import.meta.url), "utf8"));
const i18n = dataUrl(`export const useI18n=()=>({t:key=>(${JSON.stringify(messages)})[key]??key,tx:value=>value?.['zh-TW']??''});`);
const smooth = dataUrl("export const useSmoothedDetection = detection => detection;");
const guidanceCallout = compile("lib/guidanceCallout.ts");
const labelLayout = compile("lib/wiringLabelLayout.ts");
const componentOverlay = compile("components/ComponentPinOverlay.tsx", { "../lib/componentHeaderGuide": componentHeaderUrl, "../lib/wiringLabelLayout": labelLayout, "../lib/geometry": geometry, "../lib/i18n": i18n, "../lib/guidanceCallout": guidanceCallout });
const connectionOverlay = compile("components/GuideConnectionOverlay.tsx", { "../lib/geometry": geometry, "../lib/useSmoothedDetection": smooth });
const recognitionOverlay = compile("components/ObjectRecognitionOverlay.tsx", { "../lib/geometry": geometry, "../lib/i18n": i18n });

export async function renderWiringVideo({ displayMode = "standard", boardId = "raspberry-pi-5", realtimeEnabled = true,
  state = "running", eyeActive = displayMode === "smart-glasses-demo", cameraSource = eyeActive ? "xreal" : "device",
  hasTarget = true, manualOnly = false, searching = false, bodyEvidence = null, componentBodyBox = null, boardBodyPartial = false } = {}) {
  const detection = { type: "detection", board_id: boardId, runtime_revision: 12, frame_id: 77, ts_ms: 1000,
    tracking: searching ? "searching" : "locked", confidence: .92, video_size: [1920,1080],
    outline: searching ? null : [[100,100],[700,100],[700,600],[100,600]],
    pins: searching ? [] : [{id:"GPIO17",x:200,y:200,c:1,v:true},{id:"GPIO18",x:230,y:200,c:1,v:true}],
    body: { box:[100,100,700,600],confidence:.92,source:"fixture" } };
  const component = { type: "component_pose", component_id:"hc-sr04", frame_id:77, ts_ms:1000,
    tracking: searching ? "searching" : "locked", confidence:.9, video_size:[1920,1080],
    outline: searching ? null : [[800,200],[1000,200],[1000,500],[800,500]],
    pins: searching ? [] : [{id:"TRIG",x:810,y:250,c:1,v:true},{id:"ECHO",x:820,y:250,c:1,v:true}],
    body:{box:[800,200,1000,500],confidence:.9,source:"fixture"} };
  if (componentBodyBox) component.body.box=componentBodyBox;
  if (boardBodyPartial) detection.body.partial=true;
  if (bodyEvidence) for (const pose of [detection, component]) {
    const [x1,y1,x2,y2]=pose.body.box;
    Object.assign(pose.body,{display_only:true,frame_id:bodyEvidence==="current"?77:76,age_ms:20,
      outline:[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]});
  }
  const frame = { seq:77,frame_id:77,runtime_revision:12,board_id:boardId,image:"data:image/jpeg;base64,fixture",detection,components:[component],receivedAt:1000 };
  const snapshot = { detection, componentPoses:[component], hello:{board_id:boardId,runtime_revision:12,video_size:[1920,1080]}, connected:true };
  const ws = dataUrl(`export const useDetections=()=>(${JSON.stringify(snapshot)}); export const useGuidance=()=>({expected_pin_id:'GPIO18',status:'pending'});`);
  const pinOverlay = compile("components/PinOverlay.tsx", { "../lib/geometry":geometry,"../lib/i18n":i18n,"../lib/guidanceCallout":guidanceCallout,
    "../lib/piHeaderGuide":compile("lib/piHeaderGuide.ts"),
    "../lib/wiringLabelLayout":compile("lib/wiringLabelLayout.ts"),
    "../lib/capabilities":compile("lib/capabilities.ts"),"../lib/useSmoothedDetection":smooth,"../lib/wsClient":ws });
  const tracker = dataUrl(`export const calls=[]; export function useRealtimeTracking(...args){calls.push(args);return {frame:args[0]?${JSON.stringify(frame)}:null,fps:args[0]?30:0};}`);
  const guide = dataUrl(`export const calls=[];export function useGuidedPose(target,display){calls.push(target);const s=display??${JSON.stringify(snapshot)};return {...s,pose:s.componentPoses[0],visualReady:!${searching},visualHeld:false,visualDetection:s.detection,visualPose:s.componentPoses[0]};}`);
  const pinRecorder = dataUrl(`import {createElement} from ${JSON.stringify(react)}; import {PinOverlay as Actual} from ${JSON.stringify(pinOverlay)};
    export const calls=[]; export function PinOverlay(props){calls.push(props);return createElement(Actual,props);}`);
  const viewUrl = compile("components/VideoView.tsx", {
    "../lib/wiringLabelLayout":labelLayout,
    "../lib/geometry":geometry,"../lib/i18n":i18n,"../lib/wsClient":ws,"../lib/useGuidedPose":guide,"../lib/useRealtimeTracking":tracker,
    "../lib/displayMode":compile("lib/displayMode.ts"),"../lib/opticalHud":compile("lib/opticalHud.ts",{"./geometry":geometry}),
    "../lib/realtimeFrame":compile("lib/realtimeFrame.ts"),"../lib/glasses":compile("lib/glasses.ts"),
    "./PinOverlay":pinRecorder,"./ComponentPinOverlay":componentOverlay,"./GuideConnectionOverlay":connectionOverlay,
    "./ObjectRecognitionOverlay":recognitionOverlay,
    "./CalibratePanel":dataUrl("export const CalibratePanel=()=>null;"),"./OpticalHudCalibration":dataUrl("export const OpticalHudCalibrationOverlay=()=>null;"),
  });
  const { VideoView } = await import(viewUrl);
  const pinModule=await import(pinRecorder); pinModule.calls.length=0;
  const trackerModule=await import(tracker); trackerModule.calls.length=0;
  const guideModule=await import(guide); guideModule.calls.length=0;
  const target=hasTarget?{componentId:"hc-sr04",boardPinId:"GPIO17",componentPinId:"TRIG",connectionKind:"direct",manualOnly}:null;
  const element=createElement(VideoView, {
    displayMode,glassesStatus:{active:eyeActive,state,runtime_revision:12,requested:{width:1920,height:1080,fps:30,denoise:"clean"}},onGlassesDisplayFps(){},
    config:{board_id:boardId,camera_source:cameraSource,runtime_revision:12,video_size:[1920,1080],realtime_tracking:realtimeEnabled},pinsById:new Map(),
    highlightIds:new Set(["GPIO17"]),selectedPinId:"GPIO17",onSelectPin(){},backendDown:false,legend:{colorVar:"--ok",label:"Selected target",count:1},
    outlineMm:[85,56],boardName:boardId,calibrateOpen:false,onCloseCalibrate(){},onCalibrationSuccess(){},guideTarget:target,
    opticalHudCalibration:null,onOpticalHudCalibrationComplete(){},
  });
  // React 18 SSR also applies its HTML <title> warning to the existing SVG
  // title nodes. Keep production PinOverlay untouched and silence only that
  // known fixture warning (its data-URL stack would be megabytes long).
  const report=console.error;
  let html;
  try {
    console.error=(message,...details)=>{
      if (typeof message==="string" && message.startsWith("Warning: A title element received an array")) return;
      report(message,...details);
    };
    html=renderToStaticMarkup(element);
  } finally { console.error=report; }
  return {html,pin:pinModule.calls[0],tracking:trackerModule.calls[0],target:guideModule.calls[0]};
}
