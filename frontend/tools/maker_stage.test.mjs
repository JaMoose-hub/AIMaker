// Exercise the real App render tree and navigation handlers, not a copied layout.
// Child components and external hooks are inert; no Pi, camera or AI calls occur.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import ts from 'typescript';
import {maker, designFor, board} from './project_guide_fixture.mjs';

function helper(path,imports={}) {
  const compiled=ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},
  }).outputText;
  const exports={};
  new Function('require','exports',compiled)(name=>{
    if(name in imports)return imports[name];
    throw Error(`Unmocked helper import: ${name}`);
  },exports);
  return exports;
}
const photoWiring=helper('../src/lib/photoWiring.ts');
const photoWorkspace=helper('../src/lib/gpioPhotoWorkspace.ts',{'./photoWiring':photoWiring,'./maker':maker});

const code = ts.transpileModule(readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'), {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React},
}).outputText;
const fail = () => assert.fail('Rendering or navigation must not start hardware/cloud work');
function nodes(tree, predicate) {
  const found = [];
  function visit(node) {
    if (!React.isValidElement(node)) return;
    if (predicate(node)) found.push(node);
    for (const slot of ['children', 'navigation', 'left', 'assistant', 'debugTools', 'viewNavigation', 'sourceControl', 'visibilityControl']) {
      const value = node.props[slot];
      if (React.isValidElement(value) || Array.isArray(value)) React.Children.forEach(value, visit);
    }
  }
  visit(tree);
  return found;
}
function harness({state = maker.initialMaker(), locale = 'en', boardId = 'raspberry-pi-5', displayMode = 'standard'} = {}) {
  const values = [], debugCalls = [], sourceSelections=[];
  let cursor = 0, current = state, demoOpen = false;
  // These are App's local state slots; the external hooks below have no effects.
  const initial = {0: {board_id: boardId, camera_source: 'device', runtime_revision: 1}, 1: board, 14: displayMode};
  const react = {...React, useEffect() {}, useCallback: fn => fn, useMemo: fn => fn(),
    useRef: value => ({current: value}), useSyncExternalStore: (_subscribe, snapshot) => snapshot(),
    useState(value) {
      const i = cursor++;
      if (!(i in values)) values[i] = i in initial ? initial[i] : typeof value === 'function' ? value() : value;
      return [values[i], next => { values[i] = typeof next === 'function' ? next(values[i]) : next; }];
    },
  };
  const setState = next => {current = typeof next === 'function' ? next(current) : next;};
  const imports = {
    react,
    './lib/useMaker': {useMaker: () => ({state: current, setState, saved: true}), useMakerText: () => (zh, en) => locale === 'en' ? en : zh},
    './lib/useMakerAI': {useMakerAI: () => ({aiOptions:{},newProject: async () => {setState(maker.newMakerProject); return true;}})},
    './lib/assistant': {useAssistant: () => ({record:null, demoOpen, setDemoOpen:value=>{demoOpen=value;}, busy:false, prepareConversation:async()=>({id:'new'}), activateConversation:()=>{}, archiveWiring:async()=>true})},
    './lib/maker': maker,
    './lib/gpioPhotoWorkspace': photoWorkspace,
    './lib/useGpioPhotoCapture':{useGpioPhotoCapture:()=>({busy:false,needsResume:false,error:null,capture:fail,resume:fail})},
    './lib/useLiveCamera':{useLiveCamera:(config,onConfig)=>({pending:false,error:'',
      status:{kind:config?.camera_source==='phone'?'phone':'webcam',ready:true,error:null,runtime_revision:config?.runtime_revision},
      select:async kind=>{sourceSelections.push(kind);onConfig({...config,camera_source:kind==='phone'?'phone':'device',runtime_revision:config.runtime_revision+1});return true;},
      reconnect:fail})},
    './lib/i18n': {useI18n: () => ({t: key => key, tx: v => typeof v === 'string' ? v : v[locale], setLocale: fail, applyDefaultLocale: fail})},
    './lib/displayMode': {isDisplayOnlyMode: mode => mode !== 'standard', isOpticalHudMode: mode => mode === 'optical-hud-demo'},
    './lib/useGlassesStream': {useGlassesStream: () => ({status: null, pending: false, stop: fail})},
    './lib/debugSessions': {useDebugSession: (id, enabled) => {debugCalls.push({id, enabled}); return {record: null, resetVersion: 0};}},
    './lib/wsClient': {wsClient: {subscribe: fail, getSnapshot: () => ({runtime: null})}},
  };
  const require = name => {
    if (name in imports) return imports[name];
    if (name.startsWith('./components/')) return new Proxy({}, {get: (_target, key) => key});
    if (name.endsWith('.css')) return {};
    return new Proxy({}, {get: () => fail});
  };
  const module = {};
  const document={activeElement:null,getElementById:()=>null};
  new Function('React', 'require', 'exports', 'document', code)(React, require, module,document);
  const render = () => {cursor = 0; return module.default();};
  const find = (tree, type) => nodes(tree, n => n.type === type);
  const navigate = stage => {
    const nav = nodes(render(), n => n.type === 'nav')[0];
    React.Children.toArray(nav.props.children).find(n => n.key === `.$${stage}`).props.onClick();
    return render();
  };
  return {render, find, navigate, state: () => current, debugCalls,sourceSelections};
}

