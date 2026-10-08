import type { CaptureTicket, MobileBrowserApi } from './mobileBrowser';
import { initialStreamQuality, nextStreamQuality, rtcOperation, setBrowserStreamScale } from './mobileStreamPolicy';
/** Bound failed connections without tearing down a recoverable ICE interruption. */
export function watchBrowserRtcConnection(peer: RTCPeerConnection,
    onState: (state: RTCPeerConnectionState) => void,
    onEnded: (reason: 'failed' | 'closed' | 'disconnected' | 'connection_timeout') => void) {
    let active = true;
    let connectTimer: ReturnType<typeof setTimeout> | null = null;
    let disconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const dispose = () => {
        active = false;
        if (connectTimer !== null) clearTimeout(connectTimer);
        if (disconnectTimer !== null) clearTimeout(disconnectTimer);
        connectTimer = disconnectTimer = null;
        if (peer.onconnectionstatechange === changed) peer.onconnectionstatechange = null;
    };
    const finish = (reason: Parameters<typeof onEnded>[0]) => {
        if (!active) return;
        dispose();
        onEnded(reason);
    };
    const changed = () => {
        if (!active) return;
        const state = peer.connectionState;
        onState(state);
        if (!active) return;
        if (state === 'connected') {
            if (connectTimer !== null) clearTimeout(connectTimer);
            if (disconnectTimer !== null) clearTimeout(disconnectTimer);
            connectTimer = disconnectTimer = null;
        } else if (state === 'failed' || state === 'closed') finish(state);
        else if (state === 'disconnected' && disconnectTimer === null)
            disconnectTimer = setTimeout(() => finish('disconnected'), 8000);
    };
    peer.onconnectionstatechange = changed;
    connectTimer = setTimeout(() => finish('connection_timeout'), 15000);
    changed();
    return dispose;
}
/** Prefer the codec used by Safari and the laptop relay without rewriting SDP. */
export function preferBrowserH264(peer: Pick<RTCPeerConnection, 'getTransceivers'>,
    capabilities = typeof RTCRtpSender === 'undefined' || typeof RTCRtpSender.getCapabilities !== 'function'
        ? null : RTCRtpSender.getCapabilities('video')): boolean {
    const codecs = capabilities?.codecs ?? [];
    const h264 = codecs.filter(codec => codec.mimeType.toLowerCase() === 'video/h264');
    if (!h264.length || typeof peer.getTransceivers !== 'function') return false;
    const ordered = [...h264, ...codecs.filter(codec => codec.mimeType.toLowerCase() !== 'video/h264')];
    let applied = false;
    for (const transceiver of peer.getTransceivers()) {
        if (transceiver.sender.track?.kind !== 'video' && transceiver.receiver.track?.kind !== 'video') continue;
        if (typeof transceiver.setCodecPreferences !== 'function') continue;
        try { transceiver.setCodecPreferences(ordered); applied = true; }
        catch { /* Older browsers retain their supported default codec order. */ }
    }
    return applied;
}
export interface BrowserRtcStats {
    /** Local receipt time of a new counter-based measurement, not a cache replay. */
    measuredAtMs?: number;
    captureFps?: number;
    sendFps?: number;
    bitrateKbps?: number;
    width?: number;
    height?: number;
    rttMs?: number;
    qualityLimitationReason?: string;
    codec?: string;
    encodeFps?: number;
    encodeMs?: number;
    framesEncoded?: number;
    framesSent?: number;
    sampleIntervalMs?: number;
    nackCountDelta?: number;
    pliCountDelta?: number;
    retransmittedPacketsDelta?: number;
    retransmittedBytesDelta?: number;
    targetBitrateKbps?: number;
    appliedBitrateKbps?: number;
    parameterStatus?: 'accepted' | 'limited' | 'unsupported';
}
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export const browserBitrateKbps = (value?: number) => [3000, 8000, 12000].includes(value ?? 0) ? value! : 8000;
export interface PublisherStatsSample {
    id: string;
    timestamp: number;
    framesSent?: number;
    framesEncoded?: number;
    bytes?: number;
    encodeTime?: number;
    nackCount?: number;
    pliCount?: number;
    retransmittedPackets?: number;
    retransmittedBytes?: number;
}
const publisherDelta = (current: number | undefined, previous: number | undefined) =>
    finite(current) && finite(previous) && current >= previous ? current - previous : undefined;
