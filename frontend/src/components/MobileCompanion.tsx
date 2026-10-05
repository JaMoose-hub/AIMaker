import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { toDataURL } from "qrcode";
import { useMakerText } from "../lib/useMaker";
import { useHeaderPanel } from "../lib/headerPanels";
import type { AssistantController, AssistantMessage } from "../lib/assistant";
import { acceptPhotoImageSize } from "../lib/photoWiring";
import { acceptMobileCapture, mobileError, mobileRequest, mobilePreviewLease, mobileModelRuntime, mobileVideoFresh, followMobileSource, openMobileViewer, useMobileCompanion, useDesktopStreamCapture,
  mobileAddressOrigin, mobileWebOrigin, mobilePairingAtOrigin,
  type MobileCapture, type MobileCheckScope, type MobileContext, type MobileSession, type MobileWebConfiguration } from "../lib/mobile";
import { PhotoViewport } from "./PhotoWiringPoc";
import { emptyViewerMetrics, mobileMeasurementFresh, observeVideoPresentation, readViewerSample, viewerMetricDelta, type ViewerSample } from "../lib/mobileViewerStats";
import { MobileRecognitionOverlay, type PhoneOverlayOptions } from "./MobileRecognitionOverlay";
import { ImageSourceSelect, type ImageSource } from './ImageViewControls';
import "../mobile.css";

export function MobileAttachmentCards({ message, onOpen }: { message: AssistantMessage; onOpen: (id: string) => void }) {
  const tr = useMakerText();
  return <>{message.attachments?.map(asset => {
    const captureId = asset.capture_id ?? message.capture_id;
    return <figure className="mobile-chat-attachment" key={asset.asset_id}>
      {asset.type === "video" ? <video src={asset.url ?? asset.image_url} controls preload="metadata" />
        : <a href={asset.image_url} target="_blank" rel="noreferrer"><img src={asset.thumbnail_url ?? asset.image_url} loading="lazy"
          alt={asset.filename ?? tr("手機拍攝照片", "Phone photograph")} /></a>}
      <figcaption>{asset.filename ?? tr("手機照片", "Phone photo")}{asset.width && asset.height ? ` · ${asset.width} × ${asset.height}` : ""}
        {captureId ? <button type="button" onClick={() => onOpen(captureId)}>{tr("查看 GPIO 照片", "View GPIO photo")}</button> : null}</figcaption>
    </figure>;
  })}</>;
}

