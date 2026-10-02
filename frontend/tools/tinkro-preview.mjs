// npm run preview:theme — loopback-only visual QA, no backend proxy.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {build} from 'esbuild';

const base=new URL('../',import.meta.url);
// Static illustrations for the saved-preview fixture only, never a backend proxy.
export const discardImagePaths=['a','b'].map(id=>`/api/design/images/${id.repeat(32)}`);
const discardImage=preview=>`<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="1000" height="700" fill="${preview?'#e5ecfa':'#dcefe5'}"/><g fill="none" stroke="${preview?'#417abe':'#138575'}" stroke-width="5"><ellipse cx="500" cy="470" rx="290" ry="95"/><ellipse cx="500" cy="300" rx="290" ry="95"/><path d="M250 340v170m500-170v170M350 260v190m300-190v190"/><rect x="375" y="165" width="250" height="190" rx="20"/></g><text x="500" y="635" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#203065">${preview?'Unconfirmed preview v3':'Confirmed project v2'} · offline fixture</text></svg>`;
export async function startPreview(port=18770) {
const requests=[];
const connectionFixture=`
import {useState} from 'react';
const options=new URLSearchParams(location.search), stopCase=options.get('executionStop');
const offline=options.has('connectionError'), state=options.get('deployState');
const events=[];
const deny=()=>{throw Error('Pi actions disabled')};
export function usePiConnection(){
  const [status,setStatus]=useState(()=>({connected:!offline, busy:false, component_test_id:stopCase==='test'?'offline-test':null,
    pid:stopCase?41:null, invocation_id:stopCase?'offline-invocation':'',
    program:stopCase==='unknown'?'unknown':stopCase?'running':state==='failed'?'failed':state==='running'?'running':'stopped',
    deployment:state==='failed'?'failed':state==='running'?'succeeded':'idle',
    error:state==='failed'?'RuntimeError: offline layout fixture\\n'+('Diagnostic context: no hardware action was performed.\\n').repeat(12):null,
    logs:state==='running'||state==='failed'?Array.from({length:1000},(_,i)=>'[Preview] output line '+i):['[Preview] No hardware program was started.'],
    execution:{jobs:stopCase==='queue'?[{id:'offline-job',kind:'deploy',label:'Offline queued job',state:'queued'}]:[]}}));
  const [pending,setPending]=useState(false),[error,setError]=useState(null);
  window.__stopProjectQa={events,changeOwner(){setStatus(s=>({...s,invocation_id:'offline-replacement'}))}};
  async function perform(action){
    if(!stopCase)return deny();
    setPending(true);setError(null);
    const before=window.fetch;
    // In-memory response only: never forwards a request to a server/Pi.
    window.fetch=async(path,request)=>{
      if(path!=='/api/pi/stop'||request.method!=='POST')throw Error('Unexpected hardware request');
      const body=JSON.parse(request.body);events.push({path,body});
      if(stopCase==='failure')throw Error('Remote stop has not been confirmed');
      if(stopCase==='old')return {ok:false,status:404,json:async()=>({})};
      if(body.owner!=='program:'+status.invocation_id)return {ok:false,status:409,json:async()=>({detail:'stop_owner_changed'})};
      return {ok:true,json:async()=>({ok:true,status:{...status,program:'stopped',pid:null,invocation_id:''}})};
    };
    try{const result=await action();setStatus(result.status);if(!result.ok)setError(result.error)}
    catch(e){setError(e.message)}finally{window.fetch=before;setPending(false)}
  }
  return {status,networkError:offline?'Offline fixture: connection unavailable. This is a deliberately long diagnostic message, not a real Pi failure.':false,
    pending,error,perform,connect:deny,action:deny};
}`;
const result=await build({entryPoints:[fileURLToPath(new URL('tools/tinkro-preview.tsx',base))],outdir:'preview',write:false,bundle:true,jsx:'automatic',plugins:[{
  name:'offline-hardware-hooks',setup(builder){
    builder.onResolve({filter:/\/lib\/(debug|PiConnection|useComponentTests)$/},args=>({path:args.path.split('/').at(-1),namespace:'offline'}));
    builder.onLoad({filter:/.*/,namespace:'offline'},args=>({resolveDir:fileURLToPath(base),contents:({
      debug:`export const codeHash=async()=>'offline-preview'; export const useDebug=()=>({record:null,pending:false,error:'',trials:{active:null,results:[]},action(){throw Error('Hardware actions disabled')}});`,
      PiConnection:connectionFixture,
      useComponentTests:`const deny=()=>{throw Error('Component tests disabled')}; export const useComponentTests=()=>({status:{connected:true,test_busy:false,active:null,results:[],execution:{jobs:[]}},error:null,pending:false,start:deny,action:deny,connect:deny,invalidate:async()=>{}});`,
    })[args.path]}));
  }
}]});
const js=result.outputFiles.find(f=>f.path.endsWith('.js')).contents;
const css=result.outputFiles.find(f=>f.path.endsWith('.css')).contents;
const html='<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tinkro · isolated UI preview</title><script src="/theme.js"></script><link rel="icon" href="/brand/tinkro-symbol.svg"><link rel="stylesheet" href="/preview.css"></head><body><div id="root"></div><script type="module" src="/preview.js"></script></body></html>';
const server=createServer(async(req,res)=>{
  try {
    const path=new URL(req.url,'http://127.0.0.1').pathname;
    requests.push(path);
    const asset=path==='/theme.js'?[await readFile(new URL('public/theme.js',base)),'text/javascript']:path==='/'?[html,'text/html']:path==='/preview.js'?[js,'text/javascript']:path==='/preview.css'?[css,'text/css']:
      path==='/brand/tinkro-dark.png'?[await readFile(new URL('public/brand/tinkro-dark.png',base)),'image/png']:
      path==='/brand/tinkro-symbol.svg'?[await readFile(new URL('public/brand/tinkro-symbol.svg',base)),'image/svg+xml']:
      path==='/demo/distance-monitor-three-wheel-motors-v2.png'?[await readFile(new URL('public/demo/distance-monitor-three-wheel-motors-v2.png',base)),'image/png']:
      discardImagePaths.includes(path)?[discardImage(path===discardImagePaths[1]),'image/svg+xml']:null;
    if(!asset){res.writeHead(404);res.end('No API in this preview');return;}
    res.writeHead(200,{'Content-Type':asset[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});res.end(asset[0]);
  }catch{res.writeHead(500);res.end('Preview asset unavailable');}
});
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done);});
return {url:`http://127.0.0.1:${server.address().port}/`,server,requests};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const preview=await startPreview();
  console.log(`Tinkro isolated preview: ${preview.url}`);
}
