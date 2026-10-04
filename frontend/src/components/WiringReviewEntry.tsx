import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useMakerText } from "../lib/useMaker";
import type { WiringReviewState } from "../lib/wiringReview";
import { hasUnfinishedWiringReview, type WiringReviewRecommendation } from "../lib/wiringReviewEntry";
import "./wiringReview.css";

/** Display state stays local; opening and hiding this entry never submit session actions. */
export function WiringReviewEntry({ review, resumable = false, recommendation, componentLabel, toolbarTarget, disabled = false, onExpandedChange, revealRequest, children }: {
  review?: WiringReviewState | null;
  resumable?: boolean;
  recommendation?: WiringReviewRecommendation | null;
  componentLabel?: string;
  toolbarTarget?: HTMLElement | null;
  disabled?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  revealRequest?: { token: string; reviewId: string; componentId?: string } | null;
  children: (componentId?: string) => ReactNode;
}) {
  const tr = useMakerText();
  const contentId = useId();
  const reviewId = review?.id ?? null;
  const [choice, setChoice] = useState<{ reviewId: string | null; open: boolean; componentId?: string } | null>(() =>
    resumable && hasUnfinishedWiringReview(review) ? { reviewId, open: true } : null);
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    if (!revealRequest || reviewId !== revealRequest.reviewId || revealed.current === revealRequest.token) return;
    revealed.current = revealRequest.token;
    setChoice({ reviewId, open: true, componentId: revealRequest.componentId });
  }, [revealRequest?.token, revealRequest?.reviewId, reviewId]);
  const chosen = choice?.reviewId === reviewId ? choice : null;
  const expanded = chosen?.open ?? (resumable && hasUnfinishedWiringReview(review));
  useEffect(() => { onExpandedChange?.(expanded); }, [expanded, onExpandedChange]);
  // Latch a restored/new round's visibility. Confirming its last wire must not hide the retest action.
  if (expanded && !chosen) setChoice({ reviewId, open: true });
  // Retain the mounted card after hiding it, including its selected module and draft crop.
  const mounted = expanded || chosen !== null;
  const componentId = review?.component_id ?? chosen?.componentId;
  const label = expanded ? tr("收起接線核對", "Hide wiring review")
    : review ? tr("繼續／查看接線核對", "Continue / view wiring review") : tr("檢查接線", "Check wiring");
  const recommended = Boolean(recommendation && !review && !expanded);
  const trigger = <button className="wr-entry-trigger" type="button" aria-label={label} title={label}
    aria-expanded={expanded} aria-controls={contentId} disabled={disabled} data-recommended={recommended}
    onClick={() => setChoice({ reviewId, open: !expanded, componentId: chosen?.componentId ?? recommendation?.component_id })}>
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-6 6v4m-6-13v3a6 6 0 0 0 6 6" />
    </svg>
    <span>{expanded ? tr("收起核對", "Hide review") : review ? tr("查看核對", "View review") : tr("檢查接線", "Check wiring")}</span>
    {recommended ? <span className="wr-entry-dot" aria-hidden="true" /> : null}
    <svg className="wr-entry-chevron" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
  </button>;
  return <section className="wiring-review-entry" data-expanded={expanded} data-recommended={recommended}
    data-toolbar={Boolean(toolbarTarget)} aria-label={tr("接線核對入口", "Wiring review entry")}>
    {expanded ? <div className="wr-entry-collapse">{trigger}</div> : toolbarTarget ? createPortal(trigger, toolbarTarget) : <div className="wr-entry-toolbar">{trigger}
      {review && !expanded ? <small>{hasUnfinishedWiringReview(review)
        ? tr("本輪核對進度已保留。", "This round's review progress is retained.")
        : review.status === "stale" || review.status === "error" ? tr("可查看先前紀錄或重新開始。", "View previous records or start again.")
        : tr("本輪人工核對已完成。", "Human review of this round is complete.")}</small> : null}
    </div>}
      {recommended ? <p className="wr-entry-hint">
        {componentLabel ? `${componentLabel} · ` : ""}{recommendation?.source === "ai"
          ? tr("AI 建議補充接線證據，可選擇照片核對。", "AI suggests more wiring evidence. You can review photos.")
          : tr("功能結果有異常或不確定，可選擇照片核對接線。", "The functional result is abnormal or uncertain. You can review wiring photos.")}
      </p> : null}
    {mounted ? <div id={contentId} className="wr-entry-content" hidden={!expanded}>{children(componentId)}</div> : null}
  </section>;
}
