import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';
import { designFor } from './project_guide_fixture.mjs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const compile = (source, tsx = false) => ts.transpileModule(source, { compilerOptions: {
  target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.CommonJS, ...(tsx ? { jsx:ts.JsxEmit.ReactJSX } : {}),
} }).outputText;
const layoutPath = new URL('../src/lib/circuitLayout.ts',import.meta.url);
const layoutSource = readFileSync(layoutPath,'utf8').replace(/import (\w+) from "([^"]+\.json)";/g,
  (_,name,path) => `const ${name} = ${readFileSync(new URL(path,layoutPath),'utf8')};`);
const layoutHelpers = {};
new Function('exports',compile(layoutSource))(layoutHelpers);
const catalog = JSON.parse(read('../../profiles/component-catalog.json'));
const routeFor = (layout,id) => layout.modules.flatMap(module=>module.routes).find(route=>route.wire.id===id);
const find = (node,predicate) => !node || typeof node !== 'object' ? [] : [
  ...(predicate(node) ? [node] : []),
  ...React.Children.toArray(node.props?.children).flatMap(child=>find(child,predicate)),
  ...find(node.props?.toolbarStart,predicate), ...find(node.props?.toolbarEnd,predicate),
];

function harness() {
  const values=[],refs=[];let slot=0,refSlot=0;
  const react={...React,useState(initial){const index=slot++;if(!(index in values))values[index]=typeof initial==='function'?initial():initial;
    return[values[index],next=>{values[index]=typeof next==='function'?next(values[index]):next;}];},
    useRef(initial){return refs[refSlot++]??={current:initial};}};
  const exports={};
  const modules={react,'react/jsx-runtime':jsx,'../lib/circuitLayout':layoutHelpers,
    '../lib/componentWiringGuides':{guideFor:id=>catalog.modules.find(module=>module.id===id)},
    '../lib/useMaker':{useMakerText:()=>zh=>zh},'../lib/i18n':{useI18n:()=>({tx:value=>typeof value==='string'?value:value['zh-TW']})},
    './CircuitModuleArt':{CircuitModuleArt:'Art'},'./CircuitViewport':{CircuitViewport:'Viewport'}};
  new Function('require','exports',compile(read('../src/components/CircuitDiagram.tsx'),true))(name=>{
    assert.ok(name in modules,'Unmocked import '+name);return modules[name];
  },exports);
  return {render(props){slot=0;refSlot=0;return exports.CircuitDiagram(props);}};
}
const toggle = tree => find(tree,node=>node.type==='button' && node.props.title==='只調整示意圖路徑，不修改接腳或接線進度')[0];
const handle = (tree,id) => find(tree,node=>node.props?.['data-wire-bend']===id)[0];

test('routing adjustments never mutate canonical endpoints, wires, profile pin order or canvas height',()=>{
  const design=designFor(),layout=layoutHelpers.circuitLayout(design),before=JSON.stringify([design,layout]);
  const offsets=Object.fromEntries(design.wiring.map((wire,index)=>[wire.id,{x:index*7-14,y:index%2?9:-9}]));
  const changed=layoutHelpers.adjustCircuitBends(layout,offsets);
  assert.equal(changed.height,layout.height);assert.equal(changed.boardPins,layout.boardPins);
  for(const wire of design.wiring){const base=routeFor(layout,wire.id),route=routeFor(changed,wire.id);
    assert.equal(route.wire,wire);assert.equal(route.boardPin,base.boardPin);assert.equal(route.pin,base.pin);
    assert.equal(route.pin.id,wire.componentPin);assert.equal(route.boardPin.id,wire.boardPin);
  }
  assert.equal(JSON.stringify([design,layout]),before);
});

test('no offsets keep the default routes and independent wires do not move together',()=>{
  const layout=layoutHelpers.circuitLayout(designFor());
  assert.deepEqual(layoutHelpers.adjustCircuitBends(layout,{}),layout);
  const routes=layout.modules[0].routes,wire=routes[1].wire;
  const changed=layoutHelpers.adjustCircuitBends(layout,{[wire.id]:{x:32,y:12}});
  assert.equal(routeFor(changed,wire.id).laneX,routes[1].laneX+32);
  assert.equal(routeFor(changed,wire.id).boardY,routes[1].boardY+12);
  for(const other of routes.filter(route=>route.wire.id!==wire.id))assert.deepEqual(routeFor(changed,other.wire.id),other);
});

test('both module orientations clamp bends away from pins, headings and off-canvas positions',()=>{
  const layout=layoutHelpers.circuitLayout(designFor());
  for(const amount of [-1e6,1e6]) {
    const changed=layoutHelpers.adjustCircuitBends(layout,Object.fromEntries(layout.modules.flatMap(module=>module.routes).map(route=>[route.wire.id,{x:amount,y:amount}])));
    for(const module of changed.modules)for(const route of module.routes){
      assert(route.laneX>=304&&route.laneX<=420);
      if(module.headerAtTop){assert(route.boardY>=module.top+58);assert(route.boardY<=route.pin.y-22);}
      else {assert(route.boardY>=route.pin.y+22);assert(route.boardY<=module.top+module.height-28);}
    }
  }
});

test('invalid numeric offsets never make routes non-finite',()=>{
  const layout=layoutHelpers.circuitLayout(designFor());
  const changed=layoutHelpers.adjustCircuitBends(layout,Object.fromEntries(layout.modules.flatMap(module=>module.routes).map(route=>[route.wire.id,{x:NaN,y:Infinity}])));
  assert.deepEqual(changed,layout);
});

