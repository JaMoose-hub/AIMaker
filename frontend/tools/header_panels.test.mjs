import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const panels=['phone','pi','settings','reset'];
function harness() {
  let context,currentKey,cursor;
  const states=new Map();
  const react={
    createContext(value){context={Provider:'provider',value};return context;},
    useContext(){return context.value;},
    useCallback(fn){return fn;},useMemo(fn){return fn();},
    useState(initial){const key=`${currentKey}:${cursor++}`;
      if(!states.has(key))states.set(key,{value:typeof initial==='function'?initial():initial});
      const state=states.get(key);
      state.set??=next=>{state.value=typeof next==='function'?next(state.value):next;};
      return[state.value,state.set];},
  };
  const exports={};
  const js=ts.transpileModule(read('../src/lib/headerPanels.tsx'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText;
  new Function('require','exports',js)(id=>id==='react'?react:{jsx:(type,props)=>({type,props})},exports);
  const run=(key,fn)=>{currentKey=key;cursor=0;return fn();};
  function render(owner='app') {
    const tree=run(owner,()=>exports.HeaderPanelProvider({children:'unchanged workspace'}));
    context.value=tree.props.value;
    return Object.fromEntries(panels.map(panel=>[panel,run(`${owner}:${panel}`,()=>exports.useHeaderPanel(panel))]));
  }
  return{render,standalone(initial){context.value=null;return run('standalone',()=>exports.useHeaderPanel('pi',initial));}};
}

test('header panels start closed and retain the existing workspace children',()=>{
  const h=harness(),state=h.render();
  assert.deepEqual(panels.filter(panel=>state[panel][0]),[]);
});

test('every direction between phone, Pi and Settings opens only the requested panel',()=>{
  for(const first of panels)for(const second of panels.filter(panel=>panel!==first)) {
    const h=harness();h.render()[first][1](true);
    h.render()[second][1](true);
    const state=h.render();
    assert.deepEqual(panels.filter(panel=>state[panel][0]),[second]);
  }
});

test('delayed close events from an old details element cannot close the new panel',()=>{
  const h=harness(),oldPi=h.render().pi[1];oldPi(true);
  h.render().phone[1](true);oldPi(false);
  assert.equal(h.render().phone[0],true);
  const oldSettings=h.render().settings[1];oldSettings(true);
  h.render().pi[1](true);oldSettings(false);
  assert.equal(h.render().pi[0],true);
});

test('closing the current owner closes only UI and repeated closes are harmless',()=>{
  const h=harness(),close=h.render().phone[1];close(true);close(false);close(false);
  assert.deepEqual(panels.filter(panel=>h.render()[panel][0]),[]);
});

test('rapid opens before rerender keep only the last requested owner',()=>{
  const h=harness(),state=h.render();
  state.phone[1](true);state.pi[1](true);state.settings[1](true);
  const next=h.render();assert.deepEqual(panels.filter(panel=>next[panel][0]),['settings']);
});

test('independent provider instances do not share a global menu owner',()=>{
  const h=harness();h.render('one').phone[1](true);h.render('two').pi[1](true);
  assert.equal(h.render('one').phone[0],true);
  assert.equal(h.render('one').pi[0],false);
  assert.equal(h.render('two').pi[0],true);
});

test('standalone controls preserve their initial open state without a provider',()=>{
  const h=harness();const state=h.standalone(true);assert.equal(state[0],true);
  state[1](false);assert.equal(h.standalone(true)[0],false);
});

test('all three real controls share one provider without changing connections or remounting camera',()=>{
  const app=read('../src/App.tsx');
  assert.equal((app.match(/<HeaderPanelProvider>/g)??[]).length,1);
  assert.match(app,/<HeaderPanelProvider>[^]*<WorkspaceHeader[^]*<AssistantWorkspace[^]*<\/HeaderPanelProvider>/);
  for(const [file,panel] of [['MobileCompanion','phone'],['PiConnectionControl','pi'],['RuntimeToolbar','settings']]) {
    assert.match(read(`../src/components/${file}.tsx`),new RegExp(`useHeaderPanel\\("${panel}"`));
  }
  assert.doesNotMatch(read('../src/lib/headerPanels.tsx'),/fetch\(|localStorage|dispatchEvent|window\./);
  assert.match(read('../src/components/PiConnectionControl.tsx'),/if \(!menuOpen\) setStopConsent\(null\)/);
});

function activationHarness() {
  const shared=harness();
  const element=(type,props)=>({type,props});
  const noop=()=>{},deny=()=>assert.fail('Header activation must not perform hardware or connection actions');
  function load(file) {
    const exports={};
    const js=ts.transpileModule(read(`../src/components/${file}.tsx`),{
      compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
    }).outputText;
    new Function('require','exports',js)(id=>{
      if(id==='react')return {useId:()=>file,useRef:()=>({current:null}),useEffect:noop,useState:initial=>[initial,noop]};
      if(id==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
      if(id==='../lib/headerPanels')return {useHeaderPanel:panel=>shared.render()[panel]};
      if(id==='../lib/useMaker')return {useMakerText:()=> (zh)=>zh};
      if(id==='../lib/i18n')return {useI18n:()=>({locale:'en',t:key=>key,tx:value=>value})};
      if(id==='../lib/PiConnection')return {usePiConnection:()=>({status:null,pending:false,connect:deny,perform:deny,action:deny})};
      if(id==='../lib/piApi')return {executionPending:()=>false,programOwner:()=>null,stopPiProgram:deny};
      if(id==='./ThemeSelect')return {ThemeSelect:()=>null};
      throw Error(`Unmocked dependency ${id}`);
    },exports);return exports[file];
  }
  const Pi=load('PiConnectionControl'),Settings=load('RuntimeToolbar');
  const find=(node,type)=>{
    if(Array.isArray(node))return node.map(child=>find(child,type)).find(Boolean);
    if(!node?.props)return null;
    return node.type===type?node:find(node.props.children,type);
  };
  const control=panel=>panel==='pi'?Pi():Settings({collapsible:true,controllers:[],activeBoardId:null,busy:false,disabled:false,error:null,onControllerChange:deny,onLocaleChange:deny});
  return {shared,click(panel){const tree=control(panel),summary=find(tree,'summary'),details=find(tree,'details');
    assert.equal(details.props.onToggle,undefined,'native queued toggle events must not write the shared owner');
    let prevented=false;summary.props.onClick({preventDefault(){prevented=true;}});
    assert.equal(prevented,true,'cancel native expansion before switching ownership');
  }};
}

test('real Settings and Pi activations synchronously close the phone and cancel native disclosure',()=>{
  for(const panel of ['settings','pi']) {
    const h=activationHarness();h.shared.render().phone[1](true);h.click(panel);
    const state=h.shared.render();
    assert.equal(state.phone[0],false);assert.equal(state[panel][0],true);
  }
});

test('real header controls toggle off and never need a later native toggle event',()=>{
  const h=activationHarness();h.click('settings');h.click('settings');
  assert.equal(h.shared.render().settings[0],false);
  h.click('pi');h.click('settings');h.click('pi');
  const state=h.shared.render();assert.equal(state.pi[0],true);assert.equal(state.settings[0],false);
});