/** Counter resets and unsupported counters are not zero-FPS measurements. */
export function readBrowserPublisherStats(report: RTCStatsReport, previous: PublisherStatsSample | null): { stats: BrowserRtcStats; sample: PublisherStatsSample | null } {
    const stats: BrowserRtcStats = {};
    let sample: PublisherStatsSample | null = null;
    let staleSample = false;
    report.forEach(entry => {
        if (entry.type === 'media-source' && entry.kind === 'video' && finite(entry.framesPerSecond)) stats.captureFps = entry.framesPerSecond;
        if (entry.type !== 'outbound-rtp' || entry.isRemote || (entry.kind !== 'video' && entry.mediaType !== 'video') || !finite(entry.timestamp)) return;
        if (finite(entry.frameWidth) && entry.frameWidth > 0) stats.width = entry.frameWidth;
        if (finite(entry.frameHeight) && entry.frameHeight > 0) stats.height = entry.frameHeight;
        if (typeof entry.qualityLimitationReason === 'string') stats.qualityLimitationReason = entry.qualityLimitationReason;
        const codec = report.get(entry.codecId);
        if (typeof codec?.mimeType === 'string') stats.codec = codec.mimeType;
        const transport = report.get(entry.transportId), pair = report.get(transport?.selectedCandidatePairId);
        if (pair?.state === 'succeeded' && finite(pair.currentRoundTripTime)) stats.rttMs = pair.currentRoundTripTime * 1000;
        const current: PublisherStatsSample = { id: `${entry.id}:${entry.ssrc ?? ''}`, timestamp: entry.timestamp,
            framesSent: finite(entry.framesSent) ? entry.framesSent : undefined,
            framesEncoded: finite(entry.framesEncoded) ? entry.framesEncoded : undefined,
            bytes: finite(entry.bytesSent) ? entry.bytesSent : undefined,
            encodeTime: finite(entry.totalEncodeTime) ? entry.totalEncodeTime : undefined,
            nackCount: finite(entry.nackCount) ? entry.nackCount : undefined,
            pliCount: finite(entry.pliCount) ? entry.pliCount : undefined,
            retransmittedPackets: finite(entry.retransmittedPacketsSent) ? entry.retransmittedPacketsSent : undefined,
            retransmittedBytes: finite(entry.retransmittedBytesSent) ? entry.retransmittedBytesSent : undefined };
        if (previous?.id === current.id && current.timestamp <= previous.timestamp) {
            // A cached report's arrival is not a new camera/transport measurement.
            // Keep its baseline so a reset clock can recover on the next advance.
            sample = current.timestamp === previous.timestamp ? previous : current;
            staleSample = true;
            return;
        }
        stats.framesSent = current.framesSent;
        stats.framesEncoded = current.framesEncoded;
        if (finite(entry.targetBitrate)) stats.targetBitrateKbps = entry.targetBitrate / 1000;
        if (previous?.id === current.id && current.timestamp > previous.timestamp) {
            stats.sampleIntervalMs = current.timestamp - previous.timestamp;
            const seconds = stats.sampleIntervalMs / 1000;
            const sent = publisherDelta(current.framesSent, previous.framesSent);
            const encoded = publisherDelta(current.framesEncoded, previous.framesEncoded);
            const bytes = publisherDelta(current.bytes, previous.bytes);
            const encodeTime = publisherDelta(current.encodeTime, previous.encodeTime);
            if (sent !== undefined) stats.sendFps = sent / seconds;
            if (encoded !== undefined) stats.encodeFps = encoded / seconds;
            if (bytes !== undefined) stats.bitrateKbps = bytes * 8 / seconds / 1000;
            if (encodeTime !== undefined && encoded !== undefined && encoded > 0) stats.encodeMs = encodeTime * 1000 / encoded;
            stats.nackCountDelta = publisherDelta(current.nackCount, previous.nackCount);
            stats.pliCountDelta = publisherDelta(current.pliCount, previous.pliCount);
            stats.retransmittedPacketsDelta = publisherDelta(current.retransmittedPackets, previous.retransmittedPackets);
            stats.retransmittedBytesDelta = publisherDelta(current.retransmittedBytes, previous.retransmittedBytes);
        }
        // outbound framesPerSecond describes encoding, not transmission. Never
        // substitute it for sent-frame counters or bridge an encoder reset.
        const encoderReset = previous?.id === current.id && current.framesEncoded !== undefined
            && previous.framesEncoded !== undefined && current.framesEncoded < previous.framesEncoded;
        if (stats.encodeFps === undefined && !encoderReset && finite(entry.framesPerSecond)) stats.encodeFps = entry.framesPerSecond;
        sample = current;
    });
    return { stats: staleSample ? {} : stats, sample };
}
/** Retry bitrate alone when Safari rejects optional degradation/FPS controls. */
export async function tuneBrowserVideoSender(sender: RTCRtpSender, bitrateKbps: number): Promise<Pick<BrowserRtcStats, 'appliedBitrateKbps' | 'parameterStatus'>> {
    const bitrate = browserBitrateKbps(bitrateKbps) * 1000;
    for (const full of [true, false]) {
        const parameters = sender.getParameters();
        if (!parameters.encodings?.length) return { parameterStatus: 'unsupported' };
        parameters.encodings[0].maxBitrate = bitrate;
        if (full) {
            parameters.encodings[0].maxFramerate = 30;
            parameters.encodings[0].scaleResolutionDownBy = 1;
            parameters.degradationPreference = 'maintain-resolution';
        }
        try {
            await rtcOperation(sender.setParameters(parameters));
            const applied = sender.getParameters().encodings?.[0]?.maxBitrate;
            return { parameterStatus: finite(applied) && applied !== bitrate ? 'limited' : 'accepted',
                ...(finite(applied) ? { appliedBitrateKbps: applied / 1000 } : {}) };
        } catch { /* Retry only the standard bitrate control with fresh parameters. */ }
    }
    return { parameterStatus: 'unsupported' };
}
export interface BrowserRtcState {
    stream: MediaStream | null;
    status: string;
    settings: MediaTrackSettings | null;
    stats: BrowserRtcStats;
    frame?: BrowserLandscapeFrame;
    publishing?: boolean;
    generation?: number;
    waitingForLandscape?: boolean;
    sourceChanged?: boolean;
    resolution?: BrowserStreamResolution;
}
export type BrowserStreamResolution = '1080p' | '720p';
export interface BrowserStreamOptions {
    resolution?: BrowserStreamResolution;
    bitrateKbps?: number;
}
export const idleBrowserRtc = (): BrowserRtcState => ({ stream: null, status: '串流已停止', settings: null, stats: {}, publishing: false });
export type BrowserPhoneOrientation = 'landscape' | 'portrait' | 'unknown';
/** Do not equate screen axes with camera/sensor axes. Both edges must meet
 * the selected short edge; decoded pixels are checked before publishing.
 * Direction is a preference, never a prerequisite for opening the camera. */
