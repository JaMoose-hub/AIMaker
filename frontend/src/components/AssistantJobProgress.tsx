import { useMakerText } from '../lib/useMaker';
import type { AssistantProgress } from '../lib/assistantProgress';
import './assistantJobProgress.css';

export function AssistantJobProgress({ progress }: { progress: AssistantProgress }) {
  const tr = useMakerText();
  const title = progress.phase === 'image' ? tr('正在生成圖片', 'Generating your image')
    : progress.phase === 'design' ? tr('AI 正在設計作品', 'AI is designing your project')
      : tr('正在處理需求', 'Working on your request');
  return <article className="ai-debug-message is-assistant assistant-job-progress" data-message-id={progress.key}
    data-progress-phase={progress.phase} role="status" aria-live="polite" aria-atomic="true">
    <header><strong>Tinkro AI</strong><small>{tr('進行中', 'In progress')}</small></header>
    <p className="assistant-job-progress-title">{title}<span className="assistant-job-progress-dots" aria-hidden="true"><i /><i /><i /></span></p>
    <small>{tr('完成後會自動更新，可先切換工作區。', 'Results update automatically; you can switch workspaces.')}</small>
  </article>;
}
