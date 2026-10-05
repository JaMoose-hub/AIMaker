// Isolated visual check: real components, synthetic evidence, no app/API/Pi calls.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const mobileLanguage = process.argv.includes('--mobile-language');
const bundle = await build({
  entryPoints: [fileURLToPath(new URL(mobileLanguage ? 'mobile-language-preview.tsx' : 'wiring-diagnosis-preview.tsx', import.meta.url))],
  bundle: true, write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'],
  plugins: mobileLanguage ? [] : [{ name: 'fixture-translation', setup(builder) {
    builder.onResolve({ filter: /\/lib\/useMaker$/ }, () => ({ path: 'translation', namespace: 'fixture' }));
    builder.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: 'export const useMakerText=()=> (zh,en)=>zh;' }));
  } }],
});
const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents;
const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
const picture = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500">
  <rect width="800" height="500" fill="#121f27"/><rect x="70" y="190" width="660" height="210" rx="18" fill="#275745"/>
  <rect x="160" y="240" width="450" height="60" rx="8" fill="#242d33"/>
  <rect x="184" y="175" width="56" height="125" rx="6" fill="#7b91a7"/>
  <rect x="280" y="175" width="56" height="125" rx="6" fill="#efab63"/>
  <path d="M308 175V60H570" fill="none" stroke="#efab63" stroke-width="12"/>
  <text x="212" y="350" text-anchor="middle" fill="#c6e0e8" font-size="22">Pin 11</text>
  <text x="308" y="350" text-anchor="middle" fill="#c6e0e8" font-size="22">Pin 12</text>
  <text x="400" y="455" text-anchor="middle" fill="#a6bcc5" font-size="18">SYNTHETIC EXAMPLE — NOT PHYSICAL EVIDENCE</text>
</svg>`;
const html = `<!doctype html><html lang="zh-Hant" data-theme="dark"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>隔離預覽 · ${mobileLanguage ? '手機語系' : '簡易接線除錯'}</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>`;
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://127.0.0.1').pathname;
  const send = (body, type, status = 200) => { response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }); response.end(body); };
  if (request.method !== 'GET') return send('Read-only fixture', 'text/plain', 405);
  if (path === '/') return send(html, 'text/html');
  if (path === '/preview.js') return send(js, 'text/javascript');
  if (path === '/preview.css') return send(css, 'text/css');
  if (path === '/fixture.svg') return send(picture, 'image/svg+xml');
  if (path.startsWith('/brand/')) return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="2" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>', 'image/svg+xml');
  return send('No application or hardware API in this fixture', 'text/plain', 404);
});
server.listen(18806, '127.0.0.1', () => process.stdout.write('Isolated visual preview: http://127.0.0.1:18806/\n'));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)));