test('unified wiring keeps one camera and guide controls without a design demo entry', () => {
  const h = harness({state:{...maker.initialMaker(),stage:'guide',design:designFor()}});
  const tree = h.render(), camera = h.find(tree, 'VideoView');
  assert.equal(camera.length, 1);
  const stage = h.find(tree, 'GuidePaneLayout')[0];
  assert.match(stage.props.className, /assistant-wiring-stage/);
  assert.equal(stage.props.resizable, false, 'no divider while the guide is hidden');
  assert.equal(stage.props.stacked, true);
  assert.equal(h.find(tree, 'WiringWorkspace')[0].props.guideOnly, true);
  assert.equal(nodes(tree, n => n.props.className==='assistant-demo-entry').length, 0);
  const dock=nodes(tree,n=>n.props.className==='floating-guide-dock')[0];
  assert.ok(dock,'the hidden floating guide retains its one accessible expand action');
  assert.equal(nodes(dock,n=>n.props.className?.includes('guide-visibility-toggle')).length,1);
  assert.equal(nodes(camera[0].props.viewControl(null),n=>n.props.className?.includes('guide-visibility-toggle')).length,0,
    'floating guide actions do not duplicate the camera toolbar');
  const before = h.state();
  const toggle = nodes(dock, n => n.props.className?.includes('guide-visibility-toggle'))[0];
  toggle.props.onClick();
  assert.equal(h.state(), before, 'collapsing only changes local visibility');
  assert.equal(h.find(h.render(), 'VideoView').length, 1);
  assert.equal(h.find(h.render(), 'GuidePaneLayout')[0].props.resizable, false, 'the floating guide never creates a resizing divider');
  const updatedControls = h.find(h.render(), 'ProjectGuidePanel')[0].props.visibilityControl;
  nodes(updatedControls, n => n.props.className?.includes('guide-visibility-toggle'))[0].props.onClick();
  assert.equal(h.find(h.render(), 'GuidePaneLayout')[0].props.resizable, false, 'hiding the guide restores the full camera area');
});

test('design demo entry belongs only to stage 01 for both concept and blueprint views', () => {
  for (const locale of ['en','zh-TW']) for (const designView of ['concept','blueprint']) {
    const h=harness({locale,state:{...maker.initialMaker(),design:designFor(),designView}});
    const tree=h.render(),entries=nodes(tree,n=>n.props.className==='assistant-demo-entry');
    assert.equal(entries.length,1);
    assert.equal(entries[0].props.children,locale==='en'?'Try AI design demo':'體驗 AI 設計 Demo');
    assert.equal(nodes(tree,n=>n.props.className==='assistant-design-tools').length,1);
    for(const stage of ['guide','deploy']) {
      const next=h.navigate(stage);
      assert.equal(nodes(next,n=>n.props.className==='assistant-demo-entry').length,0);
      assert.equal(nodes(h.find(next,'VideoView')[0].props.viewControl(null),n=>n.props.className==='assistant-demo-entry').length,0);
    }
    const before=h.state();entries[0].props.onClick();
    assert.equal(h.find(h.render(),'DemoWorkspace').length,1,'the original demo workspace still opens');
    assert.equal(h.state(),before,'opening demo does not replace the project or wiring progress');
  }
});

