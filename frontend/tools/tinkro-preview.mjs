// npm run preview:theme — loopback-only visual QA, no backend proxy.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const base=new URL('../',import.meta.url);
const result=await build({entryPoints:[fileURLToPath(new URL('tools/tinkro-preview.tsx',base))],outdir:'preview',write:false,bundle:true,jsx:'automatic',plugins:[{
  name:'offline-hardware-hooks',setup(builder){
    builder.onResolve({filter:/\/lib\/(debug|PiConnection|useComponentTests)$/},args=>({path:args.path.split('/').at(-1),namespace:'offline'}));
    builder.onLoad({filter:/.*/,namespace:'offline'},args=>({contents:({
      debug:`export const codeHash=async()=>'offline-preview'; export const useDebug=()=>({record:null,pending:false,error:'',trials:{active:null,results:[]},action(){throw Error('Hardware actions disabled')}});`,
      PiConnection:`const deny=()=>{throw Error('Pi actions disabled')}; export const usePiConnection=()=>({status:{connected:true,program:'stopped',deployment:'idle',logs:['[Preview] No hardware program was started.'],execution:{jobs:[]}},networkError:false,pending:false,perform:deny,connect:deny,action:deny});`,
      useComponentTests:`const deny=()=>{throw Error('Component tests disabled')}; export const useComponentTests=()=>({status:{connected:true,test_busy:false,active:null,results:[],execution:{jobs:[]}},error:null,pending:false,start:deny,action:deny,connect:deny,invalidate:async()=>{}});`,
    })[args.path]}));
  }
}]});
const js=result.outputFiles.find(f=>f.path.endsWith('.js')).contents;
const css=result.outputFiles.find(f=>f.path.endsWith('.css')).contents;
const html='<!doctype html><html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tinkro · isolated UI preview</title><link rel="icon" href="/brand/tinkro-symbol.svg"><link rel="stylesheet" href="/preview.css"></head><body><div id="root"></div><script type="module" src="/preview.js"></script></body></html>';
const server=createServer(async(req,res)=>{
  try {
    const path=new URL(req.url,'http://127.0.0.1').pathname;
    const asset=path==='/'?[html,'text/html']:path==='/preview.js'?[js,'text/javascript']:path==='/preview.css'?[css,'text/css']:
      path==='/brand/tinkro-dark.png'?[await readFile(new URL('public/brand/tinkro-dark.png',base)),'image/png']:
      path==='/brand/tinkro-symbol.svg'?[await readFile(new URL('public/brand/tinkro-symbol.svg',base)),'image/svg+xml']:null;
    if(!asset){res.writeHead(404);res.end('No API in this preview');return;}
    res.writeHead(200,{'Content-Type':asset[1],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'none'"});res.end(asset[0]);
  }catch{res.writeHead(500);res.end('Preview asset unavailable');}
});
server.listen(18770,'127.0.0.1',()=>console.log('Tinkro isolated preview: http://127.0.0.1:18770/'));
