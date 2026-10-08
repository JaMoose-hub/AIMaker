import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { useI18n } from "../lib/i18n";
import type { AssistantMessage } from "../lib/assistant";
import { conversationMessageNote, conversationMessages } from "../lib/assistantHistory";
import { AssistantAnalysisTime } from "./AssistantAnalysisTime";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { WiringCaptureFraming, WiringPhotoDelivery, WiringReviewOverview } from "./WiringChatMessage";
import { compactWiringText, wiringChatSummary, wiringFlowReview } from "../lib/wiringChat";
import { wiringPhotoRoleLabel } from "../lib/wiringReview";
import { MobileWiringAlbumPanel } from "./MobileWiringAlbumPanel";
import { useMobileWiringAlbum, type MobileWiringAlbum } from "../lib/useMobileWiringAlbum";
import { mobileVideoFresh, type MobileCapture } from "../lib/mobile";
import { mobileTestHelpOffer, mobileWiringAnalysisFlow, mobileWiringPhotoFlow, useMobileAssetUrl, useMobileBrowser, type MobileWiringPhotoRequest } from "../lib/useMobileBrowser";
import { captureBrowserVideoFrame } from "../lib/mobileBrowserCapture";
import { PhoneCameraAutoTune } from "./PhoneCameraAutoTune";
import type { CaptureTicket } from "../lib/mobileBrowser";
import type { BrowserStreamResolution } from "../lib/mobileBrowserRtc";
import { mobileObjectName, mobilePairingCode, mobilePhotoGeometry, mobilePhotoLayout, mobilePhotoMatches,
  mobilePhotoReasons, mobilePhotoSource, mobileReadiness } from "../lib/mobileWebView";
import "../mobileWeb.css";

type Workspace = ReturnType<typeof useMobileBrowser>;
type MobileTab = "chat" | "camera" | "photo";
type Asset = NonNullable<AssistantMessage["attachments"]>[number];
function useMobileText() { const { locale } = useI18n(); return (zh: string, en: string) => locale === "en" ? en : zh; }

/** UI preference only: switching language never reconnects or changes camera state. */
export function MobileLanguageSwitch() {
  const { locale, setLocale } = useI18n();
  return <div className="mw-language-switch" role="group" aria-label="語言 / Language">
    <button type="button" lang="zh-Hant" aria-pressed={locale === "zh-TW"} onClick={() => setLocale("zh-TW")}>繁中</button>
    <button type="button" lang="en" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>English</button>
  </div>;
}

function Symbol({ name }: { name: "chat" | "camera" | "photo" | "arrow" | "link" | "chevron" | "attach" }) {
  const paths = { chat: "M5 4h14v12H9l-4 4V4Z M9 8h6 M9 12h4", camera: "M8 6l2-3h4l2 3h5v14H3V6h5Z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
    photo: "M3 3h18v18H3V3Z M3 16l6-6 5 5 3-3 4 4 M16 7h.01", arrow: "M5 12h14 M13 6l6 6-6 6", link: "M9 15l6-6 M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0 M13 7l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0",
    chevron: "m6 9 6 6 6-6", attach: "m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9 M6 14l8-8" };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

function SecureEntry({ url }: { url?: string }) {
  const tr = useMobileText();
  const httpsUrl = url?.startsWith("https://") ? url : null;
  return <div className="mw-notice"><strong>{tr("請使用 HTTPS 開啟手機相機", "Open the camera from HTTPS")}</strong>
    <p>{tr("Safari 的即時串流需要 HTTPS。請從電腦「連接手機」開啟新的 HTTPS 連結；聊天與附件仍可使用。", "Safari live streaming requires HTTPS. Open the HTTPS link from Connect phone on the desktop. Chat and attachments remain available.")}</p>
    {httpsUrl ? <a className="mw-button mw-primary" href={httpsUrl}>{tr("開啟 HTTPS 手機頁", "Open HTTPS phone page")}<Symbol name="arrow" /></a> : null}</div>;
}

/** The authenticated image stays local to this message; opening it never changes the workspace. */
export function MobileChatImage({ src, alt, title, openLabel }: { src: string; alt: string; title: string; openLabel: string }) {
  const tr = useMobileText();
  const [openedSrc, setOpenedSrc] = useState<string | null>(null);
  const opened = openedSrc === src;
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!opened || !element) return;
    element.showModal();
    return () => { element.close(); trigger.current?.focus({ preventScroll: true }); };
  }, [opened, src]);
  return <>
    <button ref={trigger} type="button" className="mw-photo-open" aria-haspopup="dialog" aria-label={openLabel} onClick={() => setOpenedSrc(src)}>
      <img src={src} alt={alt} loading="lazy" />
    </button>
    {opened ? <dialog ref={dialog} className="mw-wiring-original" aria-label={title} onClose={() => setOpenedSrc(null)}
      onCancel={event => { event.preventDefault(); setOpenedSrc(null); }}>
      <header><strong>{title}</strong><button type="button" className="mw-quiet" autoFocus onClick={() => setOpenedSrc(null)}>{tr("關閉", "Close")}</button></header>
      <img src={src} alt={alt} />
    </dialog> : null}
  </>;
}

function AssetView({ api, asset }: { api: Workspace["api"]; asset: Asset }) {
  const tr = useMobileText();
  const [play, setPlay] = useState(false);
  const video = asset.type === "video";
  const path = video && !play ? asset.thumbnail_url : asset.image_url || asset.url;
  const media = useMobileAssetUrl(api, path);
  return <figure className="mw-message-media">
    {media.url ? video ? play ? <video src={media.url} controls playsInline preload="metadata" />
      : <img src={media.url} alt={asset.filename ?? tr("聊天附件", "Conversation attachment")} loading="lazy" />
      : <MobileChatImage src={media.url} alt={asset.filename ?? tr("聊天附件", "Conversation attachment")}
        title={asset.filename ?? tr("圖片", "Image")} openLabel={tr("放大查看圖片", "View full image")} /> : null}
    {video && !play ? <button type="button" className="mw-quiet" onClick={() => setPlay(true)}>{tr("播放影片", "Play video")}</button> : null}
    {media.error ? <button type="button" className="mw-quiet" onClick={media.retry}>{tr("重新讀取附件", "Reload attachment")}</button> : null}
    <figcaption>{asset.filename ?? (video ? tr("影片", "Video") : tr("照片", "Photo"))}</figcaption>
  </figure>;
}

/** Persisted message actions are explicit consent; ordinary chat replies stay ordinary messages. */
export function MobileTestHelpActions({ w, message }: { w: Workspace; message: AssistantMessage }) {
  const tr = useMobileText();
  const offer = mobileTestHelpOffer(message, w.session, w.conversation);
  const error = w.testHelpError?.messageId === message.id && w.testHelpError.offerId === message.test_help_offer?.offer_id ? w.testHelpError.text : null;
  if (!offer) return error ? <p className="mw-error-text" role="alert">{error}</p> : null;
  const pending = w.testHelpPendingMessageId === message.id;
  const disabled = !w.ready || !w.connected || w.wiringReviewBusy || w.testHelpPendingMessageId !== null;
  const continuation = offer.reusable_review || offer.state === "started";
  return <div className="mw-test-help-actions" data-offer-id={offer.offer_id} aria-busy={pending}>
    <div className="mw-row">
      <button type="button" className="mw-button mw-primary" disabled={disabled || w.busy || !offer.can_act} onClick={() => void w.testHelpAction(message, "start")}>
        <Symbol name="camera" />{continuation ? tr("繼續照片核對", "Continue photo review") : tr("拍照檢查", "Photo check")}
      </button>
      <button type="button" className="mw-button mw-secondary" disabled={disabled || !offer.can_dismiss} onClick={() => void w.testHelpAction(message, "later")}>{tr("稍後", "Later")}</button>
    </div>
    {pending ? <small role="status">{tr("正在處理這個操作…", "Completing this action…")}</small> : null}
    {error ? <p className="mw-error-text" role="alert">{error}</p> : null}
  </div>;
}

