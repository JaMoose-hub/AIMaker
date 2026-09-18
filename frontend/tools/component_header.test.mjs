import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {componentHeaderUrl, compileHeaderFile as compile, dataUrl} from './component_header_fixture.mjs';
import {designFor, renderGuide, maker} from './project_guide_fixture.mjs';

const header = await import(componentHeaderUrl);
const layoutUrl = compile('lib/wiringLabelLayout.ts');
const layout = await import(layoutUrl);
const geometryUrl = compile('lib/geometry.ts');
const {toDisplay} = await import(geometryUrl);
const directionUrl = compile('lib/headerCountDirection.ts');
const {headerCountDirection} = await import(directionUrl);
const rows = {'hc-sr04':['VCC','TRIG','ECHO','GND'], 'mrd-tf240-8p-cs':['GND','VCC','SCL','SDA','RES','DC','CS','BLK']};
function localeFixture(locale) {
  const messages = JSON.parse(readFileSync(new URL(`../src/locales/${locale}.json`,import.meta.url),'utf8'));
  const t=(key,params={})=>Object.entries(params).reduce((s,[k,v])=>s.replace(`{${k}}`,v),messages[key]??key);
  const i18n=dataUrl(`export const useI18n=()=>({t:(key,params={})=>Object.entries(params).reduce((s,[k,v])=>s.replace('{'+k+'}',v),(${JSON.stringify(messages)})[key]??key)});`);
  return {t,i18n};
}

test('module ordinals use canonical physical order, including unused TFT pins', () => {
  for(const [id,pins] of Object.entries(rows)) pins.forEach((pin,i)=>{
    const location=header.componentHeaderLocation(id,pin);
    assert.equal(location.number,i+1);
    assert.equal(location.startPin,pins[0]);
    assert.deepEqual(location.pins,pins);
  });
  for(const id of ['hw-123','photoresistor-module','unknown']) assert.equal(header.componentHeaderLocation(id,'GND'),null);
  assert.equal(header.componentHeaderLocation('hc-sr04','SDA'),null);
  assert.equal(header.componentHeaderLocation('hc-sr04',null),null);
});

test('both module overlays show row direction and preserve ordinals through every mirror', async () => {
  for(const locale of ['zh-TW','en']) {
    const {t,i18n}=localeFixture(locale);
    const {ComponentPinOverlay}=await import(compile('components/ComponentPinOverlay.tsx',{
      '../lib/componentHeaderGuide':componentHeaderUrl,'../lib/wiringLabelLayout':layoutUrl,
      '../lib/headerCountDirection':directionUrl,
      '../lib/geometry':geometryUrl,'../lib/i18n':i18n,'../lib/guidanceCallout':compile('lib/guidanceCallout.ts'),
    }));
    for(const [id,pins] of Object.entries(rows)) for(const pin of pins) for(const mirrorX of [false,true]) for(const mirrorY of [false,true]) {
      const pose={component_id:id,tracking:'locked',outline:[[300,220],[500,220],[500,320],[300,320]],pins:pins.map((id,i)=>({id,x:340+i*10,y:320,v:true}))};
      const before=structuredClone(pose);
      const props={pose,letterbox:{scale:1,offx:0,offy:0,elementWidth:1000,elementHeight:700,mirrorX,mirrorY},width:1000,height:700,targetPinId:pin};
      const html=renderToStaticMarkup(createElement(ComponentPinOverlay,props));
      const text=header.componentHeaderGuideText(id,pin,t);
      const callout=html.match(/<g class="component-pin-callout"[\s\S]*?<\/g>/)?.[0];
      assert.ok(callout?.includes(text.title));
      assert.equal((callout.match(/<text/g)??[]).length,2);
      assert.match(callout,/width="288" height="52"/);
      assert.ok(callout.includes(t('headerCount.component', {direction:t(mirrorX ? 'headerCount.left' : 'headerCount.right'),pin:pins[0]})));
      assert.ok(!callout.includes('component-pin-callout-hint'));
      assert.ok(!html.includes('component-header-start'));
      assert.match(html,/markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9"/);
      assert.match(html,/class="component-guidance-arrowhead" d="M 1 1 L 9 5 L 1 9"/);
      assert.ok(!html.includes('①'));
      assert.equal(text.name,id === 'hc-sr04' ? 'HC-SR04+' : 'MRD-TFT240');
      assert.ok(!callout.includes('超音波') && !callout.includes('螢幕'));
      assert.deepEqual(pose,before);
      const noSpace=renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,guideLabel:null}));
      assert.ok(!noSpace.includes('class="component-pin-callout"'));
      assert.ok(noSpace.includes('component-guidance-halo'));
      const missingStart=renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,pose:{...pose,pins:pose.pins.map((p,i)=>({...p,v:i!==0}))}}));
      assert.ok(!missingStart.includes('component-header-start'));
      if(pin!==pins[0]) assert.ok(missingStart.includes(t('headerCount.componentFallback',{pin:pins[0]})));
      const held=renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,held:true}));
      assert.ok(held.includes(t('headerCount.componentFallback',{pin:pins[0]})));
      for(const extra of [{guidanceSuspended:true},{pose:{...pose,tracking:'searching'}}]) assert.equal(renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,...extra})),'');
    }
    const legacy=renderToStaticMarkup(createElement(ComponentPinOverlay,{pose:{component_id:'photoresistor-module',tracking:'locked',pins:[{id:'GND',x:300,y:250,v:true}]},letterbox:{scale:1,offx:0,offy:0,elementWidth:1000,elementHeight:700},width:1000,height:700,targetPinId:'GND'}));
    assert.match(legacy,/width="132" height="44"/);
    assert.ok(legacy.includes(t('componentGuide.countFromAo')));
  }
});

