export const CAPTURE_DELAY_MS = 0;

/** Capture immediately while retaining the existing readiness and single-flight guards. */
export function createCaptureCountdown(
  changed: (seconds: number | null) => void,
) {
  let pending = false;
  // There is no delayed request to cancel; an already submitted capture stays in flight.
  const cancel = () => {};
  async function run<T>(action: () => T | Promise<T>, valid: () => boolean): Promise<T | undefined> {
    if (pending || !valid()) return undefined;
    pending = true;
    try {
      changed(null);
      if (!valid()) return undefined;
      return await action();
    } finally { pending = false; }
  }
  return { run, cancel };
}
