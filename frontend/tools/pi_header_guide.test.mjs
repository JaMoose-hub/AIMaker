import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const url = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
function compile(path, replacements = {}) {
  let js = ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), {
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,jsx:ts.JsxEmit.ReactJSX},
  }).outputText;
  for (const [name, value] of Object.entries({react:import.meta.resolve('react'), 'react/jsx-runtime':import.meta.resolve('react/jsx-runtime'), ...replacements})) {
    js = js.replaceAll(JSON.stringify(name), JSON.stringify(value));
  }
  return url(js);
}
const board = JSON.parse(readFileSync(new URL('../../profiles/boards/raspberry-pi-5/board.json', import.meta.url), 'utf8'));
const helperUrl = compile('lib/piHeaderGuide.ts');
const {piHeaderLocation, piHeaderGuideText} = await import(helperUrl);
const calloutUrl = compile('lib/guidanceCallout.ts');
const {guidanceCalloutGeometry, guidancePointerGeometry} = await import(calloutUrl);
const labelUrl = compile('lib/wiringLabelLayout.ts');
const {placeWiringLabel, pointBounds, linkIntersectsLabel} = await import(labelUrl);

test('all 40 physical pins become two independent 1–20 rows without changing the profile', () => {
  const before = structuredClone(board);
  const inner = [], outer = [];
  for (const pin of board.pins) {
    const location = piHeaderLocation(pin);
    assert.equal(location.physical, Number(pin.silkscreen));
    assert.equal(location.number, Math.ceil(pin.index / 2));
    (location.row === 'inner' ? inner : outer).push(pin);
  }
  assert.equal(inner.length, 20);
  assert.equal(outer.length, 20);
  for (let i = 0; i < 20; i++) {
    assert.equal(piHeaderLocation(inner[i]).number, i + 1);
    assert.equal(piHeaderLocation(outer[i]).number, i + 1);
    assert.equal(inner[i].pos_mm[0], outer[i].pos_mm[0]);
    // The outer row really is closer to the profile's y=56 board edge.
    assert.ok(outer[i].pos_mm[1] > inner[i].pos_mm[1]);
  }
  assert.deepEqual(board, before);
  for (const [id, number, row] of [['GPIO17',6,'inner'],['GPIO18',6,'outer'],['GND_P6',3,'outer'],['GPIO21',20,'outer']]) {
    assert.deepEqual({...piHeaderLocation(board.pins.find(p => p.id === id)), signal:undefined,physical:undefined}, {number,row,signal:undefined,physical:undefined});
  }
});

test('unknown headers and invalid physical indices do not get invented Pi positions', () => {
  assert.equal(piHeaderLocation(undefined), null);
  for (const index of [0,41,1.5,NaN]) assert.equal(piHeaderLocation({...board.pins[0],index}), null);
  assert.equal(piHeaderLocation({...board.pins[0],header:'JANALOG',index:0}), null);
});

test('expanded Pi callout remains inside supported narrow and wide viewports; module default is unchanged', () => {
  for (const [width,height] of [[280,158],[300,169],[320,180],[780,440],[1280,720]]) {
    for (const [x,y] of [[0,0],[width,0],[0,height],[width,height],[width/2,height/2]]) {
      const box = guidanceCalloutGeometry(x,y,width,height,300,76);
      assert.ok(box.boxX >= 8 && box.boxX + box.boxWidth <= width - 8);
      assert.ok(box.boxY >= 8 && box.boxY + box.boxHeight <= height - 8);
    }
  }
  const standard = guidanceCalloutGeometry(200,200,800,600);
  assert.equal(standard.boxWidth,132);
  assert.equal(standard.boxHeight,44);
});

test('Pi pointers stay short and do not move the target or depend on a floating box size', () => {
  for (const [width,height] of [[280,158],[780,440],[1280,720]]) {
    for (const [x,y] of [[0,0],[width,0],[0,height],[width,height],[width/2,height/2]]) {
      const arrow = guidancePointerGeometry(x,y,width,height);
      assert.ok(Math.hypot(arrow.startX-x,arrow.startY-y) <= 38.0001);
      assert.ok(Math.hypot(arrow.endX-x,arrow.endY-y) <= 8.0001);
      assert.ok(arrow.startX >= 0 && arrow.startX <= width);
      assert.ok(arrow.startY >= 0 && arrow.startY <= height);
      assert.ok(arrow.endX >= 0 && arrow.endX <= width);
      assert.ok(arrow.endY >= 0 && arrow.endY <= height);
    }
  }
});

