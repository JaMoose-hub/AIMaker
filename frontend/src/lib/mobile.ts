import { useCallback, useEffect, useRef, useState } from "react";
import type { AssistantController, AssistantConversation } from "./assistant";
import { acceptPhotoCapture, type PhotoCapture } from "./photoWiring";
import { preferBrowserH264 } from "./mobileBrowserRtc";
import { requestLowJitterBuffer } from "./mobileViewerStats";
import { receivePhoneRecognition, type MobileRecognition } from "./mobileRecognition";

export type MobileContext = AssistantController["mobileContext"];
export interface MobilePairing { code: string; qr_payload: string | Record<string, unknown>; expires_at: number | string; base_urls: string[]; base_url?: string; web_url?: string | null }
export interface MobileWebConfiguration { available: boolean; base_url: string | null; web_url: string | null; certificate_profile_url: string; certificate_url: string }
/** Normalize an explicit address without inferring it from a historical session. */
export function mobileAddressOrigin(address: string | null | undefined): string | null {
  try {
    const url = new URL(address ?? "");
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.origin : null;
  } catch { return null; }
}
export function mobileWebOrigin(configuration: MobileWebConfiguration | null | undefined): string | null {
  const origin = configuration?.available ? mobileAddressOrigin(configuration.base_url) : null;
  return origin?.startsWith("https://") ? origin : null;
}
export function mobilePairingAtOrigin(pairing: MobilePairing | null, origin: string | null): boolean {
  if (!pairing || !origin) return false;
  const address = pairing.web_url || pairing.base_url;
  return mobileAddressOrigin(address) === origin;
}
export interface MobileStream {
  active: boolean; generation: number; publisher_connected?: boolean;
  state: "finding" | "hold_still" | "locked"; can_capture: boolean; reason?: string;
  preview_seq?: number; objects?: unknown[];
  recognition?: MobileRecognition | null;
  publisher_codec?: string | null; viewer_codecs?: string[]; codec_source?: "negotiated_sdp";
  bitrate_kbps?: number;
  publisher_stats?: { generation?: number; capture_fps?: number | null; send_fps?: number | null; send_bitrate_kbps?: number | null;
    width?: number | null; height?: number | null; rtt_ms?: number | null; quality_limitation_reason?: string | null; reported_at?: number } | null;
  server_metrics?: { updated_at?: number; latency_scope?: "server_processing_not_end_to_end"; viewer_transports?: {
    codec?: string | null; target_bitrate_kbps?: number | null; send_bitrate_kbps?: number | null; encode_ms?: number | null;
    clone_ms?: number | null; send_fps?: number | null; encode_fps?: number | null;
    encoder_policy?: string | null; encoder_fallback_reason?: string | null }[] } | null;
  valid_for_ms?: number; video_fps?: number | null; recognition_fps?: number | null; recognition_ms?: number | null;
  video_received_at?: number | null; video_receive_seq?: number; video_receive_age_ms?: number | null; video_receive_fresh?: boolean;
  model_runtime?: Record<string, { available?: boolean; actual_backend?: string; requested_backend?: string; providers?: string[] }>;
  quality?: { fps?: number; received_fps?: number; [key: string]: unknown };
}
export interface MobileSession {
  session_id: string; conversation_id: string; context_id: string; title: string; base_url: string;
  context: MobileContext; stream: MobileStream;
  view: { capture_id: string | null; wire_id: string | null; revision: number };
  available_context?: { context_id: string; conversation_id?: string; title?: string } | null;
}
/** Status-only identity. It cannot authorize photos, wiring or a camera switch. */
export type MobileConnection = Pick<MobileSession, "session_id" | "conversation_id" | "context_id" | "title">;
export type MobileCapture = PhotoCapture & {
  asset_id: string; context_id: string; original_size?: [number, number]; analysis_limited?: boolean;
  capture_source?: "camera_photo" | "phone_frame" | "desktop_stream";
  stream_identity?: { session_id: string; generation: number; frame_seq: number; received_monotonic: number; received_at: number };
};
export interface MobileStreamCaptureRequest { session_id: string; generation: number; context_id: string; request_id: string }

