import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { MakerState } from "../lib/maker";
import type { useMakerAI } from "../lib/useMakerAI";
import { useMakerText } from "../lib/useMaker";
import { AIModelControls } from "./AIModelControls";

/** Shared toolbar controls; App remains the only owner of AI state and requests. */
export function MakerModelMenu({ state, setState, assistant }: {
  state: MakerState; setState: Dispatch<SetStateAction<MakerState>>;
  assistant: ReturnType<typeof useMakerAI>;
}) {
  const tr = useMakerText();
  const { ai, aiOptions, busy, loginURL, login } = assistant;
  const menu = useRef<HTMLDetailsElement>(null);

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

  return <details className="maker-model-menu" ref={menu}
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
    <summary>
      <span className="maker-model-label">{tr("AI 模型", "AI model")}</span>
      <span className="maker-model-value"><span className={ai?.logged_in ? "maker-online" : "maker-warning"} aria-hidden="true">●</span>
        <strong>{aiOptions.selectedModel?.name ?? tr("選擇模型／登入", "Select model / sign in")}</strong><span aria-hidden="true">⌄</span></span>
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
