import type { AssistantConversation } from './assistant';
import type { MobileCapture, MobileSession, MobileStream } from './mobile';
export type { AssistantConversation, MobileCapture };
export interface BrowserPairing {
    token: string;
    session_id: string;
    conversation_id: string;
    context_id: string;
    title: string;
    base_url: string;
}
export type BrowserStream = MobileStream & {
    video_size?: [
        number,
        number
    ];
    expires_at?: number;
    received_frames?: number;
    updated_at?: number;
};
export type BrowserSession = Omit<MobileSession, 'stream'> & {
    stream: BrowserStream;
};
export interface BrowserAsset {
    id: string;
    type: 'image' | 'video';
    mime: string;
    filename?: string;
    url: string;
    thumbnail_url?: string | null;
    width: number;
    height: number;
    duration: number | null;
    size: number;
}
export interface BrowserAttachment {
    id: string;
    upload_id: string;
    file: Blob;
    name: string;
    filename: string;
    type: 'image' | 'video';
    mime: string;
    size: number;
    width: number;
    height: number;
    duration?: number;
    asset?: BrowserAsset;
    previewUrl?: string;
    progress?: number;
    error?: string;
}
export interface BrowserMessagePayload {
    request_id: string;
    text: string;
    asset_ids: string[];
    inherit_media?: boolean;
    context_id: string;
    capture_id?: string;
    check_scope?: 'one' | 'all';
    wire_id?: string;
}
export interface BrowserOutbox {
    id: string;
    payload: BrowserMessagePayload;
    attachments: BrowserAttachment[];
    status: 'pending' | 'failed';
    error?: string;
}
export interface CaptureTicket {
    ticket_id: string;
    expires_at: number;
    context_id: string;
    generation: number;
    preview_seq?: number;
}
export interface BrowserCaptureJob {
    ticket: CaptureTicket;
    attachment: BrowserAttachment;
    request_id: string;
    capture_source?: 'camera_photo' | 'phone_frame';
    error?: string;
}
export interface BrowserDraft {
    text: string;
    attachments: BrowserAttachment[];
    outbox: BrowserOutbox[];
    captureJob: BrowserCaptureJob | null;
}
export const emptyBrowserDraft = (): BrowserDraft => ({ text: '', attachments: [], outbox: [], captureJob: null });
export const MAX_BROWSER_VIDEO_BYTES = 200 * 1024 * 1024;
/** getRandomValues is available on HTTP; randomUUID may require a secure context. */
export function browserUuid(source: Pick<Crypto, 'getRandomValues'> & Partial<Pick<Crypto, 'randomUUID'>> = globalThis.crypto): string {
    if (typeof source.randomUUID === 'function') return source.randomUUID();
    const bytes = source.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0'));
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}
const PAIRING_KEY = 'tinkro.browser.pairing.v1';
export class MobileBrowserError extends Error {
    constructor(public status: number, message: string, public detail = message) { super(message); }
}
export function expiredBrowserSession(cause: unknown): cause is MobileBrowserError {
    return cause instanceof MobileBrowserError && (
        cause.status === 401 && cause.detail === 'mobile_session_expired_or_invalid'
        || cause.status === 404 && cause.detail === 'mobile_session_not_found');
}
export function sameBrowserPairing(left: BrowserPairing | null, right: BrowserPairing): boolean {
    return !!left && left.session_id === right.session_id && left.token === right.token;
}
export function mobileBrowserPath(path: string, origin = window.location.origin): string {
    const url = new URL(path, origin);
    if (url.origin !== origin || !url.pathname.startsWith('/api/mobile/'))
        throw Error('媒體網址不屬於目前連線的 Tinkro 電腦');
    return url.href;
}
export function mobileBrowserDraftKey(origin: string, conversationId: string) { return `${new URL(origin).origin}|${conversationId}`; }
export function parseBrowserPairingCode(value: string, origin = window.location.origin): string {
    const input = value.trim();
    if (/^\d{6}$/.test(input))
        return input;
    let data: unknown;
    try {
        data = JSON.parse(input);
    }
    catch {
        throw Error('請輸入桌面顯示的六位配對碼');
    }
    const qr = data as {
        type?: string;
        base_url?: string;
        code?: string;
    };
    if (qr.type !== 'tinkro-mobile' || !qr.base_url || new URL(qr.base_url).origin !== origin || !qr.code || !/^\d{6}$/.test(qr.code))
        throw Error('請先開啟 QR 指向的 Tinkro 網頁，再輸入六位配對碼');
    return qr.code;
}
export function loadBrowserPairing(): BrowserPairing | null { try {
    const p = JSON.parse(localStorage.getItem(PAIRING_KEY) || 'null');
    return p?.token && p.session_id && p.conversation_id && p.context_id && new URL(p.base_url).origin === window.location.origin ? p : null;
}
catch {
    return null;
} }
export function saveBrowserPairing(pairing: BrowserPairing | null) { if (pairing)
    localStorage.setItem(PAIRING_KEY, JSON.stringify(pairing));
else
    localStorage.removeItem(PAIRING_KEY); }