/** Follow a reconnected phone only while its desktop view remains selected. */
export function followMobileSource(previous: string | null, session: MobileSession | null, selected: boolean, canChange: boolean) {
  if (!selected) return { key: null, reselect: false };
  if (!session) return { key: previous, reselect: false };
  const key = `${session.session_id}:${session.context_id}:${session.stream.generation}`;
  if (previous === null) return { key, reselect: false };
  if (previous === key || !canChange || !mobileVideoFresh(session.stream)) return { key: previous, reselect: false };
  return { key, reselect: true };
}
export type MobileCheckScope = "one" | "all";
export const mobileError = (error: unknown) => error instanceof Error ? error.message : String(error);
/** Receipt time is independent of recognition/Locked and expires even if status delivery stops. */
export function mobileVideoAgeMs(stream: MobileStream | null | undefined, nowMs = Date.now()): number | null {
  if (typeof stream?.video_received_at !== "number" || !Number.isFinite(stream.video_received_at) || stream.video_received_at <= 0) return null;
  const localAge = nowMs - stream.video_received_at * 1000;
  if (!Number.isFinite(localAge) || localAge < -1500) return null;
  return Math.max(0, localAge, typeof stream.video_receive_age_ms === "number" ? stream.video_receive_age_ms : 0);
}
export function mobileVideoFresh(stream: MobileStream | null | undefined, nowMs = Date.now()): boolean {
  const age = mobileVideoAgeMs(stream, nowMs);
  return Boolean(stream?.active && stream.video_receive_fresh === true && age !== null && age <= 1500);
}
export type MobilePreviewLease = { key: string; deadline: number };
/** Repeated snapshots of one sample can shorten its lifetime, never renew it. */
export function mobilePreviewLease(session: MobileSession | null, now: number, previous: MobilePreviewLease): MobilePreviewLease {
  const stream = session?.stream;
  const key = `${session?.session_id ?? ""}:${stream?.generation ?? 0}:${stream?.preview_seq ?? 0}`;
  if (!stream?.active || !stream.publisher_connected) return { key, deadline: 0 };
  const ttl = Math.max(0, Math.min(1500, stream.valid_for_ms ?? 0));
  return { key, deadline: key === previous.key ? Math.min(previous.deadline, now + ttl) : now + ttl };
}
export function mobileModelRuntime(stream: MobileStream) {
  const models = Object.values(stream.model_runtime ?? {});
  const available = models.filter(model => model.available === true);
  const cuda = available.filter(model => model.actual_backend === "cuda" || (model.actual_backend === undefined && model.providers?.[0] === "CUDAExecutionProvider"));
  return { total: models.length, available: available.length, cuda: cuda.length };
}

