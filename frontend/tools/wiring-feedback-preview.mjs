import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
export async function startPreview(port = 18812) {
  const result = await build({ entryPoints: [fileURLToPath(new URL('wiring-feedback-preview.tsx', import.meta.url))],
    bundle: true, write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'] });
  const js = result.outputFiles.find(file => file.path.endsWith('.js')).contents;
  const css = result.outputFiles.find(file => file.path.endsWith('.css')).contents;
  const server = createServer((request, response) => {
    const path = new URL(request.url, 'http://127.0.0.1').pathname;
    const send = (data, type, status = 200) => { response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }); response.end(data); };
    if (path === '/') return send('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Wiring feedback isolated QA</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>', 'text/html');
    if (path === '/preview.js') return send(js, 'text/javascript');
    if (path === '/preview.css') return send(css, 'text/css');
    return send('Closed fixture: no production APIs.', 'text/plain', 404);
  });
  await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
  return { url: `http://127.0.0.1:${server.address().port}/`, server };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log((await startPreview()).url);
