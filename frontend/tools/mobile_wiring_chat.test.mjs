import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import React from 'react';

function load(file, modules = {}) {
    const exports = {};
    const js = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
    new Function('require', 'exports', 'React', js)(name => { if (!(name in modules)) throw Error(`Unexpected import ${name}`); return modules[name]; }, exports, React);
    return exports;
}
const reviewDomain = load('../src/lib/wiringReview.ts');
const analysisDomain = load('../src/lib/assistantAnalysis.ts');
const round = (revision = 1, number = 1) => ({ id: 'review', revision, round: number, component_id: 'hc-sr04', status: 'collecting', photo_flow_version: 2,
    slots: { pi_side_a: null, pi_side_b: null, component_header: null }, results: [], observations: [], reviews: {}, no_progress_count: 0, missing_roles: ['pi_side_a', 'pi_side_b', 'component_header'] });
const turn = () => new Promise(done => setImmediate(done));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

async function fixture(run, options = {}) {
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
    let review = round(), contextId = 'context', requestOverride = null, uploadOverride = null, counter = 0;
    const flow = (role = 'pi_side_a', extra = {}) => ({ flow_id: 'flow', review_id: review.id, revision: review.revision, round: review.round,
        component_id: review.component_id, kind: 'photo_request', role, current: true, can_act: true, actions: ['capture'], ...extra });
    let conversation = { id: 'chat', kind: 'project', messages: [{ id: 'question', role: 'assistant', source: 'legacy-debug', text: '請拍 Pi 第一側。', epoch: 0, round: 1, wiring_flow: flow() }], jobs: [], context_epoch: 0, round: 1 };
    const snapshot = () => ({ review: structuredClone(review), can_act: true, component_label: 'HC-SR04', conversation: structuredClone(conversation) });
    const session = () => ({ session_id: 'phone', conversation_id: 'chat', context_id: contextId, context: { round: 1,
        design: { current: { id: 'project', revision: 2, component_ids: ['hc-sr04'] } },
        context: { debug_context: { guide_run: 1, test_keys: { 'hc-sr04': 'selected-test-key' } } } },
        view: { capture_id: null, wire_id: null, revision: 1 }, stream: { active: false, generation: 0, state: 'finding', can_capture: false } });
    const empty = () => ({ text: '保留普通聊天草稿', attachments: [{ id: 'ordinary', name: 'normal.jpg', type: 'image',
        ...(options.uploadAttachment ? {} : { asset: { id: 'ordinary-asset' } }) }], outbox: structuredClone(options.outbox ?? []), captureJob: null });
    class Api {
        pairing = { token: 'synthetic', session_id: 'phone', conversation_id: 'chat' };
        cancelPending() {}
        async request(path, options = {}) {
            calls.push({ path, method: options.method ?? 'GET', body: options.body });
            const override = requestOverride?.(path, options);
            if (override !== undefined) return override;
            if (path === 'session') return session();
            if (path.startsWith('conversation')) return structuredClone(conversation);
            if (path === 'wiring-review' && !options.method) return snapshot();
            if (path === 'wiring-review') {
                const action = options.body.action;
                if (action.review_id !== review.id || action.revision !== review.revision) throw Object.assign(Error('stale_wiring_review'), { status: 409, detail: 'stale_wiring_review' });
                assert.equal(action.op, 'capture');
                const dialogue = options.body.dialogue, question = conversation.messages.find(message => message.id === dialogue?.message_id);
                assert.ok(dialogue && question?.wiring_flow.current, 'capture must reference a current shared question');
                assert.equal(question.wiring_flow.role, action.role);
                review.slots[action.role] = { role: action.role, capture_id: 'capture', sha256: 'asset-hash', image_url: '/api/mobile/wiring-review/evidence/capture',
                    size: [1080, 1920], crop: null, crop_source: 'none', available: true, provenance: { asset_id: options.body.asset_id, sha256: 'asset-hash' },
                    photo_acceptance: { source: 'human', capture_id: 'capture', sha256: 'asset-hash', round: review.round, accepted_at: 1 } };
                review.revision++; question.wiring_flow.current = false; question.wiring_flow.can_act = false;
                conversation.messages.push({ id: 'photo', role: 'user', text: 'Pi 第一側照片', epoch: 0, round: 1, capture_id: 'capture',
                    wiring_flow: flow(action.role, { kind: 'photo', capture_id: 'capture', image_url: '/api/mobile/wiring-review/evidence/capture', current: false, can_act: false, actions: [] }) });
                conversation.messages.push({ id: 'next', role: 'assistant', text: '請拍 Pi 另一側。', epoch: 0, round: 1, wiring_flow: flow('pi_side_b') });
                return snapshot();
            }
            return {};
        }
        async upload(attachment) { calls.push({ path: 'assets', attachment }); return uploadOverride ? uploadOverride(attachment) : { id: 'asset', type: 'image', sha256: 'asset-hash' }; }
    }
    const browser = { MobileBrowserApi: Api, loadBrowserPairing: () => ({ token: 'synthetic', session_id: 'phone', conversation_id: 'chat', context_id: 'context' }),
        emptyBrowserDraft: empty, idleBrowserRtc: () => ({ stats: {}, stream: null }), mobileBrowserDraftKey: () => 'draft-key', loadBrowserDraft: async () => empty(),
        saveBrowserDraft: async () => {}, saveBrowserPairing() {}, browserLease: () => ({ key: '', deadline: 0 }),
        mergeBrowserSession: (_, next) => next, mergeBrowserConversation: (_, next) => next, expiredBrowserSession: () => false,
        browserMediaReference: () => ({ asset_ids: [] }), browserUuid: () => `request-${++counter}`, browserAttachment: async selected => ({ id: 'attachment', upload_id: 'upload', file: selected, name: selected.name,
            filename: selected.name, type: 'image', mime: selected.type, size: 100, width: 1080, height: 1920 }) };
    const { useMobileBrowser, mobileWiringPhotoFlow } = load('../src/lib/useMobileBrowser.ts', { react: hooks, './mobileBrowser': browser, './usePhoneCameraTune': { usePhoneCameraTune: () => ({ busy: false }) },
        './mobile': { mobileVideoFresh: () => false }, './mobileViewerStats': { mobileMeasurementFresh: () => false },
        './mobileBrowserRtc': { idleBrowserRtc: () => ({ stats: {}, stream: null }), BrowserPublisher: class { async stop() {} stopLocal() {} } }, './wiringReview': reviewDomain,
        './assistantAnalysis': analysisDomain });
    const render = () => { stateCursor = refCursor = memoCursor = effectCursor = 0; return useMobileBrowser(); };
    try {
        render(); for (const effect of effects) { const cleanup = effect(); if (cleanup) cleanups.push(cleanup); }
        for (let i = 0; i < 4; i++) await turn();
        await run({ render, file, calls, snapshot, setReview(value) { review = value; }, getReview: () => review, setContext(value) { contextId = value; }, setEpoch(value) { conversation.context_epoch = value; },
            eligibility: mobileWiringPhotoFlow, chat: () => structuredClone(conversation), setConversation(value) { conversation = value; }, setFlow(value) { conversation.messages[0].wiring_flow = { ...conversation.messages[0].wiring_flow, ...value }; },
            onRequest(callback) { requestOverride = callback; }, onUpload(callback) { uploadOverride = callback; } });
    } finally {
        for (const cleanup of cleanups.reverse()) cleanup();
        Object.assign(globalThis, saved);
    }
}

