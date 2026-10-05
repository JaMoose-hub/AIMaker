// Isolated UI fixture. No production API, camera permission, AI or Pi requests.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
const bundle = await build({ entryPoints: [fileURLToPath(new URL('./phone-tuning-preview.tsx', import.meta.url))], bundle: true,
  write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'], loader: { '.png': 'dataurl', '.svg': 'dataurl' } });
const assets = new Map(bundle.outputFiles.map(file => [file.path.endsWith('.css') ? '/preview.css' : '/preview.js', file.contents]));
const server = createServer((req, res) => {
  const path = new URL(req.url, 'http://127.0.0.1').pathname;
  res.setHeader('Cache-Control', 'no-store');
  if (path === '/') { res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phone smart adjustment isolated QA</title><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script>');
  } else if (assets.has(path)) { res.setHeader('Content-Type', path.endsWith('.css') ? 'text/css' : 'text/javascript'); res.end(assets.get(path)); }
  else { res.statusCode = 404; res.end('No production route in this fixture'); }
});
server.listen(Number(process.env.PHONE_TUNE_PREVIEW_PORT || 18825), '127.0.0.1', () => console.log(`Phone QA: http://127.0.0.1:${server.address().port}/`));