/** A wiring photo is a normal shared user message; its original opens only on request. */
export function MobileWiringChatPhoto({ w, message }: { w: Workspace; message: AssistantMessage }) {
  const tr = useMobileText();
  const media = useMobileAssetUrl(w.api, message.wiring_flow?.kind === "photo" ? message.wiring_flow.image_url : undefined);
  if (message.wiring_flow?.kind !== "photo" || !message.wiring_flow.image_url) return null;
  return <figure className="mw-message-media mw-wiring-chat-photo">
    {media.url ? <MobileChatImage src={media.url} alt={tr("已提交的接線照片", "Submitted wiring photo")}
      title={tr("接線照片原圖", "Original wiring photo")} openLabel={tr("放大查看接線照片原圖", "View the original wiring photo larger")} /> : null}
    {message.wiring_flow.role ? <figcaption>{wiringPhotoRoleLabel(message.wiring_flow.role, tr, message.wiring_flow.capture_plan)}</figcaption> : null}
    {media.error ? <button type="button" className="mw-quiet" onClick={media.retry}>{tr("重新讀取照片", "Reload photo")}</button> : null}
  </figure>;
}

/** Camera and album submissions answer the exact current server question. */
export function MobileWiringChatActions({ w, message, photoAlbum }: { w: Workspace; message: AssistantMessage; photoAlbum?: MobileWiringAlbum }) {
  const tr = useMobileText();
  const camera = useRef<HTMLInputElement>(null);
  const album = useRef<HTMLInputElement>(null);
  const requested = useRef<MobileWiringPhotoRequest | null>(null);
  const albumRequested = useRef<MobileWiringPhotoRequest | null>(null);
  const [albumError, setAlbumError] = useState('');
  const flow = mobileWiringPhotoFlow(message, w.session, w.conversation, w.wiringReview, w.wiringCanAct);
  const analysis = mobileWiringAnalysisFlow(message, w.session, w.conversation, w.wiringReview, w.wiringCanAct, true);
  const role = message.wiring_flow?.kind === "photo_request" ? message.wiring_flow.role : undefined;
  const pending = w.pendingWiringPhoto?.dialogue?.message_id === message.id ? w.pendingWiringPhoto : null;
  const disabled = !w.ready || !w.connected || w.busy || w.wiringReviewBusy;
  if (!flow && !analysis && !pending && !role) return null;
  return <div className="mw-wiring-chat-actions" aria-busy={Boolean((pending || analysis) && w.wiringReviewBusy)}>
    {analysis ? <div className="mw-row"><button type="button" className="mw-button mw-primary" disabled={disabled || w.chatSendBlocked || !w.wiringCanAct || !analysis.can_act || !analysis.actions?.includes('analyse')}
      onClick={() => void w.analyseWiringChat(message)}>{w.wiringReviewBusy ? tr('送出中…', 'Sending…')
        : analysis.kind === 'error' ? tr('重新分析', 'Retry analysis') : tr('開始分析', 'Start analysis')}</button></div> : null}
    {role ? <WiringCaptureFraming role={role} capturePlan={message.wiring_flow?.capture_plan} current={Boolean(flow)} /> : null}
    {flow ? <><div className="mw-row mw-wiring-photo-sources">
      <button type="button" className="mw-button mw-secondary" disabled={disabled} onClick={() => {
        const target = w.prepareWiringChatPhoto(message);
        if (target) { requested.current = target; camera.current?.click(); }
      }}><Symbol name="camera" />{tr("拍這張照片", "Take this photo")}</button>
      <button type="button" className="mw-button mw-secondary" disabled={disabled} onClick={() => {
        const target = w.prepareWiringChatPhoto(message);
        if (target) { albumRequested.current = target; album.current?.click(); }
      }}><Symbol name="photo" />{tr("從相簿選擇", "Choose from album")}</button>
    </div><small>{tr("可一次選好三張，確認角度後逐張送出；接線改過請用新照片。", "Choose all three photos, check their views, then send them one at a time. Use new photos if the wiring changed.")}</small></> : null}
    <input ref={camera} type="file" accept="image/*" capture="environment" className="mw-file-input" aria-label={tr("拍攝這一題要求的照片", "Capture the photo requested in this question")} onChange={event => {
      const file = event.target.files?.[0], target = requested.current; event.target.value = ""; requested.current = null;
      if (file && target) void w.uploadWiringChatPhoto(file, target, () => photoAlbum?.submitted(target, file));
    }} />
    <input ref={album} type="file" accept="image/*" multiple={Boolean(photoAlbum)} className="mw-file-input" aria-label={tr("從相簿選擇這一題要求的照片", "Choose the photo requested in this question from your album")} onChange={event => {
      const files = Array.from(event.target.files ?? []), target = albumRequested.current; event.target.value = ""; albumRequested.current = null;
      if (!files.length || !target) return;
      setAlbumError('');
      if (files.length > 1) {
        if (!photoAlbum?.stage(files, target)) setAlbumError(tr('最多選三張，並確認目前仍是同一輪照片核對。', 'Choose up to three photos and make sure this is still the same photo-review round.'));
      } else void w.uploadWiringChatPhoto(files[0], target, () => photoAlbum?.submitted(target, files[0]));
    }} />
    {flow?.role && photoAlbum?.selection ? <MobileWiringAlbumPanel album={photoAlbum} role={flow.role} capturePlan={flow.capture_plan} disabled={disabled} tr={tr} onUse={() => {
      const target = w.prepareWiringChatPhoto(message), file = target && photoAlbum.fileFor(target);
      if (target && file) void w.uploadWiringChatPhoto(file, target, () => photoAlbum.submitted(target, file));
    }} /> : null}
    {albumError && flow ? <p className="mw-error-text" role="alert">{albumError}</p> : null}
    {pending ? <><small role="status">{w.wiringReviewBusy ? `${tr("正在提交照片", "Submitting photo")} · ${Math.round((pending.attachment.progress ?? 0) * 100)}%` : tr("尚未確認照片是否送達，可取得最新對話後重試。", "Photo delivery is not confirmed. Reload the conversation, then retry.")}</small>
      {!w.wiringReviewBusy ? <div className="mw-row"><button type="button" className="mw-quiet" disabled={disabled || !flow} onClick={() => void w.retryWiringPhoto()}>{tr("重試這張照片", "Retry this photo")}</button>
        <button type="button" className="mw-quiet" onClick={() => void w.refresh()}>{tr("重新取得對話", "Reload conversation")}</button><button type="button" className="mw-quiet" onClick={w.discardWiringPhoto}>{tr("移除待送照片", "Remove pending photo")}</button></div> : null}</> : null}
    {w.wiringReviewError ? <p className="mw-error-text" role="alert">{w.wiringReviewError}</p> : null}
  </div>;
}