test('photo actions require the current exact shared question rather than message text', async () => fixture(async f => {
    const w = f.render(), message = w.conversation.messages[0];
    assert.equal(f.eligibility(message, w.session, w.conversation, w.wiringReview, true).role, 'pi_side_a');
    for (const value of [{ current: false }, { can_act: false }, { flow_id: '' }, { role: 'other' }, { revision: 99 }, { round: 2 }, { kind: 'analysis_request' }, { actions: ['analyse'] }, { actions: undefined }])
        assert.equal(f.eligibility({ ...message, wiring_flow: { ...message.wiring_flow, ...value } }, w.session, w.conversation, w.wiringReview, true), null);
    assert.equal(f.eligibility({ ...message, role: 'user' }, w.session, w.conversation, w.wiringReview, true), null);
    assert.equal(f.calls.filter(call => call.method === 'POST' || call.path === 'assets').length, 0);
}));

test('mobile shows the current framing example without capturing and keeps old questions collapsed and inert', async () => fixture(async f => {
    const framing = () => null;
    const hooks = { ...React, useRef: current => ({ current }) };
    const { MobileWiringChatActions } = load('../src/components/MobileWebApp.tsx', {
        react: hooks, '../lib/i18n': { useI18n: () => ({ locale: 'zh-TW' }) }, '../lib/assistantHistory': {},
        './AssistantAnalysisTime': {}, './WiringChatMessage': { WiringCaptureFraming: framing }, './PhoneCameraAutoTune': { PhoneCameraAutoTune: () => null },
        '../lib/mobile': {}, '../lib/useMobileBrowser': { mobileWiringPhotoFlow: f.eligibility },
        '../lib/mobileBrowserCapture': {}, '../lib/mobileWebView': {}, '../mobileWeb.css': {} });
    const w = f.render(), message = w.conversation.messages[0];
    const nodes = tree => { const result = []; const visit = node => {
        if (!React.isValidElement(node)) return; result.push(node); React.Children.toArray(node.props.children).forEach(visit);
    }; visit(tree); return result; };
    const current = nodes(MobileWiringChatActions({ w, message }));
    assert.equal(current.find(node => node.type === framing).props.current, true);
    assert.equal(current.find(node => node.type === framing).props.role, 'pi_side_a');
    assert.equal(current.filter(node => node.type === 'button').length, 1);
    const old = nodes(MobileWiringChatActions({ w, message: { ...message, wiring_flow: { ...message.wiring_flow, current: false } } }));
    assert.equal(old.find(node => node.type === framing).props.current, false);
    assert.equal(old.filter(node => node.type === 'button').length, 0);
    assert.equal(f.calls.filter(call => call.method === 'POST' || call.path === 'assets').length, 0);
}));

