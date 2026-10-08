// Presentation-only browser checks: real components, synthetic packets, no hardware.
import {createRequire} from 'node:module';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {startPreview} from './wiring-ai-preview.mjs';

const require=createRequire(import.meta.url);
const {chromium}=require('C:/Users/james/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const artifacts=fileURLToPath(new URL('./wiring-ai-preview-artifacts/',import.meta.url));
const compiled=await build({stdin:{resolveDir:fileURLToPath(new URL('./',import.meta.url)),loader:'tsx',contents:`
  import React from 'react';
  import {renderToStaticMarkup} from 'react-dom/server';
  import {PhotoPins} from '../src/components/PhotoWiringPoc';
  import {CircuitDiagram} from '../src/components/CircuitDiagram';
  import {LocaleProvider} from '../src/lib/i18n';
  import {makerCatalog} from '../src/lib/maker';
  const outline=[[200,200],[600,200],[600,800],[200,800]];
  const moduleOutline=[[1100,300],[1480,300],[1480,550],[1100,550]];
  const pose={tracking:'locked',outline,pins:[]};
  const capture={video_size:[1920,1080],detection:{...pose,board_id:'raspberry-pi-5',
    pins:[{id:'GND_P6',x:550,y:270,v:true}]},components:[{...pose,outline:moduleOutline,
    component_id:'hc-sr04',pins:[{id:'GND',x:1310,y:520,v:true}]}],
    localization:['raspberry-pi-5','hc-sr04'].map((object_id,i)=>({object_id,status:'located',
      evidence:{board_geometry_verified:true,pin_geometry_verified:true},
      corrected_outline_px:i?moduleOutline:outline,raw_outline_px:i?moduleOutline:outline}))};
  export const photo=renderToStaticMarkup(<LocaleProvider><PhotoPins capture={capture} scale={900/1920}
    wire={{component_id:'hc-sr04',board_pin:'GND_P6',component_pin:'GND',connection_kind:'direct'}}/></LocaleProvider>);
  const modules=makerCatalog.modules.filter(m=>m.id==='hc-sr04');
  const design={id:'isolated-line-qa',revision:1,title:'Synthetic wiring fixture',
    component_ids:modules.map(m=>m.id),wiring:modules.flatMap(m=>m.steps.map(w=>({...w,id:m.id+':'+w.id,componentId:m.id}))),
    unresolved:[],instructions:[],requirements:{imports:[],devices:[]}};
  // Snapshot only the schematic SVG; viewport measurement needs a mounted client.
  export const circuit=renderToStaticMarkup(<LocaleProvider><CircuitDiagram design={design} activeId="hc-sr04:trig"/></LocaleProvider>).match(/<svg class="circuit-schematic"[\\s\\S]*?<\\/svg>/)[0];
`},bundle:true,platform:'node',format:'cjs',write:false,external:['react','react-dom/server'],loader:{'.css':'empty'}});
const module={exports:{}};
new Function('require','module','exports',compiled.outputFiles[0].text)(require,module,module.exports);
const markup=module.exports;
const css=(await Promise.all(['styles.css','photoWiring.css','maker.css'].map(name=>readFile(new URL('../src/'+name,import.meta.url),'utf8')))).join('\n');
await mkdir(artifacts,{recursive:true});
const preview=await startPreview(0),report={fixture:'Real live/photo/2D components; synthetic image and geometry only',passed:false,checks:[],warnings:[]};
let browser;
const endpoints=line=>line.getAttribute('d');
const assertOrthogonal=path=>{
  assert.match(path,/ Q /,'Wire bends should be soft, not sharp schematic corners');
  const values=path.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi).map(Number);
  const points=Array.from({length:values.length/2},(_,i)=>({x:values[i*2],y:values[i*2+1]}));
  assert.ok(points.length>=4&&points.length<=14);
  points.slice(1).forEach((point,i)=>assert((point.x===points[i].x)!==(point.y===points[i].y)));
  assert.equal(points.at(-1).x,points.at(-2).x);
  assert.ok(points.at(-2).y>points.at(-1).y,'Down-facing HC pins must be entered from below');
};
const styles=line=>line.evaluate(node=>{const s=getComputedStyle(node);return {width:s.strokeWidth,effect:s.vectorEffect,animation:s.animationName,dash:s.strokeDashoffset};});
const sampleMotion=line=>line.evaluate(async node=>{
  const first=getComputedStyle(node).strokeDashoffset;
  await new Promise(resolve=>setTimeout(resolve,160));
  return [first,getComputedStyle(node).strokeDashoffset];
});
try {
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1360,height:900},locale:'zh-TW'});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{
    if(message.type()!=='error')return;
    if(message.text().startsWith('Warning: Encountered two children with the same key')&&message.text().includes('device:1'))report.warnings.push(message.text().split('\n')[0]);
    else errors.push(message.text());
  });
  await page.goto(preview.url+'?scenario=overlay',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'開始 TRIG 步驟',exact:true}).click();
  const live=page.locator('.guide-connection-overlay'),line=live.locator('.guide-connection-line');
  const original=await endpoints(line);
  assertOrthogonal(original);
  const s=await styles(line);
  assert.equal(s.width,'2.4px');assert.equal(s.effect,'non-scaling-stroke');
  assert.match(s.animation,/guide-connection-flow/);assert.match(s.animation,/guide-connection-pulse/);
  assert.equal(await line.evaluate(node=>getComputedStyle(node).stroke),'rgb(0, 123, 255)');
  assert.equal(await live.locator('.guide-connection-glow').evaluate(node=>getComputedStyle(node).opacity),'0.6');
  const pulseOpacity=await line.evaluate(node=>node.getAnimations().find(animation=>animation.animationName==='guide-connection-pulse')
    .effect.getKeyframes().map(frame=>Number(frame.opacity)));
  assert(pulseOpacity.every(opacity=>opacity>=.9&&opacity<=1));
  const spark=live.locator('.guide-connection-spark');
  assert.equal(await spark.getAttribute('d'),original);
  assert.equal((await styles(spark)).animation,'guide-connection-spark-flow');
  assert.equal(await live.locator('.guide-connection-glow').evaluate(node=>getComputedStyle(node).stroke),'rgb(0, 123, 255)');
  assert.equal(await live.locator('.guide-connection-contrast').evaluate(node=>getComputedStyle(node).opacity),'0.24');
  report.checks.push('Soft color glow, light flowing sparks and rounded wire bends; saturated color never below 90% opacity');
  for(const [name,width] of [['contrast','4.6px'],['glow','2.4px']]) {
    const layer=live.locator('.guide-connection-'+name);
    assert.equal((await styles(layer)).width,width);assert.deepEqual(await endpoints(layer),original);
  }
  const liveMotion=await sampleMotion(line);assert.notEqual(...liveMotion);
  assert.deepEqual(await endpoints(line),original);
  await page.screenshot({path:artifacts+'/guide-line-live.png',fullPage:true});
  report.checks.push('Live: thin rounded wire route enters down-facing HC pins from below without moving endpoints during animation');
  for(const state of ['stale','guidance-held']) {
    await live.evaluate((node,state)=>node.classList.add(state),state);
    assert.equal((await styles(line)).animation,'none');
    assert.equal((await styles(spark)).animation,'none');
    assert.equal(await spark.evaluate(node=>getComputedStyle(node).opacity),'0');
    await live.evaluate((node,state)=>node.classList.remove(state),state);
  }
  report.checks.push('Held or stale geometry: animation disabled');

  // A frozen photo has no React client, video, timers or tracking subscription.
  await page.setContent('<style>'+css+'</style><main style="max-width:900px;margin:auto"><h2>Frozen photo · synthetic gray mat / GND</h2><div class="photo-poc-image-stage" style="background:#d9d9d9;aspect-ratio:16/9">'+markup.photo+'</div><h2>Static 2D SVG snapshot · current TRIG wire</h2><section class="maker-circuit">'+markup.circuit+'</section></main>');
  const photo=page.locator('.photo-poc-target-link'),photoPosition=await endpoints(photo);
  assertOrthogonal(photoPosition);
  assert.equal((await styles(photo)).width,'2.4px');
  assert.equal(await photo.evaluate(node=>getComputedStyle(node).stroke),'rgb(96, 114, 140)');
  const photoMotion=await sampleMotion(photo);assert.notEqual(...photoMotion);
  assert.deepEqual(await endpoints(photo),photoPosition);
  const active=page.locator('.circuit-connection.active .circuit-wire-path');
  assert.equal(await active.count(),1);
  assert.equal((await styles(active)).animation,'circuit-wire-pulse');
  assert.equal((await styles(page.locator('.circuit-connection:not(.active) .circuit-wire-path').first())).animation,'none');
  await page.locator('.photo-poc-image-stage').screenshot({path:artifacts+'/guide-line-frozen.png'});
  await page.locator('.maker-circuit').screenshot({path:artifacts+'/guide-line-2d.png'});
  report.checks.push('Frozen photo: GND stays readable and animates without changing positions; 2D pulses only the active route');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal((await styles(photo)).animation,'none');assert.equal((await styles(active)).animation,'none');
  assert.equal(await page.locator('.guide-connection-spark').evaluate(node=>getComputedStyle(node).opacity),'0');
  await page.goto(preview.url+'?scenario=overlay',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'開始 TRIG 步驟',exact:true}).click();
  assert.equal((await styles(page.locator('.guide-connection-line'))).animation,'none');
  report.checks.push('Reduced motion: all three presentations stay high-contrast with no animation');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:390,height:844});
  await page.goto(preview.url+'?scenario=overlay',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'開始 TRIG 步驟',exact:true}).click();
  const mobileLine=page.locator('.guide-connection-line');
  assert.equal((await styles(mobileLine)).width,'2.4px');assertOrthogonal(await endpoints(mobileLine));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:artifacts+'/guide-line-mobile.png',fullPage:true});
  report.checks.push('390px viewport: high-contrast guide without horizontal overflow');
  assert.deepEqual(errors,[]);
  assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),[]);
  assert(preview.requests.every(path=>['/','/preview.js','/preview.css','/theme.js','/brand/tinkro-light-filter.svg'].includes(path.split('?')[0])));
  report.checks.push('No page errors, storage writes or production API requests');
  report.warnings=[...new Set(report.warnings)];report.passed=true;
} finally {
  await writeFile(artifacts+'/guide-line-contrast-report.json',JSON.stringify(report,null,2));
  await browser?.close();await new Promise(resolve=>preview.server.close(resolve));
}
console.log(JSON.stringify(report,null,2));
