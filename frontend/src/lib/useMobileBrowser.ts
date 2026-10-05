import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { acceptMobileCapture, mobileVideoAgeMs, mobileVideoFresh } from './mobile';
import { mobileMeasurementFresh, mobileReconnectEligible, mobileReconnectWaitMs, restartMobileStream } from './mobileViewerStats';
import { MobileBrowserApi, browserAttachment, browserLease, browserMediaReference, browserUuid, closeBrowserSession, emptyBrowserDraft, expiredBrowserSession, loadBrowserDraft, loadBrowserPairing, mergeBrowserConversation, mergeBrowserSession, mobileBrowserDraftKey, pairMobileBrowser, sameBrowserPairing, saveBrowserDraft, saveBrowserPairing, validateBrowserAttachments, type AssistantConversation, type BrowserAttachment, type BrowserCaptureJob, type BrowserDraft, type BrowserOutbox, type BrowserPairing, type BrowserSession, type CaptureTicket, type MobileCapture, } from './mobileBrowser';
import { BrowserPublisher, browserCaptureHandoff, idleBrowserRtc, type BrowserStreamOptions } from './mobileBrowserRtc';
import { usePhoneCameraTune } from './usePhoneCameraTune';
import { boundWiringAction, type WiringPhotoRole, type WiringReviewAction, type WiringReviewState } from './wiringReview';
import type { AssistantMessage, AssistantTestHelpOffer } from './assistant';
import { assistantModelRunning, assistantWiringAnalysis } from './assistantAnalysis';
const EXPIRED_SESSION_MESSAGE = '手機連線已失效，請重新輸入電腦顯示的新配對碼。草稿與附件已保留。';
const errorText = (cause: unknown) => expiredBrowserSession(cause) ? EXPIRED_SESSION_MESSAGE
    : cause && typeof cause === 'object' && 'detail' in cause && cause.detail === 'wiring_analysis_in_progress'
      ? '接線照片正在分析，完成後才能送出訊息。文字與附件已保留。'
      : cause instanceof Error ? cause.message : String(cause);
