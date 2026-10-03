// In-memory bundle. Does not overwrite dist or contact the running backend.
import {build} from 'esbuild';
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
const result=await build({entryPoints:[fileURLToPath(new URL('./image-view-preview.tsx',import.meta.url))],bundle:true,write:false,outdir:'preview',jsx:'automatic'});
const js=result.outputFiles.find(f=>f.path.endsWith('.js')).contents;
const css=result.outputFiles.find(f=>f.path.endsWith('.css')).contents;
const server=createServer((req,res)=>{
  const path=new URL(req.url,'http://127.0.0.1').pathname;
  const files={'/preview.js':['text/javascript',js],'/preview.css':['text/css',css],'/':['text/html','<!doctype html><html lang="zh-TW"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Image view isolated QA</title><link rel="stylesheet" href="/preview.css"><script>localStorage.setItem("boardvision.locale.v1","zh-TW");document.documentElement.dataset.theme=new URLSearchParams(location.search).get("theme")||"dark";</script><div id="root"></div><script type="module" src="/preview.js"></script></html>']};
  const item=files[path];res.writeHead(item?200:404,{'Content-Type':item?.[0]??'text/plain'});res.end(item?.[1]??'Not found');
});
server.listen(18806,'127.0.0.1',()=>console.log('Image-view isolated QA http://127.0.0.1:18806/'));
