// Isolated browser QA: real mobile hook/UI, synthetic video, no production services.
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';

/** Read actual uploaded JPEG SOF dimensions, without a camera or imaging service. */
export function jpegSize(data) {
  if (data[0] !== 0xff || data[1] !== 0xd8) throw Error('Not a JPEG');
  let offset = 2;
  while (offset + 4 <= data.length) {
    if (data[offset++] !== 0xff) continue;
    while (data[offset] === 0xff) offset++;
    const marker = data[offset++];
    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    const length = data.readUInt16BE(offset);
    if (length < 2 || offset + length > data.length) throw Error('Invalid JPEG segment');
    if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker))
      return [data.readUInt16BE(offset + 5), data.readUInt16BE(offset + 3)];
    offset += length;
  }
  throw Error('JPEG has no supported SOF');
}

function multipart(data, contentType) {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType)?.slice(1).find(Boolean);
  if (!boundary) throw Error('Missing multipart boundary');
  const separator = Buffer.from(`--${boundary}`), parts = [];
  let at = data.indexOf(separator);
  while (at >= 0) {
    const start = at + separator.length;
    if (data.subarray(start, start + 2).toString() === '--') break;
    const headEnd = data.indexOf(Buffer.from('\r\n\r\n'), start);
    const next = data.indexOf(separator, headEnd + 4);
    if (headEnd < 0 || next < 0) break;
    const header = data.subarray(start, headEnd).toString();
    const name = /name="([^"]+)"/.exec(header)?.[1];
    const filename = /filename="([^"]*)"/.exec(header)?.[1];
    parts.push({ name, filename, data: data.subarray(headEnd + 4, next - 2) });
    at = next;
  }
  return parts;
}

