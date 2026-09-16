export interface PiStatus {
  host: string;
  username: string;
  remote_dir: string;
  connected: boolean;
  hostname: string;
  python_version: string;
  busy: boolean;
  deployment: "idle" | "preparing" | "uploading" | "checking" | "starting" | "succeeded" | "failed";
  program: "unknown" | "not_deployed" | "starting" | "running" | "stopping" | "stopped" | "exited" | "failed";
  pid: number | null;
  exit_code: number | null;
  error: string | null;
  connection_error: string | null;
  logs: string[];
}

export interface PiResponse {
  ok: boolean;
  error?: string | null;
  status: PiStatus;
}

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/pi/${path}`, {
    method: body === undefined ? "GET" : "POST",
    signal: AbortSignal.timeout(35000),
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(`Pi API: HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export const fetchPiStatus = (): Promise<PiStatus> => request("status");
export const connectPi = (): Promise<PiResponse> => request("connect", {});
export const deployPi = (code: string, project?: { component_ids: string[]; catalog_version: string; profile_versions?: Record<string, { version: string; sha256: string }> }): Promise<PiResponse> => request("deploy", { code, ...(project ? { project } : {}) });
