import React from 'react';
import { createRoot } from 'react-dom/client';
import { WiringChatMessage } from '../src/components/WiringChatMessage';
import { WiringReviewCard } from '../src/components/WiringReviewCard';
import type { WiringEndpoint, WiringPhotoRole, WiringReviewResult, WiringReviewState } from '../src/lib/wiringReview';
import type { AssistantMessage } from '../src/lib/assistant';
import '../src/styles.css';
import '../src/assistant.css';
import '../src/tinkro.css';

const candidate = (id: string, role: WiringPhotoRole, pin: string, physical: number | null, box: WiringEndpoint['box']): WiringEndpoint => ({
  id, role, capture_id: role, pin_id: pin, physical_pin: physical, pin_label: pin,
  color: 'orange', color_visibility: 'clear', contact: 'covers_pin', box,
  evidence: '示例資料：可見接頭位置。非真實照片判定。',
});
const boardActual = candidate('pi_side_a:c12', 'pi_side_a', '12', 12, [.35, .35, .42, .6]);
const boardExpected = candidate('pi_side_a:c11', 'pi_side_a', '11', 11, [.23, .35, .30, .6]);
const moduleActual = candidate('component_header:trig', 'component_header', 'TRIG', null, [.35, .35, .42, .6]);
const suspected: WiringReviewResult = {
  wire_id: 'trig', expected: { board_pin: '11', physical_pin: 11, bcm: 17, component_pin: 'TRIG', connection_kind: 'direct' },
  pi_candidates: [boardExpected], component_candidates: [moduleActual], comparison: 'similar',
  next_step: '先斷電，再沿 TRIG 線親自核對。', authority: 'visual_advisory',
  diagnosis: { status: 'suspected', observed_board_pin: '12', observed_physical_pin: 12, observed_component_pin: 'TRIG',
    board_connector_id: boardActual.id, component_connector_id: moduleActual.id, evidence: '示例：疑似插到相鄰腳位。', retake_roles: [] },
};
const uncertain: WiringReviewResult = { ...suspected, wire_id: 'echo',
  expected: { ...suspected.expected, board_pin: '12', physical_pin: 12, bcm: 18, component_pin: 'ECHO' },
  comparison: 'unknown', component_candidates: [], next_step: '補拍零件接頭，保留腳位文字。',
  diagnosis: { status: 'uncertain', observed_board_pin: null, observed_physical_pin: null, observed_component_pin: null,
    board_connector_id: null, component_connector_id: null, evidence: '示例：零件端腳位被遮擋。', retake_roles: ['component_header'] },
};
const roles: WiringPhotoRole[] = ['pi_side_a', 'pi_side_b', 'component_header'];
const review: WiringReviewState = { id: 'fixture-review', revision: 4, round: 1, component_id: 'hc-sr04', status: 'ready',
  slots: Object.fromEntries(roles.map(role => [role, { role, capture_id: role, image_url: '/fixture.svg', size: [800, 500],
    sha256: 'synthetic-only', crop: null, crop_source: 'none', available: true }])) as WiringReviewState['slots'],
  observations: [boardActual, boardExpected, moduleActual], results: [uncertain, suspected], reviews: {}, missing_roles: [], no_progress_count: 0,
};
const message = (result: WiringReviewResult): AssistantMessage => ({ id: result.wire_id, role: 'assistant', text: '',
  source: 'fixture', created_at: 1, stage: 'guide', capability: 'debug', epoch: 0, round: 1,
  wiring_flow: { flow_id: 'fixture-flow', review_id: review.id, revision: review.revision, round: review.round, component_id: review.component_id,
    kind: 'wire_review', result, wire_id: result.wire_id, current: true, can_act: true, actions: ['review', 'capture', 'crop', 'changed'] },
});
const noAction = async () => false;

createRoot(document.getElementById('root')!).render(<div className="app tinkro-theme diagnosis-preview">
  <style>{`
    .diagnosis-preview { display:block; padding:28px; min-height:100dvh; }
    .diagnosis-preview > header { max-width:1040px; margin:0 auto 24px; }
    .diagnosis-preview > header h1 { font-size:22px; margin:0 0 8px; }
    .diagnosis-preview > header p { color:var(--ink-secondary); font-size:13px; margin:0; }
    .diagnosis-preview-grid { display:grid; grid-template-columns:minmax(0,440px) minmax(0,440px); gap:32px; max-width:1040px; margin:auto; align-items:start; }
    .diagnosis-preview-grid > section { min-width:0; }
    .diagnosis-preview-grid h2 { font-size:14px; color:var(--ink-secondary); margin:0 0 12px; }
    .diagnosis-preview .unified-assistant { display:block; height:auto; padding:0; background:transparent; border:0; overflow:visible; }
    .diagnosis-preview .ai-debug-message { display:block; margin:0 0 14px; padding:16px; border:1px solid var(--line-default); border-radius:12px; background:var(--surface-card); }
    .diagnosis-preview .wiring-review-card { margin:0; }
    @media(max-width:740px) { .diagnosis-preview { padding:16px; } .diagnosis-preview-grid { grid-template-columns:minmax(0,440px); justify-content:center; gap:24px; } }
  `}</style>
  <header><h1>簡易接線除錯</h1><p>隔離預覽 · 示例資料，非實體接線判定 · 不會操作相機或 Pi</p></header>
  <main className="diagnosis-preview-grid">
    <section className="unified-assistant" aria-label="對話結果預覽"><h2>對話結果</h2>
      <article className="ai-debug-message"><WiringChatMessage message={message(suspected)} review={review} onAction={noAction} /></article>
      <article className="ai-debug-message"><WiringChatMessage message={message(uncertain)} review={review} onAction={noAction} /></article>
    </section>
    <section aria-label="接線卡片預覽"><h2>接線卡片</h2><WiringReviewCard review={review} components={[{ id: 'hc-sr04', label: 'HC-SR04+' }]}
      onAction={noAction} onReview={noAction} captureReady /></section>
  </main>
</div>);
