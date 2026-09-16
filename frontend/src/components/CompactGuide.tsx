import { useId, useRef, useState, type ReactNode } from "react";
import { useMakerText } from "../lib/useMaker";

interface Props {
  contextKey: string;
  phase: string;
  visible: boolean;
  title: string;
  headerActions?: ReactNode;
  progress: ReactNode;
  targetId?: string;
  actions: ReactNode;
  children: ReactNode;
  details: ReactNode;
  onClose: () => void;
}

/** Opening extra copy never changes the wiring session or its active target. */
export function CompactGuide({ contextKey, phase, visible, title, headerActions, progress, targetId, actions, children, details: extraDetails, onClose }: Props) {
  const tr = useMakerText();
  const detailsId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const [details, setDetails] = useState({ contextKey, expanded: false });
  // Reset only presentation state when the step changes, including backtracking.
  if (details.contextKey !== contextKey) setDetails({ contextKey, expanded: false });
  const expanded = details.contextKey === contextKey && details.expanded;
  const setExpanded = (value: boolean) => setDetails({ contextKey, expanded: value });
  return <section className={`photo-guide component-guide maker-project-guide compact-guide ${phase}`}
    hidden={!visible} aria-label={tr("作品 Pin 接線引導", "Project Pin wiring guide")}
    onKeyDown={event => {
      if (event.key === "Escape" && expanded) {
        event.preventDefault(); event.stopPropagation(); setExpanded(false); toggleRef.current?.focus();
      }
    }}>
    <header className="guide-panel-header">
      <div><span className="guide-panel-eyebrow">{tr("接線引導", "WIRING GUIDE")}</span>
        <h2>{title}</h2></div>
      <div className="guide-header-actions">
        {headerActions}
        <button type="button" className="compact-guide-close" aria-label={tr("收合接線卡", "Collapse guide")}
          onClick={() => { setExpanded(false); onClose(); }}>×</button>
      </div>
    </header>
    <div className="guide-panel-progress">{progress}</div>
    <div className="guide-panel-body" data-wiring-target={targetId}>
      {children}
      <section className="guide-panel-reference">
        <button ref={toggleRef} type="button" className="guide-reference-toggle" aria-expanded={expanded} aria-controls={detailsId}
          onClick={() => setExpanded(!expanded)}>
          <span>{tr("接線說明與紀錄", "Instructions & records")}</span><span aria-hidden="true">{expanded ? "−" : "+"}</span>
        </button>
        <div id={detailsId} className="compact-guide-details" hidden={!expanded}>{extraDetails}</div>
      </section>
    </div>
    <footer className="guide-panel-footer">{actions}</footer>
  </section>;
}
