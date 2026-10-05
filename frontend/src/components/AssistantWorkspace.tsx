import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useMakerText } from "../lib/useMaker";
import { ConversationGuideProvider } from "./ConversationGuideDock";
import "./ConversationGuideDock.css";

export const ASSISTANT_WIDTH_KEY = "boardvision.assistant-width.v1";
export const clampAssistantWidth = (value: number) => Math.min(520, Math.max(320, Number.isFinite(value) ? value : 400));
function initialWidth() {
  try { const value = localStorage.getItem(ASSISTANT_WIDTH_KEY); return value ? clampAssistantWidth(Number(value)) : 400; }
  catch { return 400; }
}
/** CSS hides panes; neither mobile tabs nor collapse remount their children. */
export function AssistantWorkspace({ children, assistant, latestReply = "", openRequest = 0, active = true, aiOpen, onAiOpen }: {
  children: ReactNode; assistant: ReactNode; latestReply?: string; openRequest?: number; active?: boolean;
  aiOpen: boolean; onAiOpen: (open: boolean) => void;
}) {
  const tr = useMakerText();
  const [width, setWidth] = useState(initialWidth);
  const [mobileView, setMobileView] = useState<"work" | "ai">("work");
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 1099px)").matches);
  const [seenReply, setSeenReply] = useState("");
  const unread = Boolean(latestReply && latestReply !== seenReply);
  const toggleLabel = aiOpen ? tr("收合 AI 對話", "Collapse AI conversation")
    : unread ? tr("Ask AI：展開 AI 對話，有新回覆", "Ask AI: Open AI conversation, new reply") : tr("Ask AI：展開 AI 對話", "Ask AI: Open AI conversation");
  useEffect(() => {
    const query = window.matchMedia("(max-width: 1099px)");
    const change = () => setMobile(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  useEffect(() => { if (active && (mobile ? mobileView === "ai" : aiOpen)) setSeenReply(latestReply); }, [active, mobile, mobileView, aiOpen, latestReply]);
  useEffect(() => { if (openRequest) setMobileView("ai"); }, [openRequest]);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const revealGuide = useCallback(() => { setMobileView("ai"); onAiOpen(true); }, [onAiOpen]);
  const save = (next: number) => {
    setWidth(clampAssistantWidth(next));
    try { localStorage.setItem(ASSISTANT_WIDTH_KEY, String(clampAssistantWidth(next))); } catch { /* session-only */ }
  };
  return <ConversationGuideProvider enabled={active} showing={mobile ? mobileView === "ai" : aiOpen} onReveal={revealGuide}>
    <div className={`assistant-workspace${active ? " is-unified" : ""}${aiOpen ? "" : " ai-collapsed"}`}
    data-mobile-view={mobileView} style={{ "--assistant-width": `${width}px` } as CSSProperties}>
    {active ? <div className="assistant-mobile-tabs" role="tablist" aria-label={tr("工作區與 AI", "Workspace and AI")}>
      <button role="tab" aria-selected={mobileView === "work"} aria-controls="assistant-work-surface" onClick={() => setMobileView("work")}>{tr("工作區", "Workspace")}</button>
      <button role="tab" aria-selected={mobileView === "ai"} aria-controls="assistant-chat-surface" onClick={() => { setMobileView("ai"); onAiOpen(true); }}>AI {unread && mobileView !== "ai" ? "●" : ""}</button>
    </div> : null}
    <div id="assistant-work-surface" className="assistant-work-surface">{children}</div>
    {active ? <>
      <div className="assistant-resizer" role="separator" aria-label={tr("調整 AI 對話寬度", "Resize AI conversation")}
        aria-orientation="vertical" aria-valuemin={320} aria-valuemax={520} aria-valuenow={width} tabIndex={0}
        onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, width }; }}
        onPointerMove={event => { if (drag.current) setWidth(clampAssistantWidth(drag.current.width + drag.current.x - event.clientX)); }}
        onPointerUp={event => { if (!drag.current) return; save(drag.current.width + drag.current.x - event.clientX); drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }}
        onPointerCancel={() => { if (drag.current) setWidth(drag.current.width); drag.current = null; }}
        onLostPointerCapture={() => { drag.current = null; }} onDoubleClick={() => save(400)}
        onKeyDown={event => { const next = event.key === "ArrowLeft" ? width + 10 : event.key === "ArrowRight" ? width - 10 : event.key === "Home" ? 320 : event.key === "End" ? 520 : event.key === "Enter" ? 400 : null;
          if (next !== null) { event.preventDefault(); save(next); } }} />
      <aside id="assistant-chat-surface" className="assistant-chat-surface" aria-label={tr("共用 AI 對話", "Shared AI conversation")}>
        <button className="assistant-collapse" type="button" onClick={() => onAiOpen(!aiOpen)} aria-expanded={aiOpen}
          aria-controls="assistant-chat-content" aria-label={toggleLabel} title={toggleLabel}>
          <span className="assistant-orb" aria-hidden="true"><span className="assistant-orb-energy" />
            <svg className="assistant-orb-core" viewBox="0 0 24 24" fill="none" focusable="false">
              <path d="M12 4c.9 4.8 3.2 7.1 8 8-4.8.9-7.1 3.2-8 8-.9-4.8-3.2-7.1-8-8 4.8-.9 7.1-3.2 8-8Z" fill="currentColor" />
              <circle cx="19" cy="5" r="1.25" fill="currentColor" />
              <circle cx="5" cy="19" r=".8" fill="currentColor" />
            </svg>
            <svg className="assistant-orb-chevron" viewBox="0 0 16 16" fill="none" focusable="false">
              <path d="m6 4 4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          {!aiOpen && unread ? <span className="assistant-orb-unread" aria-hidden="true" /> : null}
          <span className="assistant-orb-label" aria-hidden="true">Ask AI</span>
        </button>
        <div id="assistant-chat-content" className="assistant-chat-content">{assistant}</div>
      </aside>
    </> : null}
  </div></ConversationGuideProvider>;
}
