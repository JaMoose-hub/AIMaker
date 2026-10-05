/** A phone JPEG decode must settle even when the browser decoder stalls. */
export function decodePhoneTrackingImage(src: string, signal: AbortSignal, timeoutMs = 1000): Promise<void> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (failed: boolean, error?: unknown) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      signal.removeEventListener("abort", aborted);
      if (failed) {
        // This image is only a decoder probe; never clear the displayed image.
        image.removeAttribute("src");
        reject(error);
      } else {
        // Preserve the successful decode's cache for the existing <img> view.
        resolve();
      }
    };
    const aborted = () => finish(true, signal.reason ?? new DOMException("Tracking decode cancelled", "AbortError"));
    if (signal.aborted) {
      aborted();
      return;
    }
    signal.addEventListener("abort", aborted, { once: true });
    timer = setTimeout(() => finish(true, new DOMException("Tracking decode timed out", "TimeoutError")), timeoutMs);
    try {
      image.src = src;
      // Both handlers remain attached after cancellation, so a late decoder
      // rejection cannot become an unhandled rejection or revive old pixels.
      Promise.resolve(image.decode()).then(() => finish(false), error => finish(true, error));
    } catch (error) {
      finish(true, error);
    }
  });
}
