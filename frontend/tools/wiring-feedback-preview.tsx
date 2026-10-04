// Loopback UI evidence only. Real components, synthetic observations and readings.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { initialMaker, makerCatalog, wireSignature } from '../src/lib/maker';
import { componentTestKey } from '../src/lib/componentTests';
import { WiringChatMessage } from '../src/components/WiringChatMessage';
import { MobileWiringChatActions } from '../src/components/MobileWebApp';
import { ComponentTestCard } from '../src/components/ComponentTestCard';
import '../src/styles.css';
import '../src/maker.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import '../src/debug.css';

document.documentElement.dataset.theme = 'dark';
localStorage.setItem('boardvision.locale.v1', 'zh-TW');
const module = makerCatalog.modules.find(item => item.id === 'hc-sr04')!;
const design: any = { id: 'feedback-qa', revision: 1, catalog_version: makerCatalog.version, profile_versions: {},
  component_ids: ['hc-sr04'], wiring: module.steps.map(w => ({ ...w, id: `hc-sr04:${w.id}`, componentId: 'hc-sr04' })) };
const guide: any = { ...initialMaker().guide, componentIndex: 0,
  confirmed: Object.fromEntries(design.wiring.map((w: any) => [w.id, { signature: wireSignature(w), at: 1 }])) };
const review: any = { id: 'feedback-review', revision: 1, round: 1, component_id: 'hc-sr04', status: 'collecting' };
const baseFlow: any = { flow_id: 'feedback-flow', review_id: review.id, revision: 1, round: 1,
  component_id: 'hc-sr04', current: true, can_act: true };
const photoRequest: any = { id: 'question', role: 'assistant', text: '請拍 Pi 第一側，讓接頭底部與線色看得清楚。',
  epoch: 0, round: 1, wiring_flow: { ...baseFlow, kind: 'photo_request', role: 'pi_side_a', actions: ['capture'] } };
const wireReview: any = { id: 'wire', role: 'assistant', text: '請親自沿線核對 GND，選擇你的確認結果。',
  wiring_flow: { ...baseFlow, kind: 'wire_review', wire_id: 'ground', actions: ['review'],
    result: { wire_id: 'ground', expected: { component_pin: 'GND', physical_pin: 6, bcm: null }, comparison: 'insufficient',
      pi_candidates: [], component_candidates: [], next_step: '照片資訊不足，請沿線確認。' } } };
function testRun(variant: string): any {
  return { id: variant, project_id: design.id, revision: 1, component_id: 'hc-sr04', guide_key: componentTestKey(design, guide, 'hc-sr04'),
    created_at: 100, finished_at: 110, phase: 'finished', reason: variant === 'no-echo' ? 'no_echo' : null,
    outcome: variant === 'no-echo' ? 'inconclusive' : 'passed', reserved: false, invalidated: false, latest: null, heartbeat_at: null,
    samples: variant === 'no-echo' ? { near: { count: 0, median_cm: null }, far: { count: 0, median_cm: null } }
      : { near: { count: 20, median_cm: 15.2 }, far: { count: 20, median_cm: 30.4 } }, logs: [], options: [] };
}
function App() {
  const mobile = new URLSearchParams(location.search).get('surface') === 'mobile';
  const [chosen, setChosen] = useState('');
  const [readingAt] = useState(() => Date.now() / 1000);
  const live = new URLSearchParams(location.search).get('scenario') === 'live';
  if (mobile) {
    const workspace: any = { ready: true, connected: true, busy: false, wiringReviewBusy: false,
      session: { conversation_id: 'chat', context_id: 'context', context: { round: 1 } },
      conversation: { id: 'chat', context_epoch: 0 }, wiringReview: review, wiringCanAct: true, pendingWiringPhoto: null,
      prepareWiringChatPhoto: () => null };
    return <main className="mobile-web-app" style={{ minHeight: '100vh', padding: 14 }}>
      <p>隔離手機 UI 驗證 · 合成資料</p><article className="mw-message is-assistant"><header><strong>Tinkro AI</strong></header>
        <p>{photoRequest.text}</p><MobileWiringChatActions w={workspace} message={photoRequest} /></article>
      <p>未開啟相機、呼叫模型或操作 Pi。</p></main>;
  }
  return <main className="app tinkro-theme" style={{ display: 'block', width: '100%', maxWidth: 1100, margin: '0 auto', padding: 24 }}>
    <header><h2>接線除錯 UI 驗證</h2><p>合成資料 · 真實元件 · 未操作相機、模型或 Pi</p><a href="/?scenario=live">即時距離到期驗證</a></header>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22 }}>
      <section className="unified-assistant"><article className="ai-debug-message is-assistant">
        <strong>Tinkro AI · 拍攝提示</strong><p>{photoRequest.text}</p>
        <WiringChatMessage message={photoRequest} onAction={async () => false} /></article>
        <article className="ai-debug-message is-assistant" style={{ marginTop: 14 }}><strong>Tinkro AI · 人工核對</strong>
          <p>{wireReview.text}</p><WiringChatMessage message={wireReview} onAction={async (_message, action) => { setChosen(action.decision ?? ''); return true; }} />
          {chosen ? <p role="status">合成操作：{chosen}</p> : null}</article></section>
      <section><h3>{live ? '合成即時讀數（2 秒後消退）' : '有效距離紀錄'}</h3><ComponentTestCard design={design} session={guide}
        tests={{ status: { connected: live, active: live ? { ...testRun('live'), reserved: true, phase: 'sampling_near', outcome: 'running',
          latest: { cm: 15.2, at: readingAt }, samples: {} } : null, results: live ? [] : [testRun('valid')] },
          pending: false, error: null, action: async () => false } as any} view="dock" onViewWiring={() => {}} />
        <h3 style={{ marginTop: 24 }}>沒有有效回波</h3><ComponentTestCard design={design} session={guide}
          tests={{ status: { connected: false, active: null, results: [testRun('no-echo')] }, pending: false, error: null } as any} view="dock" onViewWiring={() => {}} /></section>
    </div></main>;
}
createRoot(document.getElementById('root')!).render(<LocaleProvider><App /></LocaleProvider>);
