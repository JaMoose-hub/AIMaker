import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const read=p=>readFileSync(new URL(p,import.meta.url),'utf8');
const source=read('../src/lib/theme.ts');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function harness(stored,blocked=false){
  const writes=[],events=new EventTarget(),attrs={};
  const data=new Map([['boardvision.maker.v1','unchanged draft'],['boardvision.ai-debug-session.v1','unchanged AI']]);
  if(stored!==undefined)data.set('boardvision.theme.v1',stored);
  const storage={getItem:k=>{if(blocked)throw Error('denied');return data.get(k)??null;},setItem:(k,v)=>{if(blocked)throw Error('denied');writes.push(k);data.set(k,v);}};
  const document={documentElement:{dataset:{}},querySelector:()=>({setAttribute:(k,v)=>attrs[k]=v})};
  const window={localStorage:storage,addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events),dispatchEvent:events.dispatchEvent.bind(events)};
  const context={exports:{},document,window,Event,localStorage:storage};
  vm.runInNewContext(read('../public/theme.js'),context);
  vm.runInNewContext(js,context);
  return {...context,api:context.exports,data,writes,attrs};
}
test('first load defaults dark, restores light, normalizes invalid preference before app entry',()=>{
  assert.equal(harness().api.getTheme(),'dark');
  assert.equal(harness('light').api.getTheme(),'light');
  assert.equal(harness('broken').api.getTheme(),'dark');
  assert.equal(harness('light',true).api.getTheme(),'dark');
  const html=read('../index.html');
  assert.ok(html.indexOf('/theme.js')<html.indexOf('/src/main.tsx'));
  assert.doesNotMatch(html.match(/<script[^>]*theme.js[^>]*>/)[0],/defer|async|module/);
  assert.match(html,/:root \{ color-scheme: dark; background: #0a0b10;/);
  assert.match(html,/:root\[data-theme="light"\] \{ color-scheme: light; background: #f3f4f7;/);
});
test('switch changes only theme preference and paint metadata, never business data',()=>{
  const h=harness();let notifications=0;
  const stop=h.api.subscribeTheme(()=>notifications++);
  h.api.setTheme('light');
  assert.equal(h.document.documentElement.dataset.theme,'light');
  assert.equal(h.attrs.content,'#f3f4f7');
  assert.deepEqual(h.writes,['boardvision.theme.v1']);
  assert.equal(h.data.get('boardvision.maker.v1'),'unchanged draft');
  assert.equal(h.data.get('boardvision.ai-debug-session.v1'),'unchanged AI');
  assert.equal(notifications,1);
  stop();h.api.setTheme('dark');assert.equal(notifications,1);
});
test('blocked browser storage still allows switching for the current session',()=>{
  const h=harness(undefined,true);h.api.setTheme('light');
  assert.equal(h.api.getTheme(),'light');assert.deepEqual(h.writes,[]);
});
test('other tabs theme changes synchronize without writing drafts or reacting to unrelated keys',()=>{
  const h=harness();let count=0;const stop=h.api.subscribeTheme(()=>count++);
  const storage=(key,newValue)=>{const e=new Event('storage');Object.assign(e,{key,newValue});h.window.dispatchEvent(e);};
  storage('boardvision.maker.v1','different draft');assert.equal(count,0);
  storage('boardvision.theme.v1','light');assert.equal(count,1);assert.equal(h.api.getTheme(),'light');
  storage(null,null);assert.equal(h.api.getTheme(),'dark');assert.deepEqual(h.writes,[]);
  stop();storage('boardvision.theme.v1','light');assert.equal(count,2);
});
test('theme subscriber is local to its accessible toolbar control, not the App tree',()=>{
  const select=read('../src/components/ThemeSelect.tsx');
  assert.match(select,/useSyncExternalStore\(subscribeTheme, getTheme/);
  assert.match(select,/aria-label=\{t\("runtime.themeLabel"\)\}/);
  assert.doesNotMatch(select,/disabled|fetch|setMaker|key=|location/);
  assert.doesNotMatch(read('../src/App.tsx'),/useTheme|ThemeProvider|key=\{theme\}/);
  const toolbar=read('../src/components/RuntimeToolbar.tsx');
  assert.ok(toolbar.indexOf('<ThemeSelect />')>toolbar.indexOf('runtime.languageLabel'));
  for(const lang of ['en','zh-TW']){const strings=JSON.parse(read('../src/locales/'+lang+'.json'));for(const key of ['themeLabel','themeDark','themeLight'])assert.ok(strings['runtime.'+key]);}
});
