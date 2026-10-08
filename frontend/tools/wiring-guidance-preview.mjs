// Read-only display preview of one saved result. No camera, model or hardware actions.
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { build } from 'esbuild';

const sessionId = process.argv[2];
let flow, output;
if (sessionId === '--result') {
  const path = resolve(process.argv[3]);
  const result = JSON.parse(await readFile(path, 'utf8'));
  flow = { summary: result.summary, wire_id: result.summary?.results?.[0]?.wire_id };
  output = resolve(dirname(path), 'ui-preview');
} else {
  if (!/^[a-f0-9]{32}$/.test(sessionId ?? '')) throw Error('Pass a saved debug session ID or --result JSON path.');
  const response = await fetch(`http://127.0.0.1:8100/api/debug/sessions/${sessionId}`);
  if (!response.ok) throw Error(`Saved result unavailable: ${response.status}`);
  const session = await response.json();
  flow = session.messages.findLast(message => message.wiring_flow?.summary)?.wiring_flow;
  output = resolve('../runs/wiring-guidance-20261006');
}
const summary = flow?.summary;
if (!summary) throw Error('No saved wiring summary.');
await mkdir(output, { recursive: true });
await writeFile(resolve(output, 'saved-summary.json'), JSON.stringify(summary, null, 2));
const source = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from './src/lib/i18n';
import { WiringReviewOverview } from './src/components/WiringChatMessage';
import './src/styles.css';
import './src/tinkro.css';
import './src/assistant.css';
localStorage.setItem('boardvision.locale.v1', 'zh-TW');
createRoot(document.getElementById('root')).render(<LocaleProvider>
  <main style={{maxWidth:640,margin:'24px auto',padding:16}}>
    <p style={{fontSize:12,opacity:.7}}>接線回覆預覽 · 沿用保存結果，未重新分析</p>
    <article className="wiring-guidance-preview" style={{padding:20,background:'#172d27',border:'1px solid #35584b',borderRadius:12}}>
      <header style={{color:'#87cbb8',marginBottom:18,fontWeight:700}}>Tinkro AI</header>
      <WiringReviewOverview summary={${JSON.stringify(summary)}} focusWireId={${JSON.stringify(flow.wire_id)}} />
    </article>
  </main>
</LocaleProvider>);`;
const bundle = await build({ stdin: { contents: source, resolveDir: process.cwd(), loader: 'tsx' },
  bundle: true, write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'] });
const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents;
const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
const html = '<!doctype html><html lang="zh-Hant" data-theme="dark"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>接線回覆預覽</title><link rel="stylesheet" href="/preview.css"><body><div id="root"></div><script src="/preview.js"></script></body></html>';
createServer((request, result) => {
  const asset = request.url === '/preview.js' ? [js, 'text/javascript'] : request.url === '/preview.css' ? [css, 'text/css'] : request.url === '/' ? [html, 'text/html; charset=utf-8'] : null;
  if (!asset) { result.writeHead(404); result.end(); return; }
  result.writeHead(200, { 'content-type': asset[1], 'cache-control': 'no-store' }); result.end(asset[0]);
}).listen(18812, '127.0.0.1', () => console.log('Read-only saved-result preview: http://127.0.0.1:18812/'));
