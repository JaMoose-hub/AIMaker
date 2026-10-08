import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const exports={};
new Function('exports',ts.transpileModule(readFileSync(new URL('../src/lib/recognitionStyle.ts',import.meta.url),'utf8'),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(exports);
const {guideConnectionPath,guideConnectionPoints}=exports;
const parse=path=>{
  const values=(path.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)??[]).map(Number);
  return Array.from({length:values.length/2},(_,i)=>({x:values[i*2],y:values[i*2+1]}));
};

test('all directions use orthogonal legs inside endpoint bounds without mutating inputs',()=>{
  for(const dx of [-300,-5,0,5,300])for(const dy of [-300,-5,0,5,300]) {
    const from={x:400,y:400},to={x:400+dx,y:400+dy},before=structuredClone([from,to]);
    const points=guideConnectionPoints(from,to);
    const gap=Math.min(8,Math.max(Math.abs(dx),Math.abs(dy))/3);
    assert.ok(points.length>=1&&points.length<=4);
    const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
    assert.ok(Math.abs(distance(points[0],from)-gap)<1e-8);
    assert.ok(Math.abs(distance(points.at(-1),to)-gap)<1e-8);
    for(const [i,point] of points.entries()) {
      assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y));
      assert.ok(point.x>=Math.min(from.x,to.x)&&point.x<=Math.max(from.x,to.x));
      assert.ok(point.y>=Math.min(from.y,to.y)&&point.y<=Math.max(from.y,to.y));
      if(i)assert.ok((point.x===points[i-1].x)!==(point.y===points[i-1].y));
    }
    assert.deepEqual([from,to],before);
  }
});

test('a diagonal guide uses exactly two right-angle turns, not a diagonal shortcut',()=>{
  for(const [from,to] of [[{x:20,y:40},{x:420,y:160}],[{x:420,y:400},{x:300,y:40}]]) {
    const points=guideConnectionPoints(from,to);assert.equal(points.length,4);
    for(let i=1;i<points.length-1;i++) {
      const a=points[i-1],b=points[i],c=points[i+1];
      assert.equal(Math.abs((b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y)),0);
    }
  }
});

test('photo zoom keeps the same route and pin clearance in display pixels',()=>{
  const from={x:100,y:200},to={x:800,y:500};
  for(const scale of [.25,.75,1,1.5]) {
    const photo=guideConnectionPoints(from,to,8/scale).map(p=>({x:p.x*scale,y:p.y*scale}));
    const display=guideConnectionPoints({x:from.x*scale,y:from.y*scale},{x:to.x*scale,y:to.y*scale});
    assert.equal(photo.length,display.length);
    photo.forEach((p,i)=>{assert.ok(Math.abs(p.x-display[i].x)<1e-8);assert.ok(Math.abs(p.y-display[i].y)<1e-8);});
  }
});

test('degenerate contacts and invalid inputs do not invent a detour or invalid SVG',()=>{
  assert.equal(guideConnectionPath({x:10,y:20},{x:10,y:20}),'M 10 20');
  for(const value of [NaN,Infinity,-Infinity])assert.equal(guideConnectionPath({x:value,y:20},{x:100,y:200}),'');
  const points=guideConnectionPoints({x:10,y:20},{x:100,y:200},-5);
  assert.deepEqual(points[0],{x:10,y:20});assert.deepEqual(points.at(-1),{x:100,y:200});
});

test('header approach follows rotation and both mirrors, with a perpendicular inward final leg',()=>{
  for(let angle=0;angle<360;angle+=15)for(const mirrorX of [false,true])for(const mirrorY of [false,true])for(const headerAtTop of [false,true]) {
    const r=angle*Math.PI/180;
    const transform=p=>({x:700+(mirrorX?-1:1)*(p.x*Math.cos(r)-p.y*Math.sin(r)),
      y:700+(mirrorY?-1:1)*(p.x*Math.sin(r)+p.y*Math.cos(r))});
    const outline=[[-120,-60],[120,-60],[120,60],[-120,60]].map(([x,y])=>transform({x,y}));
    const to=transform({x:20,y:headerAtTop?-60:60}),from=transform({x:-380,y:-200});
    const target={outline,headerAtTop},before=structuredClone([from,to,target]);
    const points=guideConnectionPoints(from,to,8,target);
    const outward=transform({x:20,y:(headerAtTop?-60:60)+(headerAtTop?-1:1)});
    const normal={x:outward.x-to.x,y:outward.y-to.y};
    const end=points.at(-1),entry=points.at(-2);
    assert.ok(Math.abs((end.x-to.x)*normal.x+(end.y-to.y)*normal.y-8)<1e-7);
    assert.ok((entry.x-end.x)*normal.x+(entry.y-end.y)*normal.y>0);
    assert.ok(Math.abs((entry.x-end.x)*normal.y-(entry.y-end.y)*normal.x)<1e-7);
    const edgeA=outline[headerAtTop?0:3],edgeB=outline[headerAtTop?1:2];
    assert.ok(Math.abs((entry.x-end.x)*(edgeB.x-edgeA.x)+(entry.y-end.y)*(edgeB.y-edgeA.y))<1e-6);
    for(let i=1;i<points.length-1;i++) {
      const a=points[i-1],b=points[i],c=points[i+1];
      const product=(b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y);
      assert.ok(Math.abs(product)<1e-6);
    }
    assert.deepEqual([from,to,target],before);
  }
});

