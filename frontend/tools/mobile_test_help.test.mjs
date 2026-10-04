import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function load(file, modules = {}) {
    const exports = {};
    const js = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
    new Function('require', 'exports', js)(name => { if (!(name in modules)) throw Error(`Unexpected import ${name}`); return modules[name]; }, exports);
    return exports;
}
const turn = () => new Promise(done => setImmediate(done));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const round = () => ({ id: 'photo-review', revision: 1, round: 1, component_id: 'hc-sr04', status: 'collecting', photo_flow_version: 2,
    slots: { pi_side_a: null, pi_side_b: null, component_header: null }, results: [], observations: [], reviews: {}, no_progress_count: 0, missing_roles: ['pi_side_a', 'pi_side_b', 'component_header'] });

async function fixture(run) {
    const saved = Object.fromEntries(['window', 'document', 'WebSocket', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'].map(key => [key, globalThis[key]]));
    globalThis.window = { isSecureContext: true, location: { origin: 'https://phone.test', href: 'https://phone.test/mobile' }, addEventListener() {}, removeEventListener() {} };
    globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
    globalThis.WebSocket = class { static OPEN = 1; static CONNECTING = 0; readyState = 1; close() {} };
    globalThis.setTimeout = globalThis.setInterval = () => 1;
    globalThis.clearTimeout = globalThis.clearInterval = () => {};
    const states = [], refs = [], memos = [], effects = [], cleanups = [];
    let stateCursor = 0, refCursor = 0, memoCursor = 0, effectCursor = 0;
    const hooks = { useState(initial) { const index = stateCursor++; if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
        return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }]; },
        useRef(initial) { const index = refCursor++; return refs[index] ??= { current: initial }; },
        useMemo(callback, deps) { const index = memoCursor++, previous = memos[index]; if (!previous || deps.some((value, i) => value !== previous.deps[i])) memos[index] = { deps, value: callback() }; return memos[index].value; },
        useCallback: callback => callback, useEffect(callback) { const index = effectCursor++; if (!(index in effects)) effects[index] = callback; } };
    const calls = [];
    let contextId = 'context', review = null, override = null;
    const offer = { offer_id: 'offer', message_id: 'message', state: 'pending', can_act: true, can_dismiss: true, component_id: 'hc-sr04', reusable_review: false,
        project_id: 'project', project_revision: 2, guide_run: 1, context_epoch: 0, guide_key: 'selected-test-key', test_id: 'test-run', reason: 'no_echo', mode: 'wiring' };
    let conversation = { id: 'chat', kind: 'project', context_epoch: 0, round: 1, before: null, total: 1, jobs: [],
        messages: [{ id: 'message', role: 'assistant', text: '要拍照檢查接線嗎？', source: 'legacy-debug', epoch: 0, round: 1, stage: 'guide', capability: 'debug', created_at: 1, test_help_offer: offer }] };
    const session = () => ({ session_id: 'phone', conversation_id: 'chat', context_id: contextId, context: { round: 1,
        design: { current: { id: 'project', revision: 2, component_ids: ['hc-sr04'] } }, context: { debug_context: { guide_run: 1,
            guide_confirmations: { wire: { source: 'human', signature: 'saved-human-confirmation', at: 100 } }, test_keys: { 'hc-sr04': 'selected-test-key' } } } },
        view: { capture_id: null, wire_id: null, revision: 1 }, stream: { active: false, generation: 0, state: 'finding', can_capture: false } });
    const snapshot = () => ({ review: structuredClone(review), can_act: Boolean(review), component_label: 'HC-SR04+' });
    const receipt = (op = 'start') => ({ ...snapshot(), offer: { ...conversation.messages[0].test_help_offer,
        state: op === 'later' ? 'dismissed' : 'started', can_act: op !== 'later', can_dismiss: op !== 'later', reusable_review: op !== 'later',
        ...(review ? { review_id: review.id } : {}) } });
    class Api {
        pairing = { token: 'synthetic', session_id: 'phone', conversation_id: 'chat' };
        cancelPending() {}
        async request(path, options = {}) {
            calls.push({ path, method: options.method ?? 'GET', body: options.body, signal: options.signal });
            const result = override?.(path, options); if (result !== undefined) return result;
            if (path === 'session') return session();
            if (path.startsWith('conversation')) return structuredClone(conversation);
            if (path === 'wiring-review' && !options.method) return snapshot();
            if (path === 'wiring-review' && options.body?.invitation) {
                const { invitation } = options.body;
                if (invitation.op === 'start' && !review) review = round();
                const next = receipt(invitation.op); conversation.messages[0].test_help_offer = next.offer; return next;
            }
            throw Error(`Unexpected simulated API call: ${path}`);
        }
    }
    const empty = () => ({ text: '保留草稿', attachments: [], outbox: [], captureJob: null });
    const browser = { MobileBrowserApi: Api, loadBrowserPairing: () => ({ token: 'synthetic', session_id: 'phone', conversation_id: 'chat', context_id: 'context' }),
        emptyBrowserDraft: empty, mobileBrowserDraftKey: () => 'draft-key', loadBrowserDraft: async () => empty(), saveBrowserDraft: async () => {}, saveBrowserPairing() {},
        browserLease: () => ({ key: '', deadline: 0 }), mergeBrowserSession: (_, next) => next,
        mergeBrowserConversation: (_, next) => next, expiredBrowserSession: () => false, browserMediaReference: () => ({ asset_ids: [] }) };
    const domain = load('../src/lib/useMobileBrowser.ts', { react: hooks, './mobileBrowser': browser,
        './mobile': { mobileVideoFresh: () => false }, './mobileViewerStats': { mobileMeasurementFresh: () => false },
        './mobileBrowserRtc': { idleBrowserRtc: () => ({ stats: {}, stream: null }), BrowserPublisher: class { async stop() {} stopLocal() {} } }, './wiringReview': {},
        './assistantAnalysis': load('../src/lib/assistantAnalysis.ts') });
    const render = () => { stateCursor = refCursor = memoCursor = effectCursor = 0; return domain.useMobileBrowser(); };
    try {
        render(); for (const effect of effects) { const cleanup = effect(); if (cleanup) cleanups.push(cleanup); }
        for (let index = 0; index < 4; index++) await turn();
        await run({ render, calls, receipt, snapshot, eligible: domain.mobileTestHelpOffer,
            chat: () => structuredClone(conversation), session, setReview(value) { review = value; }, getReview: () => review,
            setContext(value) { contextId = value; }, setEpoch(value) { conversation.context_epoch = value; },
            setOffer(value) { conversation.messages[0].test_help_offer = { ...conversation.messages[0].test_help_offer, ...value }; },
            onRequest(callback) { override = callback; } });
    } finally { for (const cleanup of cleanups.reverse()) cleanup(); Object.assign(globalThis, saved); }
}

