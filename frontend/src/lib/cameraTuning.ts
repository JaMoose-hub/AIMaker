export interface CameraTuningStatus {
  available: boolean;
  busy: boolean;
  can_restore: boolean;
  state: string;
  progress: number;
  reason: string | null;
  saved: boolean;
}

export function tuningMessage(status: CameraTuningStatus | null, error: string | null): string {
  const reasons = ["busy", "unsupported", "no_restore", "needs_light", "no_improvement", "moving",
    "no_frames", "camera_changed", "timeout", "cancelled", "control_failed", "restore_failed", "network"];
  if (error) return reasons.includes(error) ? error : "control_failed";
  if (!status) return "loading";
  if (!status.available) return "unsupported";
  if (status.busy) return status.state === "restoring" ? "restoring" : "adjusting";
  if (status.reason && reasons.includes(status.reason)) return status.reason;
  return ["improved", "restored", "cancelled"].includes(status.state) ? status.state : "ready";
}

export async function requestCameraTuning(method: "GET" | "POST" | "DELETE", restore = false): Promise<CameraTuningStatus> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`/api/camera/auto-tune${restore ? "/restore" : ""}`, {
      method, signal: controller.signal, headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(response.status === 409 ? "busy" : "network");
    const result = await response.json();
    if (result.ok === false) throw new Error(result.reason ?? "control_failed");
    return result;
  } finally {
    window.clearTimeout(timer);
  }
}