export function browserMediaReference(conversation: AssistantConversation | null, round: number | undefined, newAttachments: number, explicitCapture?: string): {
    asset_ids: string[];
    capture_id?: string;
    inherit_media: false;
    label: string | null;
} {
    const media = conversation?.active_media;
    if (newAttachments || explicitCapture || !media?.attachments?.length || media.epoch !== conversation?.context_epoch || (round !== undefined && media.round !== round))
        return { asset_ids: [], inherit_media: false, label: null };
    const names = media.attachments.map((a, i) => (a.filename || `${a.type === 'video' ? '影片' : '照片'} ${i + 1}`) + (a.type === 'video' && typeof a.duration === 'number' ? `（${a.duration.toFixed(1)} 秒）` : ''));
    const kind = media.capture_id ? '最近定位照片' : media.attachments.some(a => a.type === 'video') ? '最近影片' : `最近照片（${media.attachments.length} 張）`;
    return { asset_ids: [...media.asset_ids], ...(media.capture_id ? { capture_id: media.capture_id } : {}), inherit_media: false, label: `此訊息引用：${kind} · ${names.join('、')}` };
}
export function validateBrowserAttachments(items: Pick<BrowserAttachment, 'type' | 'size' | 'duration'>[]): string | null {
    if (items.length > 4)
        return '每則訊息最多四張照片。';
    const videos = items.filter(a => a.type === 'video');
    if (videos.length && (videos.length !== 1 || items.length !== 1))
        return '一次可選四張照片或一支影片，不能混合。';
    for (const item of items) {
        if (item.size <= 0)
            return '檔案是空的，請重新選擇。';
        if (item.size > MAX_BROWSER_VIDEO_BYTES)
            return '每個附件不得超過 200 MiB。';
        if (item.type === 'video' && (!Number.isFinite(item.duration) || !item.duration || item.duration > 60))
            return '影片必須能讀取長度，且不得超過 60 秒。';
    }
    return null;
}
export function mergeBrowserConversation(previous: AssistantConversation | null, next: AssistantConversation): AssistantConversation {
    if (!previous || previous.id !== next.id)
        return next;
    const messages = [...new Map([...previous.messages, ...next.messages].map(m => [m.id, m])).values()].sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
    return { ...next, messages, before: previous.before === null ? null : next.before === null ? null : Math.min(previous.before, next.before) };
}
/** Versioned snapshots cannot resurrect an old preview or selection after reconnect/join. */
export function mergeBrowserSession(previous: BrowserSession | null, next: BrowserSession): BrowserSession {
    if (!previous || previous.session_id !== next.session_id)
        return next;
    if (next.view.revision < previous.view.revision)
        return { ...next, context_id: previous.context_id, conversation_id: previous.conversation_id, context: previous.context, title: previous.title, view: previous.view, stream: previous.stream };
    if (next.context_id === previous.context_id && (next.stream.generation < previous.stream.generation || (next.stream.generation === previous.stream.generation && (next.stream.preview_seq ?? 0) < (previous.stream.preview_seq ?? 0))))
        return { ...next, stream: previous.stream };
    return next;
}
export function browserLease(session: BrowserSession | null, now: number, previous: {
    key: string;
    deadline: number;
}) {
    const s = session?.stream, key = `${session?.session_id}:${session?.context_id}:${s?.generation}:${s?.preview_seq}`;
    if (!s?.active || !s.publisher_connected || session?.available_context && session.available_context.context_id !== session.context_id)
        return { key, deadline: 0 };
    const ttl = Math.max(0, Math.min(1500, s.valid_for_ms ?? 0));
    return { key, deadline: key === previous.key ? Math.min(previous.deadline, now + ttl) : now + ttl };
}
export class MobileBrowserApi {
    private pending = new Set<() => void>();
    private expired = false;
    constructor(public pairing: BrowserPairing | null, private onExpired?: (cause: MobileBrowserError) => void) { }
    cancelPending() { for (const abort of [...this.pending]) abort(); this.pending.clear(); }
    private failure(status: number, value: unknown, fallback?: string): MobileBrowserError {
        const raw = value && typeof value === 'object' && 'detail' in value ? value.detail : undefined;
        const detail = typeof raw === 'string' ? raw : JSON.stringify(raw ?? value);
        const cause = new MobileBrowserError(status, fallback ?? detail ?? `HTTP ${status}`, detail);
        if (this.pairing && !this.expired && expiredBrowserSession(cause)) {
            this.expired = true;
            this.onExpired?.(cause);
        }
        return cause;
    }
    async request<T>(path: string, options: {
        method?: string;
        body?: unknown;
        signal?: AbortSignal;
        timeoutMs?: number;
    } = {}): Promise<T> {
        const controller = new AbortController(), abort = () => controller.abort();
        this.pending.add(abort);
        options.signal?.addEventListener('abort', abort, { once: true });
        if (options.signal?.aborted)
            controller.abort();
        const timer = setTimeout(abort, options.timeoutMs ?? 30000);
        try {
            const response = await fetch(mobileBrowserPath(`/api/mobile/${path.replace(/^\//, '')}`), { method: options.method ?? 'GET', signal: controller.signal, credentials: 'same-origin', headers: { Accept: 'application/json', ...(this.pairing ? { Authorization: `Bearer ${this.pairing.token}` } : {}), ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
            const data = response.status === 204 ? undefined : await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
            if (!response.ok)
                throw this.failure(response.status, data);
            return data as T;
        }
        finally {
            clearTimeout(timer);
            options.signal?.removeEventListener('abort', abort);
            this.pending.delete(abort);
        }
    }
    async assetBlob(path: string, signal?: AbortSignal): Promise<Blob> {
        const controller = new AbortController(), abort = () => controller.abort();
        this.pending.add(abort); signal?.addEventListener('abort', abort, { once: true });
        if (signal?.aborted) abort();
        try {
            const response = await fetch(mobileBrowserPath(path), { signal: controller.signal, headers: { Authorization: `Bearer ${this.pairing?.token ?? ''}` }, cache: 'no-store' });
            if (!response.ok) throw this.failure(response.status, await response.json().catch(() => null), '照片載入失敗，請重試');
            return await response.blob();
        } finally { this.pending.delete(abort); signal?.removeEventListener('abort', abort); }
    }
    upload(item: BrowserAttachment, onProgress: (fraction: number) => void, signal?: AbortSignal): Promise<BrowserAsset> {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/mobile/assets');
            xhr.setRequestHeader('Authorization', `Bearer ${this.pairing?.token ?? ''}`);
            xhr.timeout = 180000;
            const abort = () => xhr.abort();
            this.pending.add(abort);
            signal?.addEventListener('abort', abort, { once: true });
            const finish = () => { signal?.removeEventListener('abort', abort); this.pending.delete(abort); };
            xhr.upload.onprogress = e => { if (e.lengthComputable)
                onProgress(e.loaded / e.total); };
            xhr.onerror = () => { finish(); reject(Error('上傳中斷，附件已保留，請重試。')); };
            xhr.ontimeout = () => { finish(); reject(Error('上傳逾時，請重試。')); };
            xhr.onabort = () => { finish(); reject(new DOMException('上傳已停止', 'AbortError')); };
            xhr.onload = () => { finish(); try {
                const data = JSON.parse(xhr.responseText);
                if (xhr.status >= 200 && xhr.status < 300) {
                    onProgress(1);
                    resolve(data);
                }
                else
                    reject(this.failure(xhr.status, data));
            }
            catch {
                reject(Error('無法讀取上傳結果'));
            } };
            const form = new FormData();
            form.append('upload_id', item.upload_id);
            form.append('file', item.file, item.name);
            if (signal?.aborted) {
                finish();
                reject(new DOMException('上傳已停止', 'AbortError'));
                return;
            }
            xhr.send(form);
        });
    }
}
/** Credentials may be cleared only after the server revokes this pairing. */
export async function closeBrowserSession(api: MobileBrowserApi, stop: () => Promise<void>): Promise<void> {
    await stop();
    try { await api.request<void>('session', { method: 'DELETE' }); }
    catch (cause) {
        if (!(cause instanceof MobileBrowserError && [401, 404].includes(cause.status))) throw cause;
    }
}
export async function pairMobileBrowser(code: string): Promise<BrowserPairing> { const result = await new MobileBrowserApi(null).request<BrowserPairing>('pair', { method: 'POST', body: { code: parseBrowserPairingCode(code), device_name: 'Safari 手機網頁' } }); return { token: result.token, session_id: result.session_id, conversation_id: result.conversation_id, context_id: result.context_id, title: result.title, base_url: window.location.origin }; }
async function draftDatabase(): Promise<IDBDatabase> { return new Promise((resolve, reject) => { const request = indexedDB.open('tinkro-mobile-browser', 1); request.onupgradeneeded = () => request.result.createObjectStore('workspaces'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error ?? Error('無法開啟草稿儲存空間')); }); }
export async function loadBrowserDraft(key: string): Promise<BrowserDraft> { const db = await draftDatabase(); try {
    return await new Promise((resolve, reject) => { const request = db.transaction('workspaces', 'readonly').objectStore('workspaces').get(key); request.onsuccess = () => resolve(request.result ?? emptyBrowserDraft()); request.onerror = () => reject(request.error); });
}
finally {
    db.close();
} }
export async function saveBrowserDraft(key: string, value: BrowserDraft): Promise<void> { const clean = (a: BrowserAttachment) => ({ ...a, previewUrl: undefined }); const record = { ...value, attachments: value.attachments.map(clean), outbox: value.outbox.map(o => ({ ...o, attachments: o.attachments.map(clean) })), captureJob: value.captureJob ? { ...value.captureJob, attachment: clean(value.captureJob.attachment) } : null }; const db = await draftDatabase(); try {
    await new Promise<void>((resolve, reject) => { const tx = db.transaction('workspaces', 'readwrite'); tx.objectStore('workspaces').put(record, key); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error ?? Error('草稿保存中斷')); });
}
finally {
    db.close();
} }
export async function browserAttachment(file: File): Promise<BrowserAttachment> {
    const type = file.type.startsWith('video/') || /\.(mov|mp4|m4v)$/i.test(file.name) ? 'video' : 'image';
    if (type === 'image' && !file.type.startsWith('image/') && !/\.(jpe?g|png|heic|heif|webp|avif|gif|bmp|tiff?)$/i.test(file.name))
        throw Error('請選擇照片或影片檔案');
    if (file.size <= 0 || file.size > MAX_BROWSER_VIDEO_BYTES)
        throw Error('附件必須大於零且不超過 200 MiB');
    const url = URL.createObjectURL(file);
    let dimensions: {
        width: number;
        height: number;
        duration?: number;
    };
    try {
        dimensions = await new Promise((resolve, reject) => {
            const element = type === 'video' ? document.createElement('video') : new Image();
            const cleanup = () => { clearTimeout(timer); element.onerror = null; if (element instanceof HTMLVideoElement) {
                element.onloadedmetadata = null;
                element.removeAttribute('src');
                element.load();
            }
            else
                element.onload = null; };
            const timer = setTimeout(() => { cleanup(); type === 'video' ? reject(Error('無法讀取影片長度')) : resolve({ width: 0, height: 0 }); }, 12000);
            if (element instanceof HTMLVideoElement) {
                element.preload = 'metadata';
                element.onloadedmetadata = () => { const result = { width: element.videoWidth, height: element.videoHeight, duration: element.duration }; cleanup(); resolve(result); };
            }
            else
                element.onload = () => { const result = { width: element.naturalWidth, height: element.naturalHeight }; cleanup(); resolve(result); };
            element.onerror = () => { cleanup(); type === 'video' ? reject(Error('Safari 無法讀取這支影片，請改選 MP4/MOV')) : resolve({ width: 0, height: 0 }); };
            element.src = url;
        });
    }
    finally {
        URL.revokeObjectURL(url);
    }
    const id = browserUuid();
    const item: BrowserAttachment = { id, upload_id: id, file, name: file.name, filename: file.name, type, mime: file.type || (type === 'video' ? 'video/mp4' : 'application/octet-stream'), size: file.size, ...dimensions };
    const invalid = validateBrowserAttachments([item]);
    if (invalid)
        throw Error(invalid);
    return item;
}