export function browserCameraConstraints(orientation: BrowserPhoneOrientation, resolution: BrowserStreamResolution = '1080p'): MediaTrackConstraints {
    const portrait = orientation === 'portrait';
    const [long, short] = resolution === '720p' ? [1280, 720] : [1920, 1080];
    // Bound HD capture as well as requesting it, so selecting 720p cannot
    // silently retain a higher-resolution sensor mode. Either axis may rotate.
    const limit = resolution === '720p' ? { max: long } : {};
    const constraints: MediaTrackConstraints & { resizeMode: { ideal: string } } = {
        width: { min: short, ideal: portrait ? short : long, ...limit },
        height: { min: short, ideal: portrait ? long : short, ...limit },
        aspectRatio: { ideal: portrait ? 9 / 16 : 16 / 9 },
        resizeMode: { ideal: resolution === '720p' ? 'crop-and-scale' : 'none' },
        frameRate: { ideal: 30, max: 30 },
    };
    return constraints;
}
export function isFullHdSize(width: number, height: number): boolean {
    return isBrowserStreamSize(width, height, '1080p');
}
export function isBrowserStreamSize(width: number, height: number, resolution: BrowserStreamResolution): boolean {
    const [long, short] = resolution === '720p' ? [1280, 720] : [1920, 1080];
    return Number.isFinite(width) && Number.isFinite(height)
        && Math.min(width, height) >= short && Math.max(width, height) >= long;
}
/** Serialize on the same native track. A late portrait completion cannot win
 * over a newer landscape intent. Even a timed-out browser call stays owned
 * until it settles, so a second applyConstraints never races with it. */
export function syncBrowserCameraOrientation(track: MediaStreamTrack, initial: BrowserPhoneOrientation,
    signal: AbortSignal, changed: (pending: boolean, failed: boolean) => void, resolution: BrowserStreamResolution = '1080p') {
    let desired = initial, applied = initial, running = false, disposed = signal.aborted;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const dispose = () => { disposed = true; clearTimeout(timer); signal.removeEventListener('abort', dispose); };
    signal.addEventListener('abort', dispose, { once: true });
    const run = async () => {
        if (running || disposed || desired === applied || desired === 'unknown') return;
        running = true;
        changed(true, false);
        let failed = false;
        while (!disposed && desired !== applied) {
            const target = desired;
            timer = setTimeout(() => { if (!disposed) changed(true, true); }, 3000);
            try {
                if (typeof track.applyConstraints !== 'function') throw Error('phone_orientation_unsupported');
                await track.applyConstraints({ ...track.getConstraints?.(), ...browserCameraConstraints(target, resolution) });
                failed = false;
            } catch { failed = true; }
            finally { clearTimeout(timer); }
            applied = target;
        }
        running = false;
        if (!disposed) changed(false, failed);
    };
    return {
        request(orientation: BrowserPhoneOrientation) { if (!disposed && orientation !== 'unknown') { desired = orientation; void run(); } },
        dispose,
    };
}
/** Screen orientation is separate from the dimensions of decoded camera pixels. */
export function readBrowserPhoneOrientation(): BrowserPhoneOrientation {
    if (typeof window === 'undefined') return 'unknown';
    const type = window.screen?.orientation?.type;
    if (type?.startsWith('landscape')) return 'landscape';
    if (type?.startsWith('portrait')) return 'portrait';
    const angle = (window as Window & { orientation?: number }).orientation;
    if (typeof angle === 'number') return Math.abs(angle) % 180 === 90 ? 'landscape' : 'portrait';
    return typeof window.matchMedia === 'function' ? (window.matchMedia('(orientation: landscape)').matches ? 'landscape' : 'portrait') : 'unknown';
}
function watchBrowserPhoneOrientation(changed: () => void) {
    if (typeof window === 'undefined') return () => undefined;
    const orientation = window.screen?.orientation;
    const modern = typeof orientation?.addEventListener === 'function';
    if (modern) orientation.addEventListener('change', changed);
    else window.addEventListener('orientationchange', changed);
    window.addEventListener('resize', changed);
    return () => {
        if (modern) orientation.removeEventListener('change', changed);
        else window.removeEventListener('orientationchange', changed);
        window.removeEventListener('resize', changed);
    };
}
export interface BrowserLandscapeFrame {
    sourceSize: [number, number];
    outputSize: [number, number];
    rotation: 0;
    ready?: boolean;
    phoneOrientation?: BrowserPhoneOrientation;
    issue?: 'orientation' | 'resolution' | 'constraints';
}
export interface BrowserLandscapeStream {
    stream: MediaStream;
    readFrame: () => BrowserLandscapeFrame;
    dispose: () => void;
}
/** Legacy layout utility. Native publication preserves actual camera dimensions. */
export function landscapeFrameLayout(width: number, height: number, outputWidth: number, outputHeight: number) {
    if (![width, height, outputWidth, outputHeight].every(value => Number.isFinite(value) && value > 0))
        throw Error('相機影格尺寸無效');
    const scale = Math.min(outputWidth / width, outputHeight / height);
    return { rotation: 0 as const, drawWidth: width * scale, drawHeight: height * scale };
}
interface BrowserLandscapeOptions {
    readOrientation?: () => BrowserPhoneOrientation;
    waiting?: (frame: BrowserLandscapeFrame) => void;
    invalidated?: (frame: BrowserLandscapeFrame) => void;
    changed?: (frame: BrowserLandscapeFrame) => void;
}
/** Verify native camera pixels without drawing, resampling or making another track.
 * The requested resolution is a camera constraint; metadata always reports what
 * the camera actually supplied. The publisher retains ownership of its tracks.
 */