export function MobileVideo({ session, compact = false, pinsById, guideTarget }: { session: MobileSession; compact?: boolean } & PhoneOverlayOptions) {
  const tr = useMakerText();
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<RTCPeerConnectionState>("new");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [clock, setClock] = useState(Date.now);
  const [reading, setReading] = useState(() => ({ owner: "", transport: emptyViewerMetrics(), transportAt: 0, displayAt: 0, displayFps: null as number | null, size: "" }));
  const active = Boolean(session.stream.active && session.stream.publisher_connected);
  const owner = `${session.session_id}:${session.stream.generation}:${active}:${attempt}`;
  const current = reading.owner === owner ? { ...reading,
    transport: mobileMeasurementFresh(reading.transportAt, clock) ? reading.transport : emptyViewerMetrics(),
    displayFps: mobileMeasurementFresh(reading.displayAt, clock) ? reading.displayFps : null }
    : { transport: emptyViewerMetrics(), displayFps: null, size: "" };
  const receiveFresh = mobileVideoFresh(session.stream, clock);
  const runtime = mobileModelRuntime(session.stream);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 500); return () => clearInterval(timer); }, []);
  useEffect(() => {
    setError(""); setReading({ owner, transport: emptyViewerMetrics(), transportAt: 0, displayAt: 0, displayFps: null, size: "" }); setState("new");
    const element = video.current;
    if (element) element.srcObject = null;
    if (!active) return;
    let disposed = false;
    let last: ViewerSample | null = null;
    let viewer: ReturnType<typeof openMobileViewer>;
    try {
      viewer = openMobileViewer(session.session_id, session.stream.generation, stream => {
        if (element && !disposed) { element.srcObject = stream; void element.play().catch(() => undefined); }
      }, value => { if (!disposed) setState(value); });
    } catch (cause) { setError(mobileError(cause)); return; }
    void viewer.ready.catch(cause => { if (!disposed) setError(mobileError(cause)); });
    const presentation = element ? observeVideoPresentation(element) : null;
    const actualSize = () => element?.srcObject && element.videoWidth > 0 && element.videoHeight > 0 ? `${element.videoWidth} × ${element.videoHeight}` : "";
    const resized = () => { if (!disposed) setReading(value => ({ ...value, owner, size: actualSize() })); };
    element?.addEventListener("resize", resized);
    element?.addEventListener("loadedmetadata", resized);
    // A stalled getStats promise must not retain either old display or transport FPS.
    const displayTimer = setInterval(() => { if (!disposed) setReading(value => ({ ...value, owner,
      displayFps: presentation?.sample() ?? null, displayAt: Date.now(), size: actualSize() })); }, 1000);
    let timer: ReturnType<typeof setTimeout> | null = null;
    let lastReadAt = 0;
    const poll = async () => {
      let transport = emptyViewerMetrics();
      try {
        const report = await viewer.peer.getStats();
        if (disposed) return;
        const next = readViewerSample(report);
        transport = viewerMetricDelta(mobileMeasurementFresh(lastReadAt) ? last : null, next);
        last = next;
        lastReadAt = Date.now();
      } catch { last = null; }
      if (disposed) return;
      setReading(value => ({ ...value, owner, transport, transportAt: Date.now(), size: actualSize() }));
      timer = setTimeout(() => void poll(), 1000);
    };
    void poll();
    return () => { disposed = true; clearInterval(displayTimer); if (timer !== null) clearTimeout(timer); presentation?.stop(); viewer.close();
      element?.removeEventListener("resize", resized); element?.removeEventListener("loadedmetadata", resized);
      if (element) element.srcObject = null; };
  }, [session.session_id, session.stream.generation, active, attempt]);
  const number = (value: number | null | undefined, places = 1) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(places) : "—";
  const mbps = (value: number | null | undefined) => typeof value === "number" ? number(value / 1000, 2) : "—";
  const fresh = (timestamp: number | undefined) => mobileMeasurementFresh(typeof timestamp === "number" ? timestamp * 1000 : null, clock, 8000);
  const publisher = session.stream.active && session.stream.publisher_stats?.generation === session.stream.generation && fresh(session.stream.publisher_stats.reported_at) ? session.stream.publisher_stats : null;
  const server = receiveFresh && session.stream.server_metrics && fresh(session.stream.server_metrics.updated_at) ? session.stream.server_metrics : null;
  const MetricsContainer = compact ? "details" : "div";
  const decodedSize = current.size.split(" × ").map(Number) as [number, number];
  return <><div className="mobile-live-view">
    <video ref={video} autoPlay muted playsInline aria-label={tr("手機即時串流", "Live phone stream")} />
    {active && receiveFresh && state === "connected" && decodedSize.length === 2 && decodedSize.every(n => n > 0)
      ? <MobileRecognitionOverlay key={owner} session={session} videoSize={decodedSize} pinsById={pinsById} guideTarget={guideTarget} /> : null}
    {session.stream.active && !receiveFresh ? <p className="mobile-video-placeholder" role="status">{tr("等待手機送來新影格；持續中斷時請在手機重新開啟串流。", "Waiting for new phone frames. Restart the stream on your phone if it remains interrupted.")}</p>
      : !active ? <p className="mobile-video-placeholder">{tr("在手機開啟串流，即可在這裡同步觀看。", "Start streaming on your phone to see it here.")}</p>
      : state !== "connected" && !error ? <p className="mobile-video-placeholder">{tr("正在連接手機串流…", "Connecting phone stream…")}</p> : null}
    <div className="mobile-video-metrics"><span>{current.size || tr("等待影像尺寸", "Waiting for video dimensions")}</span>
      <span>{tr("解碼", "Decoded")} {number(current.transport.decodeFps)} FPS</span>
      <span>{tr("顯示", "Displayed")} {number(current.displayFps)} FPS</span>
      <span>{tr("辨識", "Recognition")} {number(receiveFresh ? session.stream.recognition_fps : null)} FPS</span>
      {runtime.total ? <span>{runtime.available === 0 ? tr("YOLO 尚未就緒", "YOLO not ready") : runtime.cuda === runtime.total ? `YOLO CUDA ${runtime.cuda}/${runtime.total}` : `YOLO CUDA ${runtime.cuda}/${runtime.total} · ${tr("CPU／未就緒", "CPU / pending")}`}</span> : null}</div>
    {error || ["failed", "disconnected"].includes(state) ? <p className="mobile-error" role="status">{error || tr("串流已中斷", "Stream disconnected")}
      <button type="button" onClick={() => setAttempt(value => value + 1)}>{tr("重新連接畫面", "Reconnect preview")}</button></p> : null}
  </div><MetricsContainer className={compact ? "mobile-stream-details" : undefined}>
    {compact ? <summary>{tr("串流資訊", "Stream details")}</summary> : null}
    <div className="mobile-info" role="status">
    <div>{tr("手機上傳", "Phone upload")} {number(publisher?.send_fps)} FPS · {mbps(publisher?.send_bitrate_kbps)} Mbps → {tr("筆電收到", "Laptop receives")} {number(receiveFresh ? session.stream.video_fps : null)} FPS</div>
    <div>{current.transport.codec ? `${current.transport.codec} · ` : ""}{tr("畫面接收", "Viewer receives")} {number(current.transport.receiveMbps, 2)} Mbps · {tr("遺失", "Loss")} {number(current.transport.packetLossPercent)}% · {tr("接收緩衝", "Receive buffer")} {number(current.transport.jitterBufferMs)} ms</div>
    {server?.latency_scope === "server_processing_not_end_to_end" ? server.viewer_transports?.map((transport, index) => <div key={index}>
      {tr("伺服器轉送", "Server relay")}{server.viewer_transports!.length > 1 ? ` ${index + 1}` : ""} · {transport.codec ?? "—"} · {mbps(transport.send_bitrate_kbps)} / {mbps(transport.target_bitrate_kbps)} Mbps {tr("目標", "target")} · {tr("編碼", "Encode")} {number(transport.encode_ms)} ms{typeof transport.encode_fps === "number" ? ` / ${number(transport.encode_fps)} FPS` : ""} · {tr("複製", "Copy")} {number(transport.clone_ms)} ms
    </div>) : null}
    <small>{tr("緩衝與處理時間不是端到端延遲。", "Buffer and processing times are not end-to-end latency.")}</small>
  </div></MetricsContainer></>;
}

export interface MobileWorkspaceTargets extends PhoneOverlayOptions {
    trigger: HTMLElement | null; preview: HTMLElement | null;
    controls?: HTMLElement | null;
  /** When present, this portal selects a source instead of selecting a view. */
  source?: ImageSource;
  /** Selected camera ownership can remain active when the guide preview is hidden. */
  phoneSourceSelected?: boolean;
  selectedPhoneSource?: { session_id: string; generation: number } | null;
  showing: boolean; canShow: boolean; onShow: (show: boolean, session?: MobileSession | null, isCurrent?: () => boolean) => Promise<boolean>;
  /** A common desktop photo surface, independent of phone pairing. */
  onPhoto?: (capture: MobileCapture, show: boolean, context: MobileContext | null) => void;
}