test('phone connection docks left of Pi; view navigation shares the camera and one explicit source owner', async () => {
  const design = designFor(), guide = {...maker.emptyGuide(), mode:'2d', confirmed:{kept:{mode:'camera',signature:'kept',at:'fixture'}}};
  const h = harness({state:{...maker.initialMaker(),stage:'guide',design,guide,code:'# kept'}});
  let tree = h.render();
  const cameraBefore=h.find(tree,'VideoView')[0];
  assert.equal(cameraBefore.props.viewNavigation.type,'ImageViewControls');
  const slot = nodes(cameraBefore.props.sourceControl,n=>n.props.className==='image-source-host')[0];
  assert.ok(slot);
  assert.equal(nodes(cameraBefore.props.sourceControl,n=>n.props.className==='mobile-toolbar-slot mobile-header-slot').length,0);
  const connectionGroup=h.find(tree,'DeviceConnectionGroups')[0];
  const connections=[connectionGroup.props.phone,connectionGroup.props.pi];
  assert.equal(connections[0].props.className,'mobile-toolbar-slot mobile-header-slot');assert.equal(connections[1].type,'PiConnectionControl');
  const host = {id:'phone-toolbar'},headerHost={id:'phone-header'}; slot.ref(host);connections[0].ref(headerHost);
  tree=h.render();
  let workspace=h.find(tree,'UnifiedAssistant')[0].props.mobileWorkspace;
  assert.equal(workspace.trigger,headerHost); assert.equal(workspace.controls,host); assert.equal(workspace.canShow,true);
  await workspace.onShow(true); tree=h.render();
  const camera=h.find(tree,'VideoView')[0];
  assert.equal(camera.props.config.camera_source,'phone');assert.equal(camera.props.alternateView,null);
  assert.equal(camera.props.sourceUnavailable,false);assert.deepEqual(h.sourceSelections,['phone']);
  const debugProps = currentTree => h.find(currentTree,'DebugPage')[0].props.assistant({context:{}}).props;
  assert.equal(debugProps(tree).webcamReady,true,'the common photo service can capture the selected ready phone source');
  assert.equal(h.find(camera.props.sourceControl,'GpioCaptureAction')[0].props.source,'phone','capture uses the same selected source owner');
  assert.equal(h.state().design,design);assert.equal(h.state().guide.confirmed,guide.confirmed);assert.equal(h.state().code,'# kept');
  assert.equal(h.state().guide.mode,'camera');
  workspace=h.find(tree,'UnifiedAssistant')[0].props.mobileWorkspace;
  assert.equal(workspace.showing,true);await workspace.onShow(false);tree=h.render();
  assert.equal(h.find(tree,'VideoView')[0].props.alternateView,null);
  assert.equal(h.find(tree,'VideoView')[0].props.config.camera_source,'device');assert.deepEqual(h.sourceSelections,['phone','webcam']);
  assert.equal(debugProps(tree).webcamReady,true);
  assert.equal(h.find(tree,'VideoView').length,1);
  for(const stage of ['design','deploy','guide']) {
    tree=h.navigate(stage);workspace=h.find(tree,'UnifiedAssistant')[0].props.mobileWorkspace;
    assert.equal(workspace.trigger,headerHost,'connection entry stays in the global header');
    assert.equal(workspace.controls,stage==='guide'?host:null);
    assert.equal(h.find(tree,'UnifiedAssistant').length,1,'do not remount a duplicate phone controller');
  }
});