test('counting directions follow semantic endpoints across rotation, mirrors and perspective', () => {
  const {t}=localeFixture('zh-TW');
  const directions=['right','downRight','down','downLeft','left','upLeft','up','upRight'];
  for(let i=0;i<8;i++) for(const mirrorX of [false,true]) for(const mirrorY of [false,true]) {
    const theta=i*Math.PI/4, start={x:300,y:250};
    const end={x:300+Math.cos(theta)*100,y:250+Math.sin(theta)*100};
    const lb={scale:.8,offx:10,offy:15,elementWidth:800,elementHeight:600,mirrorX,mirrorY};
    const a=toDisplay(lb,start.x,start.y),b=toDisplay(lb,end.x,end.y);
    let index=i;
    if(mirrorX) index=(4-index+8)%8;
    if(mirrorY) index=(8-index)%8;
    assert.equal(headerCountDirection(a,b,800,600,t),t(`headerCount.${directions[index]}`));
  }
  for(const endpoints of [[null,{x:30,y:50}],[{x:3,y:5},{x:4,y:6}],[{x:NaN,y:0},{x:30,y:50}],[{x:-5,y:0},{x:30,y:50}]]) {
    assert.equal(headerCountDirection(...endpoints,800,600,t),null);
  }
  // Actual display transform, not raw camera X/Y; a 90-degree projective map.
  const lb={scale:1,offx:0,offy:0,elementWidth:800,elementHeight:600,mirrorX:false,mirrorY:false,
    sourceToDisplay:[0,-1,600,1,0,0,0,0,1]};
  assert.equal(headerCountDirection(toDisplay(lb,100,100),toDisplay(lb,200,100),800,600,t),t('headerCount.down'));
});