test('mobile actions require the exact persisted offer and current workspace instead of matching text', async () => fixture(async f => {
    const w = f.render(), message = w.conversation.messages[0];
    assert.equal(f.eligible(message, w.session, w.conversation).offer_id, 'offer');
    for (const changed of [
        { ...message, test_help_offer: undefined }, { ...message, role: 'user' }, { ...message, epoch: -1 }, { ...message, round: 0 },
        ...[{ message_id: 'other' }, { state: 'dismissed' }, { state: 'stale' }, { mode: 'setup' }, { project_revision: 3 },
            { guide_key: 'other-key' }, { component_id: 'other' }, { context_epoch: 4 }, { can_act: false, can_dismiss: false }]
            .map(value => ({ ...message, test_help_offer: { ...message.test_help_offer, ...value } })),
    ]) assert.equal(f.eligible(changed, w.session, w.conversation), null);
    assert.equal(f.eligible(message, { ...w.session, available_context: { context_id: 'new-context' } }, w.conversation), null);
    assert.equal(f.calls.filter(call => call.method === 'POST').length, 0, 'reading messages never starts a review');
}));

test('explicit mobile Start uses the existing invitation endpoint and begins the first photo round without a model, camera or confirmation', async () => fixture(async f => {
    let w = f.render(); const confirmations = structuredClone(w.session.context.context.debug_context.guide_confirmations);
    assert.equal(w.wiringReview, null); assert.equal(w.canCapture, false);
    assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), true);
    w = f.render(); assert.equal(w.wiringReview.status, 'collecting'); assert.equal(w.wiringReview.component_id, 'hc-sr04');
    assert.equal(w.wiringReview.slots.pi_side_a, null); assert.equal(w.conversation.messages[0].test_help_offer.state, 'started');
    assert.deepEqual(f.calls.filter(call => call.method === 'POST').map(call => ({ path: call.path, body: call.body })), [
        { path: 'wiring-review', body: { invitation: { op: 'start', message_id: 'message', offer_id: 'offer', context_id: 'context' } } },
    ]);
    assert.deepEqual(w.session.context.context.debug_context.guide_confirmations, confirmations); assert.equal(w.draft, '保留草稿');
}));

test('Later is available when Start is blocked and dismisses only the offer without changing the saved review', async () => fixture(async f => {
    const existing = { ...round(), status: 'ready', revision: 6, reviews: { wire: { decision: 'confirmed', source: 'human', at: 100 } } };
    f.setReview(existing); f.setOffer({ can_act: false, can_dismiss: true });
    let w = f.render(); await w.refresh(); w = f.render(); const message = w.conversation.messages[0];
    assert.equal(f.eligible(message, w.session, w.conversation).can_dismiss, true);
    assert.equal(await w.testHelpAction(message, 'start'), false); assert.equal(await w.testHelpAction(message, 'later'), true);
    w = f.render(); assert.equal(w.conversation.messages[0].test_help_offer.state, 'dismissed'); assert.deepEqual(w.wiringReview, existing);
    assert.equal(f.calls.filter(call => call.method === 'POST').length, 1); assert.equal(f.calls.find(call => call.method === 'POST').body.invitation.op, 'later');
}));

