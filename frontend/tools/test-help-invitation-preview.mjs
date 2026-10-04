// Loopback-only transport for the actual invitation/card/assistant/debug/phone UI.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { build } from 'esbuild';
export async function startPreview(port = 18808) {
    const bundle = await build({ entryPoints: [fileURLToPath(new URL('test-help-invitation-preview.tsx', import.meta.url))], bundle: true,
        write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'] });
    const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents, css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
    const roles = ['pi_side_a', 'pi_side_b', 'component_header'];
    const chat = { id: 'invitation-fixture-conversation', kind: 'project', project_id: 'invitation-fixture-project', locale: 'zh-TW',
        messages: [], jobs: [], before: null, total: 0, context_epoch: 0, round: 2, demo: null };
    let requests = [], publishedContext = null, debugRecord = null, debugConversation = null, seedReview = false;
    const imports = new Set();
    // Exact Python json.dumps(list-of-strings, sort_keys=True, ensure_ascii=False) fingerprint.
    const importKey = (sourceId, message) => createHash('sha256').update('[' + [sourceId, message.id, message.role, message.text]
        .map(value => JSON.stringify(value)).join(', ') + ']').digest('hex');
    function readChat(before = null) {
        const end = Math.min(before === null ? chat.messages.length : Number(before), chat.messages.length), start = Math.max(0, end - 50);
        return { ...chat, messages: chat.messages.slice(start, end), before: start || null, total: chat.messages.length };
    }
    const phoneSession = () => ({ session_id: 'invitation-fixture-phone', conversation_id: chat.id, context_id: 'invitation-fixture-context', title: '隔離拍照邀請 QA',
        context: publishedContext ?? { round: 2, stage: 'guide' }, available_context: { context_id: 'invitation-fixture-context' },
        stream: { active: false, generation: 0, state: 'finding', can_capture: false }, view: { capture_id: null, wire_id: null, revision: 0 } });
    function createSession(context, symptom, purpose = 'wiring_review') {
        debugConversation = { id: 'invitation-fixture-debug-conversation', project_id: chat.project_id, archived: false, check_ids: ['invitation-fixture-debug'], messages: [], evidence: [], diagrams: [] };
        debugRecord = { id: 'invitation-fixture-debug', conversation_id: debugConversation.id, status: 'awaiting_capture', phase: 'awaiting_user', symptom,
            instruction: '請選擇要核對的零件。', context, purpose, wiring_target: context.wiring_target, camera: { source: 'device', runtime_revision: 1 }, camera_current: true,
            current_target: true, conversation_current: true, binding: { project_id: chat.project_id, code_hash: 'fixture-code-hash', test_keys: context.test_keys },
            model_busy: false, jobs: [], test_results: [], observations: [], evidence: [], messages: [], capture_task: null, created_at: 100, updated_at: 100,
            budget: { model_calls: 0, max_model_calls: 6, tests: {}, max_tests_per_component: 2, captures: 0, max_captures: 20 }, wiring_review: null, response_mode: 'fast' };
        return debugRecord;
    }
    function newReview(component_id) {
        return { id: 'invitation-fixture-review', revision: 1, round: 1, component_id, status: 'collecting', photo_flow_version: 2,
            slots: Object.fromEntries(roles.map(role => [role, null])), observations: [], results: [], reviews: {}, missing_roles: [...roles], no_progress_count: 0 };
    }
    function maybeSeed() {
        if (!seedReview || !publishedContext?.context?.debug_context) return;
        const dc = publishedContext.context.debug_context;
        const context = { ...dc, project: publishedContext.design.current, code: dc.code, locale: 'zh-TW', guide_run: publishedContext.round,
            wiring_target: dc.wiring_target ?? { component_id: 'hc-sr04', wire_id: publishedContext.design.current.wiring[0].id } };
        createSession(context, 'Saved review fixture');
        const review = newReview(context.wiring_target.component_id);
        review.revision = 4; review.status = 'ready'; review.missing_roles = [];
        review.results = [{ wire_id: context.project.wiring[0].id, expected: { physical_pin: 6, bcm: null, component_pin: 'GND', board_pin: 'GND_P6' },
            pi_candidates: [], component_candidates: [], comparison: 'unknown', next_step: 'Saved fixture observation; trace the physical wire.' }];
        review.reviews[review.results[0].wire_id] = { decision: 'confirmed', source: 'human', at: 100, review_revision: 4, evidence_stale: false };
        debugRecord.wiring_review = review; debugRecord.phase = 'wiring_review'; seedReview = false;
    }
    const server = createServer(async (request, response) => {
        const url = new URL(request.url, 'http://127.0.0.1'), path = url.pathname;
        const chunks = []; for await (const chunk of request) chunks.push(chunk);
        const body = request.headers['content-type']?.includes('application/json') ? JSON.parse(Buffer.concat(chunks).toString() || '{}') : {};
        requests.push({ path, query: url.search, method: request.method, body, bearer: request.headers.authorization === 'Bearer synthetic-phone-token' });
        const send = (value, status = 200, type = 'application/json') => { response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }); response.end(type === 'application/json' ? JSON.stringify(value) : value); };
        if (path === '/' || path === '/phone') return send('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Test-help invitation isolated QA</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>', 200, 'text/html');
        if (path === '/preview.js') return send(js, 200, 'text/javascript'); if (path === '/preview.css') return send(css, 200, 'text/css');
        if (path.startsWith('/brand/')) return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="0" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>', 200, 'image/svg+xml');
        if (path === '/__fixture/requests') return send(requests);
        if (path === '/__fixture/state') return send({ chat, publishedContext, debugRecord });
        if (path === '/__fixture/unrelated-message') {
            chat.messages.push({ id: 'unrelated-fixture-message', role: 'assistant', text: '隔離測試：這是較晚且無關的長回覆。\n' + '無關內容；不代表接線診斷。\n'.repeat(60),
                source: 'fixture', capability: 'answer', stage: 'guide', epoch: chat.context_epoch, round: 2, created_at: Date.now() / 1000 });
            chat.total = chat.messages.length; return send(chat);
        }
        if (path === '/__fixture/competing-messages') {
            const offer = chat.messages.find(message => message.source === 'legacy-debug' && message.text.includes('要拍照檢查接線嗎？'));
            if (!offer) return send({ detail: 'Create invitation first' }, 409);
            chat.messages.push({ ...offer, id: 'same-text-older-context', epoch: chat.context_epoch - 1 },
                { ...offer, id: 'same-text-older-round', round: 1 }, { ...offer, id: 'same-text-wrong-source', source: 'fixture' });
            chat.total = chat.messages.length; return send(chat);
        }
        if (path === '/__fixture/other-issue-message') {
            const offer = chat.messages.find(message => message.source === 'legacy-debug' && message.text.includes('要拍照檢查接線嗎？'));
            if (!offer) return send({ detail: 'Create invitation first' }, 409);
            const alternate = { ...offer, id: 'same-text-current-other-issue', created_at: Date.now() / 1000 };
            alternate.import_key = importKey('test-help:synthetic-different-test-id', alternate);
            chat.messages.push(alternate); chat.total = chat.messages.length; return send(chat);
        }
        if (path === '/__fixture/offscreen-messages') {
            for (let index = 0; index < 65; index += 1) chat.messages.push({ id: `synthetic-later-message-${index}`, role: 'assistant',
                text: `隔離較晚紀錄 ${index + 1}；未執行 AI 或硬體。`, source: 'fixture', capability: 'answer', stage: 'guide',
                epoch: chat.context_epoch, round: 2, created_at: Date.now() / 1000 });
            chat.total = chat.messages.length; return send(readChat());
        }
        if (path === '/__fixture/reset') { requests = []; chat.messages = []; chat.jobs = []; chat.total = 0; chat.context_epoch = 0; imports.clear(); debugRecord = null; debugConversation = null; publishedContext = null;
            seedReview = url.searchParams.get('reuse') === '1'; return send({ ok: true }); }
        if (path === '/api/assistant/conversations' || path === `/api/assistant/conversations/${chat.id}`) return send(readChat(url.searchParams.get('before')));
        if (path === `/api/assistant/conversations/${chat.id}/import`) {
            if (!imports.has(body.source_id)) { imports.add(body.source_id);
                for (const message of body.messages ?? []) chat.messages.push({ ...message, id: randomUUID().replaceAll('-', ''), import_key: importKey(body.source_id, message), source: body.kind, capability: 'debug', epoch: chat.context_epoch, round: message.round ?? 2 });
                chat.total = chat.messages.length;
            } return send(readChat());
        }
        if (path === `/api/assistant/conversations/${chat.id}/reset` && body.mode === 'clear') {
            chat.context_epoch += 1; return send(readChat());
        }
        if (path === '/api/debug/sessions' && request.method === 'GET') { maybeSeed(); return send({ active: debugRecord }); }
        if (path === '/api/debug/sessions' && request.method === 'POST') return send(createSession(body.context, body.symptom, body.purpose));
        if (path === '/api/debug/conversations') return send({ conversation: debugConversation });
        if (path === '/api/debug/sessions/invitation-fixture-debug') return debugRecord ? send(debugRecord) : send({ detail: 'session_not_found' }, 404);
        if (path === '/api/debug/sessions/invitation-fixture-debug/actions') {
            if (body.action !== 'wiring_review' || body.wiring_review?.op !== 'start') return send({ detail: 'Fixture only permits explicit photo-review start' }, 409);
            if (!debugRecord) return send({ detail: 'session_not_found' }, 404);
            debugRecord.wiring_review = newReview(body.wiring_review.component_id); debugRecord.phase = 'wiring_review';
            debugRecord.instruction = '請拍摄 Pi 排針兩側與零件接頭；保持這輪接線不變。'; return send(debugRecord);
        }
        if (path === '/api/mobile/context') { publishedContext = body; return send({ context_id: 'invitation-fixture-context' }); }
        if (path === '/api/mobile/desktop-session') return send({ session: null });
        if (path.startsWith('/api/mobile/') && request.headers.authorization !== 'Bearer synthetic-phone-token') return send({ detail: 'mobile_session_expired_or_invalid' }, 401);
        if (path === '/api/mobile/session') return send(phoneSession());
        if (path === '/api/mobile/conversation') return send(chat);
        if (path === '/api/mobile/wiring-review') return send({ review: debugRecord?.wiring_review ?? null, component_label: 'HC-SR04+', can_act: Boolean(debugRecord?.wiring_review) });
        if (path === '/api/mobile/stream' && request.method === 'DELETE') return send(phoneSession());
        return send({ detail: 'No production/model/hardware route in this fixture' }, 404);
    });
    await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
    return { url: `http://127.0.0.1:${server.address().port}/`, server };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log((await startPreview()).url);
