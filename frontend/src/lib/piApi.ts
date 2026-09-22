export interface ExecutionJob {
  id: string; kind: "test" | "deploy" | "trial"; label: string;
  state: "queued" | "preflight" | "awaiting_confirmation" | "stopping" | "blocked" | "running" | "finished" | "failed" | "cancelled";
  owner: string | null; error: string | null; run_id: string | null;
  created_at?: number; reason?: string; result?: string;
  project_id?: string; component_id?: string; guide_key?: string;
}
export interface PiExecutionStatus { jobs: ExecutionJob[]; policy: string }
export const executionPending = (job: ExecutionJob) => !["finished", "failed", "cancelled"].includes(job.state);

export interface PiStatus {
  host: string;
  username: string;
  remote_dir: string;
  connected: boolean;
  hostname: string;
  python_version: string;
  busy: boolean;
  component_test_id?: string | null;
  execution?: PiExecutionStatus;
  deployment: "idle" | "preparing" | "uploading" | "checking" | "starting" | "succeeded" | "failed";
  program: "unknown" | "not_deployed" | "starting" | "running" | "stopping" | "stopped" | "exited" | "failed";
  pid: number | null;
  exit_code: number | null;
  error: string | null;
  connection_error: string | null;
  logs: string[];
  invocation_id?: string;
  version?: {run_id: string; code_hash: string; created_at: number} | null;
}

export interface PiResponse {
  ok: boolean;
  error?: string | null;
  status: PiStatus;
}

async function request<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/pi/${path}`, {
    method: body === undefined ? "GET" : "POST",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(35000)]) : AbortSignal.timeout(35000),
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : `Pi API: HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const fetchPiStatus = (signal?: AbortSignal): Promise<PiStatus> => request("status", undefined, signal);
export const connectPi = (): Promise<PiResponse> => request("connect", {});
export const deployPi = (code: string, project?: { id?: string; component_ids: string[]; catalog_version: string; profile_versions?: Record<string, { version: string; sha256: string }> }, requestId = crypto.randomUUID()): Promise<PiResponse> => request("deploy", { code, request_id: requestId, ...(project ? { project } : {}) });
export const executionAction = (id: string, action: "confirm" | "cancel", owner?: string | null): Promise<PiResponse> => request(`execution/${encodeURIComponent(id)}/action`, {action, owner});
