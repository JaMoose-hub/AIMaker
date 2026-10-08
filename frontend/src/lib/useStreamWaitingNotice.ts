import { useEffect, useState } from 'react';

/** Presentation grace only: never extends the lifetime of video or poses. */
export function useStreamWaitingNotice(waiting: boolean) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!waiting) { setShown(false); return; }
    const timer = setTimeout(() => setShown(true), 400);
    return () => clearTimeout(timer);
  }, [waiting]);
  return waiting && shown;
}