test('Continue keeps the same valid review, revision and human decisions', async () => fixture(async f => {
    const existing = { ...round(), status: 'ready', revision: 8, reviews: { wire: { decision: 'confirmed', source: 'human', at: 100 } } };
    f.setReview(existing); f.setOffer({ state: 'started', reusable_review: true, review_id: existing.id });
    let w = f.render(); await w.refresh(); w = f.render(); assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), true);
    w = f.render(); assert.deepEqual(w.wiringReview, existing); assert.equal(w.conversation.messages[0].test_help_offer.reusable_review, true);
    assert.equal(w.draft, '保留草稿'); assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
}));

test('rapid duplicate clicks share one flight and release the buttons only after the receipt', async () => fixture(async f => {
    const pending = deferred(); f.onRequest((path, options) => path === 'wiring-review' && options.body?.invitation ? pending.promise : undefined);
    let w = f.render(); const message = w.conversation.messages[0], first = w.testHelpAction(message, 'start');
    assert.equal(await w.testHelpAction(message, 'start'), false); w = f.render(); assert.equal(w.testHelpPendingMessageId, message.id); assert.equal(w.wiringReviewBusy, true);
    f.setReview(round()); pending.resolve(f.receipt()); assert.equal(await first, true);
    w = f.render(); assert.equal(w.testHelpPendingMessageId, null); assert.equal(w.wiringReviewBusy, false); assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
}));

test('a failed response leaves the exact offer retryable and an explicit retry clears the inline error', async () => fixture(async f => {
    f.onRequest((path, options) => { if (path === 'wiring-review' && options.body?.invitation) throw Error('response lost'); });
    let w = f.render(); assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), false);
    w = f.render(); assert.deepEqual(w.testHelpError, { messageId: 'message', offerId: 'offer', op: 'start', text: 'response lost' }); assert.equal(w.testHelpPendingMessageId, null);
    assert.equal(f.eligible(w.conversation.messages[0], w.session, w.conversation).offer_id, 'offer');
    f.onRequest(null); assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), true);
    w = f.render(); assert.equal(w.testHelpError, null); assert.equal(w.wiringReview.status, 'collecting'); assert.equal(f.calls.filter(call => call.method === 'POST').length, 2);
    const existing = structuredClone(w.wiringReview);
    f.onRequest((path, options) => { if (path === 'wiring-review' && options.body?.invitation) throw Error('later response lost'); });
    assert.equal(await w.testHelpAction(w.conversation.messages[0], 'later'), false);
    await w.refresh(); w = f.render();
    assert.equal(w.conversation.messages[0].test_help_offer.state, 'started');
    assert.deepEqual(w.testHelpError, { messageId: 'message', offerId: 'offer', op: 'later', text: 'later response lost' }, 'an unchanged started offer does not prove Later succeeded');
    f.onRequest(null); assert.equal(await w.testHelpAction(w.conversation.messages[0], 'later'), true);
    w = f.render(); assert.equal(w.testHelpError, null); assert.equal(w.conversation.messages[0].test_help_offer.state, 'dismissed'); assert.deepEqual(w.wiringReview, existing);
}));

test('joining another context or clearing chat aborts the pending request and discards its late result', async () => {
    for (const change of ['context', 'epoch']) await fixture(async f => {
        const pending = deferred(); f.onRequest((path, options) => path === 'wiring-review' && options.body?.invitation ? pending.promise : undefined);
        let w = f.render(); const result = w.testHelpAction(w.conversation.messages[0], 'start');
        const request = f.calls.find(call => call.method === 'POST');
        if (change === 'context') f.setContext('other-context'); else f.setEpoch(1);
        await w.refresh(); assert.equal(request.signal.aborted, true);
        pending.resolve({ ...f.receipt(), review: round() }); assert.equal(await result, false);
        w = f.render(); assert.equal(w.wiringReview, null); assert.equal(w.testHelpPendingMessageId, null); assert.equal(w.testHelpError, null);
    });
});

test('a rearmed offer and an older conversation response cannot replace the current receipt', async () => fixture(async f => {
    const oldPost = deferred(); f.onRequest((path, options) => path === 'wiring-review' && options.body?.invitation ? oldPost.promise : undefined);
    let w = f.render(); const first = w.testHelpAction(w.conversation.messages[0], 'start'), oldReceipt = { ...f.receipt(), review: round() };
    f.setOffer({ offer_id: 'new-offer' }); await w.refresh(); oldPost.resolve(oldReceipt); assert.equal(await first, false);
    w = f.render(); assert.equal(w.wiringReview, null); assert.equal(w.conversation.messages[0].test_help_offer.offer_id, 'new-offer');
    const oldChat = f.chat(), pendingGet = deferred();
    f.onRequest(path => path.startsWith('conversation') ? pendingGet.promise : undefined);
    const refreshing = w.refresh(); await turn();
    assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), true);
    pendingGet.resolve(oldChat); await refreshing; w = f.render();
    assert.equal(w.conversation.messages[0].test_help_offer.state, 'started'); assert.equal(w.conversation.messages[0].test_help_offer.offer_id, 'new-offer');
    assert.equal(w.wiringReview.status, 'collecting'); assert.equal(w.testHelpError, null);
}));
