import type { AssistantConversation } from './assistant';

export interface AssistantWiringAnalysis {
  flow_id: string; session_id: string; review_id: string; round: number; revision: number; started_at: number | null;
}
export interface AssistantAnalysisClock { startedAt: number | null }
const validStart = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;

/** The current server projection wins over historical messages, including an explicit idle null. */
export function assistantWiringAnalysis(record: AssistantConversation | null | undefined): AssistantAnalysisClock | null {
  if (!record || record.kind !== 'project') return null;
  if (record.wiring_analysis !== undefined) return record.wiring_analysis
    ? { startedAt: validStart(record.wiring_analysis.started_at) } : null;
  // Compatibility while a previously loaded conversation has no projection yet.
  const message = [...record.messages].reverse().find(item => item.role === 'assistant' && !item.archived
    && item.epoch === record.context_epoch && item.round === record.round
    && item.wiring_flow?.current && item.wiring_flow.kind === 'analysing');
  return message ? { startedAt: validStart(message.wiring_flow?.started_at) } : null;
}

export function assistantModelRunning(record: AssistantConversation | null | undefined): boolean {
  return Boolean(record?.jobs.some(job => job.status === 'running'));
}

/** Return actual elapsed time, with no guessed duration when the source has no start time. */
export function analysisElapsedMs(startedAt: number | null | undefined, now = Date.now()): number | null {
  const start = validStart(startedAt);
  return start === null || !Number.isFinite(now) ? null : Math.max(0, now - start * 1000);
}

export function formatAnalysisDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(Number.isFinite(milliseconds) ? milliseconds / 1000 : 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
