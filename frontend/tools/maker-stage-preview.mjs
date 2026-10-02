// Serve the production build with in-memory API responses on a separate origin.
// Never proxies requests or opens a real camera/Pi/cloud connection.
import {createServer} from 'node:http';
import {readFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {maker, designFor, board} from './project_guide_fixture.mjs';

export async function startStagePreview(port = 18776) {
  const dist = new URL('../dist/', import.meta.url);
  const design = {...designFor(), title: 'Offline project', source: 'ai', code: '# Offline project code'};
  const state = {...maker.initialMaker(), design, code: design.code};
  const pi = {connected: true, busy: false, program: 'stopped', deployment: 'idle', pid: null,
    invocation_id: '', component_test_id: null, execution: {jobs: []}, logs: ['Offline history fixture — no hardware execution.']};
  const tests = {connected: true, test_busy: false, active: null, results: [], execution: {jobs: []}};
  const config = {board_id: 'raspberry-pi-5', runtime_revision: 1, default_locale: 'en', video_size: [1280, 720],
    detector: 'offline', camera_source: 'device', realtime_tracking: false, accuracy: null};
  const fixtures = {
    '/api/config': config, '/api/boards/raspberry-pi-5': board,
    '/api/controllers': {controllers: [{board_id: config.board_id, name: board.board.name, active: true}]},
    '/api/pi/status': pi, '/api/pi/component-tests': tests, '/api/debug/trials': {active: null, results: []},
    '/api/debug/sessions': {active: null}, '/api/debug/conversations': {conversation: null},
    '/api/ai/status': {available: false, logged_in: false, busy: false},
  };
  const bootstrap = `
const options = new URLSearchParams(location.search);
localStorage.setItem('boardvision.maker.v1', JSON.stringify(${JSON.stringify(state)}));
localStorage.setItem('boardvision.locale.v1', options.get('lang') || 'en');
localStorage.setItem('boardvision.theme.v1', options.get('theme') || 'dark');
localStorage.setItem('boardvision.wiring-guide-visible.v1', 'true');
const fixtures = ${JSON.stringify(fixtures)};
window.__stageQa = {requests: [], errors: []};
addEventListener('error', e => window.__stageQa.errors.push(e.message));
addEventListener('unhandledrejection', e => window.__stageQa.errors.push(String(e.reason)));
window.fetch = async (input, init = {}) => {
  const url = new URL(String(input), location.href), method = init.method || 'GET';
  window.__stageQa.requests.push({path: url.pathname, method});
  if (url.origin !== location.origin) throw Error('External requests disabled');
  if (method !== 'GET') throw Error('Mutations disabled in offline preview: ' + url.pathname);
  if (!(url.pathname in fixtures)) throw Error('Unmocked offline API: ' + url.pathname);
  return new Response(JSON.stringify(fixtures[url.pathname]), {headers: {'Content-Type': 'application/json'}});
};
window.WebSocket = class extends EventTarget {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 0; close() {this.readyState = 3;} send() {throw Error('Offline socket');}
};
`;
  const assets = new Map();
  const html = (await readFile(new URL('index.html', dist), 'utf8')).replace('<head>', '<head><script src="/fixture.js"></script>');
  assets.set('/', [html, 'text/html']);
  assets.set('/fixture.js', [bootstrap, 'text/javascript']);
  assets.set('/theme.js', [await readFile(new URL('theme.js', dist)), 'text/javascript']);
  assets.set('/brand/tinkro-symbol.svg', [await readFile(new URL('brand/tinkro-symbol.svg', dist)), 'image/svg+xml']);
  assets.set('/brand/tinkro-dark.png', [await readFile(new URL('brand/tinkro-dark.png', dist)), 'image/png']);
  for (const filename of await readdir(new URL('assets/', dist))) {
    assets.set(`/assets/${filename}`, [await readFile(new URL(`assets/${filename}`, dist)), filename.endsWith('.css') ? 'text/css' : 'text/javascript']);
  }
  const camera = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#10151d"/><text x="640" y="360" text-anchor="middle" fill="#93a4b8" font-family="sans-serif" font-size="24">Offline camera fixture · no hardware connected</text></svg>`;
  assets.set('/video', [camera, 'image/svg+xml']);
  assets.set('/frame.jpg', [camera, 'image/svg+xml']);
  const requests = [];
  const server = createServer((req, res) => {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    requests.push({method: req.method, path});
    const asset = assets.get(path);
    if (req.method !== 'GET' || !asset) {res.writeHead(404); res.end('Offline fixture: no proxy'); return;}
    res.writeHead(200, {'Content-Type': asset[1], 'Cache-Control': 'no-store',
      'Content-Security-Policy': "default-src 'self'; connect-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-src 'none'"});
    res.end(asset[0]);
  });
  await new Promise((done, reject) => {server.once('error', reject); server.listen(port, '127.0.0.1', done);});
  return {server, requests, url: `http://127.0.0.1:${server.address().port}/`};
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log((await startStagePreview()).url);
}
