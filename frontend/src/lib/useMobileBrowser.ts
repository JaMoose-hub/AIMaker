import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { acceptMobileCapture, mobileVideoAgeMs, mobileVideoFresh } from './mobile';
import { mobileMeasurementFresh, mobileReconnectEligible, mobileReconnectWaitMs, restartMobileStream } from './mobileViewerStats';
import { MobileBrowserApi, browserAttachment, browserLease, browserMediaReference, browserUuid, closeBrowserSession, emptyBrowserDraft, expiredBrowserSession, loadBrowserDraft, loadBrowserPairing, mergeBrowserConversation, mergeBrowserSession, mobileBrowserDraftKey, pairMobileBrowser, sameBrowserPairing, saveBrowserDraft, saveBrowserPairing, validateBrowserAttachments, type AssistantConversation, type BrowserAttachment, type BrowserCaptureJob, type BrowserDraft, type BrowserOutbox, type BrowserPairing, type BrowserSession, type CaptureTicket, type MobileCapture, } from './mobileBrowser';
import { BrowserPublisher, browserCaptureHandoff, idleBrowserRtc, type BrowserStreamOptions } from './mobileBrowserRtc';
const EXPIRED_SESSION_MESSAGE = '手機連線已失效，請重新輸入電腦顯示的新配對碼。草稿與附件已保留。';
const errorText = (cause: unknown) => expiredBrowserSession(cause) ? EXPIRED_SESSION_MESSAGE : cause instanceof Error ? cause.message : String(cause);
const browserForeground = () => document.visibilityState !== 'hidden';
export function useMobileAssetUrl(api: MobileBrowserApi | null, path?: string) {
    const [record, setRecord] = useState<{
        path: string;
        api: MobileBrowserApi;
        url: string;
    } | null>(null);
    const [failure, setFailure] = useState<{
        path: string;
        api: MobileBrowserApi;
        error: string;
    } | null>(null);
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        if (!api || !path)
            return;
        const abort = new AbortController();
        let url: string | null = null;
        void api.assetBlob(path, abort.signal).then(blob => { if (abort.signal.aborted)
            return; url = URL.createObjectURL(blob); setRecord({ path, api, url }); setFailure(null); }).catch(cause => { if (!abort.signal.aborted)
            setFailure({ path, api, error: errorText(cause) }); });
        return () => { abort.abort(); if (url)
            URL.revokeObjectURL(url); };
    }, [api, path, attempt]);
    return { url: record && record.path === path && record.api === api ? record.url : null, error: failure && failure.path === path && failure.api === api ? failure.error : '', retry: () => { setRecord(null); setFailure(null); setAttempt(n => n + 1); } };
}
interface SendOptions {
    text?: string;
    capture_id?: string;
    check_scope?: 'one' | 'all';
    wire_id?: string;
}
/** Safari workspace, isolated from desktop camera state and native-app persistence. */
export function useMobileBrowser() {
    const [pairing, setPairing] = useState<BrowserPairing | null>(loadBrowserPairing);
    const pairingRef = useRef(pairing); pairingRef.current = pairing;
    const expiredPairing = useRef<(previous: BrowserPairing) => void>(() => {});
    const lifecycleCleanup = useRef<((notifyServer?: boolean) => void) | null>(null);
    const api = useMemo(() => pairing ? new MobileBrowserApi(pairing, () => expiredPairing.current(pairing)) : null, [pairing]);
    const [session, setSession] = useState<BrowserSession | null>(null), sessionRef = useRef<BrowserSession | null>(null);
    const [conversation, setConversation] = useState<AssistantConversation | null>(null), conversationRef = useRef<AssistantConversation | null>(null);
    const [workspace, setWorkspace] = useState<BrowserDraft>(emptyBrowserDraft), draftRef = useRef(workspace);
    const [ready, setReady] = useState(false), [connected, setConnected] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
    const [rtc, setRtc] = useState(idleBrowserRtc), publisher = useRef<BrowserPublisher | null>(null);
    const rtcMeasurement = useRef({ stats: rtc.stats, at: 0 });
    const streamIntent = useRef(0), streamWanted = useRef(false), reconnectAttempted = useRef(false), streamFlight = useRef<number | null>(null);
    const sourceRestart = useRef<{ owner: number; intent: number; session: string; context: string } | null>(null);
    const attachmentFlight = useRef<object | null>(null);
    const startedStream = useRef<{ owner: number; session: string; context: string; generation: number; startedAt: number } | null>(null);
    const [streamBusy, setStreamBusy] = useState(false);
    const [capture, setCapture] = useState<MobileCapture | null>(null), [captureError, setCaptureError] = useState('');
    const [captureTicket, setCaptureTicket] = useState<CaptureTicket | null>(null), ticketRef = useRef<CaptureTicket | null>(null);
    const [captureAttempt, setCaptureAttempt] = useState(0), [clock, setClock] = useState(() => performance.now());
    const lease = useRef({ key: '', deadline: 0 }), owner = useRef(0), workspaceKey = useRef(''), saves = useRef(Promise.resolve());
    const sending = useRef(new Set<string>()), operations = useRef(new Set<AbortController>()), previewUrls = useRef(new Set<string>());
    const refreshCounter = useRef(0), streamOptions = useRef<BrowserStreamOptions>({ resolution: '1080p', bitrateKbps: 12000 });
    const cancelStreamIntent = () => { streamWanted.current = false; streamIntent.current++; startedStream.current = null; sourceRestart.current = null; };
    const secureContext = window.isSecureContext;
    const draftKey = pairing ? mobileBrowserDraftKey(window.location.origin, session?.conversation_id ?? pairing.conversation_id) : '';
    const setTicket = (ticket: CaptureTicket | null) => { ticketRef.current = ticket; setCaptureTicket(ticket); };
    expiredPairing.current = previous => {
        if (!sameBrowserPairing(pairingRef.current, previous)) return;
        pairingRef.current = null;
        // Invalidate pending continuations before aborting requests or releasing media.
        owner.current++;
        lifecycleCleanup.current?.(false);
        lease.current = { key: '', deadline: 0 };
        sessionRef.current = null; conversationRef.current = null;
        setSession(null); setConversation(null); setCapture(null); setTicket(null);
        setRtc(idleBrowserRtc()); setConnected(false); setBusy(false);
        try { saveBrowserPairing(null); } catch { /* Memory still returns to pairing; no drafts are removed. */ }
        setPairing(null);
        setError(EXPIRED_SESSION_MESSAGE);
    };
    const showDraft = useCallback((next: BrowserDraft) => { draftRef.current = next; setWorkspace(next); }, []);
    const persist = useCallback(async (next: BrowserDraft, key = workspaceKey.current) => {
        if (!key)
            return;
        const task = saves.current.catch(() => undefined).then(() => saveBrowserDraft(key, next));
        saves.current = task;
        try {
            await task;
        }
        catch (cause) {
            setError(`草稿無法保存：${errorText(cause)}`);
            throw cause;
        }
    }, []);
    const commit = useCallback((update: (current: BrowserDraft) => BrowserDraft, save = true) => {
        const next = update(draftRef.current);
        showDraft(next);
        return save ? persist(next) : Promise.resolve();
    }, [persist, showDraft]);
    const preview = useCallback((item: BrowserAttachment) => {
        if (item.previewUrl)
            return item;
        const previewUrl = URL.createObjectURL(item.file);
        previewUrls.current.add(previewUrl);
        return { ...item, previewUrl };
    }, []);
    useEffect(() => {
        const active = new Set([...workspace.attachments, ...workspace.outbox.flatMap(o => o.attachments), ...(workspace.captureJob ? [workspace.captureJob.attachment] : [])].map(a => a.previewUrl));
        for (const url of previewUrls.current)
            if (!active.has(url)) {
                URL.revokeObjectURL(url);
                previewUrls.current.delete(url);
            }
    }, [workspace]);
    useEffect(() => {
        let cancelled = false;
        workspaceKey.current = draftKey;
        setReady(false);
        showDraft(emptyBrowserDraft());
        if (!draftKey) {
            setReady(true);
            return;
        }
        void saves.current.catch(() => undefined).then(() => loadBrowserDraft(draftKey)).then(value => {
            if (cancelled)
                return;
            showDraft({ ...value, attachments: value.attachments.map(preview), outbox: value.outbox.map(o => ({ ...o, status: 'failed' as const, error: o.error || '尚未確認送達，請重試', attachments: o.attachments.map(preview) })), captureJob: value.captureJob ? { ...value.captureJob, attachment: preview(value.captureJob.attachment) } : null });
            setReady(true);
        }).catch(cause => { if (!cancelled) {
            setError(`無法讀取本機草稿：${errorText(cause)}`);
            setReady(true);
        } });
        return () => { cancelled = true; for (const url of previewUrls.current)
            URL.revokeObjectURL(url); previewUrls.current.clear(); };
    }, [draftKey, preview, showDraft]);
    const acceptSession = useCallback((next: BrowserSession) => {
        if (next.session_id !== pairing?.session_id)
            return;
        const previous = sessionRef.current, merged = mergeBrowserSession(previous, next);
        if (previous && previous.context_id !== merged.context_id) {
            cancelStreamIntent();
            attachmentFlight.current = null;
            setBusy(false);
            void publisher.current?.stop();
            setCapture(null);
            setTicket(null);
            lease.current = { key: '', deadline: 0 };
        }
        if (previous?.conversation_id !== merged.conversation_id) {
            conversationRef.current = null;
            setConversation(null);
        }
        sessionRef.current = merged;
        setSession(merged);
        if (pairing && (pairing.conversation_id !== merged.conversation_id || pairing.context_id !== merged.context_id)) {
            try { saveBrowserPairing({ ...pairing, conversation_id: merged.conversation_id, context_id: merged.context_id, title: merged.title }); }
            catch { setError('無法保存目前專案，重新整理後請重新加入。'); }
        }
        lease.current = browserLease(merged, performance.now(), lease.current);
        setConnected(true);
    }, [pairing?.session_id]);
    const acceptConversation = useCallback((next: AssistantConversation) => {
        if (next.id !== (sessionRef.current?.conversation_id ?? pairing?.conversation_id))
            return;
        const merged = mergeBrowserConversation(conversationRef.current, next);
        conversationRef.current = merged;
        setConversation(merged);
    }, [pairing?.conversation_id]);
    const refresh = useCallback(async () => {
        if (!api)
            return;
        const serial = owner.current, request = ++refreshCounter.current;
        try {
            const next = await api.request<BrowserSession>('session');
            if (serial !== owner.current)
                return;
            acceptSession(next);
            const chat = await api.request<AssistantConversation>('conversation?limit=60');
            if (serial === owner.current && request === refreshCounter.current)
                acceptConversation(chat);
        }
        catch (cause) {
            if (serial === owner.current) {
                setConnected(false);
                lease.current = { key: '', deadline: 0 };
                setError(errorText(cause));
            }
            throw cause;
        }
    }, [api, acceptSession, acceptConversation]);
    useEffect(() => {
        owner.current++;
        const serial = owner.current;
        attachmentFlight.current = null;
        setBusy(false);
        sessionRef.current = null;
        conversationRef.current = null;
        setSession(null);
        setConversation(null);
        setCapture(null);
        setTicket(null);
        setConnected(false);
        lease.current = { key: '', deadline: 0 };
        if (!api)
            return;
        const pub = new BrowserPublisher(api, state => {
            if (serial !== owner.current) return;
            if (state.stats !== rtcMeasurement.current.stats) rtcMeasurement.current = { stats: state.stats, at: performance.now() };
            if (!state.publishing) { lease.current = { ...lease.current, deadline: 0 }; setClock(performance.now()); }
            if (state.sourceChanged && streamWanted.current && sessionRef.current) {
                sourceRestart.current = { owner: serial, intent: streamIntent.current,
                    session: sessionRef.current.session_id, context: sessionRef.current.context_id };
            }
            setRtc(state);
        });
        publisher.current = pub;
        let stopped = false, pollTimer: ReturnType<typeof setTimeout>, wsTimer: ReturnType<typeof setTimeout>, ws: WebSocket | null = null;
        const poll = async () => { if (stopped)
            return; if (document.visibilityState !== 'hidden')
            await refresh().catch(() => undefined); if (!stopped)
            pollTimer = setTimeout(() => void poll(), 1500); };
        const connect = () => {
            if (stopped || document.visibilityState === 'hidden' || ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING)
                return;
            const url = new URL('/api/mobile/events', window.location.href);
            url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
            url.searchParams.set('token', api.pairing!.token);
            const socket = new WebSocket(url);
            ws = socket;
            const revokePreview = () => {
                // Retain the sample key: a replay of the same sample cannot restore Locked.
                lease.current = { ...lease.current, deadline: 0 };
                setClock(performance.now());
            };
            socket.onmessage = event => { if (stopped || ws !== socket)
                return; try {
                const packet = JSON.parse(event.data);
                if (packet.type === 'disconnected' && packet.session === null) {
                    expiredPairing.current(api.pairing!);
                    return;
                }
                if (packet.type === 'state' && packet.session)
                    acceptSession(packet.session);
            }
            catch { /* Invalid events cannot renew preview locks. */ } };
            socket.onclose = () => { if (stopped || ws !== socket)
                return; revokePreview(); wsTimer = setTimeout(connect, 2000); };
            socket.onerror = () => { if (!stopped && ws === socket) revokePreview(); };
        };
        const hide = () => { if (document.visibilityState === 'hidden') {
            cancelStreamIntent();
            lease.current = { key: '', deadline: 0 };
            void pub.stop();
            ws?.close();
        }
        else {
            void refresh().catch(() => undefined);
            if (!ws || ws.readyState === WebSocket.CLOSED) {
                clearTimeout(wsTimer);
                connect();
            }
        } };
        const pagehide = () => { cancelStreamIntent(); lease.current = { key: '', deadline: 0 }; void pub.stop(); };
        document.addEventListener('visibilitychange', hide);
        window.addEventListener('pagehide', pagehide);
        void poll();
        connect();
        const ticker = setInterval(() => setClock(performance.now()), 200);
        const cleanup = (notifyServer = true) => {
            if (stopped) return;
            stopped = true;
            cancelStreamIntent();
            streamFlight.current = null; setStreamBusy(false);
            owner.current++;
            clearTimeout(pollTimer);
            clearTimeout(wsTimer);
            clearInterval(ticker);
            ws?.close();
            document.removeEventListener('visibilitychange', hide);
            window.removeEventListener('pagehide', pagehide);
            for (const operation of operations.current)
                operation.abort();
            operations.current.clear();
            sending.current.clear();
            api.cancelPending();
            if (notifyServer) void pub.stop();
            else pub.stopLocal();
            if (publisher.current === pub)
                publisher.current = null;
        };
        lifecycleCleanup.current = cleanup;
        return () => { cleanup(); if (lifecycleCleanup.current === cleanup) lifecycleCleanup.current = null; };
    }, [api, refresh, acceptSession]);
    const selectedCapture = session?.view.capture_id ?? null;
    useEffect(() => {
        setCapture(null);
        setCaptureError('');
        if (!api || !selectedCapture)
            return;
        const abort = new AbortController();
        void api.request<MobileCapture>(`captures/${encodeURIComponent(selectedCapture)}`, { signal: abort.signal }).then(packet => {
            if (abort.signal.aborted)
                return;
            if (packet.capture_id !== selectedCapture || !acceptMobileCapture(packet))
                throw Error('照片與定位資料不一致，請重新拍照');
            setCapture(packet);
        }).catch(cause => { if (!abort.signal.aborted)
            setCaptureError(errorText(cause)); });
        return () => abort.abort();
    }, [api, selectedCapture, session?.context_id, captureAttempt]);
    const image = useMobileAssetUrl(api, capture?.image_url);
    const pair = async (code: string) => { setBusy(true); setError(''); try {
        cancelStreamIntent();
        await publisher.current?.stop();
        const value = await pairMobileBrowser(code);
        saveBrowserPairing(value);
        pairingRef.current = value;
        setPairing(value);
    }
    catch (cause) {
        setError(errorText(cause));
    }
    finally {
        setBusy(false);
    } };
    const disconnect = async () => {
        if (!api) return;
        setBusy(true);
        setError('');
        try {
            cancelStreamIntent();
            await closeBrowserSession(api, async () => { await publisher.current?.stop(); });
            saveBrowserPairing(null);
            pairingRef.current = null;
            setPairing(null);
            setRtc(idleBrowserRtc());
        } catch (cause) {
            setError(`中斷連線未完成，配對資料已保留，請重試：${errorText(cause)}`);
        } finally { setBusy(false); }
    };
    const join = async () => { if (!api)
        return; setBusy(true); setError(''); try {
        cancelStreamIntent();
        await publisher.current?.stop();
        await persist(draftRef.current);
        const next = await api.request<BrowserSession>('join', { method: 'POST' });
        acceptSession(next);
        setTicket(null);
        await refresh();
    }
    catch (cause) {
        setError(errorText(cause));
    }
    finally {
        setBusy(false);
    } };
    const older = async () => {
        if (!api || conversationRef.current?.before == null)
            return;
        try {
            const next = await api.request<AssistantConversation>(`conversation?limit=60&before=${encodeURIComponent(conversationRef.current.before)}`);
            const current = conversationRef.current;
            // Older pages contribute history, never replace a newer active-media reference.
            if (current && current.id === next.id)
                acceptConversation({ ...next, active_media: current.active_media, context_epoch: current.context_epoch, round: current.round, jobs: current.jobs, total: current.total });
        }
        catch (cause) {
            setError(errorText(cause));
        }
    };
    const setDraft = (text: string) => { if (ready)
        void commit(d => ({ ...d, text })).catch(() => undefined); };
    const addFiles = async (files: File[]): Promise<boolean> => { if (!ready || busy || attachmentFlight.current)
        return false; const key = workspaceKey.current, serial = owner.current, context = sessionRef.current?.context_id;
    const current = () => key === workspaceKey.current && serial === owner.current && context === sessionRef.current?.context_id;
    const flight = {};
    attachmentFlight.current = flight; setBusy(true); setError(''); try {
        const additions: BrowserAttachment[] = [];
        for (const file of files)
            additions.push(await browserAttachment(file));
        if (!current())
            return false;
        const invalid = validateBrowserAttachments([...draftRef.current.attachments, ...additions]);
        if (invalid)
            throw Error(invalid);
        await commit(d => ({ ...d, attachments: [...d.attachments, ...additions.map(preview)] }));
        return current();
    }
    catch (cause) {
        if (current()) setError(errorText(cause));
        return false;
    }
    finally {
        if (attachmentFlight.current === flight) {
            attachmentFlight.current = null;
            if (current()) setBusy(false);
        }
    } };
    const removeAttachment = (id: string) => void commit(d => ({ ...d, attachments: d.attachments.filter(a => a.id !== id) })).catch(() => undefined);
    const removeOutbox = (id: string) => { if (!sending.current.has(id))
        void commit(d => ({ ...d, outbox: d.outbox.filter(o => o.id !== id) })).catch(() => undefined); };
    const updateOutbox = async (id: string, update: (item: BrowserOutbox) => BrowserOutbox, save = true) => commit(d => ({ ...d, outbox: d.outbox.map(item => item.id === id ? update(item) : item) }), save);
    const deliver = async (item: BrowserOutbox) => {
        if (!api || sending.current.has(item.id))
            return;
        if (item.payload.context_id !== sessionRef.current?.context_id) {
            setError('這則待送訊息屬於另一個專案版本；請回到原專案後重試。');
            return;
        }
        const serial = owner.current, key = workspaceKey.current, abort = new AbortController();
        operations.current.add(abort);
        sending.current.add(item.id);
        const current = () => serial === owner.current && key === workspaceKey.current && item.payload.context_id === sessionRef.current?.context_id;
        try {
            await updateOutbox(item.id, o => ({ ...o, status: 'pending', error: undefined }));
            const assets: string[] = [];
            for (let index = 0; index < item.attachments.length; index++) {
                const attachment = item.attachments[index];
                let asset = attachment.asset;
                if (!asset) {
                    asset = await api.upload(attachment, progress => { if (current())
                        void updateOutbox(item.id, o => ({ ...o, attachments: o.attachments.map(a => a.id === attachment.id ? { ...a, progress } : a) }), false); }, abort.signal);
                    if (!current())
                        return;
                    const result = asset;
                    await updateOutbox(item.id, o => ({ ...o, attachments: o.attachments.map(a => a.id === attachment.id ? { ...a, asset: result, progress: 1 } : a) }));
                }
                assets.push(asset.id);
            }
            if (!current())
                return;
            const payload = { ...item.payload, asset_ids: item.attachments.length ? assets : item.payload.asset_ids };
            await updateOutbox(item.id, o => ({ ...o, payload }));
            ++refreshCounter.current;
            const next = await api.request<AssistantConversation>('messages', { method: 'POST', body: payload, signal: abort.signal, timeoutMs: 90000 });
            if (!current())
                return;
            ++refreshCounter.current;
            acceptConversation(next);
            await commit(d => ({ ...d, outbox: d.outbox.filter(o => o.id !== item.id) }));
            setError('');
        }
        catch (cause) {
            if (current()) {
                await updateOutbox(item.id, o => ({ ...o, status: 'failed', error: errorText(cause) })).catch(() => undefined);
                setError(errorText(cause));
            }
        }
        finally {
            sending.current.delete(item.id);
            operations.current.delete(abort);
        }
    };
    const send = async (options: SendOptions = {}) => {
        const context = sessionRef.current;
        if (!ready || !context || !api)
            return;
        // An explicit photo action belongs to that photo; leave unrelated composer media intact.
        const text = options.text ?? draftRef.current.text, attachments = options.capture_id ? [] : draftRef.current.attachments;
        if (!text.trim() && !attachments.length)
            return;
        if (options.capture_id && (!capture || capture.capture_id !== options.capture_id || capture.context_id !== context.context_id)) {
            setError('照片已切換，請重新選擇目前照片。');
            return;
        }
        const reference = browserMediaReference(conversationRef.current, context.context.round, attachments.length, options.capture_id);
        const id = browserUuid();
        const item: BrowserOutbox = { id, status: 'pending', attachments: [...attachments], payload: { request_id: id, text: text.trim(), asset_ids: reference.asset_ids, inherit_media: false, context_id: context.context_id, ...(attachments.length ? {} : options.capture_id ? { capture_id: options.capture_id } : reference.capture_id ? { capture_id: reference.capture_id } : {}), ...(options.check_scope ? { check_scope: options.check_scope } : {}), ...(options.wire_id ? { wire_id: options.wire_id } : {}) } };
        try {
            await commit(d => ({ ...d, text: options.text === undefined ? '' : d.text, attachments: options.capture_id ? d.attachments : [], outbox: [...d.outbox, item] }));
            await deliver(item);
        }
        catch (cause) {
            setError(errorText(cause));
        }
    };
    const retry = async (id: string) => { const item = draftRef.current.outbox.find(o => o.id === id); if (item)
        await deliver(item); };
    const startStream = async (options: BrowserStreamOptions = {}, automatic = false) => { if (!api || !publisher.current || streamFlight.current !== null)
        return; if (!secureContext || !navigator.mediaDevices?.getUserMedia) {
        setError('Safari 相機需要 HTTPS，請由桌面的 HTTPS 手機連結開啟。');
        return;
    } const pub = publisher.current, serial = owner.current, context = sessionRef.current;
    if (!context || !browserForeground() || (automatic && (!streamWanted.current || busy || ticketRef.current || draftRef.current.captureJob))) return;
    const intent = ++streamIntent.current;
    sourceRestart.current = null;
    streamFlight.current = intent; streamWanted.current = true;
    if (!automatic) reconnectAttempted.current = false;
    setStreamBusy(true); setError(''); streamOptions.current = { resolution: '1080p', bitrateKbps: 12000, ...options }; setTicket(null);
    const current = () => serial === owner.current && intent === streamIntent.current && streamWanted.current
        && context.session_id === sessionRef.current?.session_id && context.context_id === sessionRef.current?.context_id;
    try {
        const resumed = await restartMobileStream(() => pub.stop(), () => pub.start(streamOptions.current),
            () => current() && browserForeground() && (!automatic || (!ticketRef.current && !draftRef.current.captureJob)));
        if (resumed && current()) {
            const startedAt = Date.now();
            await refresh();
            if (current() && sessionRef.current?.stream.active) startedStream.current = { owner: serial,
                session: context.session_id, context: context.context_id, generation: sessionRef.current.stream.generation, startedAt };
        }
    }
    catch (cause) {
        if (current())
            setError(errorText(cause));
    } finally { if (streamFlight.current === intent) { streamFlight.current = null; setStreamBusy(false); } } };
    const stopStream = async () => { cancelStreamIntent(); lease.current = { key: '', deadline: 0 }; await publisher.current?.stop(); await refresh().catch(() => undefined); };
    useEffect(() => {
        const pending = sourceRestart.current;
        if (!pending) return;
        if (pending.owner !== owner.current || pending.intent !== streamIntent.current || !streamWanted.current
            || pending.session !== session?.session_id || pending.context !== session.context_id || !browserForeground()) {
            sourceRestart.current = null;
            return;
        }
        // Wait for an existing start or photo save to settle, then reconnect once
        // for this native source change. The publisher has already closed its peer.
        if (busy || streamBusy || streamFlight.current !== null || sending.current.size > 0
            || ticketRef.current || draftRef.current.captureJob) return;
        sourceRestart.current = null;
        void startStream(streamOptions.current, true);
    }, [clock, rtc.sourceChanged, session?.session_id, session?.context_id, busy, streamBusy, captureTicket, workspace.captureJob]);
    useEffect(() => {
        const started = startedStream.current;
        if (!started || started.owner !== owner.current || started.session !== session?.session_id
            || started.context !== session.context_id || started.generation !== session.stream.generation) return;
        if (!mobileReconnectEligible({ active: !!session?.stream.active, publishing: !!rtc.publishing,
            foreground: browserForeground(), wanted: streamWanted.current,
            busy: busy || streamBusy || streamFlight.current !== null || sending.current.size > 0,
            capturePending: !!ticketRef.current || !!draftRef.current.captureJob, attempted: reconnectAttempted.current,
            receiveAgeMs: mobileReconnectWaitMs(mobileVideoAgeMs(session?.stream), started.startedAt) })) return;
        reconnectAttempted.current = true;
        void startStream(streamOptions.current, true);
    }, [clock, session?.session_id, session?.context_id, session?.stream.generation, busy, streamBusy, rtc.publishing]);
    const beginCapture = async (options: { keepStreaming?: boolean } = {}): Promise<CaptureTicket | null> => {
        if (!api || !publisher.current || !rtc.publishing || busy || streamFlight.current !== null || !sessionRef.current?.stream.can_capture || lease.current.deadline <= performance.now()) {
            setError('請等畫面穩定並顯示可拍照，再拍攝正式照片。');
            return null;
        }
        const serial = owner.current, key = workspaceKey.current, contextId = sessionRef.current.context_id;
        const current = () => serial === owner.current && key === workspaceKey.current && contextId === sessionRef.current?.context_id;
        setBusy(true);
        setError('');
        try {
            const ticket = options.keepStreaming
                ? await api.request<CaptureTicket>('capture-ticket', { method: 'POST' })
                : await browserCaptureHandoff(api, publisher.current);
            if (!current() || ticket.context_id !== sessionRef.current?.context_id)
                return null;
            lease.current = { key: '', deadline: 0 };
            setTicket(ticket);
            return ticket;
        }
        catch (cause) {
            if (current()) setError(errorText(cause));
            return null;
        }
        finally {
            if (current()) setBusy(false);
        }
    };
    const runCapture = async (job: BrowserCaptureJob) => {
        if (!api || job.ticket.context_id !== sessionRef.current?.context_id) {
            setError('拍照所屬專案已變更，請重新開啟串流拍照。');
            return false;
        }
        const serial = owner.current, key = workspaceKey.current, abort = new AbortController();
        operations.current.add(abort);
        setBusy(true);
        setError('');
        const current = () => serial === owner.current && key === workspaceKey.current && job.ticket.context_id === sessionRef.current?.context_id;
        try {
            let attachment = job.attachment;
            if (!attachment.asset) {
                if (job.ticket.expires_at * 1000 <= Date.now())
                    throw Error('拍照票已逾時，請保留照片作一般附件，重新開啟串流拍攝定位照片。');
                const asset = await api.upload(attachment, progress => { if (current())
                    void commit(d => ({ ...d, captureJob: d.captureJob ? { ...d.captureJob, attachment: { ...d.captureJob.attachment, progress } } : null }), false); }, abort.signal);
                if (!current())
                    return;
                attachment = { ...attachment, asset, progress: 1 };
                const saved = { ...job, attachment, error: undefined };
                await commit(d => ({ ...d, captureJob: saved }));
            }
            const packet = await api.request<MobileCapture>('captures', { method: 'POST', body: { ticket_id: job.ticket.ticket_id, asset_id: attachment.asset!.id, request_id: job.request_id, capture_source: job.capture_source ?? 'camera_photo' }, signal: abort.signal, timeoutMs: 180000 });
            if (!current())
                return;
            if (!acceptMobileCapture(packet) || packet.context_id !== sessionRef.current?.context_id)
                throw Error('照片定位回傳資料不一致');
            await commit(d => ({ ...d, captureJob: null }));
            if (!current()) return false;
            setTicket(null);
            await refresh();
            if (!current()) return false;
            setCaptureAttempt(n => n + 1);
            return true;
        }
        catch (cause) {
            if (current()) {
                await commit(d => ({ ...d, captureJob: d.captureJob ? { ...d.captureJob, error: errorText(cause) } : null })).catch(() => undefined);
                setError(errorText(cause));
            }
            return false;
        }
        finally {
            operations.current.delete(abort);
            if (current())
                setBusy(false);
        }
    };
    const finishCapture = async (file: File, ticket: CaptureTicket | null = ticketRef.current, source: BrowserCaptureJob['capture_source'] = 'camera_photo') => {
        if (!ticket || ticket.context_id !== sessionRef.current?.context_id) {
            setError('沒有有效拍照票，請重新開啟串流。');
            return;
        }
        const serial = owner.current, key = workspaceKey.current;
        setBusy(true);
        try {
            const attachment = await browserAttachment(file);
            if (serial !== owner.current || key !== workspaceKey.current || ticket.context_id !== sessionRef.current?.context_id)
                return;
            if (attachment.type !== 'image')
                throw Error('GPIO 定位需要新拍攝的照片');
            const job: BrowserCaptureJob = { ticket, attachment: preview(attachment), request_id: browserUuid(), capture_source: source };
            await commit(d => ({ ...d, captureJob: job }));
            if (serial !== owner.current || key !== workspaceKey.current || ticket.context_id !== sessionRef.current?.context_id) return false;
            return await runCapture(job);
        }
        catch (cause) {
            if (serial === owner.current && key === workspaceKey.current && ticket.context_id === sessionRef.current?.context_id) setError(errorText(cause));
        }
        finally {
            if (serial === owner.current && key === workspaceKey.current && ticket.context_id === sessionRef.current?.context_id) setBusy(false);
        }
    };
    const cancelCapture = async (options: {
        resume?: boolean;
        ticketId?: string;
    } = {}) => { if (options.ticketId && options.ticketId !== ticketRef.current?.ticket_id) return; setTicket(null); if (options.resume)
        await startStream(streamOptions.current); };
    const retryCapture = async () => { if (draftRef.current.captureJob)
        await runCapture(draftRef.current.captureJob); };
    const discardCapture = () => { setTicket(null); void commit(d => ({ ...d, captureJob: null })).catch(() => undefined); };
    const updateView = async (captureId: string | null, wireId: string | null) => {
        if (!api)
            return;
        const serial = owner.current;
        try {
            const view = await api.request<BrowserSession['view']>('view', { method: 'PUT', body: { capture_id: captureId, wire_id: wireId } });
            if (serial === owner.current && sessionRef.current && view.revision >= sessionRef.current.view.revision)
                acceptSession({ ...sessionRef.current, view });
        }
        catch (cause) {
            setError(errorText(cause));
        }
    };
    const openCapture = (id: string) => updateView(id, null);
    const selectWire = (id: string) => updateView(sessionRef.current?.view.capture_id ?? null, id);
    const inheritedMediaLabel = browserMediaReference(conversation, session?.context.round, workspace.attachments.length).label;
    const currentRtc = mobileMeasurementFresh(rtcMeasurement.current.at, clock) ? rtc : { ...rtc,
        stats: { appliedBitrateKbps: rtc.stats.appliedBitrateKbps, parameterStatus: rtc.stats.parameterStatus } };
    const receiveFresh = mobileVideoFresh(session?.stream);
    return { pairing, api, session, conversation, capture, captureImageUrl: image.url, imageError: captureError || image.error,
        draft: workspace.text, setDraft, attachments: workspace.attachments, outbox: workspace.outbox, captureTicket, captureJob: workspace.captureJob,
        busy: busy || streamBusy, error, connected, ready, secureContext, rtc: currentRtc,
        previewFresh: connected && receiveFresh && !!rtc.publishing && !!rtc.stream && lease.current.deadline > clock,
        canCapture: connected && receiveFresh && !!rtc.publishing && !!rtc.stream && !!session?.stream.can_capture && lease.current.deadline > clock && !busy && !streamBusy, inheritedMediaLabel,
        pair, disconnect, join, send, retry, removeOutbox, removeAttachment, addFiles, startStream, stopStream, beginCapture, finishCapture, cancelCapture, retryCapture, discardCapture, openCapture, selectWire, older, refresh,
        retryCaptureImage: () => { setCaptureAttempt(n => n + 1); image.retry(); } };
}
