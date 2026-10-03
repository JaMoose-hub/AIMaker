// Serve the production build with in-memory API responses on a separate origin.
// Never proxies requests or opens a real camera/Pi/cloud connection.
import {createServer} from 'node:http';
import {readFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {maker, componentTests, designFor, board} from './project_guide_fixture.mjs';

export async function startStagePreview(port = 18776, assistantQa = false) {
  const dist = new URL('../dist/', import.meta.url);
  const design = {...designFor(assistantQa ? ['hc-sr04','mrd-tf240-8p-cs'] : ['hc-sr04']), title: 'Offline project', source: 'demo', code: '# Offline project code'};
  const state = {...maker.initialMaker(), design, code: design.code};
  // Optional read-only wiring-review scenarios. The preview still rejects all
  // test/Pi writes; these records are never sent to the real backend.
  const reviewGuide = {...maker.emptyGuide(), phase:'review', componentIndex:design.component_ids.length-1,
    index:design.wiring.filter(w=>w.componentId===design.component_ids.at(-1)).length-1,
    confirmed:Object.fromEntries(design.wiring.map(w=>[w.id,{signature:maker.wireSignature(w),mode:'camera',at:'offline-fixture'}]))};
  const reviewState = {...state, stage:'guide', guide:reviewGuide};
  const visualRun = {id:'offline-tft-test',project_id:design.id,revision:design.revision,component_id:design.component_ids.at(-1),
    guide_key:componentTests.componentTestKey(design,reviewGuide,design.component_ids.at(-1)),template_version:'fixture',wiring_hash:'fixture',
    created_at:2000,heartbeat_at:2000,outcome:'awaiting_confirmation',phase:'awaiting_visual',reason:null,detail:'',logs:[],
    samples:{},latest:null,reserved:true,program_stopped:false,invalidated:false,options:['1234','2468','4567','7890']};
  const testPhases = Object.fromEntries([
    'awaiting_near','awaiting_far','sampling_near','sampling_far',
    'display_red','display_lime','display_blue','display_code','awaiting_visual',
  ].map(phase => {
    const cid = /near|far/.test(phase) ? 'hc-sr04' : 'mrd-tf240-8p-cs';
    const guide = {...reviewGuide,componentIndex:design.component_ids.indexOf(cid),index:design.wiring.filter(w=>w.componentId===cid).length-1};
    return [phase,{state:{...reviewState,guide},run:{...visualRun,id:`offline-${phase}`,phase,component_id:cid,
      guide_key:componentTests.componentTestKey(design,guide,cid),outcome:phase==='awaiting_visual'?'awaiting_confirmation':'running'}}];
  }));
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
    '/api/ai/status': {available: assistantQa, logged_in: assistantQa, busy: false},
    '/api/ai/models': {models:[{id:'gpt-6-luna',name:'QA fake model',description:'Isolated simulation',efforts:['low','medium','high'],default_effort:'low',is_default:true,excluded_efforts:[]}],default_model:'gpt-6-luna',billing_mode:'fake'},
  };
  const bootstrap = `
const options = new URLSearchParams(location.search);
if (!${assistantQa} || !localStorage.getItem('boardvision.maker.v1')) localStorage.setItem('boardvision.maker.v1', JSON.stringify(${JSON.stringify(state)}));
localStorage.setItem('boardvision.locale.v1', options.get('lang') || 'en');
localStorage.setItem('boardvision.theme.v1', options.get('theme') || 'dark');
localStorage.setItem('boardvision.wiring-guide-visible.v1', 'true');
const fixtures = ${JSON.stringify(fixtures)};
const guideCase = options.get('guide-case');
if (${assistantQa} && ['ready','visual','lost','disconnected'].includes(guideCase)) {
  localStorage.setItem('boardvision.maker.v1', JSON.stringify(${JSON.stringify(reviewState)}));
  if (guideCase === 'disconnected') {
    fixtures['/api/pi/component-tests'].connected = false;
    fixtures['/api/pi/status'].connected = false;
  }
  if (guideCase === 'visual' || guideCase === 'lost') {
    const run = ${JSON.stringify(visualRun)};
    if (guideCase === 'lost') run.reason = 'connection_lost';
    Object.assign(fixtures['/api/pi/component-tests'], {active:run,results:[run],test_busy:true});
  }
}
const phaseFixture = (${JSON.stringify(testPhases)})[options.get('test-phase')];
if (${assistantQa} && phaseFixture) {
  localStorage.setItem('boardvision.maker.v1', JSON.stringify(phaseFixture.state));
  const run = phaseFixture.run;
  run.created_at = run.heartbeat_at = Date.now()/1000;
  Object.assign(fixtures['/api/pi/component-tests'], {active:run,results:[run],test_busy:true});
}
window.__stageQa = {requests: [], errors: []};
// A synthetic browser-only phone source. Never opens a camera or real RTC peer.
const phoneFixture = ${assistantQa} && options.get('phone-preview') === '1';
let phoneContext = null;
if (phoneFixture) {
  window.__stageQa.phoneViewers = {opened:0,closed:0};
  window.RTCPeerConnection = class {
    iceGatheringState = 'complete'; connectionState = 'new'; localDescription = null;
    addTransceiver() { return {receiver:{},setCodecPreferences(){}}; }
    getTransceivers() { return []; }
    async createOffer() { return {type:'offer',sdp:'offline-phone'}; }
    async setLocalDescription(value) { this.localDescription=value; }
    async setRemoteDescription() {
      const canvas=document.createElement('canvas');canvas.width=720;canvas.height=1280;
      const c=canvas.getContext('2d');c.fillStyle='#16343b';c.fillRect(0,0,720,1280);
      c.fillStyle='#42c5a3';c.fillRect(140,330,440,480);c.fillStyle='#ffffff';c.font='32px sans-serif';
      c.fillText('OFFLINE PHONE FIXTURE',130,260);
      this.stream=canvas.captureStream(5);this.connectionState='connected';window.__stageQa.phoneViewers.opened++;
      this.ontrack?.({streams:[this.stream],receiver:{}});this.onconnectionstatechange?.();
    }
    async getStats() { return new Map(); }
    close() { if(this.stream){this.stream.getTracks().forEach(t=>t.stop());this.stream=null;window.__stageQa.phoneViewers.closed++;} }
  };
}
addEventListener('error', e => window.__stageQa.errors.push(e.error?.stack || e.message));
addEventListener('unhandledrejection', e => window.__stageQa.errors.push(String(e.reason)));
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const url = new URL(String(input), location.href), method = init.method || 'GET';
  window.__stageQa.requests.push({path: url.pathname, method});
  if (url.origin !== location.origin) throw Error('External requests disabled');
  if(phoneFixture && url.pathname==='/api/mobile/context') { phoneContext=JSON.parse(init.body);return new Response('{}'); }
  if(phoneFixture && url.pathname==='/api/mobile/desktop-session') return new Response(JSON.stringify({session:{session_id:'offline-phone',
    conversation_id:url.searchParams.get('conversation_id'),context_id:'offline-phone-context',title:'Offline phone fixture',context:phoneContext,
    stream:{active:true,publisher_connected:true,generation:1,state:'finding',can_capture:false,preview_seq:1,valid_for_ms:1000,video_fps:null},
    view:{capture_id:null,wire_id:null,revision:0}}}));
  if(phoneFixture && url.pathname==='/api/mobile/stream/offer') return new Response(JSON.stringify({type:'answer',sdp:'offline-phone'}));
  if (${assistantQa} && (url.pathname.startsWith('/api/assistant/') || url.pathname === '/api/assistant-qa')) return nativeFetch(input, init);
  if (${assistantQa} && url.pathname === '/api/ai/estimate') return new Response(JSON.stringify({model:'gpt-6-luna',effort:'low',input_tokens:{min:1,max:1},output_tokens:{min:1,max:1},expected_output_tokens:1,api_equivalent_usd:null,reference_credits:null,pricing_checked_at:'QA fixture',unavailable_reason:'unknown_price',api_source:'',credits_source:'',rates:null}));
  if (${assistantQa} && url.pathname.endsWith('/invalidate')) return new Response('{}');
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
  assets.set('/brand/tinkro-light-filter.svg', [await readFile(new URL('brand/tinkro-light-filter.svg', dist)), 'image/svg+xml']);
  assets.set('/demo/distance-monitor-three-wheel-motors-v2.png', [await readFile(new URL('demo/distance-monitor-three-wheel-motors-v2.png', dist)), 'image/png']);
  for (const filename of await readdir(new URL('assets/', dist))) {
    assets.set(`/assets/${filename}`, [await readFile(new URL(`assets/${filename}`, dist)), filename.endsWith('.css') ? 'text/css' : 'text/javascript']);
  }
  const camera = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#10151d"/><text x="640" y="360" text-anchor="middle" fill="#93a4b8" font-family="sans-serif" font-size="24">Offline camera fixture · no hardware connected</text></svg>`;
  assets.set('/video', [camera, 'image/svg+xml']);
  assets.set('/frame.jpg', [camera, 'image/svg+xml']);
  const requests = [];
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    requests.push({method: req.method, path});
    if (assistantQa && (path.startsWith('/api/assistant/') || path === '/api/assistant-qa' || path.startsWith('/api/design/images/'))) {
      try {
        const chunks = []; for await (const chunk of req) chunks.push(chunk);
        const response = await fetch('http://127.0.0.1:18781' + req.url, {method:req.method,
          headers:{'Content-Type':'application/json'},body:req.method === 'GET' ? undefined : Buffer.concat(chunks)});
        res.writeHead(response.status, {'Content-Type':response.headers.get('content-type') || 'application/json'});
        res.end(Buffer.from(await response.arrayBuffer()));
      } catch {res.writeHead(503);res.end('QA backend unavailable');}
      return;
    }
    const asset = assets.get(path);
    if (req.method !== 'GET' || !asset) {res.writeHead(404); res.end('Offline fixture: no proxy'); return;}
    res.writeHead(200, {'Content-Type': asset[1], 'Cache-Control': 'no-store',
      'Content-Security-Policy': `default-src 'self'; connect-src ${assistantQa ? "'self'" : "'none'"}; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-src 'none'`});
    res.end(asset[0]);
  });
  await new Promise((done, reject) => {server.once('error', reject); server.listen(port, '127.0.0.1', done);});
  return {server, requests, url: `http://127.0.0.1:${server.address().port}/`};
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log((await startStagePreview(process.argv.includes('--assistant') ? 18780 : 18776, process.argv.includes('--assistant'))).url);
}
