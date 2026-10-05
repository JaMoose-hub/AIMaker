// Isolated status-widget QA: fake API responses, no backend proxy, camera or Pi.
import {createServer} from 'node:http';
import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
const base=fileURLToPath(new URL('../',import.meta.url));
const source=`
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MobileCompanion} from './src/components/MobileCompanion';
import {HeaderPanelProvider} from './src/lib/headerPanels';
import './src/styles.css';
import './src/tinkro.css';
import './src/deviceConnections.css';
const options=new URLSearchParams(location.search), scenario=options.get('case')||'other';
document.documentElement.dataset.theme=options.get('theme')||'dark';
window.__connectionQa={requests:[],errors:[]};
let network={available:true,base_url:'https://192.168.50.141:8443'},pairCount=0,delayNextPair=false,releasePair=null;
const changeNetwork=(ip,available=true)=>{network={available,base_url:'https://'+ip+':8443'};window.dispatchEvent(new Event('online'));};
window.__connectionQa.setNetwork=changeNetwork;
addEventListener('error',event=>window.__connectionQa.errors.push(event.message));
addEventListener('unhandledrejection',event=>window.__connectionQa.errors.push(String(event.reason)));
window.WebSocket=class {close(){}};
const identity={session_id:'qa-phone',conversation_id:['current','offline'].includes(scenario)?'qa-current':'qa-old',context_id:'qa-context',title:'QA project'};
const session={...identity,base_url:location.origin,context:{},stream:{active:false,generation:0,publisher_connected:false,state:'finding',can_capture:false},view:{capture_id:null,wire_id:null,revision:0}};
window.fetch=async(input,request={})=>{
 const path=new URL(typeof input==='string'?input:input.url,location.origin).pathname;
 const body=request.body?JSON.parse(request.body):{};
 window.__connectionQa.requests.push({path,method:request.method||'GET',base_url:body.base_url,cache:request.cache});
 if(path==='/api/mobile/desktop-session'&&scenario==='error')throw Error('QA: status unavailable');
 const value=path==='/api/mobile/desktop-session'?{session:['other','error','network'].includes(scenario)?null:session,connection:['offline','network'].includes(scenario)?null:identity}
  :path==='/api/mobile/context'?{}
  :path==='/api/mobile/web-config'?{...network,web_url:network.base_url+'/mobile'}
  :path==='/api/mobile/pairings'?(()=>{const origin=body.base_url||network.base_url,code=String(123450+(++pairCount));return{code,web_url:origin+'/mobile?code='+code,base_url:origin,base_urls:[origin],expires_at:Date.now()/1000+300};})():null;
 if(value===null)throw Error('Unexpected QA request: '+path);
 if(path==='/api/mobile/pairings'&&delayNextPair){delayNextPair=false;await new Promise(resolve=>releasePair=resolve);}
 return {ok:true,status:200,json:async()=>value};
};
const controller={project:{},mobileContext:{conversation_id:'qa-current',title:'目前作品'},demoOpen:false,busy:false};
function Preview(){
 const [trigger,setTrigger]=useState(null);
 return <div className="app tinkro-theme maker-layout maker-stage-design" style={{height:'100dvh',padding:12}}>
  <header className="maker-header-integrated" style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:12}}><strong>Tinkro · 連線狀態</strong><div className="maker-header-controls" ref={setTrigger}/></header>
  <p style={{padding:18,color:'var(--muted)'}}>隔離測試畫面 · 不連接相機、Pi 或正式服務</p>
  {scenario==='network'?<div style={{display:'flex',gap:8,padding:12,flexWrap:'wrap'}}>
   <button onClick={()=>changeNetwork('192.168.50.141')}>QA：切換 141</button>
   <button onClick={()=>changeNetwork('192.168.50.138')}>QA：切換 138</button>
   <button onClick={()=>changeNetwork('192.168.50.138',false)}>QA：HTTPS 尚未就緒</button>
   <button onClick={()=>{delayNextPair=true;}}>QA：延遲下一次配對</button>
   <button onClick={()=>{releasePair?.();releasePair=null;}}>QA：送回延遲配對</button>
  </div>:null}
  <MobileCompanion controller={controller} aiReady selection={null} workspace={{trigger,canShow:false,showing:false,onShow(){throw Error('Camera switches are forbidden in QA')}}}/>
 </div>;
}
createRoot(document.getElementById('root')).render(<HeaderPanelProvider><Preview/></HeaderPanelProvider>);
`;
const output=await build({stdin:{contents:source,resolveDir:base,loader:'tsx'},bundle:true,write:false,outdir:'qa',jsx:'automatic',external:['/brand/*'],plugins:[{
 name:'locale-only-qa',setup(builder){
  builder.onResolve({filter:/\/lib\/useMaker$/},()=>({path:'useMaker',namespace:'qa'}));
  builder.onLoad({filter:/.*/,namespace:'qa'},()=>({contents:`export const useMakerText=()=> (zh,en)=>new URLSearchParams(location.search).get('lang')==='en'?en:zh;`}));
 }
}]});
const js=output.outputFiles.find(file=>file.path.endsWith('.js')).contents;
const css=output.outputFiles.find(file=>file.path.endsWith('.css')).contents;
const html='<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tinkro phone connection · isolated QA</title><link rel="stylesheet" href="/qa.css"></head><body><div id="root"></div><script type="module" src="/qa.js"></script></body></html>';
const server=createServer((request,response)=>{
 const path=new URL(request.url,'http://127.0.0.1').pathname;
 const asset=path==='/'?[html,'text/html']:path==='/qa.js'?[js,'text/javascript']:path==='/qa.css'?[css,'text/css']:null;
 if(request.method!=='GET'||!asset){response.writeHead(404);response.end('No API or proxy in this fixture');return;}
 response.writeHead(200,{'Content-Type':asset[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});response.end(asset[0]);
});
server.listen(Number(process.env.MOBILE_CONNECTION_QA_PORT||0),'127.0.0.1',()=>console.log('Isolated phone status QA http://127.0.0.1:'+server.address().port+'/'));