export async function startMobileCapturePreview(port = 18789, { desktop = false } = {}) {
  const bundle = await build({ entryPoints: [fileURLToPath(new URL(desktop ? './mobile-preview.tsx' : './mobile-capture-preview.tsx', import.meta.url))],
    bundle: true, write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'] });
  const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).contents;
  const css = bundle.outputFiles.find(f => f.path.endsWith('.css')).contents;
  const context = { conversation_id: desktop ? 'preview-conversation' : 'capture-preview-conversation', title: 'Synthetic capture QA',
    stage: 'guide', target: 'auto', round: 0, context_epoch: 0,
    design: { component_ids: ['hc-sr04'], locale: 'zh-TW', model: 'fixture', effort: 'low' }, context: {} };
  const session = { session_id: 'capture-preview-phone', conversation_id: context.conversation_id,
    context_id: 'capture-preview-context', context, title: context.title, base_url: '', available_context: null,
    stream: { active: false, generation: 0, publisher_connected: false, state: 'finding', can_capture: false, preview_seq: 0, valid_for_ms: 0 },
    view: { capture_id: null, wire_id: null, revision: 0 } };
  const requests = [], assets = new Map(), captures = new Map(), tickets = new Map(), captureRequests = new Map();
  let clientMetrics = {}, started = 0, paired = !desktop, unlocked = false;
  const conversation = { id: context.conversation_id, kind: 'project', project_id: null, locale: 'zh-TW',
    messages: [], jobs: [], before: null, total: 0, context_epoch: 0, round: 0, demo: null };
  const pairing = () => ({ token: 'isolated-fixture-token', session_id: session.session_id,
    conversation_id: session.conversation_id, context_id: session.context_id, title: session.title, base_url: session.base_url });
  const update = () => {
    if (session.stream.active && session.stream.publisher_connected) {
      const elapsed = Math.max(0, Date.now() - started);
      Object.assign(session.stream, { state: unlocked ? 'finding' : elapsed >= 1100 ? 'locked' : 'hold_still',
        can_capture: !unlocked && elapsed >= 1100, preview_seq: Math.floor(elapsed * 3 / 1000) + 1,
        valid_for_ms: 1500, video_fps: 30, received_frames: Math.floor(elapsed * 30 / 1000),
        video_received_at: Date.now() / 1000, video_receive_seq: Math.floor(elapsed * 30 / 1000),
        video_receive_age_ms: 0, video_receive_fresh: true,
        video_size: clientMetrics.output_size ?? [1920, 1080], recognition_fps: 3, recognition_ms: 0,
        reason: unlocked ? 'fixture_unlocked' : elapsed >= 1100 ? 'ready_to_capture' : 'hold_still', model_runtime: {}, quality: {},
        publisher_codec: 'video/H264', codec_source: 'negotiated_sdp' });
    }
    return session;
  };
  const makeCapture = (asset, source) => {
    const [w, h] = [asset.width, asset.height], frameId = Date.now(), id = `fixture-capture-${captures.size + 1}`;
    const quad = (x, y, width, height) => [[x*w, y*h], [(x+width)*w, y*h], [(x+width)*w, (y+height)*h], [x*w, (y+height)*h]];
    const outline = quad(.08, .18, .46, .5), componentOutline = quad(.64, .3, .30, .3);
    const pin = (id, x, y) => ({ id, x: x*w, y: y*h, c: .9, v: true });
    const pose = { frame_id: frameId, runtime_revision: session.stream.generation, tracking: 'locked', video_size: [w, h] };
    return { capture_id: id, asset_id: asset.id, session_id: session.session_id, context_id: session.context_id,
      conversation_id: session.conversation_id, camera_id: 'synthetic-mobile', source: 'mobile', capture_source: source,
      image_url: asset.url, image_sha256: asset.sha256, video_size: [w, h], original_size: [w, h], analysis_limited: false,
      frame_id: frameId, runtime_revision: pose.runtime_revision, captured_at: new Date().toISOString(), quality: {},
      same_frame: true, stale: false, electrical_verified: false, coordinates_are_hints_only: true,
      detection: { ...pose, board_id: 'raspberry-pi-5', outline, pins: [pin('GPIO17', .19, .62), pin('GND_P6', .31, .62)] },
      components: [{ ...pose, component_id: 'hc-sr04', outline: componentOutline, pins: [pin('TRIG', .71, .55), pin('GND', .85, .55)] }],
      localization: [['raspberry-pi-5', outline], ['hc-sr04', componentOutline]].map(([object_id, points]) => ({ object_id,
        status: 'located', method: 'synthetic_fixture_only', reason: 'not_physical_GPIO_evidence',
        evidence: { board_geometry_verified: true, pin_geometry_verified: true }, raw_outline_px: points, corrected_outline_px: points })),
      wires: [{ wire_id: 'fixture-wire', component_id: 'hc-sr04', board_pin: 'GPIO17', component_pin: 'TRIG', connection_kind: 'direct' }] };
  };
  const desktopAsset = () => {
    const id = `fixture-asset-${assets.size+1}`, width = 1920, height = 1080;
    const bytes = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#d4e4e9"/><rect x="153.6" y="194.4" width="883.2" height="540" fill="#337c59"/><rect x="1228.8" y="324" width="576" height="324" fill="#377bc2"/><text x="180" y="380" fill="white" font-size="52">Synthetic Pi 5</text><text x="1260" y="450" fill="white" font-size="42">HC-SR04</text><text x="80" y="1030" fill="#173042" font-size="30">Isolated desktop capture fixture, no camera or physical GPIO</text></svg>`);
    const asset = { id, type: 'image', mime: 'image/svg+xml', filename: 'synthetic-stream-frame.svg', width, height,
      original_width: width, original_height: height, analysis_limited: false, duration: null, size: bytes.length,
      url: `/api/mobile/assets/${id}/file`, thumbnail_url: `/api/mobile/assets/${id}/thumbnail`,
      sha256: createHash('sha256').update(bytes).digest('hex'), bytes };
    assets.set(id, asset); return asset;
  };
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, session.base_url || 'http://127.0.0.1'), path = url.pathname;
      const chunks = []; let total = 0;
      for await (const chunk of req) { total += chunk.length; if (total > 16*1024*1024) throw Error('Fixture request too large'); chunks.push(chunk); }
      const data = Buffer.concat(chunks), type = req.headers['content-type'] || '';
      const body = type.includes('application/json') && data.length ? JSON.parse(data.toString()) : {};
      requests.push({ path, method: req.method, body: path === '/__fixture/metrics' ? {} : body });
      const send = (value, status = 200, contentType = 'application/json') => {
        res.writeHead(status, { 'Content-Type': contentType, 'Cache-Control': 'no-store' });
        res.end(contentType === 'application/json' ? JSON.stringify(value) : value);
      };
      if (path === '/' || path === '/mobile') { unlocked = url.searchParams.has('unlocked');
        return send(`<!doctype html><html lang="zh-TW" data-theme="dark"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated ${desktop ? 'desktop' : 'phone'} capture QA</title><link rel="stylesheet" href="/preview.css"><div id="root"></div><script>window.__MOBILE_CAPTURE_FIXTURE__=${JSON.stringify(pairing())}</script><script type="module" src="/preview.js"></script></html>`, 200, 'text/html'); }
      if (path === '/preview.js') return send(js, 200, 'text/javascript');
      if (path === '/preview.css') return send(css, 200, 'text/css');
      if (path === '/brand/tinkro-dark.png') return send(await readFile(new URL('../public/brand/tinkro-dark.png', import.meta.url)), 200, 'image/png');
      if (path === '/brand/tinkro-light-filter.svg') return send(await readFile(new URL('../public/brand/tinkro-light-filter.svg', import.meta.url)), 200, 'image/svg+xml');
      if (path === '/__fixture/metrics') { clientMetrics = { ...clientMetrics, ...body }; return send({ ok: true }); }
      if (path === '/__fixture/state') return send({ type: 'state', kind: 'synthetic_only', session: paired ? update() : null, context,
        diagnostics: { ...clientMetrics, unlocked }, uploads: [...assets.values()].map(({ bytes, ...asset }) => asset), captures: [...captures.values()],
        request_counts: Object.fromEntries([...new Set(requests.map(r => `${r.method} ${r.path}`))].map(key => [key, requests.filter(r => `${r.method} ${r.path}` === key).length])) });
      if (path === '/__fixture/requests') return send(requests.filter(r => !r.path.startsWith('/__fixture/')));
      if (path === '/__fixture/events') return send(paired ? { type: 'state', session: update() } : { type: 'disconnected', session: null });
      if (desktop && path === '/__fixture/pair') { paired = true; started = Date.now()-1500;
        Object.assign(session.stream, { active: true, generation: 1, publisher_connected: true }); return send({ ok: true }); }
      if (desktop && path === '/__fixture/disconnect') { paired = false; return send({ ok: true }); }
      if (desktop && path === '/api/mobile/context') { Object.assign(context, body); return send({ context_id: session.context_id }); }
      if (desktop && path === '/api/mobile/pairings') return send({ code: '482913',
        qr_payload: { type: 'tinkro-mobile', code: '482913', base_url: session.base_url },
        expires_at: Date.now()/1000+120, base_urls: [session.base_url] });
      if (desktop && path === '/api/mobile/desktop-session') return send({ type: 'state', session: paired ? update() : null, context });
      if (desktop && (path === '/api/mobile/stream-capture' || path === '/__fixture/photo')) {
        if (!paired || !session.stream.active) return send({ detail: 'mobile_stream_frame_unavailable' }, 409);
        if (body.request_id && captureRequests.has(body.request_id)) return send(captureRequests.get(body.request_id));
        const asset = desktopAsset(), capture = makeCapture(asset, 'desktop_stream');
        capture.stream_identity = { session_id: session.session_id, generation: session.stream.generation,
          frame_seq: update().stream.received_frames, received_at: Date.now()/1000 };
        captures.set(capture.capture_id, capture); if (body.request_id) captureRequests.set(body.request_id, capture);
        session.view = { capture_id: capture.capture_id, wire_id: 'fixture-wire', revision: session.view.revision+1 };
        return send(capture);
      }
      if (path === '/api/mobile/pair' && req.method === 'POST') { paired = true; return send(pairing()); }
      if (!paired) return send({ detail: 'mobile_session_expired_or_invalid' }, 401);
      if (path === '/api/mobile/session' && req.method === 'DELETE') { paired = false; return send(null, 204); }
      if (path === '/api/mobile/session') return send(update());
      if (path === '/api/mobile/conversation') return send(conversation);
      if (path === '/api/mobile/stream' && req.method === 'POST') {
        session.stream = { active: true, generation: session.stream.generation + 1, publisher_connected: false,
          state: 'finding', can_capture: false, preview_seq: 0, valid_for_ms: 0, bitrate_kbps: body.bitrate_kbps ?? 8000 };
        return send(session.stream);
      }
      if (path === '/api/mobile/stream' && req.method === 'DELETE') {
        Object.assign(session.stream, { active: false, publisher_connected: false, can_capture: false, state: 'finding', valid_for_ms: 0 });
        return send(session.stream);
      }
      if (path === '/api/mobile/stream/offer') { started = Date.now(); session.stream.publisher_connected = true;
        return send({ type: 'answer', sdp: 'isolated-no-network', codec: 'video/H264', generation: session.stream.generation }); }
      if (path === '/api/mobile/stream/metrics') return send({ ok: true });
      if (path === '/api/mobile/capture-ticket') {
        update(); if (!session.stream.can_capture) return send({ detail: 'mobile_capture_not_locked' }, 409);
        const ticket = { ticket_id: `fixture-ticket-${tickets.size+1}`, expires_at: Date.now()/1000+120,
          context_id: session.context_id, generation: session.stream.generation, preview_seq: session.stream.preview_seq };
        tickets.set(ticket.ticket_id, ticket); return send(ticket);
      }
      if (path === '/api/mobile/assets' && req.method === 'POST') {
        const parts = multipart(data, type), file = parts.find(p => p.name === 'file');
        if (!file) return send({ detail: 'missing_file' }, 422);
        const [width, height] = jpegSize(file.data), id = `fixture-asset-${assets.size+1}`;
        const asset = { id, type: 'image', mime: 'image/jpeg', filename: file.filename, width, height,
          original_width: width, original_height: height, analysis_limited: false, duration: null, size: file.data.length,
          url: `/api/mobile/assets/${id}/file`, thumbnail_url: `/api/mobile/assets/${id}/thumbnail`,
          sha256: createHash('sha256').update(file.data).digest('hex'), bytes: file.data };
        assets.set(id, asset); const { bytes, ...info } = asset; return send(info);
      }
      if (path === '/api/mobile/captures' && req.method === 'POST') {
        if (captureRequests.has(body.request_id)) return send(captureRequests.get(body.request_id));
        const ticket = tickets.get(body.ticket_id), asset = assets.get(body.asset_id);
        if (!ticket || !asset || ticket.context_id !== session.context_id) return send({ detail: 'invalid_capture' }, 409);
        const capture = makeCapture(asset, body.capture_source ?? 'camera_photo');
        captures.set(capture.capture_id, capture); captureRequests.set(body.request_id, capture);
        session.view = { capture_id: capture.capture_id, wire_id: 'fixture-wire', revision: session.view.revision+1 };
        conversation.active_media = { asset_ids: [asset.id], capture_id: capture.capture_id, epoch: 0, round: 0,
          attachments: [{ ...Object.fromEntries(Object.entries(asset).filter(([key]) => key !== 'bytes')), asset_id: asset.id }] };
        return send(capture);
      }
      const capturePath = /^\/api\/mobile\/captures\/([A-Za-z0-9_-]+)$/.exec(path);
      if (capturePath) return captures.has(capturePath[1]) ? send(captures.get(capturePath[1])) : send({ detail: 'not_found' }, 404);
      const captureImagePath = /^\/api\/mobile\/captures\/([A-Za-z0-9_-]+)\/image$/.exec(path);
      if (captureImagePath) { const asset = assets.get(captures.get(captureImagePath[1])?.asset_id);
        return asset ? send(asset.bytes, 200, asset.mime) : send({ detail: 'not_found' }, 404); }
      const assetPath = /^\/api\/mobile\/assets\/([A-Za-z0-9_-]+)\/(file|thumbnail)$/.exec(path);
      if (assetPath) { const asset = assets.get(assetPath[1]); return asset ? send(asset.bytes, 200, asset.mime) : send({ detail: 'not_found' }, 404); }
      if (path === '/api/mobile/view' && req.method === 'PUT') { session.view = { ...body, revision: session.view.revision+1 }; return send(session.view); }
      if (path === '/api/mobile/messages' && req.method === 'POST') {
        const attachments = (body.asset_ids ?? []).map(id => assets.get(id)).filter(Boolean).map(({ bytes, ...asset }) => ({ ...asset, asset_id: asset.id, image_url: asset.url }));
        conversation.messages.push({ id: `fixture-user-${conversation.messages.length}`, role: 'user', text: body.text,
          attachments, created_at: Date.now()/1000, epoch: 0, round: 0, source: 'mobile' }); conversation.total = conversation.messages.length; return send(conversation, 202);
      }
      return send({ detail: 'This isolated fixture has no production route' }, 404);
    } catch (error) { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ detail: String(error) })); }
  });
  await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
  session.base_url = `http://127.0.0.1:${server.address().port}`;
  return { url: session.base_url + '/mobile', server, requests };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const desktop = process.argv.includes('--desktop');
  const port = process.argv.slice(2).map(Number).find(Number.isInteger) || (desktop ? 18790 : 18789);
  console.log((await startMobileCapturePreview(port, { desktop })).url);
}
