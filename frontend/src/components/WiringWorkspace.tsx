import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { currentWire, wireSignature, type ProjectDesign, type ProjectGuideState } from "../lib/maker";
import { componentModelName } from "../lib/componentHeaderGuide";
import { useI18n } from "../lib/i18n";
import { useMakerText } from "../lib/useMaker";

/** Keep both panels mounted: changing tabs must not restart work or erase drafts. */
export function WiringWorkspace({ design, guide, visible, assistantOpen, onAssistantOpenChange, onClose,
  assistant, children, busy = false, replyId, guideOnly = false, panelId }: {
  design: ProjectDesign; guide: ProjectGuideState; visible: boolean;
  assistantOpen: boolean; onAssistantOpenChange: (open: boolean) => void; onClose: () => void;
  assistant: ReactNode; children: ReactNode; busy?: boolean; replyId?: string;
  guideOnly?: boolean; panelId?: string;
}) {
  const tr = useMakerText();
  const { t } = useI18n();
  const id = useId();
  const guideTab = useRef<HTMLButtonElement>(null);
  const assistantTab = useRef<HTMLButtonElement>(null);
  const previousReply = useRef(replyId);
  const [seenReply, setSeenReply] = useState(replyId);
  useEffect(() => {
    if (assistantOpen || !previousReply.current) setSeenReply(replyId);
    previousReply.current = replyId;
  }, [assistantOpen, replyId]);
  const unread = !assistantOpen && Boolean(replyId && replyId !== seenReply);
  const wire = guide.phase === "active" ? currentWire(design, guide) : undefined;
  const cid = design.component_ids[guide.componentIndex];
  const confirmed = design.wiring.filter(w => guide.confirmed[w.id]?.signature === wireSignature(w)).length;
  const name = componentModelName(cid, t) ?? cid;
  function select(next: boolean, focus = false) {
    onAssistantOpenChange(next);
    if (focus) (next ? assistantTab : guideTab).current?.focus();
  }
  return <section id={panelId} className="wiring-workspace" hidden={!visible} aria-label={tr("接線與 AI 工作區", "Wiring and AI workspace")}>
    <div hidden={guideOnly} className="wiring-workspace-tabs" role="tablist" aria-label={tr("接線工作區內容", "Wiring workspace views")}
      onKeyDown={event => {
        const next = event.key === "Home" ? false : event.key === "End" ? true
          : ["ArrowLeft", "ArrowRight"].includes(event.key) ? !assistantOpen : undefined;
        if (next === undefined) return;
        event.preventDefault(); select(next, true);
      }}>
      <button ref={guideTab} id={`${id}-guide-tab`} type="button" role="tab" aria-selected={!assistantOpen}
        aria-controls={`${id}-guide`} tabIndex={assistantOpen ? -1 : 0} onClick={() => select(false)}>{tr("接線引導", "Wiring guide")}</button>
      <button ref={assistantTab} id={`${id}-ai-tab`} type="button" role="tab" aria-selected={assistantOpen}
        aria-controls={`${id}-ai`} tabIndex={assistantOpen ? 0 : -1} onClick={() => select(true)}>
        {tr("AI 協作", "AI assistant")}{busy || unread ? <span className="wiring-tab-notice" role="status">{busy ? tr("回覆中", "Replying") : tr("新回覆", "New reply")}</span> : null}
      </button>
    </div>
    <header className="wiring-workspace-context">
      <div><strong>{guideOnly ? `${tr("接線引導", "Wiring guide")} · ` : ""}{name}</strong>{wire && !guideOnly ? <small>{wire.componentPin} → {wire.boardLabel}</small> : null}</div>
      <span className="wiring-workspace-count" title={tr("已人工確認的接線", "Manually confirmed wires")}>{confirmed} / {design.wiring.length}</span>
      <button type="button" className="wiring-workspace-close" onClick={onClose} aria-label={guideOnly ? tr("收合接線引導", "Hide wiring guide") : tr("收合側邊面板", "Collapse side panel")}>×</button>
    </header>
    <progress className="wiring-workspace-progress" max={design.wiring.length} value={confirmed} aria-label={tr("作品人工接線進度", "Project manual wiring progress")} />
    <div id={`${id}-guide`} className="wiring-workspace-view" role={guideOnly ? "region" : "tabpanel"} aria-label={guideOnly ? tr("接線引導", "Wiring guide") : undefined} aria-labelledby={guideOnly ? undefined : `${id}-guide-tab`} hidden={!guideOnly && assistantOpen}>{children}</div>
    {!guideOnly ? <div id={`${id}-ai`} className="wiring-workspace-view" role="tabpanel" aria-labelledby={`${id}-ai-tab`} hidden={!assistantOpen}>{assistant}</div> : null}
  </section>;
}
