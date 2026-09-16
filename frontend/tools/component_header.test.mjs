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

test('both module overlays show one compact line and preserve ordinals through every mirror', async () => {
  for(const locale of ['zh-TW','en']) {
    const {t,i18n}=localeFixture(locale);
    const {ComponentPinOverlay}=await import(compile('components/ComponentPinOverlay.tsx',{
      '../lib/componentHeaderGuide':componentHeaderUrl,'../lib/wiringLabelLayout':layoutUrl,
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
      assert.equal((callout.match(/<text/g)??[]).length,1);
      assert.match(callout,/width="228" height="32"/);
      assert.ok(!callout.includes('component-pin-callout-hint'));
      assert.ok(!html.includes('component-header-start'));
      assert.ok(!html.includes('①'));
      assert.equal(text.name,id === 'hc-sr04' ? 'HC-SR04' : 'MRD-TF240');
      assert.ok(!callout.includes('超音波') && !callout.includes('螢幕'));
      assert.deepEqual(pose,before);
      const noSpace=renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,guideLabel:null}));
      assert.ok(!noSpace.includes('class="component-pin-callout"'));
      assert.ok(noSpace.includes('component-guidance-halo'));
      const missingStart=renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,pose:{...pose,pins:pose.pins.map((p,i)=>({...p,v:i!==0}))}}));
      assert.ok(!missingStart.includes('component-header-start'));
      for(const extra of [{guidanceSuspended:true},{pose:{...pose,tracking:'searching'}}]) assert.equal(renderToStaticMarkup(createElement(ComponentPinOverlay,{...props,...extra})),'');
    }
    const legacy=renderToStaticMarkup(createElement(ComponentPinOverlay,{pose:{component_id:'photoresistor-module',tracking:'locked',pins:[{id:'GND',x:300,y:250,v:true}]},letterbox:{scale:1,offx:0,offy:0,elementWidth:1000,elementHeight:700},width:1000,height:700,targetPinId:'GND'}));
    assert.match(legacy,/width="132" height="44"/);
    assert.ok(legacy.includes(t('componentGuide.countFromAo')));
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
