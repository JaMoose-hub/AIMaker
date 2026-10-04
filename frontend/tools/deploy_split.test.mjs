import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const code=ts.transpileModule(readFileSync(new URL('../src/lib/deploySplit.ts',import.meta.url),'utf8'),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {DEPLOY_SPLIT_STORAGE_KEY,DEPLOY_SPLIT_HANDLE_WIDTH,DEPLOY_COLUMN_MIN_WIDTH,
  deploySplitGeometry,deploySplitRatioForLeft,dragDeploySplitRatio,keyDeploySplitRatio}
  =await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-9,`${actual} != ${expected}`);

test('deployment resizing has its own preference and fits two minimum-width columns',()=>{
  assert.equal(DEPLOY_SPLIT_STORAGE_KEY,'boardvision.deploy-split.v1');
  assert.equal(DEPLOY_SPLIT_HANDLE_WIDTH,18);
  assert.equal(DEPLOY_COLUMN_MIN_WIDTH,360);
  const threshold=DEPLOY_COLUMN_MIN_WIDTH*2+DEPLOY_SPLIT_HANDLE_WIDTH;
  assert.equal(deploySplitGeometry(threshold-1,null).sideBySide,false);
  const at=deploySplitGeometry(threshold,null);
  assert.equal(at.sideBySide,true);
  assert.equal(at.available,720);
  assert.equal(at.min,360);
  assert.equal(at.max,360);
  assert.equal(at.left,360);
});

test('default columns share actual available pane width equally',()=>{
  const geometry=deploySplitGeometry(1218,null);
  assert.equal(geometry.available,1200);
  assert.equal(geometry.left,600);
  assert.equal(geometry.available-geometry.left,600);
  assert.equal(geometry.min,360);
  assert.equal(geometry.max,840);
});

test('saved preference clamps to minimum readable columns after AI pane resizing',()=>{
  assert.equal(deploySplitGeometry(1218,.7).left,840);
  const reduced=deploySplitGeometry(918,.7);
  assert.equal(reduced.left,540);
  assert.equal(reduced.available-reduced.left,360);
  assert.equal(deploySplitGeometry(1218,-1).left,360);
  assert.equal(deploySplitGeometry(1218,2).left,840);
});

test('invalid measurements and preferences never create negative or non-finite tracks',()=>{
  for(const width of [-5,0,10,NaN,Infinity,-Infinity]) {
    const geometry=deploySplitGeometry(width,NaN);
    assert.equal(geometry.sideBySide,false);
    for(const name of ['available','min','max','left']) {
      assert.ok(Number.isFinite(geometry[name]));
      assert.ok(geometry[name]>=0);
    }
    assert.ok(geometry.left<=geometry.available);
  }
  assert.equal(deploySplitGeometry(1218,NaN).left,600);
  assert.equal(deploySplitGeometry(1218,Infinity).left,600);
  assert.equal(deploySplitRatioForLeft(NaN,1218),.5);
  assert.equal(deploySplitRatioForLeft(300,0),.5);
});

test('dragging moves only the ratio and stops at column minimums',()=>{
  near(dragDeploySplitRatio(600,100,220,1218),.6);
  near(dragDeploySplitRatio(600,100,-1000,1218),.3);
  near(dragDeploySplitRatio(600,100,3000,1218),.7);
  const ratio=dragDeploySplitRatio(600,100,220,1218);
  assert.equal(deploySplitGeometry(1218,ratio).left,720);
});

test('keyboard arrows use fine and coarse steps without violating minimums',()=>{
  near(keyDeploySplitRatio('ArrowLeft',false,600,1218),576/1200);
  near(keyDeploySplitRatio('ArrowRight',false,600,1218),624/1200);
  near(keyDeploySplitRatio('ArrowLeft',true,600,1218),520/1200);
  near(keyDeploySplitRatio('ArrowRight',true,600,1218),680/1200);
  near(keyDeploySplitRatio('ArrowLeft',false,360,1218),.3);
  near(keyDeploySplitRatio('ArrowRight',true,840,1218),.7);
});

test('Home and End select boundaries; stacked panes and unrelated keys do nothing',()=>{
  near(keyDeploySplitRatio('Home',false,600,1218),.3);
  near(keyDeploySplitRatio('End',false,600,1218),.7);
  assert.equal(keyDeploySplitRatio('Tab',false,600,1218),null);
  assert.equal(keyDeploySplitRatio('Enter',false,600,1218),null);
  for(const key of ['Home','End','ArrowLeft','ArrowRight']) {
    assert.equal(keyDeploySplitRatio(key,false,250,737),null);
  }
});
