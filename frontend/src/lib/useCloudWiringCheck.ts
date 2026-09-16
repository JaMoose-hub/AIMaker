import { useEffect, useRef, useState } from "react";
import { makerRequest } from "./maker";
import { cloudPhotoExpired, type CloudWiringJob, type cloudWiringRequest } from "./cloudWiring";

/** User initiated only; never stores photos or evidence in the project draft. */
export function useCloudWiringCheck(request: ReturnType<typeof cloudWiringRequest>, enabled: boolean, poseReady: boolean, context: string) {
  const key = JSON.stringify([context, request]);
  const [record, setRecord] = useState<{ key: string; id?: string; job?: CloudWiringJob; error?: string; submitting?: boolean; lostPose?: boolean }>({ key });
  const [retry, setRetry] = useState(0);
  const sending = useRef(false);
  const lifecycle = useRef<{ key: string; controller: AbortController } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = { key, controller };
    sending.current = false;
    // Backtracking to an earlier key must not revive its previous photo result.
    setRecord({ key });
    return () => controller.abort();
  }, [key]);
  const current = record.key === key ? record : undefined;
  const jobId = current?.id;
  const terminal = current?.job?.status === "completed" || current?.job?.status === "failed";
  useEffect(() => {
    if (!poseReady && current?.job?.capture && !current.lostPose) {
      setRecord(r => r.key === key ? { ...r, lostPose: true } : r);
    }
  }, [poseReady, current?.job?.capture, current?.lostPose, key]);
  useEffect(() => {
    if (!jobId || terminal) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const job = await makerRequest<CloudWiringJob>(`guidance/cloud-checks/${jobId}`, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setRecord(r => r.key === key && r.id === jobId ? { ...r, job, error: undefined } : r);
        if (job.status !== "completed" && job.status !== "failed") timer = setTimeout(() => void poll(), 1000);
      } catch (e) {
        const expired = e instanceof Error && "status" in e && e.status === 404;
        if (!controller.signal.aborted) setRecord(r => r.key === key && r.id === jobId
          ? { ...r, error: String(e), ...(expired ? { id: undefined, job: undefined } : {}) } : r);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, terminal, key, retry]);
  async function start() {
    // Recover a polling failure without submitting a second billable check.
    if (jobId && !terminal && current?.error) {
      setRecord(r => ({ ...r, error: undefined })); setRetry(n => n + 1); return;
    }
    if (!enabled || sending.current || (jobId && !terminal)) return;
    if (lifecycle.current?.key !== key) return;
    const { controller } = lifecycle.current;
    sending.current = true;
    setRecord({ key, submitting: true });
    try {
      const response = await makerRequest<{ job_id: string }>("guidance/cloud-checks", request, controller.signal);
      if (!controller.signal.aborted) setRecord({ key, id: response.job_id });
    } catch (e) {
      if (!controller.signal.aborted) setRecord({ key, error: String(e) });
    } finally { if (!controller.signal.aborted) sending.current = false; }
  }
  const readAgain = Boolean(jobId && !terminal && current?.error);
  return { job: current?.job, error: current?.error ?? current?.job?.error, start, readAgain,
    busy: Boolean(current?.submitting || (jobId && !terminal && !current?.error)),
    stale: cloudPhotoExpired(current?.job, Date.now(), Boolean(current?.lostPose) || !poseReady) };
}
