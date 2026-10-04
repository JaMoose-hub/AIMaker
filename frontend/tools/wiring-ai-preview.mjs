// Isolated loopback asset server: never proxies production or hardware APIs.
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
/** Exact loopback fixture routes only; never accept a production origin/API. */
export function fixtureRequestAllowed(request){
  const url=new URL(request,'http://127.0.0.1');
  return url.origin==='http://127.0.0.1'&&['/','/theme.js','/preview.js','/preview.css','/brand/tinkro-light-filter.svg','/api/debug/sessions/qa-check/evidence/photo-one'].includes(url.pathname);
}
export async function startPreview(port=18774){
  const result=await build({entryPoints:[fileURLToPath(new URL('./wiring-ai-preview.tsx',import.meta.url))],outdir:'wiring-ai-preview',write:false,bundle:true,jsx:'automatic',external:['/brand/*'],plugins:[{name:'isolated-hooks',setup(builder){
    builder.onResolve({filter:/(?:^|\/)(debug|PiConnection|useComponentTests|wsClient|motionDisplayStore|useRealtimeTracking|CameraAutoTune|CalibratePanel|OpticalHudCalibration)$/},args=>({path:args.path.split('/').at(-1),namespace:'offline'}));
    builder.onLoad({filter:/.*/,namespace:'offline'},args=>({contents:({
      debug:`export const codeHash=async()=>'qa-code';export const useDebug=()=>globalThis.__wiringQa.debug;`,
      PiConnection:`export const usePiConnection=()=>globalThis.__wiringQa.pi;`,
      useComponentTests:`export const useComponentTests=(design,guide)=>globalThis.__wiringQa.tests(design,guide);`,
      wsClient:`export const useDetections=()=>globalThis.__overlayQa?.ws??{detection:null,componentPoses:[],componentReceivedAtMs:{},connected:false,detectionsPerSec:0};export const useGuidance=()=>null;`,
      motionDisplayStore:`export const getMotionDisplay=()=>undefined;export const subscribeMotionDisplay=()=>()=>{};`,
      useRealtimeTracking:`export const useRealtimeTracking=active=>({frame:active?globalThis.__overlayQa?.frame??null:null,fps:30});`,
      CameraAutoTune:`import React from 'react';export const CameraAutoTune=()=>React.createElement('span',null,'隔離智慧調整替身');`,
      CalibratePanel:`export const CalibratePanel=()=>null;`,
      OpticalHudCalibration:`export const OpticalHudCalibrationOverlay=()=>null;`
    })[args.path],resolveDir:fileURLToPath(new URL('../',import.meta.url))}));
  }}]});
  const js=result.outputFiles.find(f=>f.path.endsWith('.js')).contents;
  const css=Buffer.concat([result.outputFiles.find(f=>f.path.endsWith('.css')).contents,Buffer.from('\n@media(max-width:700px){.wiring-ai-qa-layout{grid-template-columns:minmax(0,1fr)!important}}')]);
  const html='<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated Wiring AI QA</title><script src="/theme.js"></script><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"></head><body><div id="root"></div><script type="module" src="/preview.js"></script></body></html>';
  const requests=[];
  const server=createServer((req,res)=>{
    const url=new URL(req.url,'http://127.0.0.1');requests.push(url.pathname+url.search);
    const view=url.searchParams.get('view')||'overview';
    const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#d2e5ed"/><rect x="140" y="100" width="240" height="300" fill="#4b8e64"/><rect x="550" y="230" width="280" height="100" fill="#337fc4"/><path d="M290 140 L680 280" stroke="#eeab38" stroke-width="14"/><text x="60" y="480" font-size="38">Synthetic QA: ${view}</text></svg>`;
    const data=url.pathname==='/theme.js'?[readFileSync(new URL('../public/theme.js',import.meta.url)),'text/javascript']:url.pathname==='/brand/tinkro-light-filter.svg'?[readFileSync(new URL('../public/brand/tinkro-light-filter.svg',import.meta.url)),'image/svg+xml']:url.pathname==='/'?[html,'text/html']:url.pathname==='/preview.js'?[js,'text/javascript']:url.pathname==='/preview.css'?[css,'text/css']:url.pathname==='/api/debug/sessions/qa-check/evidence/photo-one'?[svg,'image/svg+xml']:null;
    if(!data){res.writeHead(404);res.end('No API in isolated preview');return;}
    res.writeHead(200,{'Content-Type':data[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});res.end(data[0]);
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
  return {server,requests,url:`http://127.0.0.1:${server.address().port}/`};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){const preview=await startPreview();console.log(preview.url);}
