import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";
import * as ImagePicker from "expo-image-picker";
import {
  ImageManipulator,
  SaveFormat,
  type ImageRef,
} from "expo-image-manipulator";
import { File } from "expo-file-system";
import { randomUUID } from "expo-crypto";
import { ApiError, MobileApi } from "./api";
import {
  epochMs,
  draftStorageKey,
  freezeInheritedMedia,
  mergeConversation,
  previewLease,
  requiresJpegConversion,
  validateAttachments,
} from "./domain";
import { loadDraft, releaseAsset, retainAsset, saveDraft } from "./storage";
import { Publisher, type PublisherState } from "./rtc";
import type {
  Asset,
  Capture,
  CaptureJob,
  Conversation,
  LocalAsset,
  Outbox,
  Pairing,
  Session,
  Ticket,
} from "./types";
export function useWorkspace(pairing: Pairing) {
  const api = useMemo(() => new MobileApi(pairing), [pairing]);
  const draftKey = draftStorageKey(pairing.base_url, pairing.conversation_id);
  const saved = useMemo(
    () => loadDraft(draftKey, pairing.session_id),
    [draftKey, pairing.session_id],
  );
  const [session, setSession] = useState<Session | null>(null),
    [conversation, setConversation] = useState<Conversation | null>(null),
    [capture, setCapture] = useState<Capture | null>(null),
    [draft, setDraft] = useState(saved.text),
    [attachments, setAttachments] = useState(saved.attachments),
    [outbox, setOutbox] = useState(saved.outbox),
    [captureJob, setCaptureJob] = useState<CaptureJob | null>(
      saved.captureJob ?? null,
    );
  const [error, setError] = useState(""),
    [connected, setConnected] = useState(false),
    [busy, setBusy] = useState(false),
    [camera, setCamera] = useState<{
      mode: "photo" | "video";
      ticket?: Ticket;
    } | null>(null),
    [rtc, setRtc] = useState<PublisherState>({
      stream: null,
      status: "串流已停止",
    }),
    [now, setNow] = useState(Date.now()),
    [active, setActive] = useState(AppState.currentState === "active"),
    [lockDeadline, setLockDeadline] = useState(0);
  const pub = useMemo(() => new Publisher(api, setRtc), [api]);
  const alive = useRef(true),
    lease = useRef({ key: "", deadline: 0 }),
    sending = useRef(false),
    cameraOperation = useRef(false),
    lastCapture = useRef<string | null>(null),
    snapshot = useRef({ draft, attachments, outbox, captureJob, session });
  snapshot.current = { draft, attachments, outbox, captureJob, session };
  const persist = useCallback(
    (
      patch: Partial<{
        draft: string;
        attachments: LocalAsset[];
        outbox: Outbox[];
        captureJob: CaptureJob | null;
      }> = {},
    ) => {
      const value = { ...snapshot.current, ...patch };
      try {
        saveDraft(draftKey, {
          text: value.draft,
          attachments: value.attachments,
          outbox: value.outbox,
          captureJob: value.captureJob,
        });
      } catch (e) {
        setError(`無法保存草稿：${String(e)}`);
      }
    },
    [draftKey],
  );
  useEffect(() => {
    persist();
  }, [draft, attachments, outbox, captureJob, persist]);
  const acceptSession = useCallback(
    (value: Session) => {
      if (!alive.current) return;
      setSession(value);
      setConnected(true);
      lease.current = previewLease(value.stream, Date.now(), lease.current);
      setLockDeadline(lease.current.deadline);
      const id = value.view?.capture_id ?? null;
      if (id !== lastCapture.current) {
        lastCapture.current = id;
        if (!id) setCapture(null);
        else
          void api
            .request<Capture>(`/captures/${encodeURIComponent(id)}`)
            .then((c) => {
              if (alive.current && lastCapture.current === id) setCapture(c);
            })
            .catch((e) => setError(String(e)));
      }
    },
    [api],
  );
  const refresh = useCallback(async () => {
    const [s, c] = await Promise.all([
      api.request<Session>("/session"),
      api.request<Conversation>("/conversation?limit=50"),
    ]);
    acceptSession(s);
    if (alive.current)
      setConversation((previous) => mergeConversation(previous, c));
  }, [api, acceptSession]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      void pub.stop();
    };
  }, [pub]);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      setActive(state === "active");
      if (state !== "active") {
        lease.current.deadline = 0;
        setLockDeadline(0);
      }
      if (state === "background") {
        setCamera(null);
        void pub.stop();
      }
    });
    return () => sub.remove();
  }, [pub]);
  useEffect(() => {
    if (!active) return;
    const tick = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(tick);
  }, [active]);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let socket: WebSocket | undefined;
    const poll = async () => {
      try {
        await refresh();
      } catch (e) {
        if (!stopped) {
          setConnected(false);
          setLockDeadline(0);
          if (e instanceof ApiError && e.status === 401)
            setError("配對已失效，請重新配對。草稿仍保留。");
        }
      }
      if (!stopped) timer = setTimeout(() => void poll(), 1500);
    };
    void poll();
    const url = `${api.base.replace(/^http/, "ws")}/api/mobile/events?token=${encodeURIComponent(pairing.token)}`;
    socket = new WebSocket(url);
    socket.onmessage = (event) => {
      try {
        const value = JSON.parse(event.data);
        if (!stopped && value.type === "state") acceptSession(value.session);
      } catch {
        /* Polling also reconciles state after a malformed/disconnected event. */
      }
    };
    return () => {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [active, api, acceptSession, pairing.token, refresh]);
  const upload = async (
    item: LocalAsset,
    onChange: (asset: LocalAsset) => void,
  ): Promise<Asset> => {
    if (item.asset) return item.asset;
    const asset = await api.upload(item, (progress) =>
      onChange({ ...item, progress, error: undefined }),
    );
    onChange({ ...item, asset, progress: 1, error: undefined });
    return asset;
  };
  const sendItem = async (item: Outbox) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError("");
    let current = { ...item, attachments: [...item.attachments] };
    const update = () => {
      setOutbox((old) => {
        const next = old.map((o) =>
          o.payload.request_id === current.payload.request_id ? current : o,
        );
        persist({ outbox: next });
        return next;
      });
    };
    try {
      if (current.payload.context_id !== snapshot.current.session?.context_id)
        throw Error(
          "這份草稿屬於先前專案，請回到原專案再重試，或移除此待送訊息。",
        );
      const assetIds: string[] = current.attachments.length
        ? []
        : [...current.payload.asset_ids];
      for (let i = 0; i < current.attachments.length; i++) {
        const asset = await upload(current.attachments[i], (a) => {
          current = {
            ...current,
            attachments: current.attachments.map((v, n) => (n === i ? a : v)),
          };
          update();
        });
        assetIds.push(asset.id);
      }
      current = {
        ...current,
        payload: { ...current.payload, asset_ids: assetIds },
      };
      update();
      const next = await api.request<Conversation>(
        "/messages",
        "POST",
        current.payload,
      );
      setConversation((p) => mergeConversation(p, next));
      setOutbox((old) => {
        const value = old.filter(
          (o) => o.payload.request_id !== current.payload.request_id,
        );
        persist({ outbox: value });
        return value;
      });
      current.attachments.forEach(releaseAsset);
    } catch (e) {
      current = { ...current, status: "failed", error: String(e) };
      update();
      setError(String(e));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  const enqueue = async (
    options: {
      text?: string;
      capture_id?: string;
      check_scope?: "one" | "all";
      wire_id?: string;
    } = {},
  ) => {
    const s = snapshot.current;
    if (!s.session || sending.current) return;
    if (s.session.conversation_id !== pairing.conversation_id) {
      setError("已切換對話，原草稿仍保留；請完成加入或重新配對後再送出。");
      return;
    }
    const text = options.text ?? s.draft;
    const media = options.check_scope ? [] : s.attachments;
    const invalid = validateAttachments(media);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (!text.trim() && !media.length) return;
    const item: Outbox = {
      payload: {
        request_id: randomUUID(),
        text: text.trim(),
        ...freezeInheritedMedia(
          conversation,
          media.length,
          options.capture_id ?? null,
          typeof s.session.context.round === "number"
            ? s.session.context.round
            : undefined,
        ),
        context_id: s.session.context_id,
        ...options,
      },
      attachments: media,
      status: "pending",
    };
    const next = [...s.outbox, item];
    setOutbox(next);
    if (!options.check_scope) {
      setDraft("");
      setAttachments([]);
    }
    persist({
      outbox: next,
      ...(!options.check_scope ? { draft: "", attachments: [] } : {}),
    });
    await sendItem(item);
  };
  const addAsset = (asset: LocalAsset) => {
    const retained = retainAsset(asset);
    setAttachments((old) => {
      const next = [...old, retained];
      const invalid = validateAttachments(next);
      if (invalid) {
        releaseAsset(retained);
        setError(invalid);
        return old;
      }
      return next;
    });
  };
  const pick = async (type: "image" | "video") => {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: type === "image" ? ["images"] : ["videos"],
        allowsMultipleSelection: type === "image",
        selectionLimit: 4,
        quality: 1,
        videoMaxDuration: 60,
        preferredAssetRepresentationMode:
          ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
      });
      if (result.canceled) return;
      const assets = result.assets.map((a) => ({
        upload_id: randomUUID(),
        uri: a.uri,
        name: a.fileName ?? (type === "image" ? "photo.jpg" : "video.mp4"),
        mime: a.mimeType ?? (type === "image" ? "image/jpeg" : "video/mp4"),
        type,
        size: a.fileSize ?? new File(a.uri).size,
        width: a.width,
        height: a.height,
        duration: a.duration == null ? undefined : a.duration / 1000,
      }));
      const invalid = validateAttachments([
        ...snapshot.current.attachments,
        ...assets,
      ]);
      if (invalid) {
        setError(invalid);
        return;
      }
      // Compatible is requested above; still transcode if the native picker returns HEIC.
      // Process one image at a time to avoid retaining four full-resolution native bitmaps.
      for (let i = 0; i < assets.length; i++) {
        const asset = assets[i];
        if (!requiresJpegConversion(asset)) continue;
        const context = ImageManipulator.manipulate(asset.uri);
        let image: ImageRef | undefined;
        try {
          image = await context.renderAsync();
          const jpeg = await image.saveAsync({
            format: SaveFormat.JPEG,
            compress: 1,
          });
          assets[i] = {
            ...asset,
            uri: jpeg.uri,
            name: asset.name.replace(/\.[^/.]+$/, "") + ".jpg",
            mime: "image/jpeg",
            width: jpeg.width,
            height: jpeg.height,
            size: new File(jpeg.uri).size,
          };
        } finally {
          image?.release();
          context.release();
        }
      }
      setAttachments((old) => [...old, ...assets.map(retainAsset)]);
    } catch (e) {
      setError(String(e));
    }
  };
  const beginCamera = async (mode: "photo" | "video", forAnalysis = false) => {
    if (cameraOperation.current || sending.current) return;
    cameraOperation.current = true;
    setBusy(true);
    setError("");
    try {
      let ticket: Ticket | undefined;
      if (forAnalysis)
        ticket = await api.request<Ticket>("/capture-ticket", "POST");
      await pub.stop();
      if (alive.current && AppState.currentState === "active")
        setCamera({ mode, ticket });
    } catch (e) {
      setError(String(e));
    } finally {
      cameraOperation.current = false;
      setBusy(false);
    }
  };
  const finalize = async (job: CaptureJob) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    let value = job;
    try {
      // An uploaded asset may already have a completed idempotent server receipt.
      // Allow that same request to recover; the server still rejects a new expired ticket.
      if (epochMs(job.ticket.expires_at) <= Date.now() && !job.asset.asset)
        throw Error(
          "這張照片的拍攝票已逾時。請重新串流定位並拍攝，照片已保留。",
        );
      const asset = await upload(job.asset, (next) => {
        value = { ...value, asset: next };
        setCaptureJob(value);
        persist({ captureJob: value });
      });
      const result = await api.request<Capture>("/captures", "POST", {
        ticket_id: job.ticket.ticket_id,
        asset_id: asset.id,
        request_id: job.request_id,
      });
      lastCapture.current = result.capture_id;
      setCapture(result);
      setCaptureJob(null);
      persist({ captureJob: null });
      releaseAsset(job.asset);
      await refresh();
    } catch (e) {
      value = { ...value, error: String(e) };
      setCaptureJob(value);
      persist({ captureJob: value });
      setError(String(e));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  const cameraDone = (asset: LocalAsset) => {
    const ticket = camera?.ticket;
    setCamera(null);
    try {
      if (!ticket) {
        addAsset(asset);
        return;
      }
      const job = {
        ticket,
        asset: retainAsset(asset),
        request_id: randomUUID(),
      };
      setCaptureJob(job);
      persist({ captureJob: job });
      void finalize(job);
    } catch (e) {
      setError(String(e));
    }
  };
  const selectWire = async (id: string) => {
    if (!capture) return;
    try {
      await api.request("/view", "PUT", {
        capture_id: capture.capture_id,
        wire_id: id,
      });
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };
  const join = async () => {
    try {
      persist();
      await pub.stop();
      return await api.request<Session>("/join", "POST");
    } catch (e) {
      setError(String(e));
      return null;
    }
  };
  const older = async () => {
    if (conversation?.before == null) return;
    try {
      const c = await api.request<Conversation>(
        `/conversation?before=${conversation.before}&limit=50`,
      );
      setConversation((p) => mergeConversation(p, c));
    } catch (e) {
      setError(String(e));
    }
  };
  return {
    api,
    session,
    conversation,
    capture,
    draft,
    setDraft,
    attachments,
    outbox,
    captureJob,
    error,
    setError,
    connected,
    busy,
    camera,
    setCamera,
    rtc,
    canCapture:
      connected &&
      Boolean(session?.stream.can_capture) &&
      now < lockDeadline &&
      Boolean(rtc.stream),
    startStream: async () => {
      if (cameraOperation.current || sending.current || camera) return;
      cameraOperation.current = true;
      setBusy(true);
      try {
        await pub.start();
      } catch (e) {
        setError(String(e));
      } finally {
        cameraOperation.current = false;
        setBusy(false);
      }
    },
    stopStream: () => pub.stop(),
    beginCamera,
    cameraDone,
    pick,
    enqueue,
    retry: sendItem,
    retryCapture: () => captureJob && finalize(captureJob),
    discardCapture: () => {
      if (captureJob) releaseAsset(captureJob.asset);
      setCaptureJob(null);
    },
    removeAttachment: (id: string) =>
      setAttachments((old) =>
        old.filter((a) => {
          if (a.upload_id === id) {
            releaseAsset(a);
            return false;
          }
          return true;
        }),
      ),
    discardOutbox: (id: string) =>
      setOutbox((old) =>
        old.filter((o) => {
          if (o.payload.request_id === id) {
            o.attachments.forEach(releaseAsset);
            return false;
          }
          return true;
        }),
      ),
    selectWire,
    openCapture: async (id: string) => {
      try {
        await api.request("/view", "PUT", { capture_id: id, wire_id: null });
        await refresh();
      } catch (e) {
        setError(String(e));
      }
    },
    join,
    older,
    refresh,
  };
}