export function ChatView({ w, onPhoto, onCamera, photoAlbum }: { w: Workspace; onPhoto: (id: string) => void; onCamera?: () => void; photoAlbum?: MobileWiringAlbum }) {
  const tr = useMobileText();
  const { locale } = useI18n();
  const attachments = useRef<HTMLInputElement>(null);
  const partsCamera = useRef<HTMLInputElement>(null);
  const partsAlbum = useRef<HTMLInputElement>(null);
  const partsCheck = w.attachments.some(attachment => attachment.purpose === 'parts_check');
  const messages = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const follow = useRef(true);
  const [clearedHistoryKey, setClearedHistoryKey] = useState<string | null>(null);
  const historyKey = w.conversation ? `${w.conversation.id}:${w.conversation.context_epoch}` : null;
  const showCleared = historyKey !== null && clearedHistoryKey === historyKey;
  const visibleMessages = conversationMessages(w.conversation, showCleared);
  const hasCleared = w.conversation?.messages.some(message => message.epoch !== w.conversation?.context_epoch);
  const latest = visibleMessages.at(-1)?.id;
  const analysisMessageId = w.wiringAnalysis ? visibleMessages.filter(message => message.role === "assistant"
    && message.epoch === w.conversation?.context_epoch && message.round === w.conversation?.round
    && !message.archived && message.wiring_flow?.current && message.wiring_flow.kind === "analysing").at(-1)?.id : null;
  useEffect(() => { if (follow.current && messages.current) messages.current.scrollTop = messages.current.scrollHeight; }, [latest, w.wiringReview?.revision]);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    const resize = () => { element.style.height = '0px'; element.style.height = `${Math.min(120, Math.max(44, element.scrollHeight))}px`; };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, [w.draft]);
  return <section className="mw-chat" aria-label={tr("共用對話", "Shared conversation")}>
    <div className="mw-messages" ref={messages} onScroll={() => { const el = messages.current; if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }} role="log" aria-live="polite">
      {w.conversation?.before != null ? <button type="button" className="mw-quiet mw-history" onClick={() => void w.older()}>{tr("載入較早訊息", "Earlier messages")}</button> : null}
      {hasCleared ? <button type="button" className="mw-quiet mw-history" aria-expanded={showCleared} onClick={() => setClearedHistoryKey(showCleared ? null : historyKey)}>{showCleared ? tr("隱藏已清除紀錄", "Hide cleared history") : tr("查看已清除紀錄", "View cleared history")}</button> : null}
      {!visibleMessages.length ? <div className="mw-empty"><Symbol name="chat" /><h2>{tr("接著聊，從這裡開始。", "Continue your project here.")}</h2><p>{tr("與電腦共用同一份對話。你可以提問、附上照片，或拍下目前的接線。", "The same conversation as your desktop. Ask a question, add a photo, or capture the wiring in front of you.")}</p></div> : null}
      {visibleMessages.map(message => {
        const note = conversationMessageNote(message, w.conversation!);
        const flow = message.role === "assistant" ? message.wiring_flow : undefined;
        const overview = flow?.kind === "wire_review" && flow.result ? wiringChatSummary(flow, w.wiringReview, tr) : null;
        const text = flow ? compactWiringText(flow, message.text, tr) : message.text;
        const routineHistory = Boolean(flow && (!flow.current || note)
          && ["photo_request", "analysis_request", "analysing"].includes(flow.kind));
        const content = <>
          {flow?.current && !note && ["analysis_request", "analysing", "wire_review", "error"].includes(flow.kind)
            ? <WiringPhotoDelivery review={wiringFlowReview(flow, w.wiringReview)} /> : null}
          {overview ? <WiringReviewOverview summary={overview} focusWireId={flow?.wire_id}>
            {flow?.current && !note && overview.retake_role ? <small>{tr('請在電腦按「補拍」。', 'Choose Retake on your computer.')}</small> : null}
            <details><summary>{tr("查看分析紀錄", "View analysis record")}</summary>
              <AssistantMarkdown text={message.text} />
              {typeof flow?.elapsed_ms === "number" ? <AssistantAnalysisTime active={false} durationMs={flow.elapsed_ms} className="mw-analysis-time" /> : null}
            </details>
          </WiringReviewOverview> : message.role === "assistant" ? <AssistantMarkdown text={routineHistory ? message.text : text} /> : <p>{message.text}</p>}
          {flow?.kind === "error" && flow.error ? <details><summary>{tr("查看錯誤原因", "View error details")}</summary><p>{flow.error}</p></details> : null}
          {!overview && (w.wiringAnalysis && message.id === analysisMessageId ? <AssistantAnalysisTime startedAt={w.wiringAnalysis.startedAt} active className="mw-analysis-time" />
            : message.role === "assistant" && typeof message.wiring_flow?.elapsed_ms === "number"
              ? <AssistantAnalysisTime active={false} durationMs={message.wiring_flow.elapsed_ms} className="mw-analysis-time" /> : null)}
          <MobileTestHelpActions w={w} message={message} />
          <MobileWiringChatActions w={w} message={message} photoAlbum={photoAlbum} />
          <MobileWiringChatPhoto w={w} message={message} />
          {message.attachments?.map(asset => <AssetView key={asset.asset_id} asset={asset} api={w.api} />)}
          {message.capture_id && !message.wiring_flow ? <button type="button" className="mw-photo-link" onClick={() => onPhoto(message.capture_id!)}><Symbol name="photo" />{tr("查看 GPIO 照片", "View GPIO photo")}</button> : null}
        </>;
        return <article key={message.id} data-message-id={message.id} className={`mw-message ${message.role === "user" ? "is-user" : "is-assistant"}${note ? " is-archived" : ""}`}>
          <header><strong>{message.role === "user" ? tr("你", "You") : "Tinkro"}</strong><time>{message.created_at ? new Date(message.created_at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }) : ""}</time></header>
          {routineHistory ? <details className="wiring-chat-history"><summary>{text}</summary>{content}</details> : content}
          {note === "previous_context" ? <small>{tr("先前聊天上下文", "Earlier conversation context")}</small> : note === "previous_round" ? <small>{tr("先前輪次", "Earlier round")}</small> : null}
        </article>;
      })}
      {w.wiringAnalysis && !analysisMessageId ? <AssistantAnalysisTime startedAt={w.wiringAnalysis.startedAt} active className="mw-thinking mw-analysis-time" />
        : !w.wiringAnalysis && w.conversation?.jobs.some(job => job.status === "running") ? <div className="mw-thinking" role="status"><span />{tr("Tinkro 正在思考…", "Tinkro is thinking…")}</div> : null}
      {w.outbox.map(item => <article className="mw-outbox" key={item.id}><strong>{tr("待送訊息", "Pending message")}</strong><p>{item.payload.text}</p>
        {item.attachments.map(asset => <small key={asset.id}>{asset.name} · {Math.round((asset.progress ?? 0) * 100)}%</small>)}
        <p className="mw-error-text">{item.error ?? tr("傳送中…", "Sending…")}</p><div className="mw-row">
          <button type="button" className="mw-quiet" disabled={w.chatSendBlocked} onClick={() => void w.retry(item.id)}>{tr("重試", "Retry")}</button>
          <button type="button" className="mw-quiet" disabled={w.busy} onClick={() => w.removeOutbox(item.id)}>{tr("移除", "Remove")}</button></div></article>)}
    </div>
    <form className="mw-composer" onSubmit={event => { event.preventDefault(); if (w.chatSendBlocked) return; follow.current = true; void w.send(); }}>
      {w.session?.context?.stage === 'design' && w.session.context.ui?.parts_check === true ? <div className="mw-hardware-upload"><div><strong>{tr('零件核對', 'Check hardware')}</strong><small>Pi 5 · {tr('超音波', 'Ultrasonic')} · TFT</small></div>
        <input ref={partsCamera} type="file" accept="image/*" capture="environment" className="mw-file-input" aria-label={tr('拍攝零件標籤', 'Photograph part labels')}
          onChange={event => { void w.addFiles(Array.from(event.target.files ?? []), 'parts_check'); event.target.value = ''; }} />
        <input ref={partsAlbum} type="file" accept="image/*" multiple className="mw-file-input" aria-label={tr('選擇零件照片', 'Select part photographs')}
          onChange={event => { void w.addFiles(Array.from(event.target.files ?? []), 'parts_check'); event.target.value = ''; }} />
        <div><button type="button" className="mw-quiet" disabled={w.busy || w.chatSendBlocked} onClick={() => partsCamera.current?.click()}><Symbol name="camera" />{tr('拍照核對', 'Photograph parts')}</button>
          <button type="button" className="mw-quiet" disabled={w.busy || w.chatSendBlocked} onClick={() => partsAlbum.current?.click()}><Symbol name="photo" />{tr('相簿核對', 'Select part photos')}</button></div>
        <small className="mw-hardware-upload-note">{tr('加入後按送出，只核對這三項硬體；不檢查接線。', 'Press Send to compare these three parts only, not their wiring.')}</small></div> : null}
      {partsCheck ? <p className="mw-reference" role="status">{tr('本次用途：零件核對，不重新設計作品。', 'This request: hardware comparison, not project redesign.')}</p> : null}
      {w.inheritedMediaLabel ? <div className="mw-reference is-removable"><Symbol name="link" /><span role="status">{w.inheritedMediaLabel}</span>
        <button type="button" className="mw-reference-remove" disabled={!w.ready} aria-label={tr('取消引用', 'Remove reference')} title={tr('取消引用', 'Remove reference')} onClick={w.removeMediaReference}>×</button></div> : null}
      {w.attachments.length ? <div className="mw-draft-assets">{w.attachments.map(asset => <div key={asset.id}>
        {asset.previewUrl && asset.type === "image" ? <img src={asset.previewUrl} alt={asset.name} /> : <Symbol name="photo" />}
        <span>{asset.name}<small>{(asset.size / 1048576).toFixed(1)} MB</small></span>
        <button type="button" className="mw-icon-button" aria-label={tr("移除附件", "Remove attachment")} onClick={() => w.removeAttachment(asset.id)}>×</button></div>)}</div> : null}
      <label className="mw-sr-only" htmlFor="mw-chat-input">{tr("訊息", "Message")}</label>
      <input ref={attachments} type="file" accept="image/*,video/*" multiple className="mw-file-input" aria-label={tr("選擇照片或影片附件", "Select photo or video attachments")}
        onChange={event => { void w.addFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      <div className="mw-composer-bar">
        <button type="button" className="mw-quiet mw-composer-icon" disabled={w.busy} aria-label={tr("加入附件", "Add media")} title={tr("加入附件", "Add media")} onClick={() => attachments.current?.click()}><Symbol name="attach" /></button>
        {onCamera ? <button type="button" className="mw-quiet mw-composer-icon" disabled={w.busy} aria-label={tr("拍照問 AI", "Photo for AI")} title={tr("拍照問 AI", "Photo for AI")} onClick={onCamera}><Symbol name="camera" /></button> : null}
        <textarea ref={input} id="mw-chat-input" value={w.draft} onChange={event => w.setDraft(event.target.value)} maxLength={8000} rows={1} placeholder={tr("問 Tinkro…", "Ask Tinkro…")} />
        <button className="mw-send" type="submit" disabled={w.chatSendBlocked || (!w.draft.trim() && !w.attachments.length)} aria-label={partsCheck ? tr('送出零件核對', 'Send hardware comparison') : tr("送出訊息", "Send message")} aria-describedby={w.wiringAnalysis ? "mw-analysis-send-note" : undefined}><Symbol name="arrow" /></button></div>
      {w.wiringAnalysis ? <small id="mw-analysis-send-note" className="mw-composer-note">{tr("分析完成後才能送出，草稿可以繼續編輯。", "Send after analysis finishes. You can keep editing your draft.")}</small> : null}
    </form>
  </section>;
}

export function MobileWebCamera({ w, httpsUrl, onCaptured, onDebugCaptured }: { w: Workspace; httpsUrl?: string; onCaptured: () => void; onDebugCaptured?: () => void }) {
  const tr = useMobileText();
  const video = useRef<HTMLVideoElement>(null);
  const capturing = useRef(false);
  const mounted = useRef(true);
  const latestWorkspace = useRef(w); latestWorkspace.current = w;
  const [resolution, setResolution] = useState<BrowserStreamResolution>(() => w.rtc.resolution ?? '1080p');
  useEffect(() => { if (w.rtc.resolution) setResolution(w.rtc.resolution); }, [w.rtc.resolution]);
  const [bitrate, setBitrate] = useState(12000);
  useEffect(() => {
    const applied = w.rtc.stats.appliedBitrateKbps;
    if (applied !== undefined && [3000, 8000, 12000].includes(applied)) setBitrate(applied);
  }, [w.rtc.stats.appliedBitrateKbps]);
  const [cameraOpening, setCameraOpening] = useState(false);
  const [captureKind, setCaptureKind] = useState<"debug" | "gpio" | null>(null);
  const [localFrame, setLocalFrame] = useState<{ stream: MediaStream; width: number; height: number; ready: boolean } | null>(null);
  const [playError, setPlayError] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  function frameReady(element: HTMLVideoElement, stream: MediaStream) {
    return element.srcObject === stream && element.readyState >= 2 && !element.paused && element.videoWidth > 0 && element.videoHeight > 0
      && stream.getVideoTracks().some(track => track.readyState === "live");
  }
  function readLocalFrame() {
    const element = video.current, stream = latestWorkspace.current.rtc.stream;
    if (element && stream) setLocalFrame({ stream, width: element.videoWidth, height: element.videoHeight, ready: frameReady(element, stream) });
  }
  useEffect(() => {
    const element = video.current;
    let disposed = false;
    setPlayError(""); setLocalFrame(null);
    if (element) { element.srcObject = w.rtc.stream; if (w.rtc.stream) void element.play().then(() => { if (!disposed) readLocalFrame(); }).catch(() => { if (!disposed) setPlayError(tr("點一下播放預覽", "Tap to play preview")); }); }
    return () => { disposed = true; if (element) element.srcObject = null; };
  }, [w.rtc.stream]);
  const [captureError, setCaptureError] = useState("");
  function captureOwner(snapshot: Workspace, stream: MediaStream) {
    const sessionId = snapshot.session?.session_id, contextId = snapshot.session?.context_id, conversationId = snapshot.session?.conversation_id;
    return () => mounted.current && latestWorkspace.current.session?.session_id === sessionId
      && latestWorkspace.current.session?.context_id === contextId && latestWorkspace.current.session?.conversation_id === conversationId
      && latestWorkspace.current.rtc.stream === stream;
  }
  async function captureForChat() {
    const snapshot = latestWorkspace.current, element = video.current, stream = snapshot.rtc.stream;
    if (capturing.current || snapshot.busy || !snapshot.ready || !snapshot.session || !element || !stream || !frameReady(element, stream)) return;
    const current = captureOwner(snapshot, stream);
    capturing.current = true; setCameraOpening(true); setCaptureKind("debug"); setCaptureError("");
    try {
      const file = await captureBrowserVideoFrame(element, stream);
      if (!current()) return;
      const added = await snapshot.addFiles([file]);
      if (added === true && current()) onDebugCaptured?.();
    } catch (cause) { if (current()) setCaptureError(cause instanceof Error ? cause.message : String(cause)); }
    finally { capturing.current = false; if (mounted.current) { setCameraOpening(false); setCaptureKind(null); } }
  }
  async function capture() {
    if (capturing.current || w.busy || w.rtc.publishing === false || !mobileVideoFresh(w.session?.stream) || !w.canCapture || !video.current || !w.rtc.stream) return;
    capturing.current = true; setCameraOpening(true); setCaptureKind("gpio"); setCaptureError("");
    const element = video.current, stream = w.rtc.stream;
    const current = captureOwner(w, stream);
    let ticket: CaptureTicket | null = null;
    try {
      ticket = await w.beginCapture({ keepStreaming: true });
      if (!ticket || !current()) return;
      const file = await captureBrowserVideoFrame(element, stream);
      if (!current()) return;
      if (await w.finishCapture(file, ticket, "phone_frame") && current()) onCaptured();
    } catch (cause) {
      if (current()) setCaptureError(cause instanceof Error ? cause.message : String(cause));
      if (ticket) await w.cancelCapture({ ticketId: ticket.ticket_id });
    } finally { capturing.current = false; if (mounted.current) { setCameraOpening(false); setCaptureKind(null); } }
  }
  const receiveFresh = mobileVideoFresh(w.session?.stream);
  const readiness = mobileReadiness(w.session?.stream, w.canCapture && receiveFresh, w.previewFresh && receiveFresh);
  const contextChanged = Boolean(w.session?.available_context && w.session.available_context.context_id !== w.session.context_id);
  const previewReason = w.session?.stream.reason;
  const feedback = contextChanged ? tr("筆電已更新接線步驟，請先按「加入目前作品」再拍照。", "Desktop wiring changed. Choose Join current project before taking a photo.") : w.session?.stream.active && w.rtc.publishing && !receiveFresh ? tr("等待電腦接收新的影格，正在恢復連線", "Waiting for fresh frames on the desktop; recovering the connection") : readiness === "locked" ? tr("畫面已穩定，可以拍照", "Steady and ready to capture")
    : readiness === "idle" ? tr("開啟串流，找到你的板卡", "Start streaming to find your board")
      : !w.previewFresh || previewReason === "preview_expired" || w.session?.stream.state === "locked" ? tr("等待新的定位，請保持串流", "Waiting for a fresh position; keep the camera in place")
        : readiness === "hold_still" || previewReason === "hold_still" ? tr("請穩住手機", "Hold the phone still")
          : previewReason === "find_board" ? tr("請讓 Raspberry Pi 完整入鏡", "Bring the Raspberry Pi into view")
            : previewReason === "find_target_component" ? tr("請讓目標零件入鏡", "Bring the target module into view")
              : previewReason === "move_closer" ? tr("請稍微靠近", "Move a little closer")
                : previewReason === "improve_focus_or_light" ? tr("請調整對焦距離或光線", "Adjust focus distance or lighting")
                  : tr("請讓板卡與目標零件完整入鏡", "Keep the board and target module fully in view");
  const fps = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
  const local = localFrame?.stream === w.rtc.stream ? localFrame : null;
  const sourceSize = local && local.width > 0 && local.height > 0 ? [local.width, local.height]
    : w.rtc.frame?.sourceSize ?? (w.rtc.settings?.width && w.rtc.settings.height ? [w.rtc.settings.width, w.rtc.settings.height] : null);
  const ratio = sourceSize && sourceSize.every(value => Number.isFinite(value) && value > 0) ? sourceSize[0] / sourceSize[1] : 4 / 3;
  const receivedStream = w.rtc.publishing === false || w.rtc.frame?.ready === false || !receiveFresh ? null : w.session?.stream;
  // Pending selection does not change the quality target of a running stream.
  const activeResolution = w.rtc.resolution ?? resolution;
  const belowTarget = (size: readonly number[] | undefined) => Boolean(size?.length === 2 && size.every(value => value > 0)
    && (Math.min(...size) < (activeResolution === '720p' ? 720 : 1080) || Math.max(...size) < (activeResolution === '720p' ? 1280 : 1920)));
  const uploadSize = w.rtc.stats?.width && w.rtc.stats.height ? [w.rtc.stats.width, w.rtc.stats.height] : undefined;
  const streamWarning = !w.rtc.stream ? null : w.rtc.frame?.issue === 'orientation'
    ? tr("正在同步相機方向；若持續不一致，請確認手機已開啟自動旋轉。", "Synchronizing camera orientation. If it stays incorrect, check that auto-rotate is enabled.")
    : w.rtc.frame?.issue === 'constraints' ? tr("相機未能套用方向偏好，串流持續中；請確認畫面方向。", "The camera could not apply the orientation preference. Streaming continues; check the image orientation.")
    : w.rtc.frame?.issue === 'resolution' || belowTarget(uploadSize) || belowTarget(receivedStream?.video_size)
      ? tr(`實際影像未達 ${activeResolution}，請檢查相機／網路；目前畫質未達標。`, `Actual video is below ${activeResolution}. Check the camera / network; quality target not met.`) : null;
  return <div className="mw-page mw-camera-page">
    <div className="mw-page-heading mw-camera-heading"><h2>{tr("串流", "Stream")}</h2>
      {w.rtc.stream ? <button type="button" className="mw-quiet" onClick={() => void w.stopStream()}>{tr("停止", "Stop")}</button>
        : <button type="button" className="mw-button mw-secondary" disabled={!w.secureContext || w.busy || cameraOpening || Boolean(w.captureTicket)} onClick={() => void w.startStream({ resolution, bitrateKbps: bitrate })}>{tr("開啟串流", "Start stream")}</button>}</div>
    <div className="mw-viewfinder" style={{ aspectRatio: ratio, "--mw-video-ratio": ratio } as CSSProperties}><video ref={video} autoPlay muted playsInline
      onLoadedMetadata={readLocalFrame} onLoadedData={readLocalFrame} onPlaying={readLocalFrame} onResize={readLocalFrame} onPause={readLocalFrame} onEmptied={readLocalFrame}
      aria-label={tr("iPhone 後置相機串流", "iPhone rear-camera stream")} />
      {!w.rtc.stream ? <div className="mw-camera-empty"><Symbol name="camera" /><p>{tr("你的鏡頭，你的工作台", "Your camera. Your workbench.")}</p></div> : null}
      <div className="mw-corner top-left" /><div className="mw-corner bottom-right" />
    </div>
    <div className="mw-camera-controls">
    {!w.secureContext ? <SecureEntry url={httpsUrl} /> : null}
    {playError ? <button type="button" className="mw-button mw-secondary" onClick={() => void video.current?.play().then(() => setPlayError(""))}>{playError}</button> : null}
    {streamWarning ? <p role="status" className="mw-error-text">{streamWarning}</p> : null}
    <div className="mw-camera-actions"><button type="button" className="mw-button mw-primary mw-debug-capture" disabled={!local?.ready || w.rtc.frame?.ready === false || !w.rtc.stream || !w.session || !w.ready || w.busy || cameraOpening} onClick={() => void captureForChat()}><Symbol name="camera" />{cameraOpening && captureKind === "debug" ? tr("正在加入聊天…", "Adding to chat…") : tr("拍照問 AI／除錯", "Photo for AI / debugging")}</button>
      <button type="button" className="mw-button mw-secondary mw-capture-button" disabled={contextChanged || w.rtc.publishing === false || !receiveFresh || !w.canCapture || w.busy || cameraOpening || Boolean(w.captureJob)} onClick={() => void capture()}><Symbol name="photo" />{cameraOpening && captureKind === "gpio" ? tr("保存與分析照片…", "Saving & analyzing…") : tr("GPIO 引導拍照", "GPIO guidance photo")}</button></div>
    {captureError ? <p role="alert" className="mw-error-text">{captureError}</p> : null}
    <div className={`mw-feedback mw-camera-feedback is-${readiness}`} role="status"><i /><div><strong>{tr("GPIO", "GPIO")} · {readiness === "locked" ? tr("可以拍照", "Ready to capture") : readiness === "hold_still" ? tr("請穩住", "Hold still") : readiness === "idle" ? tr("尚未串流", "Stream off") : tr("尋找中", "Finding")}</strong><p>{!w.rtc.stream ? w.rtc.status : feedback}</p></div></div>
    {w.captureJob ? <div className="mw-capture-handoff" role="status"><strong>{w.captureJob.error ?? tr("正在保存與分析這張照片", "Saving and analyzing this photo")}</strong>
      <button type="button" className="mw-quiet" disabled={w.busy || w.captureJob.ticket.context_id !== w.session?.context_id} onClick={() => void w.retryCapture()}>{tr("重試這張照片", "Retry this photo")}</button>
      {w.captureJob.ticket.context_id !== w.session?.context_id ? <button type="button" className="mw-quiet" disabled={w.busy} onClick={() => { if (w.discardCapture(true)) onDebugCaptured?.(); }}>{tr("保留為對話附件", "Keep as chat attachment")}</button> : null}
      <button type="button" className="mw-quiet" disabled={w.busy} onClick={() => w.discardCapture()}>{tr("取消這張照片", "Discard this photo")}</button></div> : null}
    <PhoneCameraAutoTune controller={w.cameraTune} video={video}
      disabled={!w.secureContext || !local?.ready || w.rtc.frame?.ready === false || !w.rtc.publishing || !receiveFresh || w.busy || cameraOpening || Boolean(w.captureTicket || w.captureJob)} />
    <details className="mw-camera-settings"><summary>{tr("串流設定", "Stream settings")}</summary><div className="mw-camera-settings-body">
    <div className="mw-stream-settings"><label>{tr("解析度", "Resolution")}<select disabled={w.busy || cameraOpening || Boolean(w.captureTicket || w.captureJob)} value={resolution} onChange={event => setResolution(event.target.value === '720p' ? '720p' : '1080p')}><option value="1080p">1920 × 1080 · 1080p</option><option value="720p">1280 × 720 · 720p</option></select></label>
      <label>{tr("畫質", "Quality")}<select disabled={w.busy || cameraOpening} value={bitrate} onChange={event => setBitrate(Number(event.target.value))}><option value={3000}>{tr("流暢", "Smooth")}</option><option value={8000}>{tr("標準", "Standard")}</option><option value={12000}>{tr("高畫質", "High")}</option></select></label></div>
    {w.rtc.stream ? <button type="button" className="mw-button mw-secondary" disabled={!w.secureContext || w.busy || cameraOpening || Boolean(w.captureTicket)} onClick={() => void w.startStream({ resolution, bitrateKbps: bitrate })}>{tr("套用並重新串流", "Apply & restart stream")}</button> : null}
    <details className="mw-camera-diagnostics"><summary>{tr("串流資訊", "Stream details")}</summary><div className="mw-camera-diagnostics-body">
    <p className="mw-metric-note" role="status">{w.rtc.status}</p>
    {w.rtc.frame && w.rtc.stream ? <p className="mw-metric-note">{tr("相機來源", "Camera input")} {w.rtc.frame.sourceSize.join(" × ")} → {tr("串流尺寸", "Streaming size")} {w.rtc.frame.outputSize.join(" × ")}</p> : null}
    <div className="mw-camera-metrics"><div><span>{tr("手機相機", "Phone capture")}</span><strong>{fps(w.rtc.stats?.captureFps)}<small> FPS</small></strong></div>
      <div><span>{tr("手機上傳", "Phone upload")}</span><strong>{fps(w.rtc.stats?.sendFps)}<small> FPS</small></strong></div>
      <div><span>{tr("電腦收到", "Desktop receives")}</span><strong>{fps(receivedStream?.video_fps)}<small> FPS</small></strong></div>
      <div><span>{tr("定位取樣", "Recognition")}</span><strong>{fps(receivedStream?.recognition_fps)}<small> FPS</small></strong></div></div>
    <p className="mw-metric-note">{typeof w.rtc.stats?.bitrateKbps === "number" ? `${tr("實際傳輸", "Actual send")} ${(w.rtc.stats.bitrateKbps / 1000).toFixed(1)} Mbps · ` : ""}{receivedStream?.video_size?.join(" × ") ?? tr("等待電腦接收", "Waiting for desktop")}{typeof receivedStream?.recognition_ms === "number" ? ` · ${receivedStream.recognition_ms.toFixed(0)} ms` : ""}</p>
    {w.rtc.stats?.width && w.rtc.stats.height ? <p className="mw-metric-note">{tr("實際上傳", "Upload size")} {w.rtc.stats.width} × {w.rtc.stats.height}{w.rtc.stats.codec ? ` · ${w.rtc.stats.codec.replace('video/', '')}` : ""}{typeof w.rtc.stats.rttMs === "number" ? ` · RTT ${w.rtc.stats.rttMs.toFixed(0)} ms` : ""}</p> : null}
    {w.rtc.stats?.qualityLimitationReason && w.rtc.stats.qualityLimitationReason !== "none" ? <p className="mw-metric-note" role="status">{w.rtc.stats.qualityLimitationReason === "bandwidth" ? tr("目前網路頻寬限制傳輸速度", "Current network bandwidth limits the stream") : w.rtc.stats.qualityLimitationReason === "cpu" ? tr("目前手機編碼運算限制傳輸速度", "Phone encoding currently limits the stream") : tr("目前裝置正在調整傳輸品質", "The device is adapting stream quality")}</p> : null}
    {w.rtc.stats?.parameterStatus === "unsupported" ? <p className="mw-metric-note">{tr("Safari 未提供碼率控制，請依實際傳輸數值確認畫質。", "Safari bitrate controls are unavailable; use the actual readings to verify quality.")}</p> : null}
    <small className="mw-explainer">{tr("流暢／標準／高畫質的碼率上限為 3／8／12 Mbps；實際速度依網路調整。", "Smooth / Standard / High caps are 3 / 8 / 12 Mbps; actual rates adapt to the network.")}</small>
    <p className="mw-footnote">{tr("橫拍與直拍都保留完整影格，不拉伸、不裁切；GPIO 引導拍照會另做照片定位。", "Portrait and horizontal photos keep the full frame without stretching or cropping. GPIO guidance photos receive separate localization.")}</p>
    </div></details></div></details>
    </div>
  </div>;
}

function PhotoOverlay({ capture, wireId, natural, scale }: { capture: MobileCapture; wireId: string | null; natural: [number, number] | null; scale: number }) {
  const tr = useMobileText();
  const geometry = mobilePhotoGeometry(capture, wireId, natural);
  if (!geometry) return null;
  const [width, height] = capture.video_size;
  const radius = 3.5 / scale, fontSize = 11 / scale;
  const { wire, boardPin, componentPin } = geometry;
  return <svg className="mw-photo-overlay" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={tr("同一張照片的板卡、GPIO 與目前接線", "Board, GPIO and selected wire on this photograph")}>
    {geometry.objects.map(object => { const outline = object.outline ?? object.localization.raw_outline_px; return <g key={object.objectId} className={object.localization.status === "located" ? "is-located" : "is-uncertain"}>
      {outline ? <><polygon points={outline.map(point => point.join(",")).join(" ")} /><text x={Math.max(fontSize, Math.min(width - fontSize * 12, Math.min(...outline.map(point => point[0]))))} y={Math.max(fontSize * 1.5, Math.min(...outline.map(point => point[1])) - fontSize)} fontSize={fontSize}>{mobileObjectName(object.objectId)}</text></> : null}
      {object.pins.map(pin => <circle key={pin.id} cx={pin.x} cy={pin.y} r={radius}><title>{pin.id}</title></circle>)}
    </g>; })}
    {wire?.connection_kind === "direct" && boardPin && componentPin ? <line className="mw-wire-line" x1={boardPin.x} y1={boardPin.y} x2={componentPin.x} y2={componentPin.y} /> : null}
    {[boardPin ? { pin: boardPin, label: wire!.board_pin } : null, componentPin ? { pin: componentPin, label: wire!.component_pin } : null].map((target, index) => target ? <g className="mw-pin-selected" key={index}><circle cx={target.pin.x} cy={target.pin.y} r={radius * 2.2} />
      <text x={Math.max(fontSize, Math.min(width - fontSize * (target.label.length + 1) * .62, target.pin.x + radius * 2.6))} y={Math.max(fontSize * 1.3, Math.min(height - fontSize, target.pin.y - radius * 3))} fontSize={fontSize}>{target.label}</text></g> : null)}
  </svg>;
}

function reasonText(reason: string, tr: ReturnType<typeof useMobileText>) {
  const labels: Record<string, [string, string]> = {
    model_missing: ["照片未辨識到物件", "Object not detected"], model_unavailable: ["定位模型尚未就緒", "Localization model is not ready"],
    localization_not_validated: ["座標尚未確認", "Coordinates are not confirmed"], j8_rows_unverified: ["Pi 排針接點仍不夠清楚", "Pi header contacts are not clear enough"],
    ambiguous_rows: ["兩排接點無法清楚區分", "The two contact rows are ambiguous"], four_visible_pcb_rings_required: ["需要清楚看到四個固定孔", "Four clear mounting holes are needed"],
    invalid_or_clipped_geometry: ["板卡未完整入鏡", "The board is cropped"], geometry_unverified: ["板框與方向尚未確認", "Board outline and orientation are unconfirmed"],
    board_geometry_unverified: ["Pi 板框與方向尚未確認，請讓四個固定孔清楚入鏡", "Pi outline and orientation are unconfirmed; keep all four mounting holes clear"],
    component_reference_unverified: ["零件方向與腳位尚未確認，請靠近並避免反光", "Module orientation and pins are unconfirmed; move closer and avoid glare"],
    tft_geometry_unverified: ["TFT 固定孔或方向不清楚", "TFT mounting holes or orientation are unclear"],
    hc_geometry_unverified: ["超音波模組細節不夠清楚", "Ultrasonic module details are unclear"],
    weak_distributed_support: ["可用細節太少，請調整距離或光線", "Too few details; adjust distance or lighting"], local_geometry_error: ["定位未完成，請重新拍照", "Localization did not finish; take another photo"],
  };
  const value = labels[reason]; return value ? tr(...value) : reason.replace(/_/g, " ");
}

export function MobileWebPhoto({ w, onAsk, onCheck }: { w: Workspace; onAsk: (id: string) => void; onCheck: (scope: "one" | "all", id: string, wireId?: string) => void }) {
  const tr = useMobileText();
  const capture = w.capture;
  const frame = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ width: 320, height: 400 });
  const [zoom, setZoom] = useState(1);
  const [loaded, setLoaded] = useState<{ capture: string; url: string; natural: [number, number] } | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  useLayoutEffect(() => {
    const element = frame.current; if (!element) return;
    const measure = () => setViewport({ width: element.clientWidth, height: element.clientHeight });
    measure(); const observer = new ResizeObserver(measure); observer.observe(element); return () => observer.disconnect();
  }, [capture?.capture_id]);
  useEffect(() => { setZoom(1); setImageFailed(false); if (frame.current) frame.current.scrollTo(0, 0); }, [capture?.capture_id, w.captureImageUrl]);
  const natural = capture && loaded?.capture === capture.capture_id && loaded.url === w.captureImageUrl ? loaded.natural : null;
  const valid = capture && mobilePhotoMatches(capture, natural);
  const layout = capture ? mobilePhotoLayout(capture.video_size, viewport.width, viewport.height, zoom) : null;
  const wireIndex = capture ? Math.max(0, capture.wires.findIndex(item => item.wire_id === w.session?.view.wire_id)) : 0;
  const wire = capture?.wires[wireIndex];
  const mismatch = natural && !valid;
  const previousContext = Boolean(capture && capture.context_id !== w.session?.context_id);
  const source = capture ? mobilePhotoSource(capture) : null;
  return <div className="mw-page mw-photo-page"><div className="mw-page-heading"><div><span className="mw-eyebrow">PHOTO WORKSPACE</span><h2>{tr("在照片上，找到接點", "Find the contacts in your photo")}</h2></div></div>
    {w.captureJob ? <div className="mw-notice" role="status"><strong>{w.busy ? tr("正在上傳與定位…", "Uploading and localizing…") : tr("照片尚未完成", "Photo is not finished")}</strong><p>{w.captureJob.attachment.name} · {Math.round((w.captureJob.attachment.progress ?? 0) * 100)}%</p>
      {w.captureJob.error ? <p>{w.captureJob.error}</p> : null}<div className="mw-row"><button type="button" className="mw-quiet" disabled={w.busy || w.captureJob.ticket.context_id !== w.session?.context_id} onClick={() => void w.retryCapture()}>{tr("重試", "Retry")}</button><button type="button" className="mw-quiet" disabled={w.busy} onClick={() => w.discardCapture()}>{tr("移除", "Remove")}</button></div></div> : null}
    {!capture ? <div className="mw-empty" role={w.busy ? "status" : undefined}><Symbol name="photo" /><h3>{w.busy ? tr("正在準備正式照片…", "Preparing the saved photograph…") : tr("清晰照片，讓接線更好找", "A clear photo makes wiring easier")}</h3><p>{w.busy ? tr("正在讀取原圖，接著會上傳並重新定位 GPIO。", "Reading the original photo before upload and fresh GPIO localization.") : tr("先到「串流」完成拍照。照片與選取的接線會同步顯示在電腦。", "Capture a photo from Stream. The photo and selected wire are shared with your desktop.")}</p></div> : <>
      {previousContext ? <div className="mw-notice">{tr("這是先前專案版本的照片，可繼續檢視；請重新拍照後再核對。", "This photograph belongs to an earlier project version. You can review it; take a new photo before checking.")}</div> : null}
      <div className="mw-photo-toolbar"><span>{capture.video_size.join(" × ")}</span><div><button type="button" className="mw-icon-button" disabled={zoom <= 1} onClick={() => setZoom(value => Math.max(1, value / 1.4))} aria-label={tr("縮小照片", "Zoom out")}>−</button><output>{Math.round(zoom * 100)}%</output><button type="button" className="mw-icon-button" disabled={zoom >= 6} onClick={() => setZoom(value => Math.min(6, value * 1.4))} aria-label={tr("放大照片", "Zoom in")}>+</button><button type="button" className="mw-quiet" onClick={() => setZoom(1)}>{tr("適合視窗", "Fit")}</button></div></div>
      <p className="mw-footnote">{capture.capture_source === "phone_frame" ? tr("手機本地串流照片", "Phone local camera frame") : capture.capture_source === "desktop_stream" ? tr("筆電截取手機影像", "Desktop capture of phone stream") : tr("手機相機原圖", "Phone camera photo")}{tr(" · 已保存至筆電", " · Saved on desktop")}{w.rtc.stream ? tr(" · 相機串流仍持續", " · Camera streaming continues") : ""}</p>
      <div ref={frame} className="mw-photo-viewport" aria-label={tr("可縮放拖曳的正式照片", "Zoomable and scrollable saved photo")}>
        {layout && w.captureImageUrl ? <div className="mw-photo-plane" style={{ width: layout.width, height: layout.height, minWidth: layout.width, minHeight: layout.height }}>
          <img src={w.captureImageUrl} alt={tr("正式接線照片", "Saved wiring photograph")} draggable={false} onLoad={event => { setImageFailed(false); setLoaded({ capture: capture.capture_id, url: w.captureImageUrl!, natural: [event.currentTarget.naturalWidth, event.currentTarget.naturalHeight] }); }} onError={() => { setLoaded(null); setImageFailed(true); }} />
          {valid ? <PhotoOverlay capture={capture} natural={natural} wireId={wire?.wire_id ?? null} scale={layout.scale} /> : null}
        </div> : <p>{tr("正在讀取照片…", "Loading photograph…")}</p>}
      </div>
      <p className="mw-footnote">{tr("放大後可滑動照片；接線選擇與電腦同步，縮放只影響此畫面。", "Scroll after zooming. Wire selection is shared; zoom stays on this device.")}</p>
      {source?.originalSize ? <p className="mw-footnote">{tr("拍攝原圖", "Original photo")} {source.originalSize.join(" × ")}{source.analysisLimited ? tr(" · 此處顯示供定位使用的等比例分析圖", " · This view uses the proportional analysis image") : ""}</p> : null}
      {w.imageError || imageFailed || mismatch ? <div className="mw-notice mw-error" role="alert"><p>{mismatch ? tr("照片尺寸與定位資料不一致，尚未顯示 GPIO。", "Image dimensions do not match the geometry; GPIO is hidden.") : w.imageError || tr("照片讀取失敗", "Could not load the photo")}</p><button type="button" className="mw-quiet" onClick={() => void w.retryCaptureImage()}>{tr("重新讀取", "Reload photo")}</button></div> : null}
      {wire ? <section className="mw-wire-card"><div className="mw-wire-heading"><span>{tr("目前接線", "Current wire")}</span><strong>{wireIndex + 1} / {capture.wires.length}</strong></div>
        <label className="mw-sr-only" htmlFor="mw-wire">{tr("選擇接線", "Select wire")}</label><select id="mw-wire" value={wire.wire_id} onChange={event => void w.selectWire(event.target.value)}>{capture.wires.map((item, index) => <option value={item.wire_id} key={item.wire_id}>{index + 1}. {mobileObjectName(item.component_id)} · {item.component_pin} → {item.board_pin}</option>)}</select>
        <div className="mw-wire-endpoints"><span>{mobileObjectName(wire.component_id)}<strong>{wire.component_pin}</strong></span><Symbol name="arrow" /><span>Raspberry Pi 5<strong>{wire.board_pin}</strong></span></div>
        {wire.connection_kind === "divider" ? <p className="mw-footnote">{tr("此步包含分壓接線，照片只標示兩端接點。", "This step uses a divider; the photo marks its endpoints.")}</p> : null}
        <nav className="mw-row" aria-label={tr("照片接線步驟", "Photo wiring steps")}><button type="button" className="mw-button mw-secondary" disabled={wireIndex === 0} onClick={() => void w.selectWire(capture.wires[wireIndex - 1].wire_id)}>{tr("上一條", "Previous")}</button><button type="button" className="mw-button mw-secondary" disabled={wireIndex === capture.wires.length - 1} onClick={() => void w.selectWire(capture.wires[wireIndex + 1].wire_id)}>{tr("下一條", "Next")}</button></nav>
      </section> : null}
      {mobilePhotoReasons(capture).length ? <div className="mw-localization-notes"><strong>{tr("還需要更清楚的地方", "Areas needing a clearer view")}</strong>{mobilePhotoReasons(capture).map(item => <p key={item.id}><span>{mobileObjectName(item.id)}</span>{reasonText(item.reason, tr)}</p>)}</div> : null}
      <div className="mw-photo-actions"><button type="button" className="mw-button mw-primary" disabled={!valid || w.busy || previousContext} onClick={() => onAsk(capture.capture_id)}>{tr("詢問這張照片", "Ask about this photo")}</button>
        <div className="mw-row"><button type="button" className="mw-button mw-secondary" disabled={!valid || w.busy || previousContext || !wire} onClick={() => onCheck("one", capture.capture_id, wire?.wire_id)}>{tr("核對這條線", "Check this wire")}</button><button type="button" className="mw-button mw-secondary" disabled={!valid || w.busy || previousContext || !capture.wires.length} onClick={() => onCheck("all", capture.capture_id)}>{tr("核對全部", "Check all wires")}</button></div></div>
    </>}
  </div>;
}

