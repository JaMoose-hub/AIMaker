import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { makerRequest, validDesign, clearMakerConversation, newMakerProject, previewDemo, type MakerState, type ProjectDesign } from "./maker";
import { MAKER_STORAGE } from "./makerMigration";
import { prepareProjectWiringEdit } from "./wiringEdit";
import { useAIOptions } from "./useAIOptions";
import { useI18n } from "./i18n";

interface AIStatus { available: boolean; logged_in: boolean; busy: boolean; error: string | null }
interface Job { status: "generating" | "completed" | "failed"; phase?: "design" | "image"; design: ProjectDesign | null; answer?: string; explanation?: string; error: string | null }

/** One owner in App: changing workflow pages never interrupts an AI job. */
export function useMakerAI(state: MakerState, setState: Dispatch<SetStateAction<MakerState>>) {
  const { locale } = useI18n();
  const [ai, setAI] = useState<AIStatus | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [phase, setPhase] = useState<"design" | "image" | "demo">("design");
  const [loginURL, setLoginURL] = useState("");
  const sending = useRef(false);
  const latestState = useRef(state);
  latestState.current = state;
  const demoController = useRef<AbortController | null>(null);
  useEffect(() => () => demoController.current?.abort(), []);
  const aiOptions = useAIOptions(state, locale, Boolean(ai?.logged_in));
  const busy = pending || Boolean(state.aiJobId);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try { const result = await makerRequest<AIStatus>("ai/status", undefined, controller.signal); if (!cancelled) setAI(result); }
      catch (e) { if (!cancelled) setAI({ available: false, logged_in: false, busy: false, error: String(e) }); }
      if (!cancelled) timer = setTimeout(() => void poll(), loginURL ? 2500 : 15000);
    }
    void poll();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [loginURL]);
  useEffect(() => {
    const jobId = state.aiJobId;
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const job = await makerRequest<Job>(`design/jobs/${jobId}`, undefined, controller.signal);
        if (cancelled) return;
        setPhase(job.phase ?? "design");
        if (job.status === "failed") throw new Error(job.error ?? "AI generation failed");
        if (job.status === "completed") {
          if (!job.answer && !validDesign(job.design)) throw new Error(locale === "en" ? "Invalid project data" : "作品資料格式不符");
          // The cloud reply is the chat message; full design details belong in the preview.
          const text = job.answer || job.explanation || job.design!.title;
          setState(s => s.aiJobId !== jobId ? s : ({ ...s, aiJobId: null,
            candidate: job.answer ? s.candidate : job.design,
            conversation: [...s.conversation, { role: "assistant" as const, text }].slice(-20) }));
          return;
        }
        timer = setTimeout(() => void poll(), 1000);
      } catch (e) { if (!cancelled) { setError(String(e)); setState(s => s.aiJobId === jobId ? ({ ...s, aiJobId: null }) : s); } }
    }
    void poll();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [state.aiJobId, setState]);

  async function generate() {
    if (busy || sending.current || !ai?.logged_in || !aiOptions.estimate || !aiOptions.selectionValid) return;
    sending.current = true; setPending(true); setPhase("design"); setError("");
    // Snapshot now; edits or a page change while enqueueing must not alter history.
    const request = JSON.parse(aiOptions.requestKey);
    try {
      const job = await makerRequest<{ job_id: string }>("design/generate", request);
      setState(s => ({ ...s, aiJobId: job.job_id,
        prompt: s.prompt === request.prompt ? "" : s.prompt,
        conversation: [...s.conversation, { role: "user" as const, text: request.prompt }].slice(-20) }));
    } catch (e) { setError(String(e)); } finally { sending.current = false; setPending(false); }
  }
  async function login() {
    setPending(true); setError("");
    try { const result = await makerRequest<{ auth_url: string }>("ai/login", {}); setLoginURL(result.auth_url); }
    catch (e) { setError(String(e)); } finally { setPending(false); }
  }
  async function retryImage() {
    const id = state.candidate?.image_job_id;
    if (!id || busy || sending.current) return;
    sending.current = true; setPending(true); setPhase("image"); setError("");
    try {
      const job = await makerRequest<{ job_id: string }>(`design/jobs/${id}/retry-image`, {});
      setState(s => ({ ...s, aiJobId: job.job_id }));
    } catch (e) { setError(String(e)); } finally { sending.current = false; setPending(false); }
  }
  async function loadDemo() {
    if (busy || sending.current) return;
    sending.current = true; setPending(true); setPhase("demo"); setError("");
    const controller = new AbortController();
    demoController.current = controller;
    try {
      const demo = await makerRequest<ProjectDesign>(`design/demo?locale=${locale}`, undefined, controller.signal);
      if (!validDesign(demo) || demo.source !== "demo") throw new Error(locale === "en" ? "Invalid demo" : "示範作品格式不符");
      if (!controller.signal.aborted) setState(s => previewDemo(s, demo));
    } catch (e) { if (!controller.signal.aborted) setError(String(e)); }
    finally { sending.current = false; if (!controller.signal.aborted) setPending(false); }
  }
  function clearConversation() {
    if (busy || sending.current) return;
    setState(clearMakerConversation);
  }
  async function newProject(): Promise<boolean> {
    if (busy || sending.current) return false;
    sending.current = true; setPending(true); setResetting(true); setError("");
    try {
      if (state.design && !await prepareProjectWiringEdit(state.design.id)) return false;
      if (latestState.current !== state) throw new Error(locale === "en" ? "The draft changed. Please confirm starting over again." : "草稿已變更，請重新確認從頭開始。");
      const fresh = newMakerProject(state);
      // Backup must succeed before resetting; never delete images or remote history.
      try {
        localStorage.setItem(`${MAKER_STORAGE}.before-new-project`, JSON.stringify(state));
        localStorage.setItem(MAKER_STORAGE, JSON.stringify(fresh));
      } catch { throw new Error(locale === "en" ? "Could not save the backup. Your current project has been kept." : "無法保存備份，已保留目前作品。"); }
      setState(s => s === state ? fresh : s);
      setPhase("design");
      return true;
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      const messages: Record<string, [string, string]> = {
        hardware_work_active: ["Pi 還有執行中的程式或測試，請先在執行管理停止；目前作品已保留。", "Stop the running Pi program or test in Execution first. Your project is kept."],
        other_debug_active: ["另一個作品的 AI 檢查仍在進行，請先停止；目前作品已保留。", "Stop the other project's AI check first. Your project is kept."],
        ai_stop_unconfirmed: ["無法確認 AI 已停止，目前作品已保留。", "AI stop could not be confirmed. Your project is kept."],
        wiring_state_unavailable: ["無法核對目前工作狀態，作品已保留；請確認後端連線後重試。", "Could not check active work. Your project is kept; check the backend connection and retry."],
        wiring_backend_restart_required: ["後端版本不符，請重啟程式後重試；目前作品已保留。", "Restart the backend to update its API, then retry. Your project is kept."],
      };
      setError(messages[code]?.[locale === "en" ? 1 : 0] ?? String(cause));
      return false;
    } finally { sending.current = false; setPending(false); setResetting(false); }
  }
  return { ai, aiOptions, busy, resetting, phase, error, loginURL, generate, login, retryImage, loadDemo, clearConversation, newProject };
}