export async function mobileRequest<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal; cache?: RequestCache } = {}): Promise<T> {
  const response = await fetch(`/api/mobile/${path}`, { method: options.method ?? "GET", signal: options.signal,
    ...(options.cache ? { cache: options.cache } : {}),
    headers: { Accept: "application/json", ...(options.body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  if (!response.ok) {
    let detail = "";
    try { const value = await response.json(); detail = typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail ?? value.error ?? ""); } catch { /* Retain HTTP status. */ }
    throw new Error(`${response.status}${detail ? ` · ${detail}` : ""}`);
  }
  return response.status === 204 ? undefined as T : response.json();
}

/** Same frozen geometry checks as the photo PoC, with the mobile image route. */
export function acceptMobileCapture(capture: MobileCapture): boolean {
  if (!capture?.asset_id || !capture.context_id || !Array.isArray(capture.components) || !Array.isArray(capture.wires)) return false;
  const photoPath = `/api/photo-wiring/captures/${encodeURIComponent(capture.capture_id)}/image`;
  const mobilePath = `/api/mobile/captures/${encodeURIComponent(capture.capture_id)}/image`;
  const assetPath = `/api/mobile/assets/${encodeURIComponent(capture.asset_id)}/file`;
  if (capture.image_url !== photoPath && capture.image_url !== mobilePath && capture.image_url !== assetPath) return false;
  return acceptPhotoCapture({ ...capture, image_url: photoPath }, capture.session_id, {
    catalog_version: "mobile", profile_versions: {},
    component_ids: capture.components.map(pose => pose.component_id), wires: capture.wires,
  });
}

const streamCaptureOwner = (session: MobileSession | null) => session
  ? JSON.stringify([session.session_id, session.stream.generation, session.context_id]) : "";
type StreamCaptureJob = { owner: string; request: MobileStreamCaptureRequest; pending: boolean; error: string };

/** Save the backend's original phone frame; retries retrieve the same capture, never a new frame. */
export function useDesktopStreamCapture(session: MobileSession | null, onCapture: (capture: MobileCapture) => void,
  request: typeof mobileRequest = mobileRequest) {
  const owner = streamCaptureOwner(session);
  const latest = useRef({ session, owner, onCapture }); latest.current = { session, owner, onCapture };
  const [job, setJob] = useState<StreamCaptureJob | null>(null);
  const jobRef = useRef(job);
  const flight = useRef<{ owner: string; abort: AbortController } | null>(null);
  useEffect(() => {
    if (jobRef.current?.owner !== owner) { jobRef.current = null; setJob(null); }
    return () => {
      if (flight.current?.owner === owner) { flight.current.abort.abort(); flight.current = null; }
    };
  }, [owner]);

  async function submit(retry: boolean) {
    const current = latest.current;
    if (!current.session || flight.current) return;
    const previous = jobRef.current;
    if (retry ? !previous || previous.pending || previous.owner !== current.owner
      : !current.session.stream.active || !current.session.stream.publisher_connected) return;
    const body = retry ? previous!.request : { session_id: current.session.session_id,
      generation: current.session.stream.generation, context_id: current.session.context_id, request_id: crypto.randomUUID() };
    const operation = { owner: current.owner, abort: new AbortController() };
    flight.current = operation;
    const update = (next: StreamCaptureJob | null) => { jobRef.current = next; setJob(next); };
    update({ owner: current.owner, request: body, pending: true, error: "" });
    let timedOut = false;
    let onAbort = () => {};
    const cancelled = new Promise<never>((_resolve, reject) => {
      onAbort = () => reject(new Error(timedOut ? "mobile_capture_timeout" : "mobile_capture_cancelled"));
      operation.abort.signal.addEventListener("abort", onAbort, { once: true });
    });
    const timeout = setTimeout(() => { timedOut = true; operation.abort.abort(); }, 180_000);
    try {
      // The local deadline also settles a transport that does not reject promptly on abort.
      const capture = await Promise.race([request<MobileCapture>("stream-capture", { method: "POST", body, signal: operation.abort.signal }), cancelled]);
      if (timedOut) throw new Error("mobile_capture_timeout");
      if (operation.abort.signal.aborted || flight.current !== operation || latest.current.owner !== current.owner) return;
      if (!acceptMobileCapture(capture) || capture.session_id !== body.session_id || capture.context_id !== body.context_id
        || (capture.stream_identity && (capture.stream_identity.session_id !== body.session_id || capture.stream_identity.generation !== body.generation))) {
        throw new Error("mobile_capture_context_mismatch");
      }
      update(null);
      latest.current.onCapture(capture);
    } catch (cause) {
      if ((!operation.abort.signal.aborted || timedOut) && flight.current === operation && latest.current.owner === current.owner) {
        update({ owner: current.owner, request: body, pending: false, error: timedOut ? "mobile_capture_timeout" : mobileError(cause) });
      }
    } finally {
      clearTimeout(timeout); operation.abort.signal.removeEventListener("abort", onAbort);
      if (flight.current === operation) flight.current = null;
    }
  }
  const currentJob = job?.owner === owner ? job : null;
  return { busy: currentJob?.pending ?? false, error: currentJob?.error ?? "",
    capture: () => submit(false), retry: () => submit(true) };
}

export function mobileStateForConversation(value: unknown, conversationId: string): MobileSession | null | undefined {
  if (!value || typeof value !== "object" || !("session" in value)) return undefined;
  const session = (value as { session: MobileSession | null }).session;
  if (session === null) return null;
  return session?.conversation_id === conversationId && typeof session.session_id === "string"
    && typeof session.context_id === "string" && session.stream && session.view ? session : undefined;
}

export function mobileConnectionFromState(value: unknown): MobileConnection | null | undefined {
  if (!value || typeof value !== "object" || !("connection" in value)) return undefined;
  const connection = (value as { connection: unknown }).connection;
  if (!connection || typeof connection !== "object") return null;
  const { session_id, conversation_id, context_id, title } = connection as Partial<MobileConnection>;
  return typeof session_id === "string" && session_id.length > 0 && typeof conversation_id === "string" && conversation_id.length > 0
    && typeof context_id === "string" && context_id.length > 0 && typeof title === "string"
    ? { session_id, conversation_id, context_id, title } : null;
}

/** A slow view response must not roll back a newer phone selection. */
export function acceptMobileView(previous: MobileSession | null, sessionId: string, view: MobileSession["view"]) {
  return previous?.session_id === sessionId && view.revision >= previous.view.revision ? { ...previous, view } : previous;
}

/** A session-independent viewer never acquires a camera or a photo-PoC lease. */
export function openMobileViewer(sessionId: string, generation: number,
  onTrack: (stream: MediaStream) => void, onState: (state: RTCPeerConnectionState) => void,
  request: typeof mobileRequest = mobileRequest, makePeer = () => new RTCPeerConnection({ iceServers: [] })) {
  const peer = makePeer();
  const abort = new AbortController();
  let disposed = false;
  let cancelGather = () => {};
  const transceiver = peer.addTransceiver("video", { direction: "recvonly" });
  requestLowJitterBuffer(transceiver?.receiver);
  preferBrowserH264(peer);
  peer.ontrack = event => { if (!disposed) { requestLowJitterBuffer(event.receiver); onTrack(event.streams[0] ?? new MediaStream([event.track])); } };
  peer.onconnectionstatechange = () => { if (!disposed) onState(peer.connectionState); };
  const ready = (async () => {
    await peer.setLocalDescription(await peer.createOffer());
    if (disposed) return;
    if (peer.iceGatheringState !== "complete") await new Promise<void>(resolve => {
      let timer: ReturnType<typeof setTimeout>;
      const finish = () => { clearTimeout(timer); peer.removeEventListener("icegatheringstatechange", check); resolve(); };
      const check = () => { if (peer.iceGatheringState === "complete") finish(); };
      cancelGather = finish;
      timer = setTimeout(finish, 6000);
      peer.addEventListener("icegatheringstatechange", check);
      check();
    });
    if (disposed) return;
    const answer = await request<RTCSessionDescriptionInit>("stream/offer", { method: "POST", signal: abort.signal,
      body: { session_id: sessionId, generation, role: "viewer", type: peer.localDescription!.type, sdp: peer.localDescription!.sdp } });
    if (!disposed) await peer.setRemoteDescription(answer);
  })();
  return { peer, ready, close() { disposed = true; abort.abort(); cancelGather(); peer.ontrack = null;
    peer.onconnectionstatechange = null; peer.close(); } };
}

export function useMobileCompanion(context: MobileContext | undefined, enabled: boolean) {
  const conversationId = context?.conversation_id ?? "";
  const contextKey = context ? JSON.stringify(context) : "";
  const contextRef = useRef(context); contextRef.current = context;
  const [sessionRecord, setSession] = useState<MobileSession | null>(null);
  const session = sessionRecord?.conversation_id === conversationId ? sessionRecord : null;
  const [connectionStatus, setConnectionStatus] = useState<{ connection: MobileConnection | null | undefined; error: string }>({ connection: undefined, error: "" });
  // Older backends provide project pairing only; never infer a foreign session from it.
  const connection = !enabled ? null : connectionStatus.connection === undefined ? session : connectionStatus.connection;
  const pairedSession = useRef(session?.session_id ?? null);
  pairedSession.current = session?.session_id ?? null;
  const [pairing, setPairing] = useState<MobilePairing | null>(null);
  const [error, setError] = useState("");
  const [pairingBusy, setPairingBusy] = useState(false);
  const pairingFlight = useRef(false);
  const published = useRef("");
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const generation = useRef(0);
  const [webConfiguration, setWebConfiguration] = useState<MobileWebConfiguration | null>(null);
  const [webConfigurationError, setWebConfigurationError] = useState("");
  const configurationSerial = useRef(0);
  const configurationAbort = useRef<AbortController | null>(null);
  const manualPairingOrigin = useRef<string | null>(null);
  const refreshWebConfiguration = useCallback(async () => {
    const epoch = generation.current, serial = ++configurationSerial.current;
    configurationAbort.current?.abort();
    const abort = new AbortController(); configurationAbort.current = abort;
    const timeout = setTimeout(() => abort.abort(), 5000);
    try {
      const next = await mobileRequest<MobileWebConfiguration>("web-config", { signal: abort.signal, cache: "no-store" });
      if (epoch !== generation.current || serial !== configurationSerial.current || abort.signal.aborted) return null;
      setWebConfiguration(next); setWebConfigurationError("");
      if (!manualPairingOrigin.current) setPairing(previous => mobilePairingAtOrigin(previous, mobileWebOrigin(next)) ? previous : null);
      return next;
    } catch (cause) {
      if (epoch !== generation.current || serial !== configurationSerial.current) return null;
      setWebConfiguration(null); setWebConfigurationError(mobileError(cause));
      if (!manualPairingOrigin.current) setPairing(null);
      return null;
    } finally {
      clearTimeout(timeout);
      if (configurationAbort.current === abort) configurationAbort.current = null;
    }
  }, []);
  const publish = useCallback((force = false) => {
    const snapshot = contextRef.current;
    if (!snapshot) return Promise.reject(new Error("Workspace is not ready"));
    const key = JSON.stringify(snapshot);
    const task = queue.current.catch(() => undefined).then(async () => {
      if (!force && key === published.current) return;
      await mobileRequest("context", { method: "POST", body: snapshot });
      published.current = key;
    });
    queue.current = task;
    return task;
  }, []);

  useEffect(() => {
    generation.current += 1; published.current = ""; setSession(null); setPairing(null); setError("");
    configurationSerial.current++; configurationAbort.current?.abort(); manualPairingOrigin.current = null;
    setWebConfiguration(null); setWebConfigurationError("");
    if (!enabled || !conversationId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let socket: WebSocket | null = null;
    let socketTimer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const accept = (value: unknown) => {
      const next = mobileStateForConversation(value, conversationId);
      if (!stopped && next !== undefined) {
        const nextId = next?.session_id ?? null;
        // An existing phone's heartbeat does not consume a newly issued invitation.
        if (nextId !== pairedSession.current) setPairing(null);
        pairedSession.current = nextId; setSession(previous => receivePhoneRecognition(previous, next, performance.now())); setError("");
      }
    };
    const connect = () => {
      if (stopped) return;
      const url = new URL("/api/mobile/events", window.location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.searchParams.set("conversation_id", conversationId);
      socket = new WebSocket(url);
      socket.onmessage = event => { try { accept(JSON.parse(event.data)); } catch { /* Ignore malformed events. */ } };
      socket.onclose = () => { if (!stopped) socketTimer = setTimeout(connect, 2000); };
    };
    const poll = async () => {
      try {
        const value = await mobileRequest(`desktop-session?conversation_id=${encodeURIComponent(conversationId)}`, { signal: controller.signal });
        if (!stopped) { setConnectionStatus({ connection: mobileConnectionFromState(value), error: "" }); accept(value); }
      }
      catch (cause) { if (!stopped) { const message = mobileError(cause); setConnectionStatus({ connection: null, error: message }); setError(message); } }
      if (!stopped) timer = setTimeout(() => void poll(), 5000);
    };
    connect(); void poll();
    return () => { stopped = true; generation.current++; controller.abort(); configurationSerial.current++; configurationAbort.current?.abort();
      clearTimeout(timer); clearTimeout(socketTimer); socket?.close(); };
  }, [conversationId, enabled]);

  useEffect(() => {
    if (!enabled || !contextKey) return;
    let disposed = false;
    const timer = setTimeout(() => { void publish().catch(cause => { if (!disposed) setError(mobileError(cause)); }); }, 350);
    return () => { disposed = true; clearTimeout(timer); };
  }, [contextKey, enabled, publish]);

  async function pair(baseUrl?: string) {
    if (pairingFlight.current || !contextRef.current) return;
    pairingFlight.current = true;
    const epoch = generation.current;
    const pairedId = pairedSession.current;
    const id = contextRef.current.conversation_id;
    const manual = baseUrl?.trim() || null;
    manualPairingOrigin.current = manual ? mobileAddressOrigin(manual) : null;
    setPairing(null); setPairingBusy(true); setError("");
    try {
      const configuration = manual ? null : await refreshWebConfiguration();
      const chosen = manual || mobileWebOrigin(configuration);
      if (epoch !== generation.current) return;
      if (!chosen) throw new Error("mobile_web_https_unavailable");
      await publish(true);
      if (epoch !== generation.current) return;
      const next = await mobileRequest<MobilePairing>("pairings", { method: "POST", body: { conversation_id: id, base_url: chosen } });
      // A network change during POST must not re-expose a code for the old IP.
      const latest = manual ? null : await refreshWebConfiguration();
      if (!manual && mobileWebOrigin(latest) !== chosen) return;
      if (epoch === generation.current && pairedId === pairedSession.current && mobilePairingAtOrigin(next, mobileAddressOrigin(chosen))) setPairing(next);
    } catch (cause) { if (epoch === generation.current) setError(mobileError(cause)); }
    finally { pairingFlight.current = false; setPairingBusy(false); }
  }
  async function selectView(captureId: string, wireId: string | null) {
    if (!session) return;
    const sid = session.session_id;
    const view = await mobileRequest<MobileSession["view"]>("view", { method: "PUT", body: { session_id: sid, capture_id: captureId, wire_id: wireId } });
    setSession(previous => acceptMobileView(previous, sid, view));
  }
  async function sendPhoto(capture: MobileCapture, text: string, scope?: MobileCheckScope, wireId?: string) {
    if (!session) throw new Error("Phone is not connected");
    return mobileRequest<AssistantConversation>("messages", { method: "POST", body: {
      session_id: session.session_id, request_id: crypto.randomUUID(), text, asset_ids: [capture.asset_id],
      context_id: capture.context_id, capture_id: capture.capture_id, ...(scope ? { check_scope: scope } : {}),
      ...(wireId ? { wire_id: wireId } : {}),
    } });
  }
  return { session, connection, connectionError: enabled ? connectionStatus.error : "", pairing, pairingBusy, error,
    webConfiguration, webConfigurationError, refreshWebConfiguration, pairingManual: Boolean(manualPairingOrigin.current), pair, selectView, sendPhoto, publish };
}
