export const CAPTURE_DELAY_MS = 10_000;

/** Delays the request itself: no photo, upload or AI call happens before zero. */
export function createCaptureCountdown(
  changed: (seconds: number | null) => void,
  clock = { now: () => performance.now(), later: (fn: () => void) => setTimeout(fn, 100), clear: (id: ReturnType<typeof setTimeout>) => clearTimeout(id) },
) {
  let pending: { timer?: ReturnType<typeof setTimeout>; cancel: () => void } | null = null;
  const cancel = () => pending?.cancel();
  function run<T>(action: () => T | Promise<T>, valid: () => boolean): Promise<T | undefined> {
    if (pending || !valid()) return Promise.resolve(undefined);
    return new Promise<T | undefined>((resolve, reject) => {
      const deadline = clock.now() + CAPTURE_DELAY_MS;
      let seconds = 10;
      let submitted = false;
      const task = { timer: undefined as ReturnType<typeof setTimeout> | undefined, cancel: () => {
        if (submitted) return; // Cancellation never pretends to undo a submitted request.
        if (task.timer !== undefined) clock.clear(task.timer);
        if (pending === task) pending = null;
        changed(null); resolve(undefined);
      } };
      pending = task;
      changed(seconds);
      const tick = () => {
        if (pending !== task) return;
        if (!valid()) { task.cancel(); return; }
        const next = Math.max(0, Math.ceil((deadline - clock.now()) / 1000));
        if (next === 0) {
          // Keep the single-flight lock until the submitted action settles.
          changed(null);
          Promise.resolve().then(() => {
            if (pending !== task || !valid()) return undefined;
            submitted = true;
            return action();
          })
            .then(resolve, reject).finally(() => { if (pending === task) pending = null; });
          return;
        }
        if (next !== seconds) { seconds = next; changed(next); }
        task.timer = clock.later(tick);
      };
      task.timer = clock.later(tick);
    });
  }
  return { run, cancel };
}