test('a moved divider still joins the real adjusted ground route before its resistor',()=>{
  const design=designFor();design.wiring.find(wire=>wire.componentPin==='ECHO').connectionKind='divider';
  const layout=layoutHelpers.circuitLayout(design),module=layout.modules[0];
  const echo=module.routes.find(route=>route.wire.componentPin==='ECHO'),ground=module.routes.find(route=>route.wire.componentPin==='GND');
  const changed=layoutHelpers.adjustCircuitBends(layout,{[echo.wire.id]:{x:1000,y:11},[ground.wire.id]:{x:1000,y:-10}});
  const e=routeFor(changed,echo.wire.id),g=routeFor(changed,ground.wire.id);
  assert.equal(e.groundY,g.boardY);assert(e.groundX>Math.max(e.laneX,g.laneX));assert(e.groundX<366);
  assert.equal(e.boardPin.id,'GPIO18');assert.equal(g.boardPin.id,'GND_P6');
});

test('adjustment mode is explicit, leaves existing guide selection untouched and offers reset',()=>{
  const design=designFor(),h=harness(),wire=design.wiring[0];let selected=0;
  const props={design,workspace:true,activeId:wire.id,onSelect(){selected++;}};
  let tree=h.render(props);assert.equal(find(tree,node=>node.props?.['data-wire-bend']).length,0);
  toggle(tree).props.onClick();tree=h.render(props);
  assert.equal(toggle(tree).props['aria-pressed'],true);
  assert.equal(find(tree,node=>node.props?.['data-wire-bend']).length,4);
  const routes=find(tree,node=>node.props?.['data-circuit-wire']);
  assert(routes.every(route=>find(route,node=>node.type==='path'&&Boolean(node.props.onPointerDown)).length===2),'visible wires and their wide hit areas are draggable');
  assert.equal(find(tree,node=>node.props?.['aria-label']==='恢復預設走線')[0].props.disabled,true);
  assert.equal(selected,0);
});

test('keyboard arrow / Home controls move only bends, including the active guide wire',()=>{
  const design=designFor(),h=harness(),wire=design.wiring[0],props={design,workspace:true,activeId:wire.id};
  toggle(h.render(props)).props.onClick();let tree=h.render(props),bend=handle(tree,wire.id),x=bend.props.cx,y=bend.props.cy;
  bend.props.onKeyDown({key:'ArrowRight',shiftKey:false,preventDefault(){},stopPropagation(){}});
  tree=h.render(props);bend=handle(tree,wire.id);assert.equal(bend.props.cx,x+8);assert.equal(bend.props.cy,y);
  bend.props.onKeyDown({key:'Home',shiftKey:false,preventDefault(){},stopPropagation(){}});
  tree=h.render(props);assert.equal(handle(tree,wire.id).props.cx,x);assert.equal(handle(tree,wire.id).props.cy,y);
});

test('pointer dragging accounts for SVG zoom / scroll transform and never calls pin selection',()=>{
  const design=designFor(),h=harness(),wire=design.wiring.find(w=>w.componentPin==='TRIG');let selected=0;
  const props={design,workspace:true,activeId:wire.id,onSelect(){selected++;}},before=JSON.stringify(design);
  toggle(h.render(props)).props.onClick();const bend=handle(h.render(props),wire.id),x=bend.props.cx,y=bend.props.cy;
  let captured=null;
  const target={ownerSVGElement:{getScreenCTM:()=>({inverse:()=>({})}),createSVGPoint:()=>({x:0,y:0,matrixTransform(){return{x:(this.x-10)/.5,y:(this.y-20)/.5};}})},
    setPointerCapture:id=>{captured=id;},hasPointerCapture:id=>captured===id,releasePointerCapture(){captured=null;}};
  const event=(clientX,clientY)=>({button:0,isPrimary:true,pointerId:7,clientX,clientY,currentTarget:target,preventDefault(){},stopPropagation(){}});
  bend.props.onPointerDown(event(x*.5+10,y*.5+20));assert.equal(captured,7);
  bend.props.onPointerMove(event(x*.5+30,y*.5+16));
  let tree=h.render(props),moved=handle(tree,wire.id);assert.equal(moved.props.cx,x+40);assert.equal(moved.props.cy,y-8);
  moved.props.onPointerUp(event(x*.5+30,y*.5+16));assert.equal(captured,null);assert.equal(selected,0);
  assert.equal(JSON.stringify(design),before);
  find(tree,node=>node.props?.['aria-label']==='恢復預設走線')[0].props.onClick();tree=h.render(props);
  assert.equal(handle(tree,wire.id).props.cx,x);assert.equal(handle(tree,wire.id).props.cy,y);
});

test('a new project revision starts with defaults and previous bends cannot leak across pin changes',()=>{
  const design=designFor(),h=harness(),wire=design.wiring[0],props={design,workspace:true,activeId:wire.id};
  toggle(h.render(props)).props.onClick();let bend=handle(h.render(props),wire.id),x=bend.props.cx;
  bend.props.onKeyDown({key:'ArrowRight',shiftKey:true,preventDefault(){},stopPropagation(){}});
  assert.equal(handle(h.render(props),wire.id).props.cx,x+24);
  const next={...design,revision:design.revision+1};assert.equal(handle(h.render({...props,design:next}),wire.id).props.cx,x);
});

test('compact historical preview does not expose adjustment controls or drag handles',()=>{
  const h=harness(),tree=h.render({design:designFor(),compactPreview:true});
  assert.equal(find(tree,node=>node.type==='button').length,0);
  assert.equal(find(tree,node=>node.props?.['data-wire-bend']).length,0);
});
