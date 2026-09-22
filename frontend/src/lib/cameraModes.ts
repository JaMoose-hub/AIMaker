export interface CameraMode { width: number; height: number; fps: number }
export interface CameraModes {
  supported: boolean;
  device_id: string | null;
  name: string | null;
  modes: CameraMode[];
  current: CameraMode | null;
  actual: { width: number; height: number } | null;
  busy: boolean;
  ok?: boolean;
  error?: string;
  restored?: boolean;
}

export const cameraModeKey = (mode: CameraMode) => `${mode.width}x${mode.height}@${mode.fps}`;

export async function fetchCameraModes(signal?: AbortSignal): Promise<CameraModes> {
  const response = await fetch('/api/camera/modes', { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('camera_modes_unavailable');
  return response.json();
}

// Do not retry POST: a lost response does not mean the camera did not switch.
export async function applyCameraMode(deviceId: string, mode: CameraMode): Promise<CameraModes> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch('/api/camera/modes', {
      method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ device_id: deviceId, ...mode }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(typeof result.detail === 'string' ? result.detail : 'camera_mode_unknown');
    }
    return response.json();
  } finally {
    window.clearTimeout(timer);
  }
}

export function modeErrorKey(error: unknown): string {
  const known = ['camera_modes_unavailable', 'camera_adjustment_busy', 'camera_modes_unsupported',
    'camera_changed', 'camera_mode_unsupported', 'camera_worker_busy', 'camera_mode_failed',
    'camera_restore_failed'];
  const message = error instanceof Error ? error.message : '';
  return `camera.modeError.${known.includes(message) ? message : 'camera_mode_unknown'}`;
}
