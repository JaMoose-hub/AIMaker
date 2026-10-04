// Isolated QA: actual card, deterministic invitation, assistant and debug hooks.
import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { initialMaker, makerCatalog, wireSignature, enterDebug } from '../src/lib/maker';
import { componentTestKey } from '../src/lib/componentTests';
import { componentTestHelpInvitation, componentTestHelpRequest, currentTestHelpInvitation, type TestHelpInvitation } from '../src/lib/componentTestHelp';
import { useAssistant } from '../src/lib/assistant';
import { useDebugSession } from '../src/lib/debugSessions';
import { ComponentTestCard } from '../src/components/ComponentTestCard';
import { AiDebugPanel } from '../src/components/AiDebugPanel';
import { UnifiedAssistant } from '../src/components/UnifiedAssistant';
import MobileWebApp from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/maker.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import '../src/debug.css';
import '../src/guideAi.css';

localStorage.setItem('boardvision.locale.v1', 'zh-TW');
localStorage.setItem('boardvision.assistant.v1', 'invitation-fixture-conversation');
localStorage.removeItem('boardvision.assistant-demo.v1.open');
document.documentElement.dataset.theme = 'dark';
class FixtureSocket { readyState = 1; close() { this.readyState = 3; } }
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
const noop = () => {};
const design: any = { id: 'invitation-fixture-project', revision: 2, catalog_version: makerCatalog.version,
    profile_versions: {}, title: '隔離拍照邀請 QA', summary: 'Synthetic UI QA only', component_ids: makerCatalog.modules.map(m => m.id),
    wiring: makerCatalog.modules.flatMap(m => m.steps.map(w => ({ ...w, id: `${m.id}:${w.id}`, componentId: m.id }))),
    code: '# synthetic fixture, never executed', unresolved: [], bom: [], instructions: [], tests: [], features: [] };