test('thin connection arrows leave Pin centres clear without changing projected locations', async () => {
  const {GuideConnectionOverlay}=await import(compile('components/GuideConnectionOverlay.tsx',{
    '../lib/geometry':geometryUrl,
    '../lib/useSmoothedDetection':dataUrl('export const useSmoothedDetection = value => value;'),
  }));
  const attr=(tag,key)=>Number(tag.match(new RegExp(` ${key}="([^"]+)"`))?.[1]);
  for(const delta of [[200,100],[3,4],[0,0]]) for(const mirrorX of [false,true]) for(const mirrorY of [false,true]) {
    const detection={tracking:'locked',pins:[{id:'6',x:100,y:200,v:true}]};
    const componentPose={tracking:'locked',pins:[{id:'GND',x:100+delta[0],y:200+delta[1],v:true}]};
    const letterbox={scale:.75,offx:10,offy:20,elementWidth:1000,elementHeight:700,mirrorX,mirrorY};
    const props={detection,componentPose,letterbox,width:1000,height:700,boardPinId:'6',componentPinId:'GND',boardDisplayOffsetPx:{x:0,y:0}};
    const before=structuredClone(props);
    const html=renderToStaticMarkup(createElement(GuideConnectionOverlay,props));
    const line=html.match(/<line class="guide-connection-line"[^>]*>/)?.[0];
    const origin=html.match(/<circle class="guide-connection-origin"[^>]*>/)?.[0];
    const target=html.match(/<circle class="guide-connection-target"[^>]*>/)?.[0];
    const from=toDisplay(letterbox,100,200), to=toDisplay(letterbox,100+delta[0],200+delta[1]);
    assert.ok(line && origin && target);
    assert.deepEqual([attr(origin,'cx'),attr(origin,'cy')],[from.x,from.y]);
    assert.deepEqual([attr(target,'cx'),attr(target,'cy')],[to.x,to.y]);
    const distance=Math.hypot(to.x-from.x,to.y-from.y);
    const gap=Math.min(8,distance/3);
    assert.ok(Math.abs(Math.hypot(attr(line,'x1')-from.x,attr(line,'y1')-from.y)-gap)<1e-8);
    assert.ok(Math.abs(Math.hypot(attr(line,'x2')-to.x,attr(line,'y2')-to.y)-gap)<1e-8);
    assert.ok(Math.abs(Math.hypot(attr(line,'x2')-attr(line,'x1'),attr(line,'y2')-attr(line,'y1'))-(distance-2*gap))<1e-8);
    assert.match(html,/markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9"/);
    assert.match(html,/class="guide-connection-arrowhead" d="M 1 1 L 9 5 L 1 9"/);
    assert.deepEqual(props,before);
    assert.equal(renderToStaticMarkup(createElement(GuideConnectionOverlay,{...props,componentPose:{...componentPose,tracking:'searching'}})),'');
  }
});

test('joint labels avoid wiring segments, both bodies, and each other across rotations and mirrors', () => {
  const intersect=(a,b)=>a.x<b.x+b.width && a.x+a.width>b.x && a.y<b.y+b.height && a.y+a.height>b.y;
  for(const [w,h] of [[1280,720],[820,620],[320,380]]) for(let angle=0;angle<360;angle+=15) for(const mx of [false,true]) for(const my of [false,true]) {
    const lb={scale:1,offx:0,offy:0,elementWidth:w,elementHeight:h,mirrorX:mx,mirrorY:my};
    const r=angle*Math.PI/180, radius=w*.18;
    const a=toDisplay(lb,w/2+Math.cos(r)*radius,h/2+Math.sin(r)*radius*.4);
    const b=toDisplay(lb,w/2-Math.cos(r)*radius,h/2-Math.sin(r)*radius*.4);
    const board={target:a,bounds:{x:a.x-35,y:a.y-45,width:70,height:90}};
    const component={target:b,bounds:{x:b.x-25,y:b.y-15,width:50,height:30}};
    const result=layout.placeWiringLabelPair(board,component,w,h);
    if(w>=820) assert.ok(result.board && result.component,`${w}/${angle}/${mx}/${my}`);
    for(const label of Object.values(result).filter(Boolean)) {
      assert.ok(label.x>=8 && label.x+label.width<=w-8);
      assert.ok(label.y>=112 && label.y+label.height<=h-8);
      assert.equal(layout.linkIntersectsLabel(a,b,label),false);
      assert.ok(!intersect(label,board.bounds) && !intersect(label,component.bounds));
    }
    if(result.board && result.component) {
      assert.ok(!intersect(result.board,result.component));
      for(const [label,peer] of [[result.board,result.component],[result.component,result.board]]) {
        assert.equal(layout.linkIntersectsLabel({x:label.startX,y:label.startY},{x:label.endX,y:label.endY},peer,8),false);
      }
    }
  }
  assert.deepEqual(layout.placeWiringLabelPair({target:null,bounds:null},{target:null,bounds:null},1000,700),{board:null,component:null});
});

test('right-side diagrams highlight every project wire without changing progress or electrical mappings', async () => {
  const design=designFor(Object.keys(rows));
  const original=structuredClone(design);
  for(const locale of ['zh-TW','en']) for(const [componentIndex,id] of design.component_ids.entries()) {
    const {t}=localeFixture(locale);
    const wires=design.wiring.filter(w=>w.componentId===id);
    for(const [index,wire] of wires.entries()) {
      const session={...maker.initialMaker().guide,phase:'active',mode:'camera',componentIndex,index};
      const before=structuredClone(session);
      const html=await renderGuide({design,session,locale});
      const row=html.match(/<ol class="component-row-count"[\s\S]*?<\/ol>/)?.[0];
      const location=header.componentHeaderGuideText(id,wire.componentPin,t);
      assert.ok(row?.includes(location.title));
      assert.equal((row.match(/<li/g)??[]).length,rows[id].length);
      assert.equal((row.match(/aria-current="step"/g)??[]).length,1);
      assert.match(row,new RegExp(`aria-current="step"><span class="component-row-number">${location.number}</span><strong>${wire.componentPin}</strong>`));
      assert.ok(!html.includes('①'));
      assert.ok(html.includes(`<h2>${location.name}</h2>`));
      assert.ok(html.includes(location.countFrom));
      assert.deepEqual(session,before);
    }
  }
  assert.deepEqual(design,original);
});
