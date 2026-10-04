// Isolated fixture server. No API proxy or filesystem photo routes.
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
const directory=fileURLToPath(new URL('../',import.meta.url));
const built=await build({entryPoints:[fileURLToPath(new URL('wiring-review-activation-preview.tsx',import.meta.url))],outdir:'fixture-build',bundle:true,write:false,jsx:'automatic',external:['/brand/*'],plugins:[{
  name:'fixture-translation-only',setup(builder){builder.onResolve({filter:/\/lib\/useMaker$/},()=>({path:'translation',namespace:'fixture'}));
    builder.onLoad({filter:/.*/,namespace:'fixture'},()=>({resolveDir:directory,contents:'export const useMakerText=()=> (zh,en)=>new URLSearchParams(location.search).get("lang")==="en"?en:zh;'}));}
}]});
const js=built.outputFiles.find(file=>file.path.endsWith('.js')).contents;
const css=built.outputFiles.find(file=>file.path.endsWith('.css')).contents;
const picture=role=>`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#e6ebee"/><rect x="100" y="480" width="1000" height="170" rx="18" fill="#488276"/><rect x="180" y="460" width="840" height="50" fill="#2c3540"/>${Array.from({length:12},(_,i)=>`<rect x="${205+i*65}" y="310" width="42" height="170" fill="#25303b"/><path d="M${225+i*65} 310V120" stroke="${['#bf5954','#d5b943','#408bb5'][i%3]}" stroke-width="20"/>`).join('')}<text x="600" y="780" text-anchor="middle" fill="#233649" font-size="30">SYNTHETIC UI FIXTURE — ${role}</text></svg>`;
const html='<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Wiring activation isolated fixture</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>';
const server=createServer((req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1').pathname;
  const assets=path==='/'?[html,'text/html']:path==='/fixture.js'?[js,'text/javascript']:path==='/fixture.css'?[css,'text/css']:
    /^\/fixture-(pi_side_a|pi_side_b|component_header)\.svg$/.test(path)?[picture(path),'image/svg+xml']:null;
  if(!assets){res.writeHead(404);res.end('No API available in this fixture');return;}
  res.writeHead(200,{'Content-Type':assets[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});res.end(assets[0]);
});
server.listen(Number(process.env.WIRING_ACTIVATION_PREVIEW_PORT||18785),'127.0.0.1',()=>console.log('Isolated wiring activation fixture: http://127.0.0.1:'+server.address().port));
