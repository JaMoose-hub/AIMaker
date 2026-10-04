// Memory-only build on a private loopback port; no shared dist or backend access.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const base=new URL('../',import.meta.url);
const connection=`const options=new URLSearchParams(location.search);const running=options.get('state')==='running';
  const deny=()=>{throw Error('Pi actions disabled in this isolated layout fixture')};
  export function usePiConnection(){return {pending:false,error:null,networkError:false,perform:deny,connect:deny,action:deny,
    status:{connected:running,busy:false,program:running?'running':'stopped',deployment:running?'succeeded':'idle',
      logs:running?Array.from({length:200},(_,i)=>'[Offline fixture] Distance sample '+i+' cm'):[],execution:{jobs:[]}}};}`;
const result=await build({entryPoints:[fileURLToPath(new URL('tools/deploy-columns-preview.tsx',base))],bundle:true,write:false,
  outdir:'preview',jsx:'automatic',external:['/brand/*'],plugins:[{name:'no-hardware',setup(builder){
    builder.onResolve({filter:/\/lib\/PiConnection$/},()=>({path:'PiConnection',namespace:'isolated'}));
    builder.onLoad({filter:/.*/,namespace:'isolated'},()=>({contents:connection,loader:'js'}));
  }}]});
const assets=new Map(result.outputFiles.map(file=>['/'+file.path.split(/[\\/]/).at(-1),[file.contents,file.path.endsWith('.css')?'text/css':'text/javascript']]));
const html='<!doctype html><html lang="zh-Hant" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tinkro · deployment layout preview</title><link rel="icon" href="/brand/tinkro-symbol.svg"><link rel="stylesheet" href="/deploy-columns-preview.css"></head><body><div id="root"></div><script type="module" src="/deploy-columns-preview.js"></script></body></html>';
const server=createServer(async(req,res)=>{
  try{
    const path=new URL(req.url,'http://127.0.0.1').pathname;
    let asset=path==='/'?[html,'text/html']:assets.get(path);
    if(['/brand/tinkro-dark.png','/brand/tinkro-symbol.svg','/brand/tinkro-light-filter.svg'].includes(path))asset=[await readFile(new URL('public'+path,base)),path.endsWith('.png')?'image/png':'image/svg+xml'];
    if(!asset){res.writeHead(404);res.end('No API in this fixture');return;}
    res.writeHead(200,{'Content-Type':asset[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'"});res.end(asset[0]);
  }catch{res.writeHead(500);res.end('Fixture unavailable');}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
console.log(`Isolated deployment layout: http://127.0.0.1:${server.address().port}/`);
