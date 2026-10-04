import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/lib/useChatScroll.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function harness(){
  const refs=[],states=[],effects=[];let ri=0,si=0,ei=0,key='reply1',visible=true,top=800,resize,disconnected=false;
  const react={useRef:value=>refs[ri++]??={current:value},useState:value=>{const i=si++;if(!(i in states))states[i]=value;return[states[i],next=>states[i]=next];},
    useLayoutEffect(fn,deps){const i=ei++;if(effects[i]?.deps.every((v,n)=>Object.is(v,deps[n])))return;effects[i]?.cleanup?.();effects[i]={deps,fn};}};
  const module={};
  new Function('require','exports','ResizeObserver',code)(()=>react,module,class{constructor(fn){resize=fn;}observe(){}disconnect(){disconnected=true;}});
  const target={dataset:{messageId:'latest'},getBoundingClientRect:()=>({top:100+top-node.scrollTop})};
  const earlier={dataset:{messageId:'invitation'},getBoundingClientRect:()=>({top:100+500-node.scrollTop})};
  const node={scrollTop:0,scrollHeight:2000,clientHeight:300,clientTop:0,getBoundingClientRect:()=>({top:100}),querySelectorAll:()=>[earlier,target]};
  function render(){ri=si=ei=0;const result=module.useChatScroll(key,visible);result.chatRef.current=node;result.contentRef.current={};for(const effect of effects){if(effect.fn){const fn=effect.fn;delete effect.fn;effect.cleanup=fn();}}return result;}
  return{node,render,setMessage(id,y){key=id;top=y;},setVisible(value){visible=value;},resize:()=>resize?.(),dispose:()=>effects.forEach(e=>e.cleanup?.()),disconnected:()=>disconnected};
}
test('initial and arriving long replies show their beginning, not the trailing status card',()=>{
  const h=harness();let hook=h.render();assert.equal(h.node.scrollTop,792);hook.onScroll();
  h.setMessage('reply2',1100);hook=h.render();assert.equal(h.node.scrollTop,1092);
  assert.notEqual(h.node.scrollTop,h.node.scrollHeight-h.node.clientHeight);
});
test('reading older messages is not interrupted, and latest-reply action restores following',()=>{
  const h=harness();let hook=h.render();h.node.scrollTop=100;hook.onScroll();
  h.setMessage('reply2',1200);h.render();hook=h.render();assert.equal(h.node.scrollTop,100);assert.equal(hook.unread,true);
  hook.showLatest();hook=h.render();assert.equal(h.node.scrollTop,1192);assert.equal(hook.unread,false);
});
test('new send resumes following even after scrolling through history',()=>{
  const h=harness();let hook=h.render();h.node.scrollTop=100;hook.onScroll();hook.followNext();
  h.setMessage('reply2',1000);h.render();assert.equal(h.node.scrollTop,992);
});
test('late image/operation resize keeps the message anchored, but never steals a history position',()=>{
  const h=harness();let hook=h.render();h.setMessage('reply1',900);h.resize();assert.equal(h.node.scrollTop,892);
  h.node.scrollTop=200;hook.onScroll();h.setMessage('reply1',1000);h.resize();assert.equal(h.node.scrollTop,200);
  h.dispose();assert.equal(h.disconnected(),true);
});
test('unrelated status polls do not force the conversation to the bottom',()=>{
  const h=harness();h.render();h.node.scrollHeight=2500;h.render();assert.equal(h.node.scrollTop,792);
});

test('reopening a deduplicated invitation focuses that message through resizes until the next reply',()=>{
  const h=harness();let hook=h.render();
  assert.equal(hook.showMessage('missing'),false);assert.equal(h.node.scrollTop,792);
  assert.equal(hook.showMessage('invitation'),true);assert.equal(h.node.scrollTop,492);
  h.resize();assert.equal(h.node.scrollTop,492);
  h.setMessage('reply2',1100);hook=h.render();assert.equal(h.node.scrollTop,1092);
});