test('Pi restores one short row/ordinal label without extra instructions, including mirrored views', async () => {
  for (const locale of ['zh-TW','en']) {
    const messages = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`, import.meta.url), 'utf8'));
    const t = (key,params={}) => Object.entries(params).reduce((s,[k,v]) => s.replace(`{${k}}`,String(v)),messages[key]??key);
    const i18n = url(`export const useI18n=()=>({t:${t.toString().replace('messages[key]',`(${JSON.stringify(messages)})[key]`)}});`);
    const {PinOverlay} = await import(compile('components/PinOverlay.tsx', {
      '../lib/geometry':compile('lib/geometry.ts'), '../lib/i18n':i18n,
      '../lib/piHeaderGuide':helperUrl,'../lib/guidanceCallout':calloutUrl,
      '../lib/wiringLabelLayout':labelUrl,
      '../lib/capabilities':compile('lib/capabilities.ts'),
      '../lib/useSmoothedDetection':url('export const useSmoothedDetection=d=>d;'),
      '../lib/wsClient':url('export const useGuidance=()=>null;'),
    }));
    const render = (pin,mirrorX,mirrorY) => {
      const report=console.error;
      try {
        console.error=(msg,...args)=>{if(typeof msg==='string' && msg.startsWith('Warning: A title element received an array'))return;report(msg,...args);};
        return renderToStaticMarkup(createElement(PinOverlay, {
          detection:{board_id:board.board.id,tracking:'locked',confidence:1,outline:[[10,10],[350,10],[350,200],[10,200]],pins:[{id:pin.id,x:200,y:100,c:1,v:true}]},
          letterbox:{scale:1,offx:0,offy:0,elementWidth:800,elementHeight:500,mirrorX,mirrorY},width:800,height:500,
          pinsById:new Map([[pin.id,pin]]),highlightIds:null,selectedPinId:null,onSelectPin(){},interactive:false,lockSeq:1,
          tracking:'locked',displayOffsetPx:{x:0,y:0},guidePinId:pin.id,localGuidanceOnly:true,
          guidePeerPose:{component_id:'hc-sr04',tracking:'locked',outline:[[560,270],[650,270],[650,340],[560,340]],pins:[{id:'TRIG',x:600,y:300,v:true}]},guidePeerPinId:'TRIG',
        }));
      } finally {console.error=report;}
    };
    for (const pin of board.pins) for (const [mx,my] of [[false,false],[true,true]]) {
      const html = render(pin,mx,my);
      const label = piHeaderGuideText(pin,t);
      assert.ok(html.includes(label.title), `${pin.id}: ${label.title}`);
      assert.ok(!html.includes(label.reference));
      assert.ok(!html.includes(label.countFromLabel));
      assert.ok(!html.includes('J8第'));
      const pointer = html.match(/<g class="component-pin-callout board-pin-callout pi-guidance-pointer"[\s\S]*?<\/g>/)?.[0];
      assert.ok(pointer);
      assert.ok(pointer.includes('component-pin-callout-arrow'));
      assert.equal((pointer.match(/<text/g)??[]).length, 1);
      assert.ok(pointer.includes('pi-row-label-box'));
      assert.match(pointer, /width="228" height="32"/);
      assert.ok(pointer.includes(label.title));
      assert.ok(!html.includes('pi-pin-callout-reference'));
    }
    const arduino = {...board.pins[0],id:'A0',header:'JANALOG',index:0,silkscreen:'A0'};
    const html = render(arduino,false,false);
    assert.ok(html.includes(t('boardGuide.countFromBoot')));
    assert.ok(!html.includes('pi-pin-callout-reference'));
    assert.match(html, /width="132" height="44"/);
  }
});

test('compact labels avoid links, endpoints and both bodies in rotated/mirrored scenes', () => {
  // Use all cardinal and diagonal arrangements, not just the current desktop pose.
  for (let angle=0; angle<360; angle+=15) for (const mirror of [-1,1]) {
    const r=angle*Math.PI/180;
    const target={x:640+Math.cos(r)*170*mirror,y:400+Math.sin(r)*170};
    const peer={x:640-Math.cos(r)*220*mirror,y:400-Math.sin(r)*220};
    const board={x:target.x-45,y:target.y-70,width:90,height:140};
    const module={x:peer.x-40,y:peer.y-30,width:80,height:60};
    const otherLabel=guidanceCalloutGeometry(peer.x,peer.y,1280,800);
    const obstacles=[module,{x:otherLabel.boxX,y:otherLabel.boxY,width:otherLabel.boxWidth,height:otherLabel.boxHeight}];
    const result=placeWiringLabel(target,peer,board,obstacles,1280,800);
    assert.ok(result, `Expected a readable placement for ${angle}/${mirror}`);
    assert.equal(linkIntersectsLabel(target,peer,result),false);
    assert.ok(result.x>=8 && result.x+result.width<=1272);
    assert.ok(result.y>=112 && result.y+result.height<=792);
    for (const block of [board,...obstacles]) {
      assert.ok(result.x>block.x+block.width+10 || result.x+result.width<block.x-10 ||
        result.y>block.y+block.height+10 || result.y+result.height<block.y-10);
    }
  }
});

test('line collision checks include endpoints and exact horizontal/vertical crossings', () => {
  const box={x:40,y:40,width:40,height:30};
  assert.equal(linkIntersectsLabel({x:0,y:55},{x:100,y:55},box,0),true);
  assert.equal(linkIntersectsLabel({x:60,y:0},{x:60,y:100},box,0),true);
  assert.equal(linkIntersectsLabel({x:50,y:50},{x:50,y:50},box,0),true);
  assert.equal(linkIntersectsLabel({x:0,y:0},{x:20,y:20},box,0),false);
  assert.equal(linkIntersectsLabel({x:0,y:30},{x:100,y:30},box,18),true);
});

test('missing peers still protect the Pi; no-free-space scenes fall back to the persistent corner/side label', () => {
  assert.equal(pointBounds([]),null);
  assert.deepEqual(pointBounds([{x:10,y:20},{x:30,y:50}]),{x:10,y:20,width:20,height:30});
  const target={x:400,y:300};
  assert.ok(placeWiringLabel(target,null,{x:350,y:250,width:100,height:100},[],800,600));
  assert.equal(placeWiringLabel(target,null,{x:0,y:0,width:800,height:600},[],800,600),null);
});
