import { useEffect, useRef, useState } from "react";

interface StatusReasonValue {
  status: string;
  reason?: string | null;
}

/**
 * Keep rapidly changing explanatory text readable without delaying a real
 * status transition.  Pass/fail/uncertain changes are immediate; only a
 * reason change inside the same status is held for the requested dwell time.
 */
export function useHeldStatusReason<T extends StatusReasonValue>(
  latest: T | null,
  holdMs = 5_000,
): T | null {
  const [displayed, setDisplayed] = useState<T | null>(latest);
  const displayedRef = useRef<T | null>(latest);
  const pendingRef = useRef<T | null>(latest);
  const shownAtRef = useRef(Date.now());
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    pendingRef.current = latest;
    const current = displayedRef.current;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    const showNow = (value: T | null) => {
      clearTimer();
      displayedRef.current = value;
      shownAtRef.current = Date.now();
      setDisplayed(value);
    };

    if (latest === null || current === null) {
      showNow(latest);
      return;
    }
    if (latest.status !== current.status) {
      showNow(latest);
      return;
    }
    if ((latest.reason ?? null) === (current.reason ?? null)) {
      clearTimer();
      displayedRef.current = latest;
      setDisplayed(latest);
      return;
    }

    const remaining = Math.max(0, holdMs - (Date.now() - shownAtRef.current));
    if (remaining === 0) {
      showNow(latest);
      return;
    }
    if (timerRef.current === null) {
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        const next = pendingRef.current;
        displayedRef.current = next;
        shownAtRef.current = Date.now();
        setDisplayed(next);
      }, remaining);
    }
  }, [holdMs, latest]);

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);

  return displayed;
}