function Preview() {
    const scenario = new URLSearchParams(location.search).get('scenario') ?? 'failed';
    const selected = new URLSearchParams(location.search).get('component') ?? 'hc-sr04';
    const [state, setState] = useState<any>(() => ({ ...initialMaker(), stage: 'guide', design, code: design.code, aiModel: 'offline-fixture', prompt: '保留我的未送出草稿',
        guide: { ...initialMaker().guide, run: 2, phase: 'review', componentIndex: design.component_ids.indexOf(selected),
            confirmed: Object.fromEntries(design.wiring.map((w: any) => [w.id, { signature: wireSignature(w), at: 100 }])) } }));
    const [invitation, setInvitation] = useState<TestHelpInvitation | null>(null);
    const [actionTarget, setActionTarget] = useState<{ invitationId: string; element: HTMLDivElement } | null>(null);
    const session = useDebugSession(design.id, true);
    const controller = useAssistant(state, setState, session.conversation, session.record, 'offline-fixture');
    const latest = useRef({ state, controller }); latest.current = { state, controller };
    const hardwareCalls = useRef<string[]>([]);
    const run: any = { id: `invitation-fixture-${selected}-${scenario}`, project_id: design.id, revision: scenario === 'old-version' ? 1 : design.revision,
        component_id: selected, guide_key: componentTestKey(design, state.guide, selected), template_version: 'fixture', wiring_hash: 'fixture',
        created_at: 100, finished_at: 110, outcome: ['passed', 'failed'].includes(scenario) ? scenario : 'inconclusive',
        phase: 'finished', failed_phase: 'sampling_far', reason: selected === 'hc-sr04' ? 'no_echo' : 'display_black',
        detail: 'Synthetic selected run detail', logs: ['fixture log line: data only'], samples: { near: { count: 0, median_cm: null } },
        latest: null, heartbeat_at: 100, exit_code: 0, reserved: false, program_stopped: true, invalidated: scenario === 'stale', options: [] };
    if (scenario === 'cancelled') run.reason = 'cancelled';
    if (scenario === 'missing-dependency') { run.reason = 'missing_dependency'; run.phase = 'preflight'; run.failed_phase = 'preflight'; run.detail = "ModuleNotFoundError: No module named 'luma'"; }
    const tests: any = { status: { connected: true, test_busy: false, active: null, results: scenario === 'untested' ? [] : [run] }, pending: false, error: null,
        start: async () => { hardwareCalls.current.push('start'); }, action: async () => { hardwareCalls.current.push('action'); }, connect: async () => { hardwareCalls.current.push('connect'); } };
    const onDebug = async (cid: string, runId?: string, symptom?: string, evidence?: any) => {
        const snapshot = enterDebug(state, cid, runId, symptom); setState(snapshot);
        if (!evidence) return false;
        const request = componentTestHelpRequest(design, evidence, 'zh-TW');
        const next = componentTestHelpInvitation(design, evidence, 'zh-TW', { id: crypto.randomUUID(), guideKey: componentTestKey(design, snapshot.guide, cid),
            guideRun: snapshot.guide.run ?? 0, contextEpoch: controller.project?.context_epoch ?? 0 });
        const accepted = await controller.offerTestHelp(snapshot, next, request.context);
        const current = latest.current;
        if (accepted && current.state.design === snapshot.design && current.state.code === snapshot.code
            && currentTestHelpInvitation(next, current.state.design, current.state.guide, current.controller.project?.context_epoch ?? 0)) setInvitation({ ...next, messageId: accepted });
        return Boolean(accepted);
    };
    const visibleInvitation = currentTestHelpInvitation(invitation, state.design, state.guide, controller.project?.context_epoch ?? 0) ? invitation : null;
    const cid = state.debug?.selectedComponentId ?? selected;
    const firstWire = design.wiring.find((wire: any) => wire.componentId === cid);
    const context: any = { project: design, code: state.code, locale: 'zh-TW', entry: state.debug, guide_run: state.guide.run,
        guide_confirmations: state.guide.confirmed, test_keys: Object.fromEntries(design.component_ids.map((id: string) => [id, componentTestKey(design, state.guide, id)])),
        wiring_target: { component_id: cid, wire_id: firstWire.id } };
    const tools = <AiDebugPanel state={state} context={context} currentCodeHash="fixture-code-hash" session={session} webcamReady eyeActive={false}
        cameraSource="device" cameraRuntimeRevision={1} repairCaseId={null} repairAppliedHash={null} repairCandidateReady={false} onReturnWebcam={noop}
        onCase={noop} onRetest={noop} onTrial={noop} onReviewRepair={noop} onManual={noop} onWiring={noop} onReviewGuideChange={(guide, expected) => {
            if (latest.current.state === expected) setState((current: any) => ({ ...current, guide })); }}
        testHelpInvitation={visibleInvitation} onTestHelpHandled={id => setInvitation(current => current?.id === id ? null : current)}
        testHelpActionTarget={actionTarget?.invitationId === visibleInvitation?.id ? actionTarget?.element : null}
        actionsOnly variant="wiring" wiringTarget={context.wiring_target} />;
    const model = { id: 'offline-fixture', name: 'Mock transport only', efforts: ['low'], default_effort: 'low', excluded_efforts: [] };
    const legacy = { ai: { logged_in: true }, busy: false, aiOptions: { options: { models: [model] }, selectedModel: model, selectionValid: true } } as never;
    (window as any).__invitationQa = { state, run, invitation: visibleInvitation, hardwareCalls: hardwareCalls.current, busy: controller.busy,
        mobileContext: controller.mobileContext, record: controller.record, debugRecord: session.record };
    return <main className="app tinkro-theme" style={{ display: 'grid', gridTemplateColumns: 'minmax(350px,1fr) minmax(400px,560px)', gap: 20, padding: 20, height: '100vh' }}>
        <section><h2>隔離邀請 QA：{scenario} · {selected}</h2><p>真實測試卡／助手／拍照引導；模擬 API。未執行 Pi、AI 或相機。</p>
            <ComponentTestCard design={design} session={state.guide} tests={tests} onViewWiring={noop} onDebug={onDebug} view="dock" /></section>
        <UnifiedAssistant state={state} setState={setState} controller={controller} legacy={legacy} debugTools={tools} onNewProject={async () => false}
            testHelpFocus={visibleInvitation?.id} testHelpText={visibleInvitation?.text} testHelpMessageId={visibleInvitation?.messageId} onTestHelpActionTargetChange={setActionTarget} />
    </main>;
}
if (location.pathname === '/phone') localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify({ token: 'synthetic-phone-token', session_id: 'invitation-fixture-phone',
    conversation_id: 'invitation-fixture-conversation', context_id: 'invitation-fixture-context', title: '隔離拍照邀請 QA', base_url: location.origin }));
createRoot(document.getElementById('root')!).render(<LocaleProvider>{location.pathname === '/phone' ? <MobileWebApp /> : <Preview />}</LocaleProvider>);