export function MobileMainPreview({ session, readiness, captureActions, onReturn, pinsById, guideTarget }: {
  session: MobileSession | null; readiness: string; captureActions: ReactNode; onReturn: () => void;
} & PhoneOverlayOptions) {
  const tr = useMakerText();
  return <section className="mobile-main-preview" aria-label={tr("主畫面手機串流", "Main phone stream")}>
    <header><strong>{tr("手機即時影像", "Live phone camera")}</strong>
      <span className={`mobile-main-readiness ${readiness}`}>{session?.stream.active && session.stream.publisher_connected
        ? readiness === "locked" ? tr("畫面穩定", "Steady view") : tr("調整畫面", "Adjust framing") : tr("等待手機影像", "Waiting for phone video")}</span>
      <button type="button" onClick={onReturn}>{tr("返回 Webcam", "Back to webcam")}</button></header>
    {session ? <MobileVideo key={`${session.session_id}:${session.stream.generation}`} session={session} compact pinsById={pinsById} guideTarget={guideTarget} />
      : <div className="mobile-main-empty" role="status">{tr("手機連線已中斷，可重新連接或返回 Webcam。", "Phone disconnected. Reconnect or return to the webcam.")}</div>}
    <footer>{captureActions}<small>{tr("YOLO 即時辨識 · 腳位為引導標示，接線仍需確認。", "Live YOLO recognition · Pin markers are guidance; confirm wiring separately.")}</small></footer>
  </section>;
}

export function MobilePhotoReview({ capture, wireId, disabled, onWire, onAsk }: {
  capture: MobileCapture; wireId: string | null; disabled: boolean;
  onWire: (id: string) => void; onAsk: (scope?: MobileCheckScope, id?: string) => void;
}) {
  const tr = useMakerText();
  const [loaded, setLoaded] = useState(false);
  const [imageError, setImageError] = useState("");
  const [imageAttempt, setImageAttempt] = useState(0);
  const index = Math.max(0, capture.wires.findIndex(wire => wire.wire_id === wireId));
  const wire = capture.wires[index];
  const source = capture.capture_source === "desktop_stream" ? tr("筆電截取手機影像", "Desktop capture of phone stream")
    : capture.capture_source === "phone_frame" ? tr("手機本地串流照片", "Phone local camera frame") : tr("手機相機原圖", "Phone camera photo");
  return <section className="mobile-photo-review" aria-label={tr("手機 GPIO 照片", "Phone GPIO photograph")}>
    <div className="mobile-photo-heading"><strong>{tr("固定照片與 GPIO", "Frozen photo & GPIO")}</strong><small>{source} · {capture.video_size.join(" × ")}</small></div>
    <PhotoViewport capture={capture} wire={wire} imageAttempt={imageAttempt} imageLoaded={loaded} onLoad={(width, height) => {
      const valid = acceptPhotoImageSize(capture, width, height); setLoaded(valid);
      setImageError(valid ? "" : tr("照片尺寸與 GPIO 座標不一致", "Photo dimensions do not match the GPIO coordinates"));
    }} onError={() => { setLoaded(false); setImageError(tr("照片讀取失敗", "Could not load the photo")); }} />
    {imageError ? <p className="mobile-error" role="alert">{imageError}<button type="button" onClick={() => setImageAttempt(value => value + 1)}>{tr("重試照片", "Retry photo")}</button></p> : null}
    {wire ? <><label className="mobile-wire-selector">{tr("照片接線步驟", "Photo wiring step")}
      <select value={wire.wire_id} onChange={event => onWire(event.target.value)}>
        {capture.wires.map((item, i) => <option key={item.wire_id} value={item.wire_id}>{i + 1}. {item.component_id} · {item.component_pin} → {item.board_pin}</option>)}
      </select></label>
      <nav className="mobile-wire-nav" aria-label={tr("照片接線導覽", "Photo wire navigation")}>
        <button type="button" disabled={index === 0} onClick={() => onWire(capture.wires[index - 1].wire_id)}>{tr("上一條", "Previous")}</button>
        <span>{index + 1} / {capture.wires.length}</span>
        <button type="button" disabled={index === capture.wires.length - 1} onClick={() => onWire(capture.wires[index + 1].wire_id)}>{tr("下一條", "Next")}</button>
      </nav></> : null}
    <div className="mobile-photo-actions"><button type="button" disabled={disabled || !loaded} onClick={() => onAsk()}>{tr("詢問這張照片", "Ask about photo")}</button>
      <button type="button" disabled={disabled || !loaded || !wire} onClick={() => onAsk("one", wire?.wire_id)}>{tr("核對這條線", "Check this wire")}</button>
      <button type="button" disabled={disabled || !loaded || !capture.wires.length} onClick={() => onAsk("all")}>{tr("核對全部", "Check all wires")}</button></div>
  </section>;
}