export async function prepareBrowserLandscapeStream(input: MediaStream, resolution: BrowserStreamResolution, signal: AbortSignal, options: BrowserLandscapeOptions = {}): Promise<BrowserLandscapeStream> {
    const source = document.createElement('video');
    source.muted = true; source.autoplay = true; source.playsInline = true;
    source.setAttribute('aria-hidden', 'true');
    // Safari needs a playing source element. This is not a second camera acquisition.
    source.style.cssText = 'position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;left:0;top:0';
    source.srcObject = input;
    document.body.appendChild(source);
    let publishedSize: [number, number] | null = null, publishedDirection: string | null = null, direction = '', disposed = false;
    let frame: BrowserLandscapeFrame = { sourceSize: [0, 0], outputSize: [0, 0], rotation: 0, ready: false };
    let waitingReady: (() => void) | null = null, detachOrientation = () => {}, waitingKey = '';
    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    let constraintsPending = false, constraintsFailed = false;
    const inspectFraming = () => {
        const phoneOrientation = (options.readOrientation ?? readBrowserPhoneOrientation)();
        const type = typeof window === 'undefined' ? undefined : window.screen?.orientation?.type;
        const angle = typeof window === 'undefined' ? undefined : (window as Window & { orientation?: number }).orientation;
        direction = options.readOrientation ? phoneOrientation : type?.startsWith('landscape') || type?.startsWith('portrait')
            ? type : typeof angle === 'number' ? String(angle) : phoneOrientation;
        const width = source.videoWidth, height = source.videoHeight;
        const ready = source.readyState >= 2 && !source.paused && Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;
        // A landscape-coded native frame can be valid while the phone is held
        // upright. Screen orientation alone does not prove rotated pixels.
        const issue = !isBrowserStreamSize(width, height, resolution) ? 'resolution' : constraintsFailed ? 'constraints' : undefined;
        frame = { ...frame, sourceSize: [width, height], outputSize: [width, height],
            ready: ready && settleTimer === null && !constraintsPending && issue !== 'resolution', phoneOrientation };
        if (issue) frame.issue = issue; else delete frame.issue;
        if (!ready && !publishedSize) {
            const key = `${width}:${height}:${phoneOrientation}`;
            if (key !== waitingKey) { waitingKey = key; options.waiting?.(frame); }
        }
        return ready;
    };
    const orientationSync = syncBrowserCameraOrientation(input.getVideoTracks()[0],
        (options.readOrientation ?? readBrowserPhoneOrientation)(), signal, (pending, failed) => {
            if (disposed) return;
            constraintsPending = pending; constraintsFailed = failed;
            inspectFraming(); options.changed?.(frame);
        }, resolution);
    const sourceChanged = (event?: Event) => {
        if (disposed) return;
        // Keyboard/viewport layout changes are not native camera source changes.
        if (publishedSize && typeof window !== 'undefined' && event?.type === 'resize' && event.target === window
                && source.videoWidth === publishedSize[0] && source.videoHeight === publishedSize[1]) return;
        if (publishedSize) {
            const wasReady = frame.ready;
            const ready = inspectFraming();
            if (!ready || direction !== publishedDirection || frame.sourceSize[0] !== publishedSize[0] || frame.sourceSize[1] !== publishedSize[1]) {
                // Rotation is a geometry change, not loss of transport ownership.
                // Safari can report orientation before native video resize. Keep
                // the peer/track and withhold capture hints until framing settles.
                publishedSize = [...frame.sourceSize]; publishedDirection = direction;
                frame = { ...frame, ready: false };
                options.changed?.(frame);
                if (settleTimer !== null) clearTimeout(settleTimer);
                settleTimer = setTimeout(() => {
                    settleTimer = null;
                    if (disposed) return;
                    inspectFraming(); options.changed?.(frame);
                }, 600);
                // Set the settling guard first: unsupported controls can fail
                // synchronously and notify us before request() returns.
                orientationSync.request(frame.phoneOrientation ?? 'unknown');
            } else if (!wasReady && frame.ready) {
                options.changed?.(frame);
            }
        } else waitingReady?.();
    };
    const dispose = () => {
        if (disposed) return;
        disposed = true;
        if (settleTimer !== null) clearTimeout(settleTimer);
        signal.removeEventListener('abort', dispose);
        detachOrientation();
        orientationSync.dispose();
        for (const event of ['resize', 'playing', 'loadeddata', 'canplay', 'pause', 'emptied']) source.removeEventListener(event, sourceChanged);
        source.pause(); source.srcObject = null; source.remove();
    };
    signal.addEventListener('abort', dispose, { once: true });
    for (const event of ['resize', 'playing', 'loadeddata', 'canplay', 'pause', 'emptied']) source.addEventListener(event, sourceChanged);
    detachOrientation = watchBrowserPhoneOrientation(sourceChanged);
    try {
        await new Promise<void>((resolve, reject) => {
            let settled = false;
            const cleanup = () => {
                clearTimeout(timeout);
                waitingReady = null;
                signal.removeEventListener('abort', cancelled);
                for (const event of ['loadeddata', 'canplay', 'playing']) source.removeEventListener(event, ready);
            };
            const finish = (error?: unknown) => { if (settled) return; settled = true; cleanup(); error ? reject(error) : resolve(); };
            const cancelled = () => finish(new DOMException('相機串流已取消', 'AbortError'));
            const ready = () => {
                if (source.readyState < 2 || !source.videoWidth || !source.videoHeight) return;
                clearTimeout(timeout);
                if (inspectFraming()) finish();
            };
            const timeout = setTimeout(() => finish(Error('相機影像尚未就緒，請重新開啟串流')), 10000);
            signal.addEventListener('abort', cancelled, { once: true });
            for (const event of ['loadeddata', 'canplay', 'playing']) source.addEventListener(event, ready);
            waitingReady = ready;
            if (signal.aborted) { cancelled(); return; }
            void source.play().then(ready, finish);
            ready();
        });
        if (signal.aborted || disposed) throw new DOMException('相機串流已取消', 'AbortError');
        if (!inspectFraming()) throw Error('相機影像尚未就緒，請重新開啟串流');
        if (!input.getVideoTracks().length) throw Error('相機影片來源不存在');
        publishedSize = [...frame.sourceSize];
        publishedDirection = direction;
        return { stream: input, readFrame: () => ({ ...frame, sourceSize: [...frame.sourceSize], outputSize: [...frame.outputSize] }), dispose };
    } catch (cause) { dispose(); throw cause; }
}
interface PublisherDependencies {
    getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
    makePeer: () => RTCPeerConnection;
    normalizeStream?: typeof prepareBrowserLandscapeStream;
}
export async function browserCaptureHandoff(api: MobileBrowserApi, publisher: Pick<BrowserPublisher, 'stop'>): Promise<CaptureTicket> {
    const ticket = await api.request<CaptureTicket>('capture-ticket', { method: 'POST' });
    await publisher.stop();
    return ticket;
}
/** Owns one native camera. Cancellation also drains a pending permission prompt. */
export class BrowserPublisher {
    private serial = 0;
    private sourceChangeIntent = 0;
    private peer: RTCPeerConnection | null = null;
    private media: MediaStream | null = null;
    private nativeMedia: MediaStream | null = null;
    private landscape: BrowserLandscapeStream | null = null;
    private detachNativeEnd: (() => void) | null = null;
    private detachConnection: (() => void) | null = null;
    private opening: Promise<void> | null = null;
    private stopping: Promise<boolean> | null = null;
    // One publication owner per Start, not per paired phone or guide snapshot.
    // An idle/old tab must never stop the publication created by another tab.
    private remoteOwner: string | null = null;
    private cancelGather: (() => void) | null = null;
    private abort: AbortController | null = null;
    private timer: ReturnType<typeof setTimeout> | null = null;
    private state = idleBrowserRtc();
    private resolution: BrowserStreamResolution = '1080p';
    private bitrateCeiling = 8000;
    private bitrateFlight = false;
    private quality = initialStreamQuality();
    private scaleFlight = false;
    constructor(private api: MobileBrowserApi, private changed: (state: BrowserRtcState) => void, private deps: PublisherDependencies = { getUserMedia: c => navigator.mediaDevices.getUserMedia(c), makePeer: () => new RTCPeerConnection({ iceServers: [] }) }) { }
    async start(options: BrowserStreamOptions = {}) {
        const intent = ++this.sourceChangeIntent;
        if (this.stopping) {
            await this.stopping;
            if (intent !== this.sourceChangeIntent) return;
        }
        if (this.opening)
            return this.opening;
        if (this.media)
            return;
        const task = this.open(options);
        this.opening = task;
        try {
            await task;
        }
        finally {
            if (this.opening === task)
                this.opening = null;
        }
    }
    private emit(state: BrowserRtcState) { this.state = { ...state, resolution: this.resolution }; this.changed(this.state); }
    private async open(options: BrowserStreamOptions) {
        this.resolution = options.resolution === '720p' ? '720p' : '1080p';
        this.stopLocal();
        this.bitrateCeiling = browserBitrateKbps(options.bitrateKbps);
        const serial = this.serial, abort = new AbortController();
        this.abort = abort;
        this.emit({ ...idleBrowserRtc(), status: '連接後置相機…' });
        try {
            let stream: MediaStream;
            try {
                stream = await this.deps.getUserMedia({ audio: false, video: {
                    // Acquire the selected native mode independently of how the
                    // handset is held. Rotation preferences are applied later
                    // to this same track, without another camera acquisition.
                    facingMode: { ideal: 'environment' }, ...browserCameraConstraints('unknown', this.resolution),
                } });
            }
            catch (cause) {
                if (serial !== this.serial) return;
                if (cause instanceof Error && cause.name === 'OverconstrainedError')
                    throw Error(`相機無法提供 ${this.resolution}；請選擇其他解析度或確認相機支援後重試`);
                throw cause;
            }
            if (serial !== this.serial) {
                stream.getTracks().forEach(t => t.stop());
                return;
            }
            this.nativeMedia = stream;
            const nativeTrack = stream.getVideoTracks()[0];
            const ended = () => {
                if (serial !== this.serial) return;
                void this.stop();
                this.emit({ ...idleBrowserRtc(), status: '相機已中斷，請重新開啟串流' });
            };
            nativeTrack?.addEventListener?.('ended', ended);
            this.detachNativeEnd = () => nativeTrack?.removeEventListener?.('ended', ended);
            const nativeStream = stream;
            const landscape = await (this.deps.normalizeStream ?? prepareBrowserLandscapeStream)(stream, this.resolution, abort.signal, {
                waiting: frame => {
                    if (serial !== this.serial) return;
                    this.emit({ stream: nativeStream, settings: { ...nativeTrack?.getSettings(), width: frame.sourceSize[0], height: frame.sourceSize[1] },
                        status: '等待相機影像，尚未開始傳送',
                        stats: {}, frame, publishing: false, waitingForLandscape: false });
                },
                changed: frame => {
                    if (serial !== this.serial) return;
                    this.emit({ ...this.state, frame, settings: { ...nativeTrack?.getSettings(),
                        width: frame.sourceSize[0], height: frame.sourceSize[1] } });
                },
                invalidated: frame => {
                    if (serial !== this.serial) return;
                    const stopped = this.stopInternal();
                    const stoppedSerial = this.serial, intent = this.sourceChangeIntent;
                    void stopped.then(confirmed => {
                        if (stoppedSerial !== this.serial || intent !== this.sourceChangeIntent) return;
                        if (!confirmed) {
                            this.emit({ ...idleBrowserRtc(), status: '尚未確認舊串流已停止，請重新開啟串流', frame });
                            return;
                        }
                        // The hook may reconnect only after the old DELETE has completed.
                        this.emit({ ...idleBrowserRtc(), status: '相機方向或尺寸已改變，準備重新串流', frame, sourceChanged: true });
                    });
                },
            });
            if (serial !== this.serial) { landscape.dispose(); return; }
            this.landscape = landscape;
            const verifiedFrame = landscape.readFrame();
            if (!isBrowserStreamSize(...verifiedFrame.sourceSize, this.resolution))
                throw Error(`相機實際影像未達 ${this.resolution}，未開始低於所選解析度的串流；請確認相機支援並重試`);
            stream = landscape.stream;
            this.media = stream;
            this.remoteOwner = crypto.randomUUID();
            const started = await this.api.request<{ generation: number }>('stream', { method: 'POST', signal: abort.signal,
                body: { bitrate_kbps: browserBitrateKbps(options.bitrateKbps), publisher_id: this.remoteOwner } });
            if (serial !== this.serial) return;
            const peer = this.deps.makePeer();
            this.peer = peer;
            this.emit({ stream, status: '正在協商影像傳輸…', settings: stream.getVideoTracks()[0]?.getSettings() ?? null, stats: {}, frame: landscape.readFrame(), publishing: false });
            const videoSenders: RTCRtpSender[] = [];
            const tune = async (sender: RTCRtpSender) => {
                const result = await tuneBrowserVideoSender(sender, browserBitrateKbps(options.bitrateKbps));
                if (serial === this.serial) this.state = { ...this.state, stats: { ...this.state.stats, ...result } };
            };
            for (const track of stream.getTracks()) {
                const sender = peer.addTrack(track, stream);
                if (track.kind === 'video') {
                    videoSenders.push(sender);
                    await tune(sender);
                    if (serial !== this.serial)
                        return;
                }
            }
            preferBrowserH264(peer);
            const offer = await rtcOperation(peer.createOffer(), 5000);
            if (serial !== this.serial)
                return;
            await rtcOperation(peer.setLocalDescription(offer), 5000);
            if (serial !== this.serial)
                return;
            await new Promise<void>((resolve, reject) => {
                if (peer.iceGatheringState === 'complete') {
                    resolve();
                    return;
                }
                const finish = (error?: Error) => { clearTimeout(timer); peer.onicegatheringstatechange = null; this.cancelGather = null; error ? reject(error) : resolve(); };
                const timer = setTimeout(() => finish(Error('區域網路協商逾時，請確認手機與電腦網路')), 10000);
                this.cancelGather = () => finish();
                peer.onicegatheringstatechange = () => { if (peer.iceGatheringState === 'complete')
                    finish(); };
            });
            if (serial !== this.serial)
                return;
            const answer = await this.api.request<RTCSessionDescriptionInit>('stream/offer', { method: 'POST', signal: abort.signal, body: { sdp: peer.localDescription?.sdp, type: 'offer', role: 'publisher', generation: started.generation } });
            if (serial !== this.serial)
                return;
            await rtcOperation(peer.setRemoteDescription(answer), 5000);
            if (serial !== this.serial)
                return;
            for (const sender of videoSenders) {
                await tune(sender);
                if (serial !== this.serial) return;
            }
            this.emit({ ...this.state, status: '等待影像連線…', publishing: false, generation: started.generation });
            this.detachConnection = watchBrowserRtcConnection(peer, state => {
                if (serial !== this.serial) return;
                this.emit({ ...this.state, publishing: state === 'connected',
                    status: state === 'connected' ? '串流中' : state === 'disconnected' ? '網路暫時中斷，等待恢復…' : '等待影像連線…' });
            }, reason => {
                if (serial !== this.serial) return;
                void this.stopInternal();
                this.emit({ ...idleBrowserRtc(), status: reason === 'connection_timeout'
                    ? '影像連線逾時，請確認網路後重新開啟串流' : '串流中斷，請重新開啟串流' });
            });
            if (serial !== this.serial) return;
            this.sampleStats(serial, peer, started.generation, abort.signal);
        }
        catch (cause) {
            if (serial === this.serial) {
                this.stopLocal();
                this.emit({ ...idleBrowserRtc(), status: cause instanceof Error ? cause.message : String(cause) });
                await this.releaseRemote(this.remoteOwner);
                throw cause;
            }
        }
    }
    private sampleStats(serial: number, peer: RTCPeerConnection, generation: number, signal: AbortSignal) {
        let previous: PublisherStatsSample | null = null;
        let reportedAt = 0, reporting = false;
        const poll = async () => {
            try {
                const report = await rtcOperation(peer.getStats());
                if (serial !== this.serial)
                    return;
                const measured = readBrowserPublisherStats(report, previous);
                previous = measured.sample;
                const stats = { ...measured.stats, ...(measured.stats.sampleIntervalMs ? { measuredAtMs: Date.now() } : {}),
                    appliedBitrateKbps: this.state.stats.appliedBitrateKbps, parameterStatus: this.state.stats.parameterStatus };
                this.emit({ ...this.state, settings: this.media?.getVideoTracks()[0]?.getSettings() ?? null, stats, frame: this.landscape?.readFrame() });
                void this.adaptStream(serial, stats);
                if (!reporting && Date.now() - reportedAt >= 3000 && Object.keys(measured.stats).length) {
                    reportedAt = Date.now(); reporting = true;
                    void this.api.request('stream/metrics', { method: 'POST', signal, timeoutMs: 2500,
                        body: { generation, capture_fps: stats.captureFps, send_fps: stats.sendFps, send_bitrate_kbps: stats.bitrateKbps,
                            width: stats.width, height: stats.height, rtt_ms: stats.rttMs, quality_limitation_reason: stats.qualityLimitationReason,
                            encode_fps: stats.encodeFps ?? null, encode_ms: stats.encodeMs ?? null,
                            frames_encoded: stats.framesEncoded ?? null, frames_sent: stats.framesSent ?? null,
                            sample_interval_ms: stats.sampleIntervalMs ?? null,
                            nack_count_delta: stats.nackCountDelta ?? null, pli_count_delta: stats.pliCountDelta ?? null,
                            retransmitted_packets_delta: stats.retransmittedPacketsDelta ?? null,
                            retransmitted_bytes_delta: stats.retransmittedBytesDelta ?? null,
                            target_bitrate_kbps: stats.targetBitrateKbps ?? null } })
                        .catch(() => undefined).finally(() => { reporting = false; });
                }
            }
            catch {
                // Do not average across a failed poll or retain its old clock baseline.
                previous = null;
            }
            if (serial === this.serial)
                this.timer = setTimeout(() => void poll(), 1000);
        };
        void poll();
    }
    private liveSender(stream: MediaStream) {
        if (stream !== this.media || !this.state.publishing || this.peer?.connectionState !== 'connected') return null;
        const track = stream.getVideoTracks()[0];
        return track?.readyState === 'live' ? this.peer.getSenders?.().find(sender => sender.track === track) ?? null : null;
    }
    private async adaptStream(serial: number, stats: BrowserRtcStats) {
        const stream = this.media, sender = stream && this.liveSender(stream);
        if (!sender || this.scaleFlight || this.bitrateFlight || this.quality.disabled) return;
        const settings = stream!.getVideoTracks()[0].getSettings();
        const before = this.quality;
        const next = nextStreamQuality(before, stats, Date.now(), Math.min(settings.width ?? 0, settings.height ?? 0),
            Math.max(settings.width ?? 0, settings.height ?? 0));
        this.quality = next;
        if (next.scale === before.scale) return;
        this.scaleFlight = true;
        try {
            await setBrowserStreamScale(sender, next.scale);
        } catch {
            // Unsupported/ambiguous browser controls are not retried every second.
            if (serial === this.serial) this.quality = { ...before, disabled: true };
        } finally { if (serial === this.serial) this.scaleFlight = false; }
    }
    readLiveBitrate(stream: MediaStream): number | null {
        try {
            const value = this.liveSender(stream)?.getParameters().encodings?.[0]?.maxBitrate;
            return finite(value) && value > 0 ? value / 1000 : null;
        } catch { return null; }
    }
    /** Only change the existing sender, with readback and rollback; no new peer. */
    async adjustLiveBitrate(stream: MediaStream, bitrateKbps: number, signal?: AbortSignal): Promise<number> {
        const sender = this.liveSender(stream), serial = this.serial;
        if (!sender) throw Error('phone_tune_source_changed');
        if (this.bitrateFlight || this.scaleFlight || !finite(bitrateKbps) || bitrateKbps < 100 || bitrateKbps > this.bitrateCeiling) throw Error('phone_tune_unsupported');
        const before = this.readLiveBitrate(stream);
        if (before === null) throw Error('phone_tune_unsupported');
        const current = () => serial === this.serial && this.liveSender(stream) === sender;
        const cancel = () => { if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError'); if (!current()) throw Error('phone_tune_source_changed'); };
        cancel(); this.bitrateFlight = true;
        let attempted = false;
        try {
            const parameters = sender.getParameters(); parameters.encodings[0].maxBitrate = bitrateKbps * 1000;
            attempted = true; await sender.setParameters(parameters); cancel();
            if (this.readLiveBitrate(stream) !== bitrateKbps) throw Error('phone_tune_unsupported');
            this.emit({ ...this.state, stats: { ...this.state.stats, appliedBitrateKbps: bitrateKbps, parameterStatus: 'accepted' } });
            return bitrateKbps;
        } catch (cause) {
            if (attempted && current()) {
                try {
                    const parameters = sender.getParameters(); parameters.encodings[0].maxBitrate = before * 1000;
                    await sender.setParameters(parameters);
                    if (current() && this.readLiveBitrate(stream) !== before) throw Error('readback');
                } catch { throw Error('phone_tune_restore_failed'); }
            }
            throw cause;
        } finally { if (serial === this.serial) this.bitrateFlight = false; }
    }
    stopLocal() {
        this.sourceChangeIntent++;
        this.serial++;
        this.quality = initialStreamQuality();
        this.scaleFlight = this.bitrateFlight = false;
        this.abort?.abort();
        this.abort = null;
        this.cancelGather?.();
        if (this.timer)
            clearTimeout(this.timer);
        this.timer = null;
        this.detachNativeEnd?.();
        this.detachNativeEnd = null;
        this.detachConnection?.();
        this.detachConnection = null;
        if (this.peer) {
            this.peer.onconnectionstatechange = null;
            this.peer.close();
            this.peer = null;
        }
        this.landscape?.dispose();
        this.landscape = null;
        this.nativeMedia?.getTracks().forEach(t => t.stop());
        this.nativeMedia = null;
        this.media = null;
        this.emit(idleBrowserRtc());
    }
    async stop() {
        this.sourceChangeIntent++;
        await this.stopInternal();
    }
    private async releaseRemote(owner: string | null): Promise<boolean> {
        if (!owner) return true;
        try {
            await this.api.request('stream', { method: 'DELETE', body: { publisher_id: owner }, timeoutMs: 5000 });
        } catch (cause) {
            // A newer publisher is intentionally unaffected by our cleanup.
            if (cause && typeof cause === 'object' && 'detail' in cause && cause.detail === 'mobile_stream_publisher_changed') {
                if (this.remoteOwner === owner) this.remoteOwner = null;
            }
            // Do not authorize an automatic restart that would steal it back.
            return false;
        }
        if (this.remoteOwner === owner) this.remoteOwner = null;
        return true;
    }
    private async stopInternal() {
        if (this.stopping)
            return this.stopping;
        const owner = this.remoteOwner;
        this.stopLocal();
        const opening = this.opening;
        const task = (async () => {
            await opening?.catch(() => undefined);
            return this.releaseRemote(owner);
        })();
        this.stopping = task;
        try {
            return await task;
        }
        finally {
            if (this.stopping === task)
                this.stopping = null;
        }
    }
}