for (const locale of ['en', 'zh-TW']) test(`New project → 02 uses the empty guide, never 03 or legacy tools (${locale})`, async () => {
  const design = designFor();
  const h = harness({locale, state: {...maker.initialMaker(), design, code: 'previous code', debug: {panelOpen: true, caseId: 'old'}}});
  const assistant = h.find(h.render(), 'UnifiedAssistant')[0];
  assert.equal(await assistant.props.onNewProject(), true);
  assert.equal(h.state().design, null);
  const tree = h.navigate('guide');
  assert.equal(nodes(tree,n=>n.props.className?.includes('maker-wiring-full-width')).length,1);
  for (const component of ['PiDeployPanel', 'WiringGuidePanel', 'DebugPage', 'aside']) assert.equal(h.find(tree, component).length, 0, component);
  assert.equal(h.find(tree, 'VideoView').length, 1);
  assert.equal(h.find(tree, 'GuidePaneLayout')[0].props.resizable, false);
  assert.equal(h.debugCalls.at(-1).enabled, false);
  const empty = nodes(tree, n => n.props.className?.includes('maker-guide-empty'))[0];
  assert.equal(empty.props.hidden, false);
  assert.equal(h.find(empty, 'h2')[0].props.children, locale === 'en' ? 'No confirmed project yet' : '尚未確認作品');
  const before = h.state();
  nodes(empty,n=>n.type==='button'&&n.props.className==='guide-primary-action')[0].props.onClick();
  assert.equal(h.state().stage, 'design');
  for (const field of ['design', 'candidate', 'code', 'guide', 'conversation']) assert.equal(h.state()[field], before[field]);
  assert.equal(h.find(h.render(), 'PiDeployPanel').length, 0);
  assert.equal(h.find(h.render(), 'UnifiedAssistant').length, 1);
});

test('02 after restoring an empty project or with an unconfirmed preview cannot show deployment or legacy wiring', () => {
  for (const state of [maker.restoreMaker(JSON.stringify({...maker.initialMaker(), stage: 'guide'})),
    {...maker.initialMaker(), stage: 'guide', candidate: designFor()}]) {
    const h = harness({state});
    const tree = h.navigate('guide');
    assert.equal(nodes(tree,n=>n.props.className?.includes('maker-wiring-full-width')).length,1);
    assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 1);
    assert.equal(h.find(tree, 'PiDeployPanel').length, 0);
    assert.equal(h.find(tree, 'WiringGuidePanel').length, 0);
    for (const field of ['design', 'candidate', 'code', 'guide']) assert.equal(h.state()[field], state[field]);
  }
});

test('03 is the only Maker stage that renders one deployment panel, with or without a project', () => {
  for (const design of [null, designFor()]) {
    const h = harness({state: {...maker.initialMaker(), design, code: 'manual draft'}});
    for (const stage of ['design', 'guide', 'deploy', 'guide', 'design']) {
      const tree = h.navigate(stage), panels = h.find(tree, 'PiDeployPanel');
      assert.equal(panels.length, stage === 'deploy' ? 1 : 0, stage);
      if (panels.length) {
        assert.equal(panels[0].props.project, design ?? undefined);
        assert.equal(panels[0].props.draft, design ? 'manual draft' : undefined);
      }
    }
  }
});

test('confirmed-project wiring, AI and guide state remain bound to the original project', () => {
  const design = designFor(), guide = {...maker.emptyGuide(), index: 2};
  const h = harness({state: {...maker.initialMaker(), design, guide, debug: {panelOpen: true}}});
  const tree = h.navigate('guide');
  const workspace = h.find(tree, 'WiringWorkspace')[0];
  assert.equal(workspace.props.design, design);
  assert.equal(workspace.props.guide, guide);
  assert.equal(workspace.props.guideOnly, true);
  assert.equal(workspace.props.assistant, null);
  assert.equal(h.find(tree, 'DebugPage').length, 1);
  assert.equal(h.find(tree, 'ProjectGuidePanel')[0].props.session, guide);
  assert.equal(h.debugCalls.at(-1).enabled, true);
  assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 0);
});

test('03 diagnosis opens shared AI without switching stage or recreating the camera', () => {
  const h = harness({state:{...maker.initialMaker(),design:designFor(),code:'manual draft'}});
  const before=h.state();const tree=h.navigate('deploy');
  const panel=h.find(tree,'PiDeployPanel')[0];panel.props.onDebug({program:'stopped',logs:['error']});
  const after=h.render();assert.equal(h.state().stage,'deploy');
  assert.equal(h.state().code,before.code);assert.equal(h.state().design,before.design);
  assert.equal(h.find(after,'UnifiedAssistant').length,1);
  assert.equal(h.find(after,'VideoView').length,1);
  assert.equal(h.find(after,'AssistantWorkspace')[0].props.openRequest,1);
});

