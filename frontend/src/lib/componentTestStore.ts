import { makerRequest } from "./maker";
import type { ComponentTestStatus } from "./componentTests";

type Snapshot = { status: ComponentTestStatus; error: string | null; pending: boolean };
type Request = <T>(path: string, body?: unknown, signal?: AbortSignal) => Promise<T>;

/** One poll and one mutation lane per project, shared by guide/chat/manual cards. */
export function createComponentTestStore(projectId: string, request: Request = makerRequest) {
  const endpoint = `pi/component-tests?project_id=${encodeURIComponent(projectId)}`;
  let snapshot: Snapshot = { status: {connected:false,test_busy:false,active:null,results:[]}, error:null, pending:false };
  const listeners = new Set<() => void>();
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let epoch = 0;
  let lifecycle = 0;
  function publish(change: Partial<Snapshot>) {
    snapshot = {...snapshot, ...change};
    for (const listener of listeners) listener();
  }
  async function poll(generation: number) {
    if (!listeners.size || generation !== lifecycle) return;
    const version = epoch;
    const own = new AbortController(); controller = own;
    try {
      const next = await request<ComponentTestStatus>(endpoint, undefined, own.signal);
      if (!own.signal.aborted && version === epoch && generation === lifecycle && !snapshot.pending)
        publish({status:next,error:snapshot.error === "connection_lost" ? null : snapshot.error});
    } catch {
      if (!own.signal.aborted && version === epoch && generation === lifecycle) publish({error:"connection_lost"});
    } finally {
      if (listeners.size && generation === lifecycle && !own.signal.aborted) timer = setTimeout(()=>void poll(generation),1000);
    }
  }
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      if (listeners.size === 1) { lifecycle++; void poll(lifecycle); }
      return () => {
        listeners.delete(listener);
        if (!listeners.size) { lifecycle++; controller?.abort(); clearTimeout(timer); }
      };
    },
    async send(path: string, body: unknown) {
      if (snapshot.pending) return false;
      epoch++; publish({pending:true,error:null});
      try {
        const next = await request<ComponentTestStatus>(path, body);
        publish({status:next,error:next.ok === false ? next.error ?? "program_error" : null});
        return next.ok !== false;
      } catch (reason) {
        publish({error:reason instanceof Error ? reason.message : "connection_lost"});
        return false;
      } finally { epoch++; publish({pending:false}); }
    },
    setError: (error: string) => publish({error}),
  };
}

const stores = new Map<string, ReturnType<typeof createComponentTestStore>>();
export function componentTestStore(projectId: string) {
  let store = stores.get(projectId);
  if (!store) { store = createComponentTestStore(projectId); stores.set(projectId,store); }
  return store;
}