test('explicit photo submission freezes the role, autoaccepts one asset and synchronizes normal shared photo and next question', async () => fixture(async f => {
    let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    assert.equal(request.role, 'pi_side_a'); assert.equal(w.canCapture, false);
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), true); w = f.render();
    const mutation = f.calls.find(call => call.method === 'POST');
    assert.deepEqual(mutation.body, { action: { op: 'capture', role: 'pi_side_a', review_id: 'review', revision: 1 }, asset_id: 'asset',
        dialogue: { message_id: 'question', flow_id: 'flow', request_id: 'request-1' } });
    assert.deepEqual(w.conversation.messages.map(message => [message.id, message.role]), [['question', 'assistant'], ['photo', 'user'], ['next', 'assistant']]);
    assert.equal(w.wiringReview.slots.pi_side_a.photo_acceptance.source, 'human'); assert.equal(w.wiringReview.reviews.wire, undefined);
    assert.equal(w.conversation.messages.at(-1).wiring_flow.role, 'pi_side_b'); assert.equal(w.prepareWiringChatPhoto(w.conversation.messages[0]), null);
    assert.equal(w.draft, '保留普通聊天草稿'); assert.equal(w.attachments[0].id, 'ordinary'); assert.equal(w.pendingWiringPhoto, null);
    assert.equal(f.calls.filter(call => ['capture-ticket', 'messages', 'captures'].includes(call.path)).length, 0);
}));

test('changing the requested role after opening the camera rejects the frozen photograph', async () => fixture(async f => {
    let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    f.setFlow({ role: 'component_header' }); await w.refresh();
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), false);
    assert.equal(f.calls.filter(call => call.path === 'assets' || call.method === 'POST').length, 0);
}));

test('retry preserves the exact question and immutable upload while preventing duplicate submissions', async () => fixture(async f => {
    const uploading = deferred(); f.onUpload(() => uploading.promise);
    let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    const first = w.uploadWiringChatPhoto(f.file, request); await turn();
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), false);
    f.onRequest((path, options) => { if (path === 'wiring-review' && options.method === 'POST') throw Error('response lost'); });
    uploading.resolve({ id: 'asset', type: 'image', sha256: 'asset-hash' }); assert.equal(await first, false);
    w = f.render(); assert.equal(w.pendingWiringPhoto.dialogue.request_id, request.request_id); assert.match(w.wiringReviewError, /response lost/);
    f.onRequest(null); assert.equal(await w.retryWiringPhoto(), true); w = f.render();
    assert.equal(f.calls.filter(call => call.path === 'assets').length, 1); assert.equal(w.pendingWiringPhoto, null);
    assert.deepEqual(f.calls.filter(call => call.method === 'POST').map(call => call.body.dialogue), [
        { message_id: 'question', flow_id: 'flow', request_id: 'request-1' }, { message_id: 'question', flow_id: 'flow', request_id: 'request-1' }]);
}));

