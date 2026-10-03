import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
function load(path,imports={}) {
  const js=ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',js)(name=>{if(name in imports)return imports[name];throw Error(name);},exports,React);return exports;
}
const palette=load('../src/lib/recognitionStyle.ts');
const photo=load('../src/lib/photoWiring.ts');
const board=JSON.parse(read('../../profiles/boards/raspberry-pi-5/board.json'));
const {PhotoPins}=load('../src/components/PhotoWiringPoc.tsx',{
  react:React,'../../../profiles/boards/raspberry-pi-5/board.json':{default:board},
  '../lib/i18n':{useI18n:()=>({locale:'zh-TW'})},'../lib/componentHeaderGuide':{},'../lib/circuitZoom':{},
  '../lib/capabilities':load('../src/lib/capabilities.ts'),'../lib/recognitionStyle':palette,
  '../lib/photoWiring':photo,'../photoWiring.css':{},
});
function fixture() {
  const outline=[[10,10],[300,10],[300,300],[10,300]];
  const pose=extra=>({tracking:'locked',outline,pins:[],...extra});
  const capture={video_size:[1920,1080],
    detection:pose({board_id:'raspberry-pi-5',pins:[{id:'GPIO18',x:100,y:100,v:true},{id:'GND_P6',x:110,y:120,v:true}]}),
    components:[pose({component_id:'hc-sr04',pins:[{id:'ECHO',x:800,y:500,v:true},{id:'GND',x:850,y:500,v:true}]})],
    localization:['raspberry-pi-5','hc-sr04'].map(object_id=>({object_id,status:'located',
      evidence:{board_geometry_verified:true,pin_geometry_verified:true},corrected_outline_px:outline,raw_outline_px:outline}))};
  const wire={component_id:'hc-sr04',board_pin:'GPIO18',component_pin:'ECHO',connection_kind:'direct'};
  return {capture,wire};
}
const render=props=>renderToStaticMarkup(React.createElement(PhotoPins,props));

test('live and photo imports share the unchanged connection and component palettes',()=>{
  for(const [pin,color] of Object.entries({VCC:'#ff9a56',GND:'#b4becd',AO:'#5ee0b2',ECHO:'#66dfff',CS:'#66dfff'}))
    assert.equal(palette.guideConnectionColor(pin),color);
  assert.equal(palette.componentPinColor('ECHO'),'#c891ff');assert.equal(palette.componentPinColor('VCC'),'#ff7777');
  assert.equal(palette.componentPinColor('unknown'),'#61dafb');
  for(const file of ['PhotoWiringPoc','GuideConnectionOverlay','ComponentPinOverlay'])
    assert.match(read(`../src/components/${file}.tsx`),/from "\.\.\/lib\/recognitionStyle"/);
});

test('trusted photos use live outline, wire, arrow and target-ring classes without changing the capture',()=>{
  const props=fixture(),before=structuredClone(props),html=render(props);
  assert.equal((html.match(/class="board-outline"/g)||[]).length,2);
  assert.match(html,/photo-poc-target-link guide-connection-line/);
  assert.match(html,/--guide-connection-color:#66dfff/);assert.match(html,/guide-connection-arrowhead/);
  assert.match(html,/guidance-halo guidance-halo-inner/);assert.match(html,/--mk:#c891ff/);
  assert.deepEqual(props,before);
});

test('ground and power wiring use live colors instead of a fixed yellow connection',()=>{
  const props=fixture();props.wire={...props.wire,board_pin:'GND_P6',component_pin:'GND'};
  assert.match(render(props),/--guide-connection-color:#b4becd/);
  props.wire.component_pin='VCC';assert.match(render(props),/--guide-connection-color:#ff9a56/);
});

test('unverified, raw, absent endpoints and divider wiring never gain a decorative direct link',()=>{
  for(const mutate of [p=>p.capture.localization[1].status='uncertain',p=>p.capture.localization[0].evidence.pin_geometry_verified=false,
    p=>p.capture.components[0].pins=[],p=>p.wire.connection_kind='divider',p=>p.mode='raw']) {
    const props=fixture();mutate(props);assert.doesNotMatch(render(props),/photo-poc-target-link/);
  }
  const props=fixture();props.capture.localization[1].status='uncertain';
  assert.match(render(props),/photo-poc-uncertain-outline/);
});

test('detected but unlocalized modules remain visible as uncertain candidates, without pins or wires',()=>{
  const props=fixture(),local=props.capture.localization[1];
  local.status='uncertain';local.corrected_outline_px=null;local.evidence={};
  const html=render(props);
  assert.equal((html.match(/class="board-outline"/g)||[]).length,2);
  assert.match(html,/HC-SR04\+ · 座標待確認/);
  assert.doesNotMatch(html,/photo-poc-target-link|cx="800"/);
  assert.equal(photo.reliablePhotoPose(props.capture,'hc-sr04'),null);
});

test('fit and zoom retain the original coordinate system and scale target rings to display pixels',()=>{
  for(const scale of [.25,.5,1,2]) {
    const html=render({...fixture(),scale});
    assert.match(html,/viewBox="0 0 1920 1080"/);
    assert.ok(html.includes(`cx="100" cy="100" r="${17/scale}"`));
    assert.ok(html.includes(`markerWidth="${9/scale}"`));
  }
});

test('multiple photo overlays have unique arrow ids',()=>{
  const html=renderToStaticMarkup(React.createElement(React.Fragment,null,
    React.createElement(PhotoPins,fixture()),React.createElement(PhotoPins,fixture())));
  const ids=[...html.matchAll(/<marker id="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(ids.length,2);assert.equal(new Set(ids).size,2);
});

test('photo CSS does not override the shared live palette or imply ongoing tracking',()=>{
  const css=read('../src/photoWiring.css');
  assert.doesNotMatch(css,/\.photo-poc-target-link\s*\{/);
  assert.doesNotMatch(css,/#71baff|#77beff|#ffc970/);
  assert.match(css,/\.photo-poc-active-pin :is\(\.guidance-halo,\.pin-dot\) \{ animation:none/);
  assert.match(css,/\.photo-poc-uncertain-outline polygon \{ fill:none; filter:none;.*stroke-dasharray/);
});
