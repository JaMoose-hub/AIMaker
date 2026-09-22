import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { makerRequest, validDesign, clearMakerConversation, previewDemo, type MakerState, type ProjectDesign } from "./maker";
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
  const [phase, setPhase] = useState<"design" | "image" | "demo">("design");
  const [loginURL, setLoginURL] = useState("");
  const sending = useRef(false);
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
          if (!job.answer && !validDesign(job.design)) throw new Error("Invalid project data / 作品資料格式不符");
          const text = job.answer || `${job.explanation || job.design!.title}\n${job.design!.summary}${job.design?.image_error ? `\n圖片生成失敗：${job.design.image_error}` : ""}`;
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
      const demo = await makerRequest<ProjectDesign>("design/demo", undefined, controller.signal);
      if (!validDesign(demo) || demo.source !== "demo") throw new Error("Invalid demo / 示範作品格式不符");
      if (!controller.signal.aborted) setState(s => previewDemo(s, demo));
    } catch (e) { if (!controller.signal.aborted) setError(String(e)); }
    finally { sending.current = false; if (!controller.signal.aborted) setPending(false); }
  }
  function clearConversation() {
    if (busy || sending.current) return;
    setState(clearMakerConversation);
  }
  return { ai, aiOptions, busy, phase, error, loginURL, generate, login, retryImage, loadDemo, clearConversation };
}