test('a new workspace or cleared chat rejects a late native upload and never posts it into the next conversation', async () => {
    for (const changed of ['context', 'epoch']) await fixture(async f => {
        const uploading = deferred(); f.onUpload(() => uploading.promise);
        let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
        const pending = w.uploadWiringChatPhoto(f.file, request); await turn();
        if (changed === 'context') f.setContext('new-context'); else f.setEpoch(1);
        await w.refresh(); uploading.resolve({ id: 'late', type: 'image', sha256: 'asset-hash' }); assert.equal(await pending, false);
        w = f.render(); assert.equal(w.pendingWiringPhoto, null); assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
        assert.equal(w.conversation.messages.some(message => message.role === 'user'), false);
    });
});

test('a failed response reconciles saved photo evidence and the shared next question without a second capture or model request', async () => fixture(async f => {
    let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    f.onRequest((path, options) => {
        if (path !== 'wiring-review' || options.method !== 'POST') return;
        const next = round(2); next.slots.pi_side_a = { role: 'pi_side_a', capture_id: 'saved', sha256: 'asset-hash',
            provenance: { asset_id: 'asset', sha256: 'asset-hash' }, photo_acceptance: { source: 'human', capture_id: 'saved', sha256: 'asset-hash', round: 1 } };
        f.setReview(next); f.setFlow({ current: false, can_act: false }); throw Error('lost after save');
    });
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), false); w = f.render(); assert.ok(w.pendingWiringPhoto);
    await w.refreshWiringReview(); w = f.render(); assert.equal(w.pendingWiringPhoto, null); assert.equal(w.wiringReviewError, '');
    assert.equal(w.conversation.messages[0].wiring_flow.current, false); assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
}));

test('an old snapshot or a mismatched conversation receipt cannot replace the current question', async () => {
  await fixture(async f => {
    let w = f.render(); const original = f.snapshot(), delayed = deferred();
    f.onRequest((path, options) => path === 'wiring-review' && !options.method ? delayed.promise : undefined);
    const refresh = w.refreshWiringReview(), request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), true); delayed.resolve(original); await refresh; w = f.render();
    assert.equal(w.conversation.messages.at(-1).id, 'next'); assert.equal(w.wiringReview.revision, 2);
  });
  for (const invalid of ['conversation', 'asset', 'hash']) await fixture(async f => {
    let w = f.render(); const request = w.prepareWiringChatPhoto(w.conversation.messages[0]);
    f.onRequest((path, options) => {
        if (path !== 'wiring-review' || options.method !== 'POST') return;
        const snapshot = f.snapshot(), hash = invalid === 'hash' ? 'other-hash' : 'asset-hash';
        snapshot.review.slots.pi_side_a = { role: 'pi_side_a', capture_id: 'wrong-receipt', sha256: hash,
            provenance: { asset_id: invalid === 'asset' ? 'other-asset' : 'asset' },
            photo_acceptance: { source: 'human', capture_id: 'wrong-receipt', sha256: hash, round: 1 } };
        return { ...snapshot, conversation: { ...snapshot.conversation, id: invalid === 'conversation' ? 'foreign' : 'chat' } };
    });
    assert.equal(await w.uploadWiringChatPhoto(f.file, request), false); w = f.render();
    assert.equal(w.wiringReview.revision, 1); assert.equal(w.conversation.messages[0].id, 'question'); assert.ok(w.pendingWiringPhoto);
    assert.match(w.wiringReviewError, /照片回覆/);
  });
});