export function MobileStreamCaptureActions({ live, active, busy, error, onCapture, onRetry }: {
  live: boolean; active: boolean; busy: boolean; error: string; onCapture: () => void; onRetry: () => void;
}) {
  const tr = useMakerText();
  return <div className="mobile-stream-capture">
    {live ? <button type="button" disabled={!active || busy} onClick={onCapture}>
      {tr("截取手機影像", "Capture phone frame")}</button> : null}
    {busy ? <p className="mobile-info" role="status">{tr("正在截取手機影像並定位 GPIO…", "Saving the phone frame and locating GPIO…")}</p> : null}
    {error ? <div className="mobile-error" role="alert"><p>{error === "mobile_capture_timeout"
      ? tr("等候已超過 180 秒，可重試讀取同張影像。", "The wait exceeded 180 seconds. Retry to retrieve the same capture.")
      : <>{tr("影像尚未完成讀取", "Capture could not be completed")} · {error}</>}</p>
      <button type="button" disabled={busy} onClick={onRetry}>{tr("重試讀取同張影像", "Retry the same capture")}</button>
      <small>{tr("若仍失敗，可按「截取手機影像」重新取一張。", "If it still fails, use Capture phone frame to take a new image.")}</small></div> : null}
  </div>;
}

export function MobileCompanion({ controller, aiReady, selection, workspace }: { controller: AssistantController; aiReady: boolean;
  selection: { id: string; nonce: number } | null; workspace?: MobileWorkspaceTargets }) {
  const tr = useMakerText();
  const mobile = useMobileCompanion(controller.mobileContext, Boolean(controller.project) && !controller.demoOpen);
  const [open, setOpen] = useHeaderPanel("phone");
  const container = useRef<HTMLDivElement>(null);
  const [panelHost, setPanelHost] = useState<Element | null>(null);
  useEffect(() => { setPanelHost(container.current?.closest(".app") ?? null); }, []);
  const [qrRecord, setQr] = useState<{ payload: string; image: string; error?: string } | null>(null);
  const [webConfiguration, setWebConfiguration] = useState<MobileWebConfiguration | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const connectionRead = useRef(0);
  const autoPairAttempt = useRef<string | null>(null);
  const currentMobile = useRef(mobile); currentMobile.current = mobile;
  const [actionError, setActionError] = useState("");
  const [sending, setSending] = useState(false);
  const [capture, setCapture] = useState<MobileCapture | null>(null);
  const captureRef = useRef(capture); captureRef.current = capture;
  const [captureId, setCaptureId] = useState<string | null>(null);
  const [localWire, setLocalWire] = useState<{ captureId: string; wireId: string } | null>(null);
  const [photoLoading, setPhotoLoading] = useState(false);
  const [view, setView] = useState<"connection" | "live" | "photo">("connection");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [pairingExpired, setPairingExpired] = useState(false);
  const [connectionChecked, setConnectionChecked] = useState(false);
  const flight = useRef(false);
  const previewLease = useRef({ key: "", deadline: 0 });
  const [previewClock, setPreviewClock] = useState(0);
  const session = mobile.session;
  const connection = mobile.connection === undefined ? session : mobile.connection;
  const connectionError = mobile.connectionError || mobile.error;
  const phoneConnected = Boolean(connection && !connectionError);
  const needsProjectSync = phoneConnected && connection?.conversation_id !== controller.mobileContext?.conversation_id;
  const shownStream = useRef<string | null>(null);
  const sourceFollow = useRef<{ key: string; attempts: number; failedAt: number | null } | null>(null);
  const sourceFlight = useRef<object | null>(null);
  const followCurrent = useRef({ selected: false, key: null as string | null, epoch: 0 });
  const followingPhone = Boolean((workspace?.phoneSourceSelected ?? workspace?.showing)
    && (workspace?.source === undefined || workspace.source === 'phone'));
  const followSelected = Boolean(followingPhone && session?.stream.active);
  const followKey = followMobileSource(null, session, true, false).key;
  if (followCurrent.current.selected !== followSelected || followCurrent.current.key !== followKey)
    followCurrent.current = { selected: followSelected, key: followKey, epoch: followCurrent.current.epoch + 1 };
  useEffect(() => () => { followCurrent.current = { selected: false, key: null, epoch: followCurrent.current.epoch + 1 }; }, []);
  useEffect(() => {
    let baseline = shownStream.current;
    if (baseline === null && followingPhone && workspace?.selectedPhoneSource && session) {
      // Returning to a live workspace may reveal an old source while the phone
      // has already reconnected. Its actual generation is the initial baseline.
      baseline = followMobileSource(null, { ...session, session_id: workspace.selectedPhoneSource.session_id,
        stream: { ...session.stream, generation: workspace.selectedPhoneSource.generation } }, true, false).key;
    }
    const next = followMobileSource(baseline, session, followingPhone, Boolean(workspace?.canShow));
    // The desktop source owns one generation and one pixel size. Re-select only
    // the phone view the user is already watching after its camera reconnects.
    if (!followingPhone) { shownStream.current = null; sourceFollow.current = null; return; }
    if (!next.reselect) { shownStream.current = next.key; return; }
    if (!session || !workspace || !next.key || sourceFlight.current) return;
    if (sourceFollow.current?.key !== next.key) sourceFollow.current = { key: next.key, attempts: 0, failedAt: null };
    const attempt = sourceFollow.current;
    if (attempt.attempts >= 2 || (attempt.failedAt !== null && Date.now() - attempt.failedAt < 5000)) return;
    const flight = {}; sourceFlight.current = flight; attempt.attempts++;
    const epoch = followCurrent.current.epoch;
    const current = () => followCurrent.current.selected && followCurrent.current.key === attempt.key && followCurrent.current.epoch === epoch;
    void (async () => {
      try {
        const selected = await workspace.onShow(true, session, current);
        if (!current() || sourceFollow.current !== attempt) return;
        if (selected) shownStream.current = attempt.key;
        else attempt.failedAt = Date.now();
      } catch {
        if (current() && sourceFollow.current === attempt) attempt.failedAt = Date.now();
      } finally { if (sourceFlight.current === flight) sourceFlight.current = null; }
    })();
  }, [session?.session_id, session?.context_id, session?.stream.generation, session?.stream.video_receive_fresh, session?.stream.video_received_at,
    followingPhone, workspace?.canShow, workspace?.onShow, workspace?.selectedPhoneSource?.session_id, workspace?.selectedPhoneSource?.generation]);
  // Only a fresh invitation is paired with a six-digit code. A consumed code is
  // never reused; the plain entry remains the fallback for connected phones.
  const configuration = mobile.webConfiguration === undefined ? webConfiguration : mobile.webConfiguration;
  const automaticOrigin = mobileWebOrigin(open && view === "connection" && !connectionChecked ? null : configuration);
  const chosenOrigin = baseUrl.trim() ? mobileAddressOrigin(baseUrl.trim()) : automaticOrigin;
  const phoneEntryUrl = automaticOrigin ? `${automaticOrigin}/mobile` : null;
  const invitation = mobile.pairing && !pairingExpired && mobilePairingAtOrigin(mobile.pairing, chosenOrigin) ? mobile.pairing : null;
  const qrPayload = invitation
    ? invitation.web_url || (typeof invitation.qr_payload === "string" ? invitation.qr_payload : JSON.stringify(invitation.qr_payload))
    : session ? phoneEntryUrl ?? "" : "";
  const qr = qrRecord?.payload === qrPayload ? qrRecord.image : "";
  const qrFailureMessage = tr("QR Code 產生失敗，請按「更新 QR Code」重試。", "Could not generate the QR code. Press Refresh QR code to retry.");
  const pairedId = session?.session_id;
  const photoId = session?.view.capture_id;
  const observedPhoto = useRef<{ sessionId: string; captureId: string | null } | null>(null);
  const wantedPhoto = useRef<string | null>(null);
  const photoWorkspace = useRef(workspace); photoWorkspace.current = workspace;
  const conversationId = controller.mobileContext?.conversation_id;
  useEffect(() => {
    if (!open || view !== "connection") { autoPairAttempt.current = null; return; }
    let disposed = false;
    const read = async () => {
      if (currentMobile.current.pairingBusy) return;
      const serial = ++connectionRead.current;
      try {
        const next = currentMobile.current.refreshWebConfiguration
          ? await currentMobile.current.refreshWebConfiguration()
          : await mobileRequest<MobileWebConfiguration>("web-config", { cache: "no-store" });
        if (!disposed && serial === connectionRead.current) { setWebConfiguration(next); setConnectionChecked(true); }
      } catch { if (!disposed && serial === connectionRead.current) { setWebConfiguration(null); setConnectionChecked(true); } }
    };
    const foreground = () => { if (!currentMobile.current.pairingBusy && (typeof document === "undefined" || document.visibilityState !== "hidden")) void read(); };
    void read(); const timer = setInterval(foreground, 5000);
    if (typeof window !== "undefined") window.addEventListener?.("online", foreground);
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", foreground);
    return () => { disposed = true; connectionRead.current++; clearInterval(timer);
      if (typeof window !== "undefined") window.removeEventListener?.("online", foreground);
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", foreground); };
  }, [open, view, conversationId, mobile.pairingBusy]);
  useEffect(() => {
    if (!open || view !== "connection" || baseUrl.trim()) return;
    if (!automaticOrigin) { autoPairAttempt.current = null; return; }
    if (invitation || mobile.pairingBusy) return;
    const key = `${conversationId}:${automaticOrigin}`;
    if (autoPairAttempt.current === key) return;
    autoPairAttempt.current = key;
    void currentMobile.current.pair();
  }, [open, view, conversationId, automaticOrigin, invitation, mobile.pairingBusy, baseUrl]);
  const streamCapture = useDesktopStreamCapture(session, next => {
    setCapture(next); setCaptureId(next.capture_id); setPhotoLoading(false); setActionError(""); setView("photo");
    if (photoWorkspace.current?.controls && photoWorkspace.current.onPhoto) {
      photoWorkspace.current.onPhoto(next, true, next.context_id === session?.context_id ? session.context : null); setOpen(false);
    } else setOpen(true);
  });

  useEffect(() => {
    const now = performance.now();
    previewLease.current = mobilePreviewLease(session, now, previewLease.current);
    setPreviewClock(now);
  }, [session]);
  useEffect(() => {
    if ((!open && !workspace?.showing) || !session) return;
    const timer = setInterval(() => setPreviewClock(performance.now()), 200);
    return () => clearInterval(timer);
  }, [open, pairedId, workspace?.showing]);

  useEffect(() => { setOpen(false); setCapture(null); setCaptureId(null); setActionError(""); }, [conversationId]);
  useEffect(() => { if (selection) {
    setCaptureId(selection.id); setView("photo");
    if (photoWorkspace.current?.controls && photoWorkspace.current.onPhoto) {
      wantedPhoto.current = selection.id; setOpen(false);
      if (captureRef.current?.capture_id === selection.id) {
        photoWorkspace.current.onPhoto(captureRef.current, true, captureRef.current.context_id === session?.context_id ? session.context : null);
        wantedPhoto.current = null;
      }
    } else setOpen(true);
  } }, [selection]);
  useEffect(() => {
    const previous = observedPhoto.current;
    observedPhoto.current = pairedId ? { sessionId: pairedId, captureId: photoId ?? null } : null;
    if (!photoId) return;
    // Restoring a session keeps its photo available without selecting or opening it.
    setCaptureId(photoId);
    if (previous && previous.sessionId === pairedId && previous.captureId !== photoId) {
      setView("photo");
      if (photoWorkspace.current?.controls && photoWorkspace.current.onPhoto) { wantedPhoto.current = photoId; setOpen(false); }
      else setOpen(true);
    }
  }, [photoId, pairedId]);
  useEffect(() => {
    if (!qrPayload) return;
    let disposed = false;
    void toDataURL(qrPayload, { width: 220, margin: 2, errorCorrectionLevel: "M" })
      .then(image => { if (!disposed) setQr({ payload: qrPayload, image }); }).catch(() => {
        if (!disposed) setQr({ payload: qrPayload, image: "", error: qrFailureMessage });
      });
    return () => { disposed = true; };
  }, [qrPayload, qrFailureMessage]);
  useEffect(() => {
    setPairingExpired(false);
    if (!mobile.pairing) return;
    const raw = mobile.pairing.expires_at;
    const expiry = typeof raw === "number" ? raw * (raw < 1e12 ? 1000 : 1) : Date.parse(raw);
    const expire = () => setPairingExpired(Number.isFinite(expiry) && Date.now() >= expiry);
    expire(); const timer = setInterval(expire, 1000);
    return () => clearInterval(timer);
  }, [mobile.pairing]);
  useEffect(() => {
    setActionError("");
    if (!captureId) { setCapture(null); setPhotoLoading(false); return; }
    // The capture POST already returned the canonical image and geometry.
    if (captureRef.current?.capture_id === captureId) { setPhotoLoading(false); return; }
    setCapture(null);
    const abort = new AbortController(); setPhotoLoading(true);
    void mobileRequest<MobileCapture>(`captures/${encodeURIComponent(captureId)}`, { signal: abort.signal }).then(next => {
      if (abort.signal.aborted) return;
      if (next.capture_id !== captureId || !acceptMobileCapture(next)) throw new Error(tr("照片與 GPIO 資料不一致", "Photo and GPIO data do not match"));
      setCapture(next);
      const show = wantedPhoto.current === captureId;
      wantedPhoto.current = null;
      photoWorkspace.current?.onPhoto?.(next, show, next.context_id === session?.context_id ? session.context : null);
    }).catch(cause => { if (!abort.signal.aborted) setActionError(mobileError(cause)); })
      .finally(() => { if (!abort.signal.aborted) setPhotoLoading(false); });
    return () => abort.abort();
  }, [captureId, loadAttempt]);

  const currentCapture = capture?.capture_id === captureId ? capture : null;
  const outdated = Boolean(currentCapture && session && currentCapture.context_id !== session.context_id);
  async function showConnection() {
    const closing = open && view === "connection";
    setView("connection"); setConnectionChecked(false); setOpen(!closing);
    if (!closing) {
      setWebConfiguration(null); autoPairAttempt.current = null;
      // Automatic pairing has one owner: the effect after the fresh panel read.
      if (baseUrl.trim() && (!mobile.pairing || pairingExpired)) await mobile.pair(baseUrl.trim());
    }
  }
  async function ask(scope?: MobileCheckScope, wireId?: string) {
    if (!currentCapture || !session || flight.current || controller.busy || !aiReady) return;
    flight.current = true; setSending(true); setActionError("");
    const text = scope === "all" ? tr("請核對這張照片中的全部接線。", "Please check all wires in this photograph.")
      : scope === "one" ? tr("請核對這張照片目前選取的接線。", "Please check the selected wire in this photograph.")
        : tr("請根據這張照片與目前作品，說明你看見的情況及下一步。", "Using this photograph and the current project, explain what you see and the next step.");
    try { controller.acceptExternal(await mobile.sendPhoto(currentCapture, text, scope, wireId)); }
    catch (cause) { setActionError(mobileError(cause)); }
    finally { flight.current = false; setSending(false); }
  }
  function selectWire(id: string) {
    if (!currentCapture) return;
    setLocalWire({ captureId: currentCapture.capture_id, wireId: id });
    void mobile.selectView(currentCapture.capture_id, id).catch(cause => setActionError(mobileError(cause)));
  }
  const currentLeaseKey = `${session?.session_id ?? ""}:${session?.stream.generation ?? 0}:${session?.stream.preview_seq ?? 0}`;
  const previewFresh = previewLease.current.key === currentLeaseKey && previewClock < previewLease.current.deadline;
  const readiness = previewFresh && session?.stream.active && session.stream.publisher_connected
    && (session.stream.state !== "locked" || session.stream.can_capture) ? session.stream.state : "finding";
  const mainControls = Boolean(workspace?.controls);
  const connectionLabel = connectionError ? tr("手機連線狀態待確認", "Phone connection status unavailable")
    : phoneConnected ? needsProjectSync ? tr("手機已連接，尚未同步目前作品", "Phone connected, current project not synced") : tr("手機已連接", "Phone connected") : tr("連接手機", "Connect phone");
  const trigger = <button type="button" className="mobile-connect-button" data-connected={phoneConnected}
    aria-label={connectionLabel} title={connectionLabel} aria-expanded={open && view === "connection"} aria-controls="mobile-companion-panel" disabled={!controller.project || controller.demoOpen}
    onClick={() => void showConnection()}>{workspace?.trigger ? <><svg className="mobile-device-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
      <rect x="5.5" y="2" width="9" height="16" rx="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 4h4M9 15.5h2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg><span className="mobile-connection-dot" aria-hidden="true" />
      <span className="mobile-connection-label">{connectionError ? tr("待確認", "Unknown") : phoneConnected ? tr("已連接", "Connected") : tr("連接", "Connect")}</span></> : connectionLabel}</button>;
  const viewControls = <div className="mobile-view-tabs" role="group" aria-label={tr("手機影像檢視", "Phone image views")}>
    <button type="button" aria-pressed={mainControls ? workspace?.showing : open && view === "live"}
      disabled={!session || Boolean(mainControls && !workspace?.canShow)} onClick={() => {
        setView("live");
        if (mainControls && workspace?.canShow) { workspace.onShow(true, session); setOpen(false); }
        else setOpen(true);
      }}>{tr("手機串流", "Phone stream")}</button>
    {!workspace?.onPhoto || !mainControls ? <button type="button" aria-pressed={open && view === "photo"} disabled={!session || !captureId}
      onClick={() => { setView("photo"); setOpen(true); }}>{tr("GPIO 照片", "GPIO photo")}</button>
      : null}
  </div>;
  const connectionView = view === "connection";
  const connectionUrl = invitation?.web_url || (session ? phoneEntryUrl : null);
  const panelError = (connectionView ? connectionError || mobile.webConfigurationError : mobile.error) || (connectionView ? qrRecord?.payload === qrPayload ? qrRecord.error ?? "" : "" : actionError);
  const panel = open ? <section id="mobile-companion-panel" className={`mobile-companion-panel${connectionView ? " is-connection" : ""}`} aria-label={connectionView ? tr("手機連線", "Phone connection") : tr("手機連線與串流", "Phone connection and streaming")}>
      <header><div><strong>{connectionView ? tr("手機連線", "Phone connection") : tr("手機協作", "Phone companion")}</strong><small>{session?.title ?? controller.mobileContext?.title ?? "Tinkro"}</small></div>
        <button type="button" onClick={() => setOpen(false)} aria-label={tr("收起手機面板", "Close phone panel")}>×</button></header>
      {connectionView ? <div className="mobile-pairing mobile-connection-pairing">
        <div className="mobile-pairing-status" role="status" data-connected={phoneConnected}><span aria-hidden="true" />
          {connectionError ? tr("連線狀態待確認", "Connection status unavailable") : phoneConnected ? tr("手機已連接", "Phone connected") : session ? tr("手機已配對，目前離線", "Phone paired, currently offline") : mobile.pairingBusy ? tr("準備 QR Code…", "Preparing QR code…") : pairingExpired ? tr("QR Code 已過期，請更新", "QR code expired; refresh to connect") : tr("等待手機掃碼", "Waiting for phone scan")}</div>
        {needsProjectSync ? <p className="mobile-project-sync" role="status">{tr("尚未同步目前作品。請在手機切換到最新工作區，再重新開啟串流。", "Current project not synced. Switch to the latest workspace on your phone, then restart streaming.")}</p> : null}
        {qr && (session || !pairingExpired) ? <img className="mobile-pairing-qr" src={qr} alt={invitation ? tr("手機配對 QR code", "Phone pairing QR code") : tr("手機頁面 QR Code", "Phone page QR code")} /> : null}
        <div className="mobile-pairing-code-card" aria-label={tr("手機配對碼", "Phone pairing code")}>
          <span>{tr("配對碼", "Pairing code")}</span>
          {invitation ? <strong className="mobile-pairing-code">{invitation.code}</strong>
            : pairingExpired ? <strong className="mobile-pairing-code">{tr("配對碼已過期", "Pairing code expired")}</strong>
            : <small role="status">{mobile.pairingBusy ? tr("正在產生…", "Preparing…") : tr("請更新配對碼", "Refresh to get a code")}</small>}
          {invitation ? <small>{tr("5 分鐘內有效・限用一次", "Valid for 5 minutes · one use")}</small> : null}
        </div>
        <p>{phoneConnected ? invitation ? tr("掃碼或輸入配對碼；目前手機保持連線。", "Scan or enter the code. Your current phone stays connected.")
          : tr("掃碼返回手機頁面；串流與照片請在工作區操作。", "Scan to reopen the phone page. Streaming and photos stay in the workspace.") : tr("手機與筆電使用同一 Wi-Fi，掃碼開啟 Safari。", "Use the same Wi-Fi as the laptop and scan to open Safari.")}</p>
        {connectionUrl ? <a href={connectionUrl} target="_blank" rel="noreferrer">{tr("開啟手機網頁", "Open phone page")}</a> : null}
        <button type="button" disabled={mobile.pairingBusy} onClick={() => void mobile.pair(baseUrl.trim() || undefined)}>{mobile.pairingBusy ? tr("準備配對…", "Preparing pairing…") : session ? tr("更新配對碼", "Refresh pairing code") : tr("更新 QR Code", "Refresh QR code")}</button>
        {!session ? <details className="mobile-pairing-help"><summary>{tr("首次連線／連不上？", "First connection / connection help")}</summary>
          <p>{tr("首次使用請先安裝並信任 Tinkro 區網憑證，再開啟 Safari 相機。", "First install and trust the Tinkro local certificate, then enable the Safari camera.")}</p>
          {configuration && !configuration.available ? <p>{tr("HTTPS 手機入口尚未啟動。", "The HTTPS phone entry point is not running.")}</p> : null}
          <label>{tr("手動指定筆電網路位址（選填）", "Manual laptop address (optional)")}<input value={baseUrl} placeholder={automaticOrigin || "https://192.168.1.10:8443"} onChange={event => setBaseUrl(event.target.value)} /></label>
        </details> : null}
      </div> : !session ? <div className="mobile-pairing"><p>{mobile.pairing?.web_url ? tr("iPhone 與筆電連上同一個 Wi-Fi，用手機相機掃描 QR code，選擇以 Safari 開啟 Tinkro。", "Connect iPhone and laptop to the same Wi-Fi. Scan with the phone camera and open Tinkro in Safari.") : tr("請先啟動筆電的手機網頁服務。原生開發版也可輸入下方位址與配對碼。", "Start the laptop's mobile web service. A native development build can also use the address and code below.")}</p>
        {mobile.pairing?.web_url ? <p className="mobile-info">{tr("第一次連線需先在 iPhone 安裝並信任 Tinkro 區網憑證；完成後即可使用 Safari 相機。", "On first connection, install and trust the Tinkro local certificate on iPhone to enable Safari camera access.")}</p> : webConfiguration && !webConfiguration.available ? <p className="mobile-info">{tr("HTTPS 手機入口尚未啟動。", "The HTTPS phone entry point is not running.")}</p> : null}
        {qr && !pairingExpired ? <img className="mobile-pairing-qr" src={qr} alt={tr("手機配對 QR code", "Phone pairing QR code")} /> : null}
        {invitation ? <><strong className="mobile-pairing-code">{invitation.code}</strong>
          {invitation.web_url ? <a href={invitation.web_url} target="_blank" rel="noreferrer">{tr("開啟手機網頁", "Open phone page")}</a> : null}</> : null}
        <label>{tr("手動指定筆電網路位址（選填）", "Manual laptop address (optional)")}<input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder={automaticOrigin || "https://192.168.1.10:8443"} /></label>
        <button type="button" disabled={mobile.pairingBusy} onClick={() => void mobile.pair(baseUrl || undefined)}>{mobile.pairingBusy ? tr("準備配對…", "Preparing pairing…") : tr("產生配對碼", "Create pairing code")}</button>
      </div> : <>
        {session.available_context && session.available_context.context_id !== session.context_id ? <p className="mobile-info">{tr("筆電內容已更新，請在手機切換到最新工作區。", "The desktop context has changed. Switch to the latest workspace on your phone.")}</p> : null}
        {!mainControls ? viewControls : null}
        {view === "live" ? <>{!mainControls && !workspace?.showing ? <MobileVideo key={`${session.session_id}:${session.stream.generation}`} session={session} />
          : <p className="mobile-info">{workspace?.showing ? tr("手機影像正在主畫面顯示。", "Phone video is shown in the main workspace.")
            : workspace?.canShow ? tr("按「手機串流」，在主畫面觀看即時影像。", "Press Phone stream to view live video in the main workspace.")
              : tr("請先完成目前的拍照或校正，再切換串流。", "Finish the current capture or calibration before switching the stream.")}</p>}
          <div className={`mobile-feedback ${readiness}`} role="status"><strong>{readiness === "locked" ? "Locked" : readiness === "hold_still" ? "Hold still" : "Finding"}</strong>
            <span>{readiness === "locked" ? tr("畫面穩定，可以拍照。", "The view is steady and ready to capture.") : readiness === "hold_still" ? tr("請保持手機穩定，讓接點清晰。", "Hold the phone steady so the contacts are clear.") : tr("讓板卡與零件完整入鏡，調整距離及光線。", "Keep the boards fully in view and adjust distance and light.")}</span></div></> : null}
        {!workspace?.showing || view === "photo" ? <MobileStreamCaptureActions live={view === "live"} active={Boolean(session.stream.active && session.stream.publisher_connected)}
          busy={streamCapture.busy} error={streamCapture.error} onCapture={() => void streamCapture.capture()} onRetry={() => void streamCapture.retry()} /> : null}
      </>}
      {view === "photo" ? photoLoading ? <p role="status">{tr("正在讀取照片定位…", "Loading photo geometry…")}</p> : currentCapture ? <>
        {outdated ? <p className="mobile-info">{tr("這是先前工作區的照片，可繼續檢視；核對前請在手機重新拍攝。", "This photo belongs to an earlier workspace. Retake on the phone before checking it.")}</p> : null}
        <MobilePhotoReview key={currentCapture.capture_id} capture={currentCapture} wireId={session?.view.capture_id === currentCapture.capture_id ? session.view.wire_id : localWire?.captureId === currentCapture.capture_id ? localWire.wireId : null}
          disabled={sending || controller.busy || !aiReady || !session || outdated} onWire={selectWire} onAsk={(scope, id) => void ask(scope, id)} />
      </> : captureId ? <button type="button" onClick={() => setLoadAttempt(value => value + 1)}>{tr("重新讀取照片", "Reload photo")}</button> : null : null}
      {!connectionView && (sending || controller.busy) ? <p role="status" className="mobile-info">{tr("AI 處理中，回覆會出現在同一份聊天。", "AI is working. The reply will appear in the same conversation.")}</p> : null}
      {panelError ? <p className="mobile-error" role="alert">{panelError}</p> : null}
    </section> : null;
  return <div ref={container} className={`mobile-companion${workspace?.trigger ? " is-docked" : ""}`}>
    {workspace?.trigger ? createPortal(trigger, workspace.trigger) : trigger}
    {workspace?.controls ? createPortal(workspace.source ? <ImageSourceSelect source={workspace.source}
      disabled={!workspace.canShow} phoneConnected={Boolean(session && !mobile.error)}
      onConnect={() => void showConnection()}
      onSelect={source => { workspace.onShow(source === 'phone', session); setOpen(false); }} /> : viewControls, workspace.controls) : null}
    {panel && panelHost ? createPortal(panel, panelHost) : panel}
    {workspace?.showing && workspace.preview ? createPortal(<MobileMainPreview session={session} readiness={readiness}
      pinsById={workspace.pinsById} guideTarget={workspace.guideTarget}
      onReturn={() => workspace.onShow(false)} captureActions={<MobileStreamCaptureActions live active={Boolean(session?.stream.active && session.stream.publisher_connected)}
        busy={streamCapture.busy} error={streamCapture.error} onCapture={() => void streamCapture.capture()} onRetry={() => void streamCapture.retry()} />} />, workspace.preview) : null}
  </div>;
}
