export type Pairing = {
  base_url: string;
  token: string;
  session_id: string;
  conversation_id: string;
  context_id: string;
  title: string;
};
export type StreamStatus = {
  video_size?: [number, number];
  video_fps?: number | null;
  recognition_fps?: number | null;
  recognition_ms?: number | null;
  model_runtime?: Record<
    string,
    {
      runtime?: string;
      backend?: string;
      providers?: string[];
      available?: boolean;
    }
  >;
  preview_seq?: number;
  active?: boolean;
  state?: string;
  can_capture?: boolean;
  valid_for_ms?: number;
  locked_until?: number;
  expires_at?: number;
  updated_at?: number;
  generation?: number;
  message?: string;
  reason?: string;
  width?: number;
  height?: number;
  fps?: number;
};
export type Session = Pairing & {
  context: Record<string, unknown>;
  stream: StreamStatus;
  view: { capture_id: string | null; wire_id: string | null; revision: number };
  available_context?: { context_id?: string; title?: string } | null;
};
export type Asset = {
  filename?: string;
  id: string;
  type: "image" | "video";
  mime: string;
  url: string;
  thumbnail_url?: string | null;
  width?: number;
  height?: number;
  duration?: number;
  size: number;
};
export type LocalAsset = {
  upload_id: string;
  uri: string;
  name: string;
  mime: string;
  type: "image" | "video";
  size: number;
  width: number;
  height: number;
  duration?: number;
  asset?: Asset;
  progress?: number;
  error?: string;
};
export type Message = {
  capture_id?: string | null;
  id: string;
  role: string;
  text: string;
  created_at?: number | null;
  asset_ids?: string[];
  assets?: Asset[];
  attachments?: (Asset & { capture_id?: string })[];
  archived?: boolean;
};
export type Conversation = {
  context_epoch?: number;
  round?: number;
  active_media?: {
    asset_ids: string[];
    capture_id?: string | null;
    attachments: Asset[];
    epoch?: number;
    round?: number;
  } | null;
  id: string;
  messages: Message[];
  jobs: { id: string; status: string; error?: string; request_id?: string }[];
  before: number | null;
  total: number;
};
export type SendPayload = {
  inherit_media?: boolean;
  request_id: string;
  text: string;
  asset_ids: string[];
  context_id: string;
  capture_id?: string;
  check_scope?: "one" | "all";
  wire_id?: string;
};
export type Outbox = {
  payload: SendPayload;
  attachments: LocalAsset[];
  error?: string;
  status: "pending" | "failed";
};
export type Pin = { id: string; x: number; y: number; v: boolean; c?: number };
export type Pose = {
  board_id?: string;
  component_id?: string;
  frame_id: number;
  video_size: [number, number];
  tracking: string;
  outline: [number, number][] | null;
  pins: Pin[];
};
export type Wire = {
  wire_id: string;
  component_id: string;
  board_pin: string;
  component_pin: string;
  connection_kind: string;
};
export type Localization = {
  object_id: string;
  status: string;
  raw_outline_px: [number, number][] | null;
  corrected_outline_px: [number, number][] | null;
  evidence: Record<string, unknown>;
};
export type Capture = {
  capture_id: string;
  session_id: string;
  image_url: string;
  frame_id: number;
  video_size: [number, number];
  detection: Pose;
  components: Pose[];
  localization?: Localization[];
  wires: Wire[];
  stale?: boolean;
};
export type Ticket = {
  ticket_id: string;
  expires_at: number;
  context_id: string;
  generation: number;
};
export type CaptureJob = {
  ticket: Ticket;
  asset: LocalAsset;
  request_id: string;
  error?: string;
};
export type SavedDraft = {
  text: string;
  attachments: LocalAsset[];
  outbox: Outbox[];
  captureJob?: CaptureJob | null;
};
