// Loopback-only QA server. No production, hardware or model calls.
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { build } from 'esbuild';
export async function startPreview(port = 18808) {
    const bundle = await build({ entryPoints: [fileURLToPath(new URL('component-test-help-preview.tsx', import.meta.url))], bundle: true,
        write: false, outdir: 'preview', jsx: 'automatic', external: ['/brand/*'] });
    const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).contents;
    const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).contents;
    const chat = { id: 'help-fixture-conversation', kind: 'project', project_id: 'help-fixture-project', locale: 'zh-TW',
        messages: [], jobs: [], before: null, total: 0, context_epoch: 0, round: 2, demo: null };
    const requests = []; let publishedContext = null;
    const session = () => ({ session_id: 'help-fixture-phone', conversation_id: chat.id, context_id: 'help-fixture-context', title: '隔離測試協助',
        context: publishedContext ?? { round: 2, stage: 'guide' }, available_context: { context_id: 'help-fixture-context' },
        stream: { active: false, generation: 0, state: 'finding', can_capture: false }, view: { capture_id: null, wire_id: null, revision: 0 } });
    const server = createServer(async (request, response) => {
        const path = new URL(request.url, 'http://127.0.0.1').pathname;
        const chunks = []; for await (const chunk of request) chunks.push(chunk);
        const body = request.headers['content-type']?.includes('application/json') ? JSON.parse(Buffer.concat(chunks).toString() || '{}') : {};
        requests.push({ path, method: request.method, body, bearer: request.headers.authorization === 'Bearer synthetic-phone-token' });
        const send = (value, status = 200, type = 'application/json') => { response.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' }); response.end(type === 'application/json' ? JSON.stringify(value) : value); };
        if (path === '/' || path === '/phone') return send('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Component test help isolated QA</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/preview.css"><div id="root"></div><script type="module" src="/preview.js"></script></html>', 200, 'text/html');
        if (path === '/preview.js') return send(js, 200, 'text/javascript');
        if (path === '/preview.css') return send(css, 200, 'text/css');
        if (path.startsWith('/brand/')) return send('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="40"><text x="0" y="30" fill="#29b7a6" font-size="30">tinkro</text></svg>', 200, 'image/svg+xml');
        if (path === '/__fixture/requests') return send(requests);
        if (path === '/__fixture/state') return send({ chat, publishedContext });
        if (path === '/api/assistant/conversations') return send(chat);
        if (path === `/api/assistant/conversations/${chat.id}`) return send(chat);
        if (path === `/api/assistant/conversations/${chat.id}/messages`) {
            await new Promise(done => setTimeout(done, 600));
            chat.messages.push({ id: `u-${chat.messages.length}`, role: 'user', text: body.text, source: 'desktop', created_at: 110, stage: body.stage, capability: 'debug', epoch: 0, round: 2 },
                { id: `a-${chat.messages.length + 1}`, role: 'assistant', text: '這是隔離 QA 回覆。先確認測試環境與症狀；測試失敗本身不代表接線錯誤。', source: 'mock', created_at: 111, stage: 'guide', capability: 'debug', epoch: 0, round: 2 });
            chat.total = chat.messages.length; return send(chat);
        }
        if (path === '/api/mobile/context') { publishedContext = body; return send({ context_id: 'help-fixture-context' }); }
        if (path === '/api/mobile/desktop-session') return send({ session: null });
        if (path === '/api/mobile/session') return request.headers.authorization === 'Bearer synthetic-phone-token' ? send(session()) : send({ detail: 'mobile_session_expired_or_invalid' }, 401);
        if (path === '/api/mobile/conversation') return request.headers.authorization === 'Bearer synthetic-phone-token' ? send(chat) : send({ detail: 'mobile_session_expired_or_invalid' }, 401);
        if (path === '/api/mobile/wiring-review') return send({ review: null, can_act: false });
        if (path === '/api/mobile/stream' && request.method === 'DELETE') return send(session());
        return send({ detail: 'No production route in this isolated fixture' }, 404);
    });
    await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
    return { url: `http://127.0.0.1:${server.address().port}/`, server, requests };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log((await startPreview()).url);
