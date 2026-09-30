import { useSyncExternalStore } from "react";
import { makerRequest, type ProjectDesign, type ProjectGuideState } from "./maker";
import { componentTestKey, componentTestRequest, type ComponentTestRun } from "./componentTests";
import { componentTestStore } from "./componentTestStore";

export function useComponentTests(design: ProjectDesign, session: ProjectGuideState) {
  const store = componentTestStore(design.id);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  return { ...state,
    async connect() {
      try { await makerRequest("pi/connect", {}); }
      catch { store.setError("connection_lost"); }
    },
    // Only an explicit local edit invalidates a run; viewing another card does not.
    async invalidate(cid?: string) {
      const {status} = store.getSnapshot();
      const runs = status.results.filter(run=>run.project_id === design.id && (!cid || run.component_id === cid) && !run.invalidated);
      if (status.active && !runs.some(run=>run.id===status.active!.id) && status.active.project_id===design.id && (!cid||status.active.component_id===cid)) runs.push(status.active);
      for (const run of runs) if (!await store.send(`pi/component-tests/${run.id}/action`, {action:"invalidate",guide_key:run.guide_key})) return false;
      return true;
    },
    start: (cid: string) => {
      if (!store.getSnapshot().status.execution) { store.setError("executor_restart_required"); return Promise.resolve(false); }
      return store.send("pi/component-tests", {...componentTestRequest(design, session, cid),request_id:crypto.randomUUID()});
    },
    action: (run: ComponentTestRun, action: string, extra: Record<string, unknown> = {}) => store.send(`pi/component-tests/${run.id}/action`,
      {action,guide_key:componentTestKey(design,session,run.component_id),...extra}),
  };
}
