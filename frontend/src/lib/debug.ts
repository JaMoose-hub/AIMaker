import { useEffect, useRef, useState } from "react";
import { makerRequest, type ProjectDesign } from "./maker";
import type { ComponentTestRun } from "./componentTests";

export interface DebugContext { project: ProjectDesign | null; code: string; test_keys: Record<string,string>; entry: object }
export interface DebugIssue { reason: string; next_action: string; component_id?: string; fact?: string }
export interface DebugCase {
  id: string; status: string; progress: string; rounds: number; finished_at?: number; error?: string; eligible?: boolean;
  binding: { project_id: string|null; code_hash: string; test_keys?:Record<string,string> }; current_target?:boolean; issues?: DebugIssue[];
  evidence?: { environment_ready?: boolean; tests?: ComponentTestRun[]; pi?: {program: string; exit_code: number; version?: {code_hash:string;run_id:string}; telemetry?: object; logs?: string[]} };
  analysis?: {facts:string; possible_causes:string; next_step:string};
  candidate?: {id:string; applied:boolean; diff:string; offline:object}; history?: object[]; can_restore?:boolean;
}
export interface TrialRun {
  id:string; project_id:string; phase:string; outcome:string; reserved:boolean; reason?:string; detail?:string;
  created_at:number; heartbeat_at?:number; program_stopped:boolean; binding:{code_hash:string;test_keys?:Record<string,string>};
  evidence?: {program_ok:boolean; structured:boolean; sample_seq:number; display_seq:number; latest_valid_at?:number; last_display_at?:number; exit_code?:number; distance_cm?:number};
}
export interface Trials {active:TrialRun|null;results:TrialRun[]}
export function useDebug(caseId: string | undefined, projectId: string | undefined) {
  const [record, setRecord] = useState<DebugCase | null>(null);
  const [trials, setTrials] = useState<Trials>({active:null,results:[]});
  const [pending, setPending] = useState(false), [error, setError] = useState("");
  const flight = useRef(false), epoch = useRef(0), mounted = useRef(false);
  useEffect(() => {
    mounted.current = true; epoch.current++; setRecord(null);
    const controller = new AbortController(); let timer = 0;
    async function poll() {
      const version = epoch.current;
      try {
        const [nextCase, nextTrials] = await Promise.allSettled([
          caseId ? makerRequest<DebugCase>(`debug/cases/${caseId}`, undefined, controller.signal) : Promise.resolve(null),
          makerRequest<Trials>(`debug/trials${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`, undefined, controller.signal),
        ]);
        if (!controller.signal.aborted && version === epoch.current && !flight.current) {
          if (nextCase.status === "fulfilled") setRecord(nextCase.value);
          if (nextTrials.status === "fulfilled") setTrials(nextTrials.value);
          // A missing historical case must never hide a live run's stop control.
          const failed = [nextCase,nextTrials].find(result=>result.status === "rejected");
          if (failed?.status === "rejected") setError(failed.reason instanceof Error ? failed.reason.message : "connection_lost");
        }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "connection_lost"); }
      finally { if (!controller.signal.aborted) timer = window.setTimeout(poll, 1500); }
    }
    void poll();
    return () => { mounted.current = false; controller.abort(); window.clearTimeout(timer); };
  }, [caseId, projectId]);
  async function action<T>(path:string, body:unknown): Promise<T | undefined> {
    if (flight.current) return;
    flight.current = true; epoch.current++; setPending(true); setError("");
    try { return await makerRequest<T>(path, body); }
    catch(e) { if (mounted.current) setError(e instanceof Error ? e.message : "connection_lost"); }
    finally { flight.current = false; if (mounted.current) setPending(false); }
  }
  return {record, trials, pending, error, action};
}

export async function codeHash(code:string) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(code)))].map(v => v.toString(16).padStart(2,"0")).join("");
}