export function MobileWebSurface({ workspace: w, httpsUrl }: { workspace: Workspace; httpsUrl?: string }) {
  const tr = useMobileText();
  const photoAlbum = useMobileWiringAlbum({ contextId: w.session?.context_id, conversationId: w.conversation?.id,
    epoch: w.conversation?.context_epoch, review: w.wiringReview });
  const [code, setCode] = useState(() => mobilePairingCode(typeof window === "undefined" ? "" : window.location.search));
  const [tab, setTab] = useState<MobileTab>("chat");
  const [infoExpanded, setInfoExpanded] = useState(false);
  const [pairingBusy, setPairingBusy] = useState(false);
  const latestCapture = useRef<string | null>(null);
  useEffect(() => { if (w.capture?.capture_id && w.capture.capture_id !== latestCapture.current) { latestCapture.current = w.capture.capture_id; setTab("photo"); } }, [w.capture?.capture_id]);
  function navigate(next: MobileTab) { setTab(next); }
  const aiBusy = w.busy || w.conversation?.jobs.some(job => job.status === "running");
  const changed = w.session?.available_context && w.session.available_context.context_id !== w.session.context_id;
  const tabs: MobileTab[] = w.capture || w.session?.view?.capture_id || tab === "photo" ? ["chat", "camera", "photo"] : ["chat", "camera"];
  return <div className="mobile-web-app" data-tab={tab} data-camera-layout={w.ready && w.pairing && tab === "camera" ? "active" : undefined}>
    {!w.ready ? <div className="mw-loading" role="status">Tinkro · {tr("正在載入…", "Loading…")}</div> : !w.pairing ? <main className="mw-connect">
      <div className="mw-connect-header"><div className="mw-brand-mark"><img src="/brand/tinkro-dark.png" alt={tr("Tinkro", "Tinkro")} width={128} height={40} /></div><MobileLanguageSwitch /></div><span className="mw-eyebrow">TINKRO / MOBILE WORKSPACE</span><h1>{tr("把鏡頭，\n接上你的作品。", "Connect your camera.\nContinue your project.")}</h1>
      <p>{tr("與電腦共用聊天、串流與 GPIO 照片。", "Share your conversation, stream and GPIO photos with your desktop.")}</p>
      {!w.secureContext ? <SecureEntry url={httpsUrl} /> : null}
      <form className="mw-pair-form" onSubmit={event => { event.preventDefault(); if (pairingBusy) return; setPairingBusy(true); void w.pair(code).finally(() => setPairingBusy(false)); }}>
        <label htmlFor="mw-pair-code">{tr("電腦上的六位配對碼", "Six-digit code from your desktop")}</label>
        <input id="mw-pair-code" value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" onChange={event => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder={tr("輸入配對碼", "Enter pairing code")} />
        <button type="submit" className="mw-button mw-primary" disabled={pairingBusy || code.length !== 6}>{pairingBusy ? tr("正在連接…", "Connecting…") : tr("連接工作區", "Connect workspace")}<Symbol name="arrow" /></button>
      </form><p className="mw-connect-help">{tr("在電腦 Tinkro 聊天區按「連接手機」。兩台裝置請使用同一個 Wi-Fi。", "Choose Connect phone in desktop Tinkro. Keep both devices on the same Wi-Fi.")}</p>
      {w.error ? <div className="mw-notice mw-error" role="alert">{w.error}</div> : null}
    </main> : <>
      <header className="mw-header"><div className="mw-wordmark"><img src="/brand/tinkro-dark.png" alt={tr("Tinkro", "Tinkro")} width={100} height={32} /></div><div className="mw-project-title"><strong>{w.session?.title ?? tr("正在連接工作區", "Connecting workspace")}</strong><span><i className={w.connected ? "is-online" : ""} />{w.connected ? tr("已與電腦同步", "Synced with desktop") : tr("重新連接中", "Reconnecting")}</span></div>
        {tab === "camera" ? <MobileLanguageSwitch /> : null}
        {tab !== "camera" ? <button type="button" className="mw-quiet mw-info-toggle" aria-expanded={infoExpanded} aria-controls="mw-session-details"
          aria-label={infoExpanded ? tr("收合工作區資訊", "Collapse workspace details") : tr("展開工作區資訊與語言", "Expand workspace details and language")}
          title={tr("工作區資訊與語言", "Workspace details and language")} onClick={() => setInfoExpanded(value => !value)}><Symbol name="chevron" /></button> : null}
        <button type="button" className="mw-quiet mw-disconnect" onClick={() => void w.disconnect()}>{tr("離線", "Disconnect")}</button></header>
      <div id="mw-session-details" className="mw-session-status" hidden={!infoExpanded || tab === "camera"}><div className="mw-session-info"><span>{aiBusy ? tr("Tinkro 處理中", "Tinkro is working") : tr("共用同一份對話", "One shared conversation")}</span><span>{w.rtc.stream ? w.rtc.publishing === false ? tr("手機本地預覽", "Local camera preview") : tr("相機串流中", "Camera streaming") : w.session?.context?.stage === "guide" ? tr("接線", "Wiring") : w.session?.context?.stage === "deploy" ? tr("程式與輸出", "Code & output") : tr("設計", "Design")}</span></div>{tab !== "camera" ? <MobileLanguageSwitch /> : null}</div>
      {changed ? <div className="mw-context-notice"><span>{tr("電腦已更新工作區", "Desktop workspace updated")}<strong>{w.session?.available_context?.title}</strong></span><button type="button" className="mw-quiet" disabled={w.busy} onClick={() => void w.join()}>{tr("加入目前作品", "Join current project")}</button></div> : null}
      {w.error ? <div className="mw-global-error" role="alert">{w.error}</div> : null}
      <main className="mw-main">{tab === "chat" ? <ChatView w={w} photoAlbum={photoAlbum} onCamera={() => navigate("camera")} onPhoto={id => { navigate("photo"); void w.openCapture(id); }} />
        : tab === "camera" ? <MobileWebCamera w={w} httpsUrl={httpsUrl} onCaptured={() => setTab("photo")} onDebugCaptured={() => setTab("chat")} />
          : <MobileWebPhoto w={w} onAsk={id => { navigate("chat"); void w.send({ text: tr("請說明這張照片目前的接線狀況與下一步。", "Describe the wiring in this photograph and the next step."), capture_id: id }); }}
            onCheck={(scope, id, wireId) => { navigate("chat"); void w.send({ text: scope === "one" ? tr("請核對這張照片中的這條接線。", "Check the selected wire in this photograph.") : tr("請核對這張照片中的全部接線。", "Check all wiring in this photograph."), capture_id: id, check_scope: scope, ...(wireId ? { wire_id: wireId } : {}) }); }} />}</main>
      <nav className="mw-tabs" aria-label={tr("手機工作區", "Mobile workspace")}>{tabs.map(item => <button type="button" key={item} aria-current={tab === item ? "page" : undefined} onClick={() => navigate(item)}><Symbol name={item} /><span>{item === "chat" ? tr("對話", "Chat") : item === "camera" ? tr("串流", "Stream") : tr("GPIO 照片", "GPIO photo")}</span>{item === "photo" && w.capture ? <i /> : null}</button>)}</nav>
    </>}
  </div>;
}

export function MobileWebApp({ httpsUrl }: { httpsUrl?: string }) { return <MobileWebSurface workspace={useMobileBrowser()} httpsUrl={httpsUrl} />; }
export default MobileWebApp;
