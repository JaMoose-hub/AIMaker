import { makerRequest } from "./maker";
import type { PiStatus } from "./piApi";
import type { ComponentTestStatus } from "./componentTests";
import type { Trials } from "./debug";
import type { DebugSession } from "./debugSessions";

const terminal = (status: string) => ["stopped", "complete", "error"].includes(status);
const pendingJob = (state: string) => !["finished", "failed", "cancelled"].includes(state);

/** Resetting guide records ends this project's AI check, preserving its history.
 * Read actual reservations as well as the queue: an empty queue alone does not
 * prove a remote test stopped, especially after a backend restart.
 */
export async function prepareProjectWiringEdit(projectId: string, request = makerRequest): Promise<boolean> {
  async function snapshot() {
    const [pi, tests, trials, sessions] = await Promise.all([
      request<PiStatus>("pi/status"),
      request<ComponentTestStatus>("pi/component-tests"),
      request<Trials>("debug/trials"),
      request<{active: DebugSession | null}>("debug/sessions"),
    ]);
    if (!pi.execution || !Array.isArray(pi.execution.jobs) || !Array.isArray(tests.results) || !Array.isArray(trials.results)) {
      throw new Error("wiring_state_unavailable");
    }
    return {pi, tests, trials, session: sessions.active,
      jobs: [...pi.execution.jobs, ...(tests.execution?.jobs ?? [])].filter(job => pendingJob(job.state))};
  }
  try {
    let current = await snapshot();
    const session = current.session;
    const ownSession = session?.binding?.project_id === projectId;
    const ownedJobs = new Set(ownSession ? session?.jobs.map(job => job.id) : []);
    if (current.jobs.some(job => !ownedJobs.has(job.id))) throw new Error("hardware_work_active");
    if (session && !terminal(session.status)) {
      if (ownSession) {
        // 'stop' is also supported by existing backends and by restored cases
        // whose original context is absent. It never starts a replacement check.
        const stopped = await request<DebugSession>(`debug/sessions/${encodeURIComponent(session.id)}/actions`, {
          action: "stop", request_id: crypto.randomUUID(),
        });
        if (stopped.id !== session.id || !["stopped", "complete"].includes(stopped.status)) throw new Error("ai_stop_unconfirmed");
        current = await snapshot();
      } else if (session.status !== "paused" || session.model_busy) {
        throw new Error("other_debug_active");
      }
    }
    // A paused foreign check cannot dispatch work; it is a history record, not
    // a hardware reservation. Do not stop or modify another project's check.
    if (current.session && !terminal(current.session.status) &&
        (current.session.status !== "paused" || current.session.model_busy)) throw new Error("other_debug_active");
    const {pi, tests, trials, jobs} = current;
    const unknownPriorWork = pi.program === "unknown" && Boolean(pi.pid || pi.invocation_id || pi.version);
    if (jobs.length || tests.active || trials.active || tests.test_busy ||
        tests.results.some(run => run.reserved) || trials.results.some(run => run.reserved) ||
        pi.busy || pi.component_test_id || pi.pid || unknownPriorWork ||
        ["running", "starting", "stopping", "reconnecting"].includes(pi.program)) throw new Error("hardware_work_active");
    return true;
  } catch (cause) {
    if ([404, 405, 422].includes((cause as {status?: number})?.status ?? 0)) throw new Error("wiring_backend_restart_required");
    if (cause instanceof Error && ["hardware_work_active", "other_debug_active", "ai_stop_unconfirmed", "wiring_state_unavailable"].includes(cause.message)) throw cause;
    throw new Error("wiring_state_unavailable");
  }
}