test('all three stages keep the shared chat and no longer duplicate its model menu in the header', () => {
  const h = harness({state: {...maker.initialMaker(), design: designFor()}});
  for (const stage of ['design', 'guide', 'deploy']) {
    const tree = h.navigate(stage);
    const header = h.find(tree, 'WorkspaceHeader')[0];
    assert.equal(h.find(header, 'MakerModelMenu').length, 0);
    assert.equal(h.find(header, 'DeviceConnectionGroups')[0].props.pi.type, 'PiConnectionControl');
    const chat = h.find(tree, 'UnifiedAssistant');
    assert.equal(chat.length, 1);
    assert.equal(chat[0].props.state, h.state());
  }
  const hud = harness({displayMode: 'optical-hud-demo'});
  assert.equal(hud.find(hud.render(), 'MakerModelMenu').length, 1, 'HUD keeps its model control without a chat pane');
});

test('non-Maker controllers, standalone wiring and HUD keep their board guide without a deployment panel', () => {
  for (const options of [{boardId: 'arduino-uno'}, {state: {...maker.initialMaker(), standalone: true, stage: 'guide'}}, {displayMode: 'optical-hud-demo'}]) {
    const h = harness(options), tree = h.render();
    assert.equal(h.find(tree, 'WiringGuidePanel').length, 1);
    assert.equal(h.find(tree, 'GuidePaneLayout')[0].props.stacked, false, 'legacy board and HUD layouts keep their orientation');
    assert.equal(h.find(tree, 'PiDeployPanel').length, 0);
    assert.equal(nodes(tree, n => n.props.className?.includes('maker-guide-empty')).length, 0);
  }
});

test('GPIO photo is a passive main view without a POC entry, retaining camera and guide state', () => {
  const design = designFor();
  const state = {...maker.initialMaker(), design, aiModel: 'selected-image-model', aiEffort: 'low'};
  const h = harness({state});
  const tree = h.navigate('guide');
  const controls = h.find(tree, 'VideoView')[0].props.viewNavigation;
  assert.equal(nodes(controls,node=>node.props.className==='photo-poc-trigger').length,0);
  assert.equal(controls.type,'ImageViewControls');assert.equal(controls.props.photoDisabled,false);
  const before = h.state();
  controls.props.onChange('photo');
  const photoTree = h.render();
  assert.equal(h.find(photoTree, 'VideoView').length, 1);
  assert.equal(h.find(photoTree, 'WiringWorkspace').length, 1);
  const photo = h.find(photoTree,'VideoView')[0].props.alternateView;
  assert.equal(photo.type,'GpioPhotoWorkspace');assert.equal(photo.props.record,null);
  assert.equal(h.find(photoTree, 'PhotoWiringPoc').length, 0);
  assert.equal(h.find(h.find(photoTree,'VideoView')[0].props.viewControl(null),'StatusBar').length,0);
  assert.equal(h.state(), before);
  photo.props.onReturn();
  assert.equal(h.find(h.render(), 'VideoView').length, 1);
  assert.equal(h.state(), before);
});

test('mobile capture enters the common photo view and waits for Start wiring before following the exact guide',()=>{
  const design=designFor(),state={...maker.initialMaker(),stage:'guide',design};const h=harness({state});
  let tree=h.render();const workspace=h.find(tree,'UnifiedAssistant')[0].props.mobileWorkspace;
  const wire=design.wiring[0],capture={capture_id:'phone-photo',wires:[{wire_id:wire.id}],video_size:[1920,1080]};
  workspace.onPhoto(capture,true,{round:0,context:{workspace_project_id:design.id,project_version:design.revision}});
  tree=h.render();let view=h.find(tree,'VideoView')[0].props.alternateView;
  assert.equal(view.type,'GpioPhotoWorkspace');assert.equal(view.props.record.source,'phone');assert.equal(view.props.historical,false);
  assert.equal(view.props.target,undefined,'a prepared guide cannot select the first wire automatically');
  h.find(tree,'ProjectGuidePanel')[0].props.onChange(maker.startProjectGuide(h.state().guide));
  tree=h.render();view=h.find(tree,'VideoView')[0].props.alternateView;
  assert.equal(view.props.target.id,wire.id);
  const before=h.state();view.props.onReturn();tree=h.render();assert.equal(h.state(),before);
  assert.equal(h.find(tree,'VideoView').length,1);
});
