import type { AssistantConversation } from './assistant';

export interface AssistantProgress {
  key: string;
  phase: 'processing' | 'design' | 'image';
}

/** Read the existing job state; never infer image generation from a reply or an old result. */
export function assistantProgress(record: AssistantConversation | null, pending = false,
  legacyJob?: { id: string | null; phase?: string }): AssistantProgress | null {
  if (record) {
    for (let index = record.jobs.length - 1; index >= 0; index--) {
      const job = record.jobs[index];
      if (job.status !== 'running' || job.epoch !== undefined && job.epoch !== record.context_epoch) continue;
      return {
        key: `progress:${record.id}:${job.id}`,
        phase: job.capability === 'design' ? (job.phase === 'image' ? 'image' : 'design') : 'processing',
      };
    }
  }
  if (legacyJob?.id) return {
    key: `progress:legacy:${legacyJob.id}`,
    phase: legacyJob.phase === 'image' ? 'image' : 'design',
  };
  // The POST may still be in flight, before its authoritative job exists.
  return pending ? { key: `progress:${record?.id ?? 'assistant'}:pending`, phase: 'processing' } : null;
}