test('the mobile chat mounts shared-message actions and photos without a persistent sequence, analysis or manual-review panel', () => {
    const source = readFileSync(new URL('../src/components/MobileWebApp.tsx', import.meta.url), 'utf8');
    const chat = source.slice(source.indexOf('export function ChatView('), source.indexOf('export function CameraView('));
    assert.match(chat, /<MobileWiringChatActions w=\{w\} message=\{message\}/); assert.match(chat, /<MobileWiringChatPhoto w=\{w\} message=\{message\}/);
    assert.doesNotMatch(source, /MobileWiringPhotoDialogue|WiringPhotoSequence|FramingGuide|onAnalyse=|wiringReviewAction\(/);
    assert.match(source, /message\.capture_id && !message\.wiring_flow/);
});

test('invitation Start synchronizes the first shared photo question from its receipt without waiting for another poll', async () => fixture(async f => {
    const offer = { offer_id: 'offer', message_id: 'invitation', state: 'pending', can_act: true, can_dismiss: true,
        component_id: 'hc-sr04', reusable_review: false, project_id: 'project', project_revision: 2, guide_run: 1,
        context_epoch: 0, guide_key: 'selected-test-key', test_id: 'test', reason: 'no_echo', mode: 'wiring' };
    const question = f.chat().messages[0], invitation = { id: 'invitation', role: 'assistant', source: 'legacy-debug', epoch: 0, round: 1,
        text: '要拍照檢查嗎？', test_help_offer: offer };
    f.setConversation({ id: 'chat', context_epoch: 0, round: 1, messages: [invitation], jobs: [] });
    let w = f.render(); await w.refresh(); w = f.render();
    f.onRequest((path, options) => {
        if (path !== 'wiring-review' || !options.body?.invitation) return;
        const receipt = { ...offer, state: 'started', reusable_review: true, review_id: 'review' };
        return { ...f.snapshot(), offer: receipt, conversation: { ...f.chat(), messages: [{ ...invitation, test_help_offer: receipt }, question] } };
    });
    assert.equal(await w.testHelpAction(w.conversation.messages[0], 'start'), true); w = f.render();
    assert.equal(w.conversation.messages.at(-1).id, 'question'); assert.equal(w.prepareWiringChatPhoto(w.conversation.messages.at(-1)).role, 'pi_side_a');
    assert.equal(f.calls.filter(call => call.method === 'POST').length, 1); assert.equal(w.draft, '保留普通聊天草稿');
}));

const activeAnalysis = started => ({ flow_id: 'analysis', session_id: 'debug', review_id: 'review', round: 1, revision: 4, started_at: started });
test('mobile analysis blocks direct send and saved-message retries while preserving editable draft and attachments', async () => fixture(async f => {
    const staleRender = f.render();
    f.setConversation({ ...f.chat(), wiring_analysis: activeAnalysis(123) });
    await staleRender.refresh();
    await staleRender.send(); await staleRender.retry('waiting');
    let w = f.render(); assert.equal(w.chatSendBlocked, true); assert.deepEqual(w.wiringAnalysis, { startedAt: 123 });
    assert.equal(w.draft, '保留普通聊天草稿'); assert.equal(w.attachments[0].id, 'ordinary'); assert.equal(w.outbox.length, 1);
    w.setDraft('分析中仍能編輯'); w = f.render(); assert.equal(w.draft, '分析中仍能編輯');
    assert.equal(f.calls.filter(call => call.path === 'assets' || call.method === 'POST').length, 0);
}, { outbox: [{ id: 'waiting', status: 'failed', attachments: [], payload: { request_id: 'waiting', text: '保存的待送訊息', context_id: 'context', asset_ids: [] } }] }));

test('mobile analysis ends authoritatively despite an older analysing message and re-enables one explicit send', async () => fixture(async f => {
    f.setFlow({ kind: 'analysing', started_at: 123, actions: [], can_act: false });
    f.setConversation({ ...f.chat(), wiring_analysis: activeAnalysis(123) });
    let w = f.render(); await w.refresh(); w = f.render(); assert.equal(w.chatSendBlocked, true);
    f.setConversation({ ...f.chat(), wiring_analysis: null }); await w.refresh(); w = f.render();
    assert.equal(w.chatSendBlocked, false); assert.equal(w.wiringAnalysis, null);
    f.onRequest((path, opts) => path === 'messages' && opts.method === 'POST' ? f.chat() : undefined);
    await w.send(); w = f.render(); assert.equal(f.calls.filter(call => call.path === 'messages' && call.method === 'POST').length, 1);
    assert.equal(w.draft, ''); assert.equal(w.outbox.length, 0);
}));

test('mobile analysis locks ordinary model jobs without inventing a photo-analysis clock', async () => fixture(async f => {
    f.setConversation({ ...f.chat(), jobs: [{ id: 'model', status: 'running' }], wiring_analysis: null });
    let w = f.render(); await w.refresh(); w = f.render();
    assert.equal(w.chatSendBlocked, true); assert.equal(w.wiringAnalysis, null); await w.send();
    assert.equal(f.calls.filter(call => call.method === 'POST').length, 0);
    f.setConversation({ ...f.chat(), jobs: [{ id: 'model', status: 'completed' }] }); await w.refresh();
    assert.equal(f.render().chatSendBlocked, false);
}));

test('mobile analysis arriving during attachment upload stops the text POST and retains the immutable pending message', async () => fixture(async f => {
    const uploading = deferred(); f.onUpload(() => uploading.promise);
    const w = f.render(), sending = w.send(); await turn();
    assert.equal(f.calls.filter(call => call.path === 'assets').length, 1);
    f.setConversation({ ...f.chat(), wiring_analysis: activeAnalysis(123) }); await w.refresh();
    uploading.resolve({ id: 'ordinary-upload', type: 'image' }); await sending;
    const current = f.render(); assert.equal(current.chatSendBlocked, true); assert.equal(current.outbox.length, 1);
    assert.equal(current.outbox[0].payload.text, '保留普通聊天草稿'); assert.equal(current.outbox[0].attachments[0].asset.id, 'ordinary-upload');
    assert.equal(current.outbox[0].status, 'failed'); assert.match(current.outbox[0].error, /分析.*保留/);
    assert.equal(f.calls.filter(call => call.path === 'messages' && call.method === 'POST').length, 0);
}, { uploadAttachment: true }));

test('mobile analysis UI keeps one inline server clock, blocks form submission and leaves the draft editable', () => {
    const time = () => null, edits = [], calls = [];
    const hooks = { ...React, useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}], useRef: current => ({ current }), useEffect() {}, useLayoutEffect() {} };
    const { ChatView } = load('../src/components/MobileWebApp.tsx', { react: hooks, '../lib/i18n': { useI18n: () => ({ locale: 'zh-TW' }) },
        '../lib/assistantHistory': load('../src/lib/assistantHistory.ts'), './AssistantAnalysisTime': { AssistantAnalysisTime: time }, '../lib/mobile': {},
        '../lib/useMobileBrowser': {}, '../lib/mobileBrowserCapture': {}, '../lib/mobileWebView': {}, '../mobileWeb.css': {},
        './WiringChatMessage': { WiringCaptureFraming: () => null }, './PhoneCameraAutoTune': { PhoneCameraAutoTune: () => null } });
    const w = { draft: '可以編輯', attachments: [], outbox: [], busy: false, chatSendBlocked: true, wiringAnalysis: { startedAt: 123 },
        conversation: { id: 'chat', context_epoch: 0, round: 1, before: null, jobs: [], messages: [
            { id: 'old', role: 'assistant', text: '舊分析', epoch: 0, round: 0, wiring_flow: { current: true, kind: 'analysing' } },
            { id: 'current', role: 'assistant', text: '正在檢查照片', epoch: 0, round: 1, wiring_flow: { current: true, kind: 'analysing' } }] },
        send: () => calls.push('send'), setDraft: value => edits.push(value) };
    const tree = ChatView({ w, onPhoto() {} }), nodes = [];
    const visit = node => { if (!React.isValidElement(node)) return; nodes.push(node); for (const child of React.Children.toArray(node.props.children)) visit(child); }; visit(tree);
    const clocks = nodes.filter(node => node.type === time); assert.equal(clocks.length, 1); assert.equal(clocks[0].props.startedAt, 123);
    const form = nodes.find(node => node.type === 'form'); let prevented = false; form.props.onSubmit({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true); assert.equal(calls.length, 0); assert.equal(nodes.find(node => node.props.className === 'mw-send').props.disabled, true);
    const input = nodes.find(node => node.type === 'textarea'); assert.equal(input.props.disabled, undefined); input.props.onChange({ target: { value: '更新草稿' } }); assert.deepEqual(edits, ['更新草稿']);
    const finishedTree = ChatView({ w: { ...w, wiringAnalysis: null, chatSendBlocked: false,
      conversation: { ...w.conversation, messages: [{ ...w.conversation.messages[1], wiring_flow: {
        current: false, kind: 'analysing', elapsed_ms: 65999 } }] } }, onPhoto() {} });
    nodes.length = 0; visit(finishedTree);
    const done = nodes.filter(node => node.type === time); assert.equal(done.length, 1);
    assert.equal(done[0].props.active, false); assert.equal(done[0].props.durationMs, 65999);
    assert.equal(nodes.find(node => node.props.className === 'mw-send').props.disabled, false);
});
