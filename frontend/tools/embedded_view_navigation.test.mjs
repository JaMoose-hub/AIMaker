import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const read=p=>readFileSync(new URL(p,import.meta.url),'utf8');

test('one pure App selector is passed to each view instead of the outer toolbar',()=>{
  const source=read('../src/App.tsx');
  const tree=ts.createSourceFile('App.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const tags=[]; const selectors=[];
  function visit(node){
    if(ts.isJsxSelfClosingElement(node)||ts.isJsxOpeningElement(node)) {
      tags.push(node); if(node.tagName.getText(tree)==='ImageViewControls') selectors.push(node);
    }
    ts.forEachChild(node,visit);
  }
  visit(tree); assert.equal(selectors.length,1);
  for(const [name,prop] of [['VideoView','viewNavigation'],['GpioPhotoWorkspace','viewControls'],['StepDiagramView','viewControls'],['DiagramInspectionView','viewControls']]) {
    const el=tags.find(n=>n.tagName.getText(tree)===name);
    assert.ok(el); assert.equal(el.attributes.properties.find(n=>n.name?.getText(tree)===prop).initializer.expression.getText(tree),'imageViewControls');
  }
  const video=tags.find(n=>n.tagName.getText(tree)==='VideoView');
  const toolbar=video.attributes.properties.find(n=>n.name?.getText(tree)==='viewControl').getText(tree);
  assert.doesNotMatch(toolbar,/ImageViewControls/);
  assert.match(toolbar,/createPortal\(renderCameraTools/,'existing settings owner is retained');
  assert.match(source,/disabled=\{calibrateOpen \|\| liveCamera.pending \|\| photoOperationBusy\}/);
});

test('empty outer toolbars consume no space, while legacy controls and live legends remain available',()=>{
  const css=read('../src/assistant.css');
  assert.match(css,/\.video-control-toolbar:empty\s*\{\s*display:\s*none/);
  assert.match(css,/\.video-control-toolbar\s*\{[^}]*display:\s*flex/);
  const live=read('../src/components/LiveCameraOverlay.css');
  assert.match(live,/\.live-camera-toolbar\s*\{[^}]*position:absolute/);
  assert.match(live,/\.live-camera-toolbar > \.image-view-controls\s*\{[^}]*pointer-events:auto/);
  assert.match(live,/\.video-shell.has-view-navigation \.video-legend\s*\{\s*top:58px/);
  assert.match(live,/\.live-camera-toolbar > \.image-view-controls\s*\{\s*flex-basis:100%/,'narrow controls wrap rather than clip');
});
