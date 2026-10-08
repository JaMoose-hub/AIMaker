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
const reviewDomain = load('../src/lib/wiringReview.ts');
const round = (revision = 1, number = 1) => ({ id: 'review', revision, round: number, component_id: 'hc-sr04', status: 'collecting', photo_flow_version: 2,
    slots: { pi_side_a: null, pi_side_b: null, component_header: null }, results: [], observations: [], reviews: {}, no_progress_count: 0, missing_roles: ['pi_side_a', 'pi_side_b', 'component_header'] });
const turn = () => new Promise(done => setImmediate(done));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

async function fixture(run) {
    const saved = { window: globalThis.window, document: globalThis.document, WebSocket: globalThis.WebSocket, setTimeout: globalThis.setTimeout,
        clearTimeout: globalThis.clearTimeout, setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
    globalThis.window = { isSecureContext: true, location: { origin: 'https://phone.test', href: 'https://phone.test/mobile' }, addEventListener() {}, removeEventListener() {} };
    globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
    globalThis.WebSocket = class { static OPEN = 1; static CONNECTING = 0; readyState = 1; close() {} };
    globalThis.setTimeout = globalThis.setInterval = () => 1;
    globalThis.clearTimeout = globalThis.clearInterval = () => {};
    const states = [], refs = [], memos = [], effects = [], cleanups = [];
    let stateCursor = 0, refCursor = 0, memoCursor = 0, effectCursor = 0;
    const hooks = { useState(initial) { const i = stateCursor++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
        return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
        useRef(initial) { const i = refCursor++; return refs[i] ??= { current: initial }; },
        useMemo(callback, deps) { const i = memoCursor++, previous = memos[i]; if (!previous || deps.some((value, index) => value !== previous.deps[index])) memos[i] = { deps, value: callback() }; return memos[i].value; },
        useCallback: callback => callback, useEffect(callback) { const i = effectCursor++; if (!(i in effects)) effects[i] = callback; } };
    const calls = [], file = { name: 'side.jpg', type: 'image/jpeg' };
    let review = round(), contextId = 'context', requestOverride = null, uploadOverride = null;
    const snapshot = () => ({ review: structuredClone(review), can_act: true, component_label: 'HC-SR04' });
    const session = () => ({ session_id: 'phone', conversation_id: 'chat', context_id: contextId, context: { round: 1 },
        view: { capture_id: null, wire_id: null, revision: 1 }, stream: { active: false, generation: 0, state: 'finding', can_capture: false } });
    const empty = () => ({ text: '', attachments: [], outbox: [], captureJob: null });
    class Api {
        pairing = { token: 'synthetic', session_id: 'phone', conversation_id: 'chat' };
        cancelPending() {}
        async request(path, options = {}) {
            calls.push({ path, method: options.method ?? 'GET', body: options.body });
            const override = requestOverride?.(path, options);
            if (override !== undefined) return override;
            if (path === 'session') return session();
            if (path.startsWith('conversation')) return { id: 'chat', messages: [], jobs: [], context_epoch: 0, round: 1 };
            if (path === 'wiring-review' && !options.method) return snapshot();
            if (path === 'wiring-review') {
                const action = options.body.action;
                if (action.review_id !== review.id || action.revision !== review.revision) throw Object.assign(Error('stale_wiring_review'), { status: 409, detail: 'stale_wiring_review' });
                if (action.op === 'capture') review.slots[action.role] = { role: action.role, capture_id: 'capture', sha256: 'asset-hash', image_url: '/api/mobile/wiring-review/evidence/capture',
                    size: [1080, 1920], crop: null, crop_source: 'none', available: true, provenance: { asset_id: options.body.asset_id, sha256: 'asset-hash' } };
                if (action.op === 'accept_photo') review.slots[action.role].photo_acceptance = { source: 'human', capture_id: action.capture_id, sha256: action.sha256, round: review.round, accepted_at: 1 };
                review.revision++; return snapshot();
            }
            return {};
        }
        async upload(attachment) { calls.push({ path: 'assets', attachment }); return uploadOverride ? uploadOverride(attachment) : { id: 'asset', type: 'image', sha256: 'asset-hash' }; }
    }
    const browser = { MobileBrowserApi: Api, loadBrowserPairing: () => ({ token: 'synthetic', session_id: 'phone', conversation_id: 'chat', context_id: 'context' }),
        emptyBrowserDraft: empty, idleBrowserRtc: () => ({ stats: {}, stream: null }), mobileBrowserDraftKey: () => 'draft-key', loadBrowserDraft: async () => empty(),
        saveBrowserDraft: async () => {}, saveBrowserPairing() {}, browserLease: () => ({ key: '', deadline: 0 }),
        mergeBrowserSession: (_, next) => next, sameBrowserWorkspace: load('../src/lib/mobileBrowser.ts').sameBrowserWorkspace,
        mergeBrowserConversation: (_, next) => next, expiredBrowserSession: () => false,
        browserMediaReference: () => ({ asset_ids: [] }), browserAttachment: async selected => ({ id: 'attachment', upload_id: 'upload', file: selected, name: selected.name,
            filename: selected.name, type: 'image', mime: selected.type, size: 100, width: 1080, height: 1920 }) };
    const { useMobileBrowser } = load('../src/lib/useMobileBrowser.ts', { react: hooks, './mobileBrowser': browser, './usePhoneCameraTune': { usePhoneCameraTune: () => ({ busy: false }) },
        './mobile': { mobileVideoFresh: () => false }, './mobileViewerStats': { mobileMeasurementFresh: () => false },
        './mobileBrowserRtc': { idleBrowserRtc: () => ({ stats: {}, stream: null }), BrowserPublisher: class { async stop() {} stopLocal() {} } }, './wiringReview': reviewDomain,
        './assistantAnalysis': load('../src/lib/assistantAnalysis.ts') });
    const render = () => { stateCursor = refCursor = memoCursor = effectCursor = 0; return useMobileBrowser(); };
    try {
        render(); for (const effect of effects) { const cleanup = effect(); if (cleanup) cleanups.push(cleanup); }
        for (let i = 0; i < 4; i++) await turn();
        await run({ render, file, calls, snapshot, setReview(value) { review = value; }, getReview: () => review, setContext(value) { contextId = value; },
            onRequest(callback) { requestOverride = callback; }, onUpload(callback) { uploadOverride = callback; } });
    } finally {
        for (const cleanup of cleanups.reverse()) cleanup();
        Object.assign(globalThis, saved);
    }
}

test('mobile photo collection uses the exact native asset and explicit receipt without pose tickets, model calls or physical confirmation', async () => fixture(async f => {
    let w = f.render(); assert.equal(w.ready, true); assert.equal(w.canCapture, false);
    const expected = w.wiringReview;
    assert.equal(await w.uploadWiringPhoto(f.file, 'pi_side_b', expected), true);
    w = f.render(); const slot = w.wiringReview.slots.pi_side_b;
    assert.equal(slot.photo_acceptance, undefined);
    await w.wiringReviewAction(reviewDomain.boundWiringAction(w.wiringReview, { op: 'accept_photo', role: 'pi_side_b', capture_id: slot.capture_id, sha256: slot.sha256 }));
    w = f.render(); assert.equal(w.wiringReview.slots.pi_side_b.photo_acceptance.source, 'human');
    const mutations = f.calls.filter(call => call.method === 'POST');
    assert.deepEqual(mutations.map(call => call.body.action.op), ['capture', 'accept_photo']);
    assert.deepEqual(mutations[0].body, { action: { op: 'capture', role: 'pi_side_b', review_id: 'review', revision: 1 }, asset_id: 'asset' });
    assert.equal(f.calls.filter(call => ['capture-ticket', 'messages', 'captures'].includes(call.path)).length, 0);
    await assert.rejects(w.wiringReviewAction(reviewDomain.boundWiringAction(w.wiringReview, { op: 'review', wire_id: 'wire', decision: 'confirmed' })), /接線確認請回到電腦/);
}));

test('upload failure retains the same photo for explicit retry and an older snapshot cannot overwrite its saved slot', async () => fixture(async f => {
    f.onUpload(() => { throw Error('offline'); });
    let w = f.render(); assert.equal(await w.uploadWiringPhoto(f.file, 'pi_side_a', w.wiringReview), false);
    w = f.render(); assert.equal(w.pendingWiringPhoto.attachment.file, f.file); assert.match(w.wiringReviewError, /offline/);
    const waiting = deferred(); f.onRequest((path, options) => path === 'wiring-review' && !options.method ? waiting.promise : undefined);
    const old = f.snapshot(), staleGet = w.refreshWiringReview();
    f.onUpload(() => ({ id: 'asset', type: 'image', sha256: 'asset-hash' }));
    assert.equal(await w.retryWiringPhoto(), true); waiting.resolve(old); await staleGet;
    w = f.render(); assert.equal(w.pendingWiringPhoto, null); assert.equal(w.wiringReview.revision, 2); assert.equal(w.wiringReview.slots.pi_side_a.capture_id, 'capture');
}));

test('switching workspace during native upload drops the late response and never inserts the photograph into a new round', async () => fixture(async f => {
    const uploading = deferred(); f.onUpload(() => uploading.promise);
    let w = f.render(); const pending = w.uploadWiringPhoto(f.file, 'component_header', w.wiringReview); await turn();
    f.setContext('new-context'); f.setReview(round(8, 2)); await w.refresh();
    uploading.resolve({ id: 'old-asset', type: 'image', sha256: 'asset-hash' }); assert.equal(await pending, false);
    w = f.render(); assert.equal(w.wiringReview.round, 2); assert.equal(w.pendingWiringPhoto, null);
    assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
}));

test('an ambiguous failed capture response is reconciled only when the current round contains the same immutable asset and hash', async () => fixture(async f => {
    f.onRequest((path, options) => {
        if (path !== 'wiring-review' || options.body?.action.op !== 'capture') return;
        const next = round(2); next.slots.pi_side_a = { role: 'pi_side_a', capture_id: 'server-saved', sha256: 'asset-hash', image_url: '/api/mobile/wiring-review/evidence/server-saved',
            size: [1080, 1920], available: true, provenance: { asset_id: options.body.asset_id, sha256: 'asset-hash' } };
        f.setReview(next); throw Error('response lost');
    });
    let w = f.render(); assert.equal(await w.uploadWiringPhoto(f.file, 'pi_side_a', w.wiringReview), false);
    w = f.render(); assert.ok(w.pendingWiringPhoto); await w.refreshWiringReview(); w = f.render();
    assert.equal(w.pendingWiringPhoto, null); assert.equal(w.wiringReviewError, '');
    assert.equal(w.wiringReview.slots.pi_side_a.photo_acceptance, undefined, 'saving a photo cannot approve it or confirm a wire');
}));

test('an old deployment without the review endpoint preserves ordinary phone chat, while other errors remain visible', async () => fixture(async f => {
    let w = f.render();
    for (const detail of ['Not Found', 'HTTP 404']) {
        f.onRequest((path, options) => { if (path === 'wiring-review' && !options.method) throw Object.assign(Error('HTTP 404'), { status: 404, detail }); });
        await w.refreshWiringReview(); w = f.render();
        assert.equal(w.wiringReview, null); assert.equal(w.wiringCanAct, false); assert.equal(w.wiringReviewError, ''); assert.equal(w.session.conversation_id, 'chat');
    }
    f.onRequest((path, options) => { if (path === 'wiring-review' && !options.method) throw Object.assign(Error('permission denied'), { status: 403, detail: 'mobile_session_mismatch' }); });
    await w.refreshWiringReview(); w = f.render(); assert.match(w.wiringReviewError, /permission denied/); assert.equal(w.session.conversation_id, 'chat');
}));