test('perspective header entry stays outside the board and photo zoom preserves the route',()=>{
  const from={x:100,y:100},to={x:730,y:500};
  const target={outline:[{x:600,y:300},{x:900,y:330},{x:870,y:520},{x:620,y:490}],headerAtTop:false};
  const route=guideConnectionPoints(from,to,8,target);
  const entry=route.at(-2),normal={x:(entry.x-to.x)/Math.hypot(entry.x-to.x,entry.y-to.y),
    y:(entry.y-to.y)/Math.hypot(entry.x-to.x,entry.y-to.y)};
  assert.ok(target.outline.every(p=>(entry.x-p.x)*normal.x+(entry.y-p.y)*normal.y>0));
  for(const scale of [.25,.75,1.5]) {
    const scaled=p=>({x:p.x*scale,y:p.y*scale});
    const display=guideConnectionPoints(scaled(from),scaled(to),8,{...target,outline:target.outline.map(scaled)});
    const photo=guideConnectionPoints(from,to,8/scale,target).map(scaled);
    photo.forEach((p,i)=>{assert.ok(Math.abs(p.x-display[i].x)<1e-7);assert.ok(Math.abs(p.y-display[i].y)<1e-7);});
  }
});

test('missing or degenerate header geometry uses the prior route, not a guessed downward side',()=>{
  const from={x:20,y:40},to={x:420,y:160},fallback=guideConnectionPath(from,to);
  for(const outline of [[],[{x:1,y:2}],Array(4).fill({x:20,y:20}),[{x:NaN,y:10},{x:20,y:10},{x:20,y:20},{x:10,y:20}]]) {
    assert.equal(guideConnectionPath(from,to,8,{outline,headerAtTop:false}),fallback);
  }
});

test('soft bends preserve exact contacts, final approach and zoom while rounding only the corners',()=>{
  const from={x:100,y:100},to={x:800,y:500};
  const target={outline:[{x:700,y:400},{x:900,y:400},{x:900,y:500},{x:700,y:500}],headerAtTop:false};
  const path=guideConnectionPath(from,to,8,target),drawn=parse(path),route=guideConnectionPoints(from,to,8,target);
  assert.match(path,/ Q /);assert.equal((path.match(/ Q /g)??[]).length,3);
  assert.deepEqual(drawn[0],route[0]);assert.deepEqual(drawn.at(-1),route.at(-1));
  assert.equal(drawn.at(-2).x,drawn.at(-1).x);assert.ok(drawn.at(-2).y>drawn.at(-1).y);
  const minX=Math.min(...route.map(p=>p.x)),maxX=Math.max(...route.map(p=>p.x));
  const minY=Math.min(...route.map(p=>p.y)),maxY=Math.max(...route.map(p=>p.y));
  assert.ok(drawn.every(p=>p.x>=minX&&p.x<=maxX&&p.y>=minY&&p.y<=maxY));
  for(const scale of [.25,.75,1.5]) {
    const scaled=p=>({x:p.x*scale,y:p.y*scale});
    const display=parse(guideConnectionPath(scaled(from),scaled(to),8,{...target,outline:target.outline.map(scaled)}));
    const photo=parse(guideConnectionPath(from,to,8/scale,target)).map(scaled);
    assert.equal(photo.length,display.length);
    photo.forEach((p,i)=>{assert.ok(Math.abs(p.x-display[i].x)<1e-7);assert.ok(Math.abs(p.y-display[i].y)<1e-7);});
  }
  assert.doesNotMatch(guideConnectionPath({x:10,y:20},{x:100,y:20}),/Q/);
});
