// No production API, camera, AI or Pi. This fixture renders the real mobile UI/hooks.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';

export async function startPreview(port = 18798, { partsCheck = false } = {}) {
    const directory = fileURLToPath(new URL('../', import.meta.url));
    const bundle = await build({ entryPoints: [fileURLToPath(new URL('mobile-wiring-preview.tsx', import.meta.url))], bundle: true,
        write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'], plugins: [{ name: 'fixture-translation', setup(builder) {
            builder.onResolve({ filter: /\/lib\/useMaker$/ }, () => ({ path: 'translation', namespace: 'fixture' }));
            builder.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ resolveDir: directory, contents: 'export const useMakerText=()=> (zh,en)=>new URLSearchParams(location.search).get("lang")==="en"?en:zh;' }));
        } }] });
    const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents;
    const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
    const roles = ['pi_side_a', 'pi_side_b', 'component_header'];
    const picture = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#dce8e8"/><rect x="90" y="550" width="1020" height="140" fill="#37725b"/>${Array.from({ length: 10 }, (_, n) => `<rect x="${180 + n * 85}" y="330" width="52" height="220" fill="#243849"/><path d="M${206 + n * 85} 330V140" stroke="${['#cd5355', '#d5b838', '#4498c9'][n % 3]}" stroke-width="22"/>`).join('')}<text x="600" y="810" text-anchor="middle" fill="#25414b" font-size="32">SYNTHETIC PHONE PHOTO — no physical evidence</text></svg>`;
    const fresh = (round = 1, revision = 1) => ({ id: 'fixture-review', revision, round, component_id: 'hc-sr04', status: 'collecting', photo_flow_version: 2,
        slots: Object.fromEntries(roles.map(role => [role, null])), observations: [], results: [], reviews: {}, missing_roles: [...roles], no_progress_count: 0 });
    let review = fresh(), assetIndex = 0, failUpload = false, delayUpload = false;
    const requests = [], assets = new Set();
    const snapshot = () => partsCheck ? { review: null, can_act: false } : ({ review: structuredClone(review), component_label: 'HC-SR04', can_act: review.status !== 'analysing' });
    const session = { session_id: 'fixture-phone', conversation_id: 'fixture-conversation', context_id: 'fixture-context', title: '接線照片對話測試',
        context: { round: 1, stage: partsCheck ? 'design' : 'guide', design: { locale: 'zh-TW' } }, available_context: { context_id: 'fixture-context' }, stream: { active: false, generation: 0, state: 'finding', can_capture: false },
        view: { capture_id: null, wire_id: null, revision: 0 } };
    const chat = { id: 'fixture-conversation', messages: [{ id: 'start', role: 'assistant', text: '我會陪你一張一張拍。先保持接線不變，我們從 Pi 第一側開始。', source: 'fixture', created_at: 1, epoch: 0, round: 1 }],
        jobs: [], before: null, total: 1, context_epoch: 0, round: 1, locale: 'zh-TW' };
    if (partsCheck) chat.messages[0].text = '隔離測試：本次只核對 Pi 5、超音波與 TFT，不分析接線，也不呼叫真實 AI。';
    const html = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Actual mobile photo dialogue — isolated fixture</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>';
    const server = createServer(async (request, response) => {
        const path = new URL(request.url, 'http://127.0.0.1').pathname;
        const chunks = []; for await (const chunk of request) chunks.push(chunk);
        let body = {}; if (request.headers['content-type']?.includes('application/json')) body = JSON.parse(Buffer.concat(chunks).toString() || '{}');
        requests.push({ path, method: request.method, body, bearer: request.headers.authorization === 'Bearer synthetic-phone-token' });
        const send = (value, status = 200, type = 'application/json') => { response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }); response.end(type === 'application/json' ? JSON.stringify(value) : value); };
        if (path === '/') return send(html, 200, 'text/html');
        if (path === '/preview.js') return send(js, 200, 'text/javascript');
        if (path === '/preview.css') return send(css, 200, 'text/css');
        if (path.startsWith('/brand/')) return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="0" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>', 200, 'image/svg+xml');
        if (path === '/__fixture/requests') return send(requests);
        if (path === '/__fixture/state') return send(snapshot());
        if (path === '/__fixture/fail-next-upload') { failUpload = true; return send({ ok: true }); }
        if (path === '/__fixture/delay-next-upload') { delayUpload = true; return send({ ok: true }); }
        if (path === '/__fixture/new-round') { review = fresh(review.round + 1, review.revision + 1); return send(snapshot()); }
        if (path === '/__fixture/photo.svg') return send(picture, 200, 'image/svg+xml');
        if (path.startsWith('/api/mobile/') && request.headers.authorization !== 'Bearer synthetic-phone-token') return send({ detail: 'mobile_session_expired_or_invalid' }, 401);
        if (path === '/api/mobile/session') return send(session);
        if (path === '/api/mobile/conversation') return send(chat);
        if (path === '/api/mobile/messages' && request.method === 'POST' && partsCheck) {
            if (body.purpose !== 'parts_check' || body.inherit_media !== false || !body.asset_ids?.length || body.asset_ids.some(id => !assets.has(id)))
                return send({ detail: 'fixture_expected_explicit_parts_check' }, 422);
            chat.messages.push({ id: body.request_id, role: 'user', text: '模擬收到：請核對本次零件照片，不檢查接線。', source: 'fixture', created_at: 2, epoch: 0, round: 1 });
            chat.messages.push({ id: `${body.request_id}-reply`, role: 'assistant', text: '本機模擬回覆：三項硬體皆無法確認。這不是實際 AI 或硬體驗證。', source: 'fixture', created_at: 3, epoch: 0, round: 1 });
            chat.total = chat.messages.length;
            return send(chat);
        }
        if (path === '/api/mobile/stream' && request.method === 'DELETE') return send(session);
        if (path === '/api/mobile/wiring-review' && request.method === 'GET') return send(snapshot());
        if (path === '/api/mobile/assets') {
            if (failUpload) { failUpload = false; return send({ detail: 'synthetic_upload_failed' }, 503); }
            if (delayUpload) { delayUpload = false; await new Promise(done => setTimeout(done, 1500)); }
            const id = `fixture-asset-${++assetIndex}`; assets.add(id);
            return send({ id, type: 'image', mime: 'image/svg+xml', width: 1200, height: 900, size: 5000, duration: null, filename: 'synthetic-photo.svg', url: `/api/mobile/assets/${id}/file` });
        }
        if (/^\/api\/mobile\/assets\/[^/]+\/file$/.test(path)) return send(picture, 200, 'image/svg+xml');
        if (/^\/api\/mobile\/wiring-review\/evidence\//.test(path)) return send(picture, 200, 'image/svg+xml');
        if (path === '/api/mobile/wiring-review' && request.method === 'POST') {
            const action = body.action;
            if (action.review_id !== review.id || action.revision !== review.revision) return send({ detail: 'stale_wiring_review' }, 409);
            if (action.op === 'capture') {
                if (!roles.includes(action.role) || !assets.has(body.asset_id)) return send({ detail: 'synthetic_asset_missing' }, 409);
                const id = `${body.asset_id}-${action.role}`;
                review.slots[action.role] = { role: action.role, capture_id: id, sha256: `fixture-hash-${id}`, size: [1200, 900],
                    image_url: `/api/mobile/wiring-review/evidence/${id}`, crop: null, crop_source: 'none', available: true };
                review.missing_roles = roles.filter(role => !review.slots[role]);
            } else if (action.op === 'accept_photo') {
                const slot = review.slots[action.role];
                if (!slot || slot.capture_id !== action.capture_id || slot.sha256 !== action.sha256) return send({ detail: 'stale_wiring_review' }, 409);
                slot.photo_acceptance = { capture_id: slot.capture_id, sha256: slot.sha256, round: review.round, accepted_at: 1, source: 'human' };
            } else if (action.op === 'analyse') {
                if (roles.some(role => !review.slots[role]?.photo_acceptance)) return send({ detail: 'wiring_review_photos_not_accepted' }, 409);
                review.status = 'ready'; review.results = [{ wire_id: 'trig', expected: { physical_pin: 11, bcm: 17, component_pin: 'TRIG' },
                    pi_candidates: [], component_candidates: [], comparison: 'unknown', next_step: '模擬分析：請回到電腦，親自沿線核對。' }];
            } else return send({ detail: 'mobile_wiring_review_action_not_allowed' }, 409);
            review.revision++; return send(snapshot());
        }
        return send({ detail: 'No production route in this fixture' }, 404);
    });
    await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
    return { url: `http://127.0.0.1:${server.address().port}/`, server, requests };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log((await startPreview()).url);
