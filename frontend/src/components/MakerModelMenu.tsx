import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { MakerState } from "../lib/maker";
import type { useMakerAI } from "../lib/useMakerAI";
import { useMakerText } from "../lib/useMaker";
import { AIModelControls } from "./AIModelControls";

/** Shared model controls; App remains the only owner of AI state and requests. */
export function MakerModelMenu({ state, setState, assistant, compact = false }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>;
  assistant: ReturnType<typeof useMakerAI>;
  compact?: boolean;
}) {
  const tr = useMakerText();
  const { ai, aiOptions, busy, loginURL, login } = assistant;
  const menu = useRef<HTMLDetailsElement>(null);
  const modelLabel = `${tr("選擇 AI 模型與推理強度", "Choose AI model and reasoning effort")} · ${aiOptions.selectedModel?.name ?? tr("選擇模型／登入", "Select model / sign in")}`;

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) {
        menu.current.open = false;
      }
    };
    document.addEventListener("pointerdown", closeOutside, true);
    return () => document.removeEventListener("pointerdown", closeOutside, true);
  }, []);
  useEffect(() => { if (menu.current) menu.current.open = false; }, [state.stage]);

  return <details className={`maker-model-menu${compact ? " is-compact" : ""}`} ref={menu}
    onKeyDown={event => {
      if (event.key === "Escape" && menu.current?.open) {
        event.preventDefault();
        event.stopPropagation();
        menu.current.open = false;
        menu.current.querySelector("summary")?.focus();
      }
    }}
    onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
    }}>
    <summary title={compact ? modelLabel : undefined} aria-label={compact ? modelLabel : undefined}>
      {compact ? <svg className="maker-model-brain" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M12 6a3 3 0 0 0-5.8-1A4 4 0 0 0 3 11a4 4 0 0 0 1 7.4A4 4 0 0 0 12 19V6Z" />
        <path d="M12 6a3 3 0 0 1 5.8-1A4 4 0 0 1 21 11a4 4 0 0 1-1 7.4A4 4 0 0 1 12 19" />
        <path d="M7 8c2 0 3 1 3 3M4 14c2-1 4 0 4 2M7 19v-2M17 8c-2 0-3 1-3 3M20 14c-2-1-4 0-4 2M17 19v-2" />
      </svg> : <>
      <span className="maker-model-label">{tr("AI 模型", "AI model")}</span>
      <span className="maker-model-value"><span className={ai?.logged_in ? "maker-online" : "maker-warning"} aria-hidden="true">●</span>
        <strong>{aiOptions.selectedModel?.name ?? tr("選擇模型／登入", "Select model / sign in")}</strong><span aria-hidden="true">⌄</span></span>
      </>}
    </summary>
    <div className="maker-model-popover">
      <div className="maker-auth"><span>{ai?.logged_in ? tr("ChatGPT 已登入", "ChatGPT connected") : tr("需要 ChatGPT 登入", "Sign-in required")}</span>
        <button type="button" disabled={busy} onClick={() => void login()}>{tr("登入 ChatGPT", "Sign in")}</button></div>
      {loginURL && !ai?.logged_in ? <a href={loginURL} target="_blank" rel="noreferrer">{tr("開啟 ChatGPT 登入頁", "Open ChatGPT sign-in")}</a> : null}
      {ai?.error ? <p className="maker-warning" role="alert">{ai.error}</p> : null}
      <AIModelControls state={state} setState={setState} ai={aiOptions} busy={busy} />
    </div>
  </details>;
}
