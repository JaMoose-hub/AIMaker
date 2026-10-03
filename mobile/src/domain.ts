import type {
  Capture,
  Conversation,
  LocalAsset,
  Pose,
  StreamStatus,
} from "./types";
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024;
export function requiresJpegConversion(
  asset: Pick<LocalAsset, "type" | "mime" | "name" | "uri">,
): boolean {
  return (
    asset.type === "image" &&
    (/image\/(heic|heif|avif)(?:$|[-;])/i.test(asset.mime) ||
      /\.(heic|heif|avif)(?:$|[?#])/i.test(asset.name) ||
      /\.(heic|heif|avif)(?:$|[?#])/i.test(asset.uri))
  );
}
export function normalizeBase(value: string): string {
  const url = new URL(value.trim());
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw Error("請輸入 http:// 或 https:// 電腦位址");
  url.hash = "";
  url.search = "";
  url.pathname = url.pathname
    .replace(/\/api\/mobile\/?$/, "")
    .replace(/\/$/, "");
  return url.toString().replace(/\/$/, "");
}
export function draftStorageKey(baseUrl: string, conversationId: string) {
  return `${encodeURIComponent(normalizeBase(baseUrl))}_${encodeURIComponent(conversationId)}`;
}
export function parsePairingQr(value: string): {
  base_url: string;
  code: string;
} {
  const data = JSON.parse(value);
  if (
    data.type !== "tinkro-mobile" ||
    typeof data.code !== "string" ||
    !data.code.trim()
  )
    throw Error("這不是 Tinkro 配對 QR");
  return { base_url: normalizeBase(data.base_url), code: data.code.trim() };
}
export function validateAttachments(items: LocalAsset[]): string | null {
  if (!items.length) return null;
  const videos = items.filter((a) => a.type === "video");
  if (videos.length && (videos.length !== 1 || items.length !== 1))
    return "每次可傳 4 張照片，或 1 支影片，不能混合。";
  if (items.length > 4) return "最多 4 張照片。";
  for (const a of items) {
    if (a.size <= 0) return "無法讀取附件大小，請重新選擇。";
    if (
      a.type === "video" &&
      (a.size > MAX_VIDEO_BYTES || !a.duration || a.duration > 60)
    )
      return "影片必須在 60 秒及 200 MB 以內。";
  }
  return null;
}
export function mergeConversation(
  previous: Conversation | null,
  next: Conversation,
): Conversation {
  if (!previous || previous.id !== next.id) return next;
  const messages = [
    ...new Map(
      [...previous.messages, ...next.messages].map((m) => [m.id, m]),
    ).values(),
  ];
  messages.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
  return {
    ...next,
    messages,
    before:
      previous.before === null
        ? null
        : next.before === null
          ? null
          : Math.min(previous.before, next.before),
  };
}
export function fitRect(size: [number, number], viewport: [number, number]) {
  const scale = Math.min(viewport[0] / size[0], viewport[1] / size[1]);
  return {
    width: size[0] * scale,
    height: size[1] * scale,
    x: (viewport[0] - size[0] * scale) / 2,
    y: (viewport[1] - size[1] * scale) / 2,
    scale,
  };
}
export function reliablePose(capture: Capture, pose: Pose): boolean {
  const id = pose.component_id ?? pose.board_id;
  const l = capture.localization?.find((x) => x.object_id === id);
  return (
    !capture.stale &&
    pose.frame_id === capture.frame_id &&
    pose.video_size[0] === capture.video_size[0] &&
    pose.video_size[1] === capture.video_size[1] &&
    pose.tracking === "locked" &&
    l?.status === "located" &&
    l.evidence.board_geometry_verified === true &&
    l.evidence.pin_geometry_verified === true
  );
}
export function epochMs(value: number): number {
  return value < 1e12 ? value * 1000 : value;
}
export function photoImageMatches(
  size: [number, number],
  width: number,
  height: number,
) {
  return (
    Number.isFinite(width) &&
    Number.isFinite(height) &&
    width > 0 &&
    height > 0 &&
    size[0] === width &&
    size[1] === height
  );
}
export type PreviewLease = { key: string; deadline: number };
export function inheritedMediaLabel(
  conversation: Conversation | null,
  newAttachmentCount: number,
  explicitCapture: string | null,
  currentRound?: number,
): string | null {
  if (newAttachmentCount || explicitCapture) return null;
  const media = conversation?.active_media;
  if (!media?.attachments?.length) return null;
  if (
    media.epoch !== undefined &&
    conversation?.context_epoch !== undefined &&
    media.epoch !== conversation.context_epoch
  )
    return null;
  if (
    media.round !== undefined &&
    (currentRound ?? conversation?.round) !== undefined &&
    media.round !== (currentRound ?? conversation?.round)
  )
    return null;
  const names = media.attachments
    .map(
      (a, i) =>
        (a.filename || (a.type === "video" ? "影片" : "照片") + ` ${i + 1}`) +
        (a.type === "video" && a.duration != null
          ? `（${a.duration.toFixed(1)} 秒）`
          : ""),
    )
    .join("、");
  const kind = media.capture_id
    ? "最近定位照片"
    : media.attachments.some((a) => a.type === "video")
      ? "最近影片"
      : `最近照片（${media.attachments.length} 張）`;
  return `此訊息引用：${kind} · ${names}`;
}
export function freezeInheritedMedia(
  conversation: Conversation | null,
  newAttachmentCount: number,
  explicitCapture: string | null,
  currentRound?: number,
): { asset_ids: string[]; capture_id?: string; inherit_media: false } {
  if (
    !inheritedMediaLabel(
      conversation,
      newAttachmentCount,
      explicitCapture,
      currentRound,
    )
  )
    return { asset_ids: [], inherit_media: false };
  const media = conversation!.active_media!;
  return {
    asset_ids: [...media.asset_ids],
    inherit_media: false,
    ...(media.capture_id ? { capture_id: media.capture_id } : {}),
  };
}
/** Re-reading the same preview must never extend permission to capture. */
export function previewLease(
  status: StreamStatus,
  now: number,
  previous: PreviewLease,
): PreviewLease {
  const key = `${status.generation ?? 0}:${status.preview_seq ?? status.updated_at ?? 0}`;
  if (!status.can_capture) return { key, deadline: 0 };
  const ttl = Math.max(
    0,
    Math.min(
      1500,
      status.valid_for_ms ?? 1500,
      status.expires_at ? epochMs(status.expires_at) - now : 1500,
    ),
  );
  return {
    key,
    deadline:
      key === previous.key ? Math.min(previous.deadline, now + ttl) : now + ttl,
  };
}
