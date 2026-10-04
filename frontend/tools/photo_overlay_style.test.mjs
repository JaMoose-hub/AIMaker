import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {componentHeaderUrl} from './component_header_fixture.mjs';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
function load(path,imports={}) {
  const js=ts.transpileModule(read(path),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const exports={};new Function('require','exports','React',js)(name=>{if(name in imports)return imports[name];throw Error(name);},exports,React);return exports;
}
const palette=load('../src/lib/recognitionStyle.ts');
const photo=load('../src/lib/photoWiring.ts');
const board=JSON.parse(read('../../profiles/boards/raspberry-pi-5/board.json'));
const messages=JSON.parse(read('../src/locales/zh-TW.json'));
const t=(key,params={})=>Object.entries(params).reduce((s,[name,value])=>s.replace(`{${name}}`,value),messages[key]??key);
const {PhotoPins}=load('../src/components/PhotoWiringPoc.tsx',{
  react:React,'../../../profiles/boards/raspberry-pi-5/board.json':{default:board},
  '../lib/i18n':{useI18n:()=>({locale:'zh-TW',t})},'../lib/componentHeaderGuide':await import(componentHeaderUrl),'../lib/circuitZoom':{},
  '../lib/piHeaderGuide':load('../src/lib/piHeaderGuide.ts'),'../lib/headerCountDirection':load('../src/lib/headerCountDirection.ts'),
  '../lib/wiringLabelLayout':load('../src/lib/wiringLabelLayout.ts'),
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

test('trusted photos use live outline, wire, arrow and centre dots without outer rings or capture changes',()=>{
  const props=fixture(),before=structuredClone(props),html=render(props);
  assert.equal((html.match(/class="board-outline"/g)||[]).length,2);
  assert.match(html,/photo-poc-target-link guide-connection-line/);
  assert.match(html,/--guide-connection-color:#66dfff/);assert.match(html,/guide-connection-arrowhead/);
  assert.equal((html.match(/class="pin-marker guidance-target"/g)||[]).length,2);
  assert.doesNotMatch(html,/guidance-halo/);assert.match(html,/--mk:#c891ff/);
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

test('a TFT body-only detection stays labelled without borrowing HC pins or drawing a link',()=>{
  const props=fixture();
  props.capture.components.push({component_id:'mrd-tf240-8p-cs',tracking:'searching',outline:null,pins:[],
    body:{box:[900,500,1400,1079],confidence:.73,partial:true}});
  props.capture.localization.push({object_id:'mrd-tf240-8p-cs',status:'uncertain',raw_outline_px:null,corrected_outline_px:null,
    reason:'invalid_model_geometry',evidence:{board_geometry_verified:false,pin_geometry_verified:false}});
  props.wire={...props.wire,component_id:'mrd-tf240-8p-cs',component_pin:'GND'};
  const before=structuredClone(props),html=render(props);
  assert.match(html,/MRD-TFT240 · 已辨識 · 腳位未定位/);
  assert.match(html,/HC-SR04\+ · 座標可靠/);
  assert.match(html,/data-component-id="mrd-tf240-8p-cs" class="photo-poc-component-pins photo-poc-uncertain-outline"/);
  assert.doesNotMatch(html,/photo-poc-target-link/);
  assert.equal(photo.reliablePhotoPose(props.capture,'mrd-tf240-8p-cs'),null);
  assert.deepEqual(props,before);
});

test('invalid candidate boxes cannot become photo geometry',()=>{
  for(const box of [[NaN,10,30,40],[30,40,10,20],[-40,0,-10,40],[2000,10,2200,100]]) {
    const props=fixture(),c=props.capture.components[0],l=props.capture.localization[1];
    c.body={box};c.outline=null;l.status='uncertain';l.corrected_outline_px=null;l.raw_outline_px=null;
    assert.equal(photo.photoOverlayObjects(props.capture,'corrected')[1].outline,null);
    assert.doesNotMatch(render(props),/photo-poc-target-link/);
  }
});

test('two located components with the same GND pin name use their own endpoints',()=>{
  const props=fixture();
  props.capture.components.push({component_id:'mrd-tf240-8p-cs',tracking:'locked',outline:props.capture.components[0].outline,
    pins:[{id:'GND',x:1300,y:800,v:true}]});
  props.capture.localization.push({...props.capture.localization[1],object_id:'mrd-tf240-8p-cs'});
  props.capture.detection.pins.push({id:'GND_P20',x:140,y:180,v:true});
  for(const [id,boardPin,x,y] of [['hc-sr04','GND_P6',850,500],['mrd-tf240-8p-cs','GND_P20',1300,800]]) {
    props.wire={component_id:id,board_pin:boardPin,component_pin:'GND',connection_kind:'direct'};
    const html=render(props);
    assert.equal((html.match(/photo-poc-target-link/g)||[]).length,1);
    const active=[...html.matchAll(/class="photo-poc-active-pin">([\s\S]*?)<\/g>/g)].map(m=>m[1]);
    assert.equal(active.length,2);
    assert.ok(active[1].includes(`cx="${x}" cy="${y}"`));
  }
});

test('fit and zoom retain source coordinates and constant-size centre dots without target rings',()=>{
  for(const scale of [.25,.5,1,2]) {
    const html=render({...fixture(),scale});
    assert.match(html,/viewBox="0 0 1920 1080"/);
    assert.ok(html.includes(`cx="100" cy="100" r="${3/scale}"`));
    assert.doesNotMatch(html,/guidance-halo/);
    assert.ok(html.includes(`markerWidth="${9/scale}"`));
  }
});

test('multiple photo overlays have unique arrow ids',()=>{
  const html=renderToStaticMarkup(React.createElement(React.Fragment,null,
    React.createElement(PhotoPins,fixture()),React.createElement(PhotoPins,fixture())));
  const ids=[...html.matchAll(/<marker id="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(ids.length,4);assert.equal(new Set(ids).size,4);
});

test('photo callouts use live row and component instructions with physical pin order',()=>{
  const props=fixture();
  props.capture.detection.pins.push({id:'5V_P2',x:110,y:40,v:true},{id:'GPIO21',x:110,y:240,v:true});
  props.capture.components[0].outline=[[700,400],[950,400],[950,600],[700,600]];
  props.capture.localization[1].corrected_outline_px=props.capture.components[0].outline;
  props.capture.components[0].pins.push({id:'VCC',x:750,y:500,v:true});
  const before=structuredClone(props),html=render(props);
  assert.match(html,/外排（靠板邊緣） · 第 6 支/);
  assert.match(html,/HC-SR04\+ · 第 3 支 · ECHO/);
  assert.match(html,/從上往下 ↓ 數，起點算第 1 支/);
  assert.match(html,/從左往右 → 數，VCC 算第 1 支/);
  assert.equal((html.match(/photo-poc-guide-callout/g)||[]).length,2);
  assert.deepEqual(props,before);
});

test('fitted photos use letterboxing for both instructions while retaining the image coordinates',()=>{
  const props=fixture();
  const outlines=[[[486,194],[821,194],[822,693],[488,694]],[[1184,190],[1440,217],[1436,321],[1174,290]],
    [[1091,786],[1123,532],[1546,587],[1520,849]]];
  props.capture.detection.outline=outlines[0];
  props.capture.detection.pins=[{id:'GND_P6',x:796,y:266,v:true},{id:'5V_P2',x:796,y:236,v:true},{id:'GPIO21',x:797,y:520,v:true},
    {id:'3V3_P17',x:781,y:356,v:true},{id:'3V3_P1',x:781,y:236,v:true},{id:'GND_P39',x:782,y:520,v:true}];
  props.capture.components[0].outline=outlines[1];
  props.capture.components[0].pins=[{id:'VCC',x:1282,y:303,v:true},{id:'GND',x:1327,y:308,v:true}];
  props.capture.components.push({component_id:'mrd-tf240-8p-cs',tracking:'locked',outline:outlines[2],
    pins:[{id:'GND',x:1103,y:702,v:true},{id:'VCC',x:1105,y:689,v:true},{id:'BLK',x:1115,y:609,v:true}]});
  props.capture.localization.push({...props.capture.localization[1],object_id:'mrd-tf240-8p-cs'});
  props.capture.localization.forEach((item,i)=>item.corrected_outline_px=outlines[i]);
  const before=structuredClone(props);
  for(const [id,pin,boardPin,title] of [['hc-sr04','GND','GND_P6','HC-SR04+ · 第 4 支 · GND'],
    ['mrd-tf240-8p-cs','VCC','3V3_P17','MRD-TFT240 · 第 2 支 · VCC']]) {
    for(const scale of [.22,.285,.4,1]) {
      const html=render({...props,wire:{component_id:id,component_pin:pin,board_pin:boardPin,connection_kind:'direct'},scale,
        calloutArea:{width:830,height:440}});
      assert.equal((html.match(/photo-poc-guide-callout/g)||[]).length,2,`${id} at ${scale}`);
      assert.ok(html.includes(title));
      assert.match(html,/viewBox="0 0 1920 1080"/);
    }
  }
  assert.deepEqual(props,before);
});

test('photo CSS does not override the shared live palette or imply ongoing tracking',()=>{
  const css=read('../src/photoWiring.css');
  assert.doesNotMatch(css,/\.photo-poc-target-link\s*\{/);
  assert.doesNotMatch(css,/#71baff|#77beff|#ffc970/);
  assert.match(css,/\.photo-poc-active-pin :is\(\.guidance-halo,\.pin-dot\) \{ animation:none/);
  assert.match(css,/\.photo-poc-uncertain-outline polygon \{ fill:none; filter:none;.*stroke-dasharray/);
});
