// Real desktop/mobile chat components with a closed synthetic loopback transport.
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { initialMaker, makerCatalog, makerRequest } from '../src/lib/maker';
import { confirmReviewedWire, unconfirmReviewedWire, invalidateReviewedComponent, contextWithReviewGuide } from '../src/lib/wiringReviewGuide';
import { componentTestKey } from '../src/lib/componentTests';
import { componentTestHelpInvitation, componentTestHelpRequest, currentTestHelpInvitation, type TestHelpInvitation } from '../src/lib/componentTestHelp';
import { useAssistant, type AssistantMessage, type AssistantWiringFlowResult } from '../src/lib/assistant';
import { guideFromWiringReceipt } from '../src/lib/wiringReceipt';
import { useDebugSession } from '../src/lib/debugSessions';
import { AiDebugPanel } from '../src/components/AiDebugPanel';
import { UnifiedAssistant } from '../src/components/UnifiedAssistant';
import MobileWebApp from '../src/components/MobileWebApp';
import type { WiringReviewAction } from '../src/lib/wiringReview';
import type { DebugSession } from '../src/lib/debug';
import '../src/styles.css';
import '../src/maker.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import '../src/debug.css';
import '../src/guideAi.css';

const qa = { errors: [] as string[], cameraOpens: 0, hardwareCalls: [] as string[] };
(window as any).__wiringChatQA = qa;
window.addEventListener('error', e => qa.errors.push(e.message));
window.addEventListener('unhandledrejection', e => qa.errors.push(String(e.reason)));
const consoleError = console.error.bind(console);
console.error = (...values) => { qa.errors.push(values.map(String).join(' ')); consoleError(...values); };
class FixtureSocket { static OPEN = 1; static CONNECTING = 0; static CLOSED = 3; readyState = 1; close() { this.readyState = 3; } }
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => { qa.cameraOpens++; throw Error('This fixture cannot open a real camera.'); };
document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
localStorage.setItem('boardvision.locale.v1', 'zh-TW');
localStorage.setItem('boardvision.assistant.v1', 'wiring-chat-conversation');
localStorage.removeItem('boardvision.assistant-demo.v1.open');
const noop = () => {};
const module = makerCatalog.modules.find(m => m.id === 'hc-sr04')!;
const design: any = { id: 'wiring-chat-project', revision: 2, catalog_version: makerCatalog.version, profile_versions: {},
  title: '聊天接線核對 · 隔離 QA', summary: 'Synthetic UI validation only', component_ids: ['hc-sr04'],
  wiring: module.steps.map(step => ({ ...step, id: `hc-sr04:${step.id}`, componentId: 'hc-sr04' })),
  code: '# synthetic code; never executed', unresolved: [], bom: [], instructions: [], tests: [], features: [] };

