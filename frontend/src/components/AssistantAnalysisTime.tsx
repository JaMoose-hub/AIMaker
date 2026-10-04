import { useEffect, useState } from 'react';
import { useMakerText } from '../lib/useMaker';
import { analysisElapsedMs, formatAnalysisDuration } from '../lib/assistantAnalysis';

/** A local clock for an existing analysis; ticking never polls or starts another inference. */
export function AssistantAnalysisTime({ startedAt, active = true, durationMs, className = 'assistant-analysis-time' }: {
  startedAt?: number | null; active?: boolean; durationMs?: number | null; className?: string;
}) {
  const tr = useMakerText();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || analysisElapsedMs(startedAt) === null) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, startedAt]);
  const elapsed = active ? analysisElapsedMs(startedAt, now)
    : typeof durationMs === 'number' && Number.isFinite(durationMs) && durationMs >= 0 ? durationMs : null;
  if (!active && elapsed === null) return null;
  return <small className={className} role="status" aria-live="off">{active ? tr('分析中', 'Analysing') : tr('分析用時', 'Analysis time')}
    {elapsed !== null ? ` · ${active ? tr('已用', 'Elapsed') + ' ' : ''}${formatAnalysisDuration(elapsed)}` : ''}</small>;
}