const browserForeground = () => document.visibilityState !== 'hidden';
interface MobileWiringSnapshot { review: WiringReviewState | null; component_label?: string; can_act: boolean; offer?: AssistantTestHelpOffer; conversation?: AssistantConversation }
export interface MobileWiringPhotoRequest {
    message_id: string; flow_id: string; request_id: string; role: WiringPhotoRole;
    review: WiringReviewState; contextId: string; conversationId: string; epoch: number;
}
interface MobileTestHelpError { messageId: string; offerId: string; op: 'start' | 'later'; text: string }
/** Message actions require the server offer and the paired workspace, never matching chat text. */
export function mobileTestHelpOffer(message: AssistantMessage, session: BrowserSession | null, conversation: AssistantConversation | null): AssistantTestHelpOffer | null {
    const offer = message.test_help_offer, workspace = session?.context, design = workspace?.design?.current;
    if (!session || !conversation || !offer || conversation.id !== session.conversation_id || message.role !== 'assistant'
        || message.source !== 'legacy-debug' || offer.message_id !== message.id || !offer.offer_id || offer.mode !== 'wiring'
        || !(offer.can_act || offer.can_dismiss) || !['pending', 'started'].includes(offer.state) || message.archived
        || message.epoch !== conversation.context_epoch || offer.context_epoch !== conversation.context_epoch
        || message.round !== offer.guide_run || workspace?.round !== offer.guide_run
        || session.available_context && session.available_context.context_id !== session.context_id
        || !design || design.id !== offer.project_id || design.revision !== offer.project_revision
        || !design.component_ids.some(componentId => componentId === offer.component_id)
        || workspace?.context?.debug_context?.guide_run !== offer.guide_run
        || workspace?.context?.debug_context?.test_keys?.[offer.component_id] !== offer.guide_key) return null;
    return offer;
}
interface PendingWiringPhoto { attachment: BrowserAttachment; role: WiringPhotoRole; review: WiringReviewState; contextId: string; dialogue?: MobileWiringPhotoRequest }
/** Only the current server question can bind a photo; visible chat text is never a role. */
export function mobileWiringPhotoFlow(message: AssistantMessage, session: BrowserSession | null, conversation: AssistantConversation | null,
    review: WiringReviewState | null, canAct: boolean) {
    const flow = message.wiring_flow;
    if (!session || !conversation || !review || !flow || !canAct || flow.current !== true || flow.can_act !== true || !flow.flow_id
        || !Number.isInteger(flow.revision) || flow.revision < 0 || !Number.isInteger(flow.round) || flow.round < 0
        || message.role !== 'assistant' || flow.kind !== 'photo_request' || !Array.isArray(flow.actions) || !flow.actions.includes('capture')
        || !flow.role || !['pi_side_a', 'pi_side_b', 'component_header'].includes(flow.role)
        || conversation.id !== session.conversation_id || message.epoch !== conversation.context_epoch || message.archived
        || message.round !== session.context.round || session.available_context && session.available_context.context_id !== session.context_id
        || flow.review_id !== review.id || flow.revision !== review.revision || flow.round !== review.round
        || flow.component_id !== review.component_id || ['stale', 'analysing'].includes(review.status)) return null;
    return flow;
}
const wiringErrorText = (cause: unknown) => {
    const detail = cause && typeof cause === 'object' && 'detail' in cause ? String(cause.detail) : errorText(cause);
    const labels: Record<string, string> = {
        stale_wiring_review: '照片輪次或視角已更新，請查看目前這一輪後重新拍攝。',
        stale_wiring_review_photo: '這張照片已被替換，請查看目前照片後再選用。',
        stale_wiring_dialogue: '拍照問題已更新，請使用目前那則訊息的拍照按鈕。',
        wiring_dialogue_reference_required: '請取得最新對話，再用目前那則訊息的按鈕提交照片。',
        wiring_dialogue_role_mismatch: '照片視角與目前問題不一致，請從目前那則訊息重新拍攝。',
        request_id_conflict: '這張照片的提交已變更，請取得最新對話後重新拍攝。',
        action_result_unknown: '尚未確認這張照片是否送達，請取得最新對話後再重試。',
        model_call_in_progress: '照片分析正在進行，完成後才能繼續操作。',
        wiring_analysis_in_progress: '接線照片正在分析，完成後才能送出訊息。文字與附件已保留。',
        mobile_wiring_review_busy_or_source_changed: '電腦仍在處理，或鏡頭來源已變更。請等目前操作完成；切換鏡頭後請回電腦重新開啟拍照核對。',
        mobile_wiring_review_context_changed: '電腦已更新作品或接線輪次，請加入目前作品後重新拍攝。',
        mobile_context_changed: '電腦已更新工作區，請加入目前作品後重新拍攝。',
        wiring_review_photos_incomplete: '請先完成 Pi 兩側與零件接頭的拍攝。',
        wiring_review_photos_not_accepted: '請先逐張查看並選擇使用照片，再開始分析。',
        human_review_required: '這些照片仍不足以判斷，請回到電腦查看下一步並親自沿線核對。',
        test_help_stale: '這個拍照邀請已更新，請查看目前的助手回覆後再操作。',
        test_help_context_changed: '電腦已更新作品或接線輪次，請加入目前作品後再開始。',
        test_help_busy: '電腦正在處理目前操作，請稍候再試。',
    };
    return labels[detail] ?? errorText(cause);
};
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
    const captureFlight = useRef(false);
    const [capture, setCapture] = useState<MobileCapture | null>(null), [captureError, setCaptureError] = useState('');
    const [wiringSnapshot, setWiringSnapshot] = useState<MobileWiringSnapshot>({ review: null, can_act: false });
    const wiringSnapshotRef = useRef(wiringSnapshot); wiringSnapshotRef.current = wiringSnapshot;
    const [wiringReviewError, setWiringReviewError] = useState(''), [wiringReviewBusy, setWiringReviewBusy] = useState(false);
    const [pendingWiringPhoto, setPendingWiringPhoto] = useState<PendingWiringPhoto | null>(null);
    const pendingWiringPhotoRef = useRef(pendingWiringPhoto); pendingWiringPhotoRef.current = pendingWiringPhoto;
    const wiringRecovery = useRef<{ action: WiringReviewAction; review: WiringReviewState } | null>(null);
    const wiringFlight = useRef<object | null>(null), wiringRefreshCounter = useRef(0);
    const wiringPhotoPreparing = useRef<object | null>(null);
    const testHelpRequest = useRef<{ flight: object; abort: AbortController } | null>(null);
    const [testHelpPendingMessageId, setTestHelpPendingMessageId] = useState<string | null>(null);
    const [testHelpError, setTestHelpError] = useState<MobileTestHelpError | null>(null);
    const cancelTestHelp = () => {
        const pending = testHelpRequest.current;
        if (pending) {
            pending.abort.abort();
            if (wiringFlight.current === pending.flight) { wiringFlight.current = null; setWiringReviewBusy(false); }
        }
        testHelpRequest.current = null; setTestHelpPendingMessageId(null); setTestHelpError(null);
    };
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
        cancelTestHelp();
        lifecycleCleanup.current?.(false);
        lease.current = { key: '', deadline: 0 };
        sessionRef.current = null; conversationRef.current = null;
        setSession(null); setConversation(null); setCapture(null); setTicket(null);
        wiringRefreshCounter.current++; wiringFlight.current = null;
        wiringPhotoPreparing.current = null;
        wiringSnapshotRef.current = { review: null, can_act: false };
        setWiringSnapshot({ review: null, can_act: false }); setWiringReviewBusy(false); setPendingWiringPhoto(null);
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
            cancelTestHelp();
            wiringPhotoPreparing.current = null;
            cancelStreamIntent();
            attachmentFlight.current = null;
            setBusy(false);
            void publisher.current?.stop();
            setCapture(null);
            setTicket(null);
            lease.current = { key: '', deadline: 0 };
            wiringRefreshCounter.current++; wiringFlight.current = null;
            wiringSnapshotRef.current = { review: null, can_act: false };
            setWiringSnapshot({ review: null, can_act: false }); setWiringReviewBusy(false); setPendingWiringPhoto(null);
        }
        if (previous?.conversation_id !== merged.conversation_id) {
            cancelTestHelp();
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
        if (conversationRef.current && conversationRef.current.context_epoch !== merged.context_epoch) {
            cancelTestHelp();
            if (pendingWiringPhotoRef.current?.dialogue) {
                wiringRefreshCounter.current++; wiringFlight.current = null; wiringPhotoPreparing.current = null;
                pendingWiringPhotoRef.current = null; setPendingWiringPhoto(null); setWiringReviewBusy(false); setWiringReviewError('');
            }
        }
        conversationRef.current = merged;
        setConversation(merged);
        setTestHelpError(previous => {
            const offer = merged.messages.find(message => message.id === previous?.messageId)?.test_help_offer;
            return previous && offer?.offer_id === previous.offerId
                && offer.state === (previous.op === 'later' ? 'dismissed' : 'started') ? null : previous;
        });
    }, [pairing?.conversation_id]);
    const refreshWiringReview = useCallback(async () => {
        if (!api || wiringFlight.current || !sessionRef.current) return;
        const serial = owner.current, contextId = sessionRef.current.context_id, request = ++wiringRefreshCounter.current;
        try {
            const next = await api.request<MobileWiringSnapshot>('wiring-review');
            if (serial !== owner.current || contextId !== sessionRef.current?.context_id || request !== wiringRefreshCounter.current) return;
            const previous = wiringSnapshotRef.current.review;
            if (previous && next.review?.id === previous.id && next.review.revision < previous.revision) return;
            wiringSnapshotRef.current = next; setWiringSnapshot(next);
            if (next.conversation) acceptConversation(next.conversation);
            const pending = pendingWiringPhotoRef.current, updated = next.review;
            if (pending && updated?.id === pending.review.id && updated.round === pending.review.round
                && updated.component_id === pending.review.component_id && pending.contextId === contextId) {
                const slot = updated.slots[pending.role] as (NonNullable<WiringReviewState['slots'][WiringPhotoRole]> & { provenance?: { asset_id?: string; sha256?: string } }) | null;
                const asset = pending.attachment.asset as (BrowserAttachment['asset'] & { sha256?: string });
                // A failed response is ambiguous: the next snapshot may prove
                // the same immutable asset was saved, without approving the photo.
                if (slot && asset?.id && slot.provenance?.asset_id === asset.id
                    && slot.sha256 === (asset.sha256 ?? slot.provenance.sha256)) {
                    pendingWiringPhotoRef.current = null; setPendingWiringPhoto(null); setWiringReviewError('');
                }
            }
            const recovery = wiringRecovery.current;
            if (recovery && updated?.id === recovery.review.id && updated.round === recovery.review.round && updated.component_id === recovery.review.component_id) {
                const action = recovery.action, slot = action.role ? updated.slots[action.role] : null, receipt = slot?.photo_acceptance;
                if (action.op === 'accept_photo' && slot && slot.capture_id === action.capture_id && slot.sha256 === action.sha256
                    && receipt?.source === 'human' && receipt.capture_id === slot.capture_id && receipt.sha256 === slot.sha256 && receipt.round === updated.round
                    || (action.op === 'analyse' && ['analysing', 'ready', 'needs_human'].includes(updated.status) && updated.revision > recovery.review.revision)) {
                    wiringRecovery.current = null; setWiringReviewError('');
                }
            }
        } catch (cause) {
            if (serial === owner.current && contextId === sessionRef.current?.context_id && request === wiringRefreshCounter.current) {
                const missing = cause && typeof cause === 'object' && 'status' in cause && cause.status === 404
                    && 'detail' in cause && ['Not Found', 'HTTP 404'].includes(String(cause.detail));
                if (missing) {
                    // Existing deployments without the new endpoint retain
                    // normal phone chat and single-photo capture behaviour.
                    wiringSnapshotRef.current = { review: null, can_act: false }; setWiringSnapshot({ review: null, can_act: false }); setWiringReviewError('');
                } else setWiringReviewError(wiringErrorText(cause));
            }
        }
    }, [api]);
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
            if (serial === owner.current) await refreshWiringReview();
        }
        catch (cause) {
            if (serial === owner.current) {
                setConnected(false);
                lease.current = { key: '', deadline: 0 };
                setError(errorText(cause));
            }
            throw cause;
        }
    }, [api, acceptSession, acceptConversation, refreshWiringReview]);
    useEffect(() => {
        owner.current++;
        cancelTestHelp();
        const serial = owner.current;
        wiringPhotoPreparing.current = null;
        attachmentFlight.current = null;
        setBusy(false);
        sessionRef.current = null;
        conversationRef.current = null;
        setSession(null);
        setConversation(null);
        setCapture(null);
        wiringRefreshCounter.current++; wiringFlight.current = null;
        wiringSnapshotRef.current = { review: null, can_act: false };
        setWiringSnapshot({ review: null, can_act: false }); setWiringReviewError(''); setWiringReviewBusy(false); setPendingWiringPhoto(null);
        setTicket(null);
        setConnected(false);
        lease.current = { key: '', deadline: 0 };
        if (!api)
            return;
        const pub = new BrowserPublisher(api, state => {
            if (serial !== owner.current) return;
            if (state.stats !== rtcMeasurement.current.stats) rtcMeasurement.current = { stats: state.stats, at: performance.now() };
            // A completed publisher negotiation owns this generation; chat refresh
            // failures must not prevent recovery of an already-running camera.
            const context = sessionRef.current, started = startedStream.current;
            if (state.publishing && state.stream && Number.isInteger(state.generation) && state.generation! >= 1
                && streamWanted.current && context && (!started || started.owner !== serial
                    || started.session !== context.session_id || started.context !== context.context_id || started.generation !== state.generation)) {
                startedStream.current = { owner: serial, session: context.session_id, context: context.context_id,
                    generation: state.generation!, startedAt: Date.now() };
            }
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
            cancelTestHelp();
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
    const wiringCurrent = (review: WiringReviewState, contextId: string) => {
        const current = wiringSnapshotRef.current.review;
        return contextId === sessionRef.current?.context_id && wiringSnapshotRef.current.can_act
            && current?.id === review.id && current.round === review.round && current.component_id === review.component_id
            && current.revision === review.revision;
    };
    const wiringChatCurrent = (request: MobileWiringPhotoRequest) => {
        const context = sessionRef.current, chat = conversationRef.current;
        const message = chat?.messages.find(item => item.id === request.message_id);
        const flow = message ? mobileWiringPhotoFlow(message, context, chat, wiringSnapshotRef.current.review, wiringSnapshotRef.current.can_act) : null;
        return Boolean(flow && context?.context_id === request.contextId && chat?.id === request.conversationId
            && chat.context_epoch === request.epoch && flow.flow_id === request.flow_id && flow.role === request.role
            && flow.review_id === request.review.id && flow.revision === request.review.revision && flow.round === request.review.round);
    };
    const prepareWiringChatPhoto = (message: AssistantMessage): MobileWiringPhotoRequest | null => {
        const context = sessionRef.current, chat = conversationRef.current, review = wiringSnapshotRef.current.review;
        const entry = chat?.messages.find(item => item.id === message.id);
        const flow = entry ? mobileWiringPhotoFlow(entry, context, chat, review, wiringSnapshotRef.current.can_act) : null;
        if (!ready || !connected || !context || !chat || !review || !flow?.role || wiringFlight.current || wiringPhotoPreparing.current
            || message.wiring_flow?.flow_id !== flow.flow_id) return null;
        return { message_id: message.id, flow_id: flow.flow_id, request_id: browserUuid(), role: flow.role, review,
            contextId: context.context_id, conversationId: chat.id, epoch: chat.context_epoch };
    };
    const testHelpAction = async (message: AssistantMessage, op: 'start' | 'later') => {
        const context = sessionRef.current, chat = conversationRef.current;
        const currentMessage = chat?.messages.find(item => item.id === message.id);
        const offer = currentMessage ? mobileTestHelpOffer(currentMessage, context, chat) : null;
        if (!api || !ready || !connected || !context || !chat || !offer || wiringFlight.current
            || op === 'start' && !offer.can_act || op === 'later' && !offer.can_dismiss
            || message.test_help_offer?.offer_id !== offer.offer_id) return false;
        const serial = owner.current, epoch = chat.context_epoch, flight = {}, abort = new AbortController();
        wiringFlight.current = flight; testHelpRequest.current = { flight, abort };
        wiringRefreshCounter.current++; refreshCounter.current++; operations.current.add(abort);
        setWiringReviewBusy(true); setTestHelpPendingMessageId(message.id); setTestHelpError(null);
        const current = () => {
            const latest = conversationRef.current, entry = latest?.messages.find(item => item.id === message.id), fresh = entry?.test_help_offer;
            return serial === owner.current && !abort.signal.aborted && wiringFlight.current === flight
                && context.context_id === sessionRef.current?.context_id && context.conversation_id === sessionRef.current?.conversation_id
                && latest?.context_epoch === epoch && entry?.epoch === epoch && fresh?.offer_id === offer.offer_id
                && fresh.project_id === offer.project_id && fresh.project_revision === offer.project_revision
                && fresh.guide_run === offer.guide_run && fresh.guide_key === offer.guide_key
                && !['dismissed', 'stale'].includes(fresh.state)
                && (!sessionRef.current?.available_context || sessionRef.current.available_context.context_id === context.context_id);
        };
        try {
            const next = await api.request<MobileWiringSnapshot>('wiring-review', { method: 'POST', body: {
                invitation: { op, message_id: message.id, offer_id: offer.offer_id, context_id: context.context_id },
            }, signal: abort.signal, timeoutMs: 90000 });
            if (!current()) return false;
            const receipt = next.offer;
            if (!receipt || receipt.offer_id !== offer.offer_id || receipt.message_id !== message.id
                || receipt.context_epoch !== epoch || receipt.project_id !== offer.project_id || receipt.project_revision !== offer.project_revision
                || receipt.guide_run !== offer.guide_run || receipt.guide_key !== offer.guide_key
                || receipt.state !== (op === 'later' ? 'dismissed' : 'started')
                || next.conversation && (next.conversation.id !== chat.id || next.conversation.context_epoch !== epoch)
                || op === 'start' && next.review?.component_id !== offer.component_id) throw Error('拍照邀請回覆與目前作品不一致，請重新取得引導後再試。');
            wiringRefreshCounter.current++; refreshCounter.current++;
            const previous = wiringSnapshotRef.current.review;
            if (!previous || next.review?.id !== previous.id || next.review.revision >= previous.revision) {
                wiringSnapshotRef.current = next; setWiringSnapshot(next);
            }
            const synchronized = next.conversation ?? conversationRef.current!;
            acceptConversation({ ...synchronized, messages: synchronized.messages.map(item => item.id === message.id
                ? { ...item, test_help_offer: receipt } : item) });
            setTestHelpError(null); return true;
        } catch (cause) {
            if (current()) setTestHelpError({ messageId: message.id, offerId: offer.offer_id, op, text: wiringErrorText(cause) });
            return false;
        } finally {
            operations.current.delete(abort);
            if (testHelpRequest.current?.flight === flight) testHelpRequest.current = null;
            if (wiringFlight.current === flight) { wiringFlight.current = null; setWiringReviewBusy(false); setTestHelpPendingMessageId(null); }
        }
    };
    const wiringReviewAction = async (action: WiringReviewAction) => {
        const review = wiringSnapshotRef.current.review, context = sessionRef.current;
        if (!api || !review || !context || wiringFlight.current) return null;
        // A paired phone may collect photographs and observe results; physical
        // confirmations, wiring changes and tests remain explicit desktop actions.
        if (!['accept_photo', 'crop', 'analyse'].includes(action.op)) {
            const message = '手機只能拍攝照片與查看分析，接線確認請回到電腦操作。'; setWiringReviewError(message); throw Error(message);
        }
        if (action.review_id !== review.id || action.revision !== review.revision || !wiringCurrent(review, context.context_id)) {
            const message = '照片輪次或視角已更新，請查看目前這一輪再操作。'; setWiringReviewError(message); throw Error(message);
        }
        const serial = owner.current, flight = {}, abort = new AbortController();
        wiringFlight.current = flight; wiringRefreshCounter.current++; operations.current.add(abort);
        setWiringReviewBusy(true); setWiringReviewError('');
        const current = () => serial === owner.current && context.context_id === sessionRef.current?.context_id && wiringFlight.current === flight;
        try {
            const next = await api.request<MobileWiringSnapshot>('wiring-review', { method: 'POST', body: { action }, signal: abort.signal, timeoutMs: 90000 });
            if (!current()) return null;
            wiringRefreshCounter.current++; wiringSnapshotRef.current = next; setWiringSnapshot(next);
            wiringRecovery.current = null;
            return next.review;
        } catch (cause) {
            if (current()) { wiringRecovery.current = { action, review }; setWiringReviewError(wiringErrorText(cause)); }
            throw cause;
        } finally {
            operations.current.delete(abort);
            if (wiringFlight.current === flight) { wiringFlight.current = null; setWiringReviewBusy(false); }
        }
    };
    const runWiringPhoto = async (pending: PendingWiringPhoto) => {
        if (!api || wiringFlight.current) return false;
        if (!wiringCurrent(pending.review, pending.contextId) || pending.dialogue && !wiringChatCurrent(pending.dialogue)) {
            setWiringReviewError('照片輪次或視角已更新，這張待送照片不能加入新一輪；請重拍目前要求的視角。');
            return false;
        }
        const serial = owner.current, flight = {}, abort = new AbortController();
        wiringFlight.current = flight; wiringRefreshCounter.current++; operations.current.add(abort);
        setWiringReviewBusy(true); setWiringReviewError('');
        const current = () => serial === owner.current && pending.contextId === sessionRef.current?.context_id && wiringFlight.current === flight
            && (!pending.dialogue || wiringChatCurrent(pending.dialogue));
        try {
            let attachment = pending.attachment;
            if (!attachment.asset) {
                const asset = await api.upload(attachment, progress => { if (current()) setPendingWiringPhoto(value => value ? { ...value, attachment: { ...value.attachment, progress } } : null); }, abort.signal);
                if (!current()) return false;
                attachment = { ...attachment, asset, progress: 1 };
                pendingWiringPhotoRef.current = { ...pending, attachment };
                setPendingWiringPhoto({ ...pending, attachment });
            }
            if (!current()) return false;
            const next = await api.request<MobileWiringSnapshot>('wiring-review', { method: 'POST', body: {
                action: boundWiringAction(pending.review, { op: 'capture', role: pending.role }), asset_id: attachment.asset!.id,
                ...(pending.dialogue ? { dialogue: { message_id: pending.dialogue.message_id, flow_id: pending.dialogue.flow_id, request_id: pending.dialogue.request_id } } : {}),
            }, signal: abort.signal, timeoutMs: 90000 });
            if (!current()) return false;
            if (pending.dialogue) {
                const slot = next.review?.slots[pending.role] as (NonNullable<WiringReviewState['slots'][WiringPhotoRole]> & { provenance?: { asset_id?: string } }) | null | undefined;
                const accepted = slot?.photo_acceptance, asset = attachment.asset as BrowserAttachment['asset'] & { sha256?: string };
                if (!next.conversation || next.conversation.id !== pending.dialogue.conversationId || next.conversation.context_epoch !== pending.dialogue.epoch
                    || next.review?.id !== pending.review.id || next.review.round !== pending.review.round || next.review.component_id !== pending.review.component_id
                    || next.review.revision < pending.review.revision || !slot || !slot.sha256 || slot.provenance?.asset_id !== asset.id
                    || asset.sha256 && asset.sha256 !== slot.sha256 || accepted?.source !== 'human'
                    || accepted.capture_id !== slot.capture_id || accepted.sha256 !== slot.sha256 || accepted.round !== next.review.round)
                    throw Error('照片回覆與目前拍照問題不一致，請重新取得對話後再試。');
            }
            wiringRefreshCounter.current++; refreshCounter.current++; wiringSnapshotRef.current = next; setWiringSnapshot(next);
            if (next.conversation) acceptConversation(next.conversation);
            pendingWiringPhotoRef.current = null; setPendingWiringPhoto(null);
            return true;
        } catch (cause) {
            if (current()) setWiringReviewError(wiringErrorText(cause));
            return false;
        } finally {
            operations.current.delete(abort);
            if (wiringFlight.current === flight) { wiringFlight.current = null; setWiringReviewBusy(false); }
        }
    };
    const uploadWiringPhoto = async (file: File, role: WiringPhotoRole, review: WiringReviewState, dialogue?: MobileWiringPhotoRequest) => {
        const contextId = sessionRef.current?.context_id;
        if (dialogue && (dialogue.contextId !== contextId || dialogue.conversationId !== conversationRef.current?.id
            || dialogue.epoch !== conversationRef.current?.context_epoch)) return false;
        if (!ready || !contextId || wiringFlight.current || wiringPhotoPreparing.current || !wiringCurrent(review, contextId)
            || dialogue && (dialogue.role !== role || dialogue.review !== review || !wiringChatCurrent(dialogue))) {
            setWiringReviewError('照片輪次或視角已更新，請查看目前這一輪後重新拍攝。'); return false;
        }
        const serial = owner.current, preparation = {}; wiringPhotoPreparing.current = preparation;
        try {
            const attachment = await browserAttachment(file);
            if (serial !== owner.current || !wiringCurrent(review, contextId) || dialogue && !wiringChatCurrent(dialogue)) return false;
            if (attachment.type !== 'image') throw Error('接線視角需要照片，請重新拍攝。');
            const pending = { attachment, role, review, contextId, ...(dialogue ? { dialogue } : {}) };
            pendingWiringPhotoRef.current = pending;
            setPendingWiringPhoto(pending);
            return await runWiringPhoto(pending);
        } catch (cause) { if (serial === owner.current && contextId === sessionRef.current?.context_id) setWiringReviewError(wiringErrorText(cause)); return false; }
        finally { if (wiringPhotoPreparing.current === preparation) wiringPhotoPreparing.current = null; }
    };
    const uploadWiringChatPhoto = (file: File, request: MobileWiringPhotoRequest) => uploadWiringPhoto(file, request.role, request.review, request);
    const retryWiringPhoto = async () => pendingWiringPhoto ? runWiringPhoto(pendingWiringPhoto) : false;
    const discardWiringPhoto = () => { if (!wiringFlight.current) { pendingWiringPhotoRef.current = null; setPendingWiringPhoto(null); setWiringReviewError(''); } };
    const removeOutbox = (id: string) => { if (!sending.current.has(id))
        void commit(d => ({ ...d, outbox: d.outbox.filter(o => o.id !== id) })).catch(() => undefined); };
    const updateOutbox = async (id: string, update: (item: BrowserOutbox) => BrowserOutbox, save = true) => commit(d => ({ ...d, outbox: d.outbox.map(item => item.id === id ? update(item) : item) }), save);
    // Read the latest server snapshot at the event boundary, including a reply
    // that arrived after the composer rendered or while an attachment uploaded.
    const chatModelBusy = () => Boolean(assistantWiringAnalysis(conversationRef.current) || assistantModelRunning(conversationRef.current));
    const chatSendBlocked = busy || streamBusy || wiringReviewBusy || chatModelBusy();
    const deliver = async (item: BrowserOutbox) => {
        if (!api || sending.current.has(item.id) || chatModelBusy() || wiringFlight.current)
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
            if (chatModelBusy() || wiringFlight.current)
                throw Error('AI 正在分析，完成後才能送出這則訊息。待送文字與附件已保留。');
            const payload = { ...item.payload, asset_ids: item.attachments.length ? assets : item.payload.asset_ids };
            await updateOutbox(item.id, o => ({ ...o, payload }));
            if (chatModelBusy() || wiringFlight.current)
                throw Error('AI 正在分析，完成後才能送出這則訊息。待送文字與附件已保留。');
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
        if (!ready || !context || !api || busy || streamBusy || attachmentFlight.current || wiringFlight.current || chatModelBusy())
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
    const startStream = async (options: BrowserStreamOptions = {}, automatic = false) => { if (!api || !publisher.current || streamFlight.current !== null || captureFlight.current || cameraTune.isRunning?.())
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
            await refresh();
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
        if (!api || !publisher.current || !rtc.publishing || busy || captureFlight.current || cameraTune.isRunning?.() || streamFlight.current !== null || !sessionRef.current?.stream.can_capture || lease.current.deadline <= performance.now()) {
            setError('請等畫面穩定並顯示可拍照，再拍攝正式照片。');
            return null;
        }
        const serial = owner.current, key = workspaceKey.current, contextId = sessionRef.current.context_id;
        const current = () => serial === owner.current && key === workspaceKey.current && contextId === sessionRef.current?.context_id;
        captureFlight.current = true;
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
            captureFlight.current = false;
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
    const cameraTune = usePhoneCameraTune({ stream: currentRtc.stream,
        scope: `${session?.session_id ?? ''}:${session?.context_id ?? ''}:${currentRtc.generation ?? ''}`,
        busy: busy || streamBusy || wiringReviewBusy || Boolean(captureTicket || workspace.captureJob),
        blocked: () => captureFlight.current || streamFlight.current !== null || Boolean(ticketRef.current || draftRef.current.captureJob), stats: currentRtc.stats,
        readBitrate: stream => publisher.current?.readLiveBitrate(stream) ?? null,
        adjustBitrate: (stream, value, signal) => publisher.current?.adjustLiveBitrate(stream, value, signal) ?? Promise.reject(Error('phone_tune_source_changed')) });
    return { pairing, api, session, conversation, capture, captureImageUrl: image.url, imageError: captureError || image.error,
        wiringReview: wiringSnapshot.review, wiringComponentLabel: wiringSnapshot.component_label, wiringCanAct: wiringSnapshot.can_act,
        wiringReviewBusy, wiringReviewError, pendingWiringPhoto, wiringReviewAction, uploadWiringPhoto, retryWiringPhoto, discardWiringPhoto, refreshWiringReview,
        prepareWiringChatPhoto, uploadWiringChatPhoto,
        testHelpAction, testHelpPendingMessageId, testHelpError,
        draft: workspace.text, setDraft, attachments: workspace.attachments, outbox: workspace.outbox, captureTicket, captureJob: workspace.captureJob,
        busy: busy || streamBusy || cameraTune.busy, chatSendBlocked: chatSendBlocked || cameraTune.busy,
        cameraTune, wiringAnalysis: assistantWiringAnalysis(conversation), error, connected, ready, secureContext, rtc: currentRtc,
        previewFresh: connected && receiveFresh && !!rtc.publishing && !!rtc.stream && lease.current.deadline > clock,
        canCapture: connected && receiveFresh && !!rtc.publishing && !!rtc.stream && !!session?.stream.can_capture && lease.current.deadline > clock && !busy && !streamBusy && !cameraTune.busy, inheritedMediaLabel,
        pair, disconnect, join, send, retry, removeOutbox, removeAttachment, addFiles, startStream, stopStream, beginCapture, finishCapture, cancelCapture, retryCapture, discardCapture, openCapture, selectWire, older, refresh,
        retryCaptureImage: () => { setCaptureAttempt(n => n + 1); image.retry(); } };
}