function Preview() {
  const [state, setState] = useState<any>(() => ({ ...initialMaker(), stage: 'guide', design, code: design.code, aiModel: 'offline-fixture',
    prompt: '保留我的未送出草稿', debug: { componentId: 'hc-sr04', runId: 'synthetic-failed-test', symptom: 'no_echo' },
    guide: { ...initialMaker().guide, run: 2, phase: 'review', componentIndex: 0 } }));
  const [target, setTarget] = useState<{ invitationId: string; element: HTMLDivElement } | null>(null);
  const [handled, setHandled] = useState('');
  const session = useDebugSession(design.id, true);
  const controller = useAssistant(state, setState, session.conversation, session.record, 'offline-fixture');
  const firstWire = design.wiring[0];
  const context: any = { project: design, code: state.code, locale: 'zh-TW', entry: state.debug, guide_run: 2, guide_confirmations: state.guide.confirmed,
    test_keys: { 'hc-sr04': componentTestKey(design, state.guide, 'hc-sr04') }, wiring_target: { component_id: 'hc-sr04', wire_id: firstWire.id } };
  const invitationMessage = controller.project?.messages.findLast(m => m.test_help_offer && ['pending', 'started'].includes(m.test_help_offer.state));
  const offer = invitationMessage?.test_help_offer;
  const invitation: TestHelpInvitation | null = offer && invitationMessage ? { id: offer.offer_id, messageId: invitationMessage.id,
    canAct: offer.can_act, canDismiss: offer.can_dismiss, projectId: offer.project_id, revision: offer.project_revision,
    componentId: offer.component_id, guideKey: offer.guide_key, guideRun: offer.guide_run, contextEpoch: offer.context_epoch, mode: offer.mode, text: invitationMessage.text } : null;
  const visible = invitation && handled !== invitation.id && currentTestHelpInvitation(invitation, design, state.guide, controller.project?.context_epoch ?? 0) ? invitation : null;
  const flight = useRef(false);
  const latest = useRef(state); latest.current = state;
  function applyDecision(result: AssistantWiringFlowResult) {
    if (!result.outbox) return false;
    const epoch = controller.project?.context_epoch ?? 0, conversationId = controller.mobileContext.conversation_id;
    const guide = guideFromWiringReceipt(latest.current, result.outbox, result.guide_receipt, result.debug_session, conversationId, epoch);
    if (!guide || !session.adoptReview(result.debug_session)) return false;
    setState((current: any) => {
      const recovered = guideFromWiringReceipt(current, result.outbox!, result.guide_receipt, result.debug_session, conversationId, epoch);
      return recovered ? { ...current, guide: recovered } : current;
    });
    controller.acknowledgeWiringFlow(result.outbox.request_id);
    return true;
  }
  async function recoverDecision(retryMissing = true) {
    const result = await controller.recoverWiringFlow(retryMissing);
    return Boolean(result && applyDecision(result));
  }
  useEffect(() => {
    if (controller.wiringReceiptPending && !controller.pending && !session.pending) void recoverDecision(false);
  }, [controller.wiringReceiptRequestId, controller.wiringReceiptPending, controller.pending, session.pending]);
  const linked = controller.project?.messages.findLast(m => m.wiring_flow?.current && m.epoch === controller.project?.context_epoch && m.round === 2);
  useEffect(() => {
    const flow = linked?.wiring_flow, id = linked?.session_id;
    if (!flow || !id || session.pending || session.record?.id === id) return;
    let cancelled = false;
    void makerRequest<DebugSession>(`debug/sessions/${encodeURIComponent(id)}`).then(next => {
      if (!cancelled && next.wiring_review?.id === flow.review_id && next.wiring_review.revision === flow.revision && next.wiring_review.round === flow.round) session.adoptReview(next);
    }).catch(controller.reportError);
    return () => { cancelled = true; };
  }, [linked?.id, linked?.wiring_flow?.revision, session.record?.id, session.pending]);
  const onFlow = async (message: AssistantMessage, action: WiringReviewAction) => {
    const original = state, live = session.record;
    if (flight.current || controller.wiringReceiptPending || !live || live.wiring_review?.id !== message.wiring_flow?.review_id || live.wiring_review?.revision !== message.wiring_flow?.revision) return false;
    flight.current = true;
    const unchanged = () => latest.current.design === original.design && latest.current.code === original.code && latest.current.guide === original.guide;
    try {
      let guide = original.guide;
      const retracting = action.op === 'review' && action.decision !== 'confirmed' && Boolean(action.wire_id && guide.confirmed[action.wire_id]);
      if (action.op === 'changed' || retracting || action.op === 'review' && action.decision === 'needs_change') {
        const prepared = await session.action('prepare_wiring', context, undefined, live.response_mode, undefined, live.id);
        if (!prepared?.wiring_edit_ready || !unchanged()) throw Error('Synthetic prepare_wiring did not reconcile the current context.');
      }
      if (action.op === 'changed') guide = invalidateReviewedComponent(design, guide, action.component_id);
      else if (action.op === 'review' && action.wire_id) guide = action.decision === 'confirmed'
        ? confirmReviewedWire(design, guide, action.wire_id) : unconfirmReviewedWire(design, guide, action.wire_id);
      const nextContext = contextWithReviewGuide(context, design, guide);
      if (!unchanged()) return false;
      const result = await controller.wiringFlowAction(message, action, nextContext);
      if (!result || !unchanged()) return false;
      if (result.outbox) return applyDecision(result);
      if (!session.adoptReview(result.debug_session)) return false;
      return true;
    } catch (cause) { if (unchanged()) controller.reportError(cause); return false; }
    finally { flight.current = false; }
  };
  async function simulateFailure() {
    setHandled('');
    const evidence: any = { componentId: 'hc-sr04', outcome: 'failed', reason: 'no_echo', historical: false, stale: false,
      run: { id: 'synthetic-failed-test', project_id: design.id, revision: design.revision, component_id: 'hc-sr04', outcome: 'failed',
        reason: 'no_echo', phase: 'finished', failed_phase: 'sampling_far', exit_code: 0, samples: {}, logs: [], detail: 'Synthetic diagnostic only' } };
    const next = componentTestHelpInvitation(design, evidence, 'zh-TW', { id: crypto.randomUUID(), guideKey: context.test_keys['hc-sr04'],
      guideRun: 2, contextEpoch: controller.project?.context_epoch ?? 0 });
    await controller.offerTestHelp(state, next, componentTestHelpRequest(design, evidence, 'zh-TW').context);
  }
  const tools = <AiDebugPanel state={state} context={context} currentCodeHash="synthetic-code-hash" session={session} webcamReady eyeActive={false}
    cameraSource="device" cameraRuntimeRevision={1} repairCaseId={null} repairAppliedHash={null} repairCandidateReady={false} onReturnWebcam={noop}
    onCase={noop} onRetest={() => qa.hardwareCalls.push('unexpected-retest')} onTrial={() => qa.hardwareCalls.push('unexpected-trial')}
    onReviewRepair={noop} onManual={noop} onWiring={noop} testHelpInvitation={visible}
    onReviewGuideChange={(guide, expected) => { if (latest.current === expected) setState((current: any) => current === expected ? { ...current, guide } : current); }}
    onTestHelpHandled={setHandled} onTestHelpAction={async (value, op) => {
      const result = await controller.testHelpAction(value, op); if (!result) return false;
      if (op === 'later') return true;
      return result.debug_session && session.adoptReview(result.debug_session) ? result.debug_session : false;
    }} testHelpActionTarget={target && visible && target.invitationId === visible.id ? target.element : null} actionsOnly chatGuidance variant="wiring" wiringTarget={context.wiring_target} />;
  const model = { id: 'offline-fixture', name: 'Synthetic transport', efforts: ['low'], default_effort: 'low', excluded_efforts: [] };
  const legacy = { ai: { logged_in: true }, busy: false, aiOptions: { options: { models: [model] }, selectedModel: model, selectionValid: true } } as never;
  Object.assign(qa, { state, conversation: controller.record, review: session.record?.wiring_review, busy: controller.busy });
  return <main className="app tinkro-theme wiring-chat-preview" style={{ display: 'grid', gridTemplateColumns: 'minmax(200px, 300px) minmax(0, 620px)', justifyContent: 'center', gap: 20, padding: 20, height: '100vh' }}>
    <style>{'@media(max-width:700px){.wiring-chat-preview{grid-template-columns:minmax(0,1fr)!important;padding:8px!important;gap:8px!important}.wiring-chat-preview>aside{display:none}}'}</style>
    <aside><h2>聊天接線核對 QA</h2><p>真實桌面／手機聊天元件；隔離 API 與合成照片。</p><p>没有執行 AI、相機或 Pi。</p>
      <button type="button" onClick={() => void simulateFailure()}>模擬測試失敗，請 AI 幫忙</button><p><a href="/phone" target="_blank">手機預覽</a></p></aside>
    <UnifiedAssistant state={state} setState={setState} controller={controller} legacy={legacy} debugTools={tools} onNewProject={async () => false}
      testHelpFocus={visible?.id} testHelpText={visible?.text} testHelpMessageId={visible?.messageId} onTestHelpActionTargetChange={setTarget}
      wiringReview={session.record?.wiring_review} onWiringFlowAction={onFlow} onWiringReceiptRetry={() => recoverDecision(true)}
      onStartWiringReview={async componentId => { const result = await controller.startWiringReview(componentId); return Boolean(result && session.adoptReview(result.debug_session)); }} />
  </main>;
}
if (location.pathname === '/phone') localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify({ token: 'synthetic-wiring-chat-token',
  session_id: 'wiring-chat-phone', conversation_id: 'wiring-chat-conversation', context_id: 'wiring-chat-context', title: '聊天接線核對', base_url: location.origin }));
createRoot(document.getElementById('root')!).render(<LocaleProvider>{location.pathname === '/phone' ? <MobileWebApp /> : <Preview />}</LocaleProvider>);
