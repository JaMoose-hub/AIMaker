// Isolated QA only: real card/helper/assistant hooks, simulated transport.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { initialMaker, makerCatalog, wireSignature, enterDebug } from '../src/lib/maker';
import { componentTestKey } from '../src/lib/componentTests';
import { componentTestHelpRequest } from '../src/lib/componentTestHelp';
import { useAssistant } from '../src/lib/assistant';
import { ComponentTestCard } from '../src/components/ComponentTestCard';
import { UnifiedAssistant } from '../src/components/UnifiedAssistant';
import MobileWebApp from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/maker.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import '../src/debug.css';

localStorage.setItem('boardvision.locale.v1', 'zh-TW');
localStorage.setItem('boardvision.assistant.v1', 'help-fixture-conversation');
localStorage.removeItem('boardvision.assistant-demo.v1.open');
document.documentElement.dataset.theme = 'dark';
class FixtureSocket { readyState = 1; close() { this.readyState = 3; } }
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
const design: any = { id: 'help-fixture-project', revision: 2, catalog_version: makerCatalog.version,
    profile_versions: {}, title: '隔離測試協助', summary: 'Synthetic UI QA only', component_ids: makerCatalog.modules.map(m => m.id),
    wiring: makerCatalog.modules.flatMap(m => m.steps.map(w => ({ ...w, id: `${m.id}:${w.id}`, componentId: m.id }))),
    code: '# synthetic fixture, never executed', unresolved: [], bom: [], instructions: [], tests: [], features: [] };
function Preview() {
    const scenario = new URLSearchParams(location.search).get('scenario') ?? 'failed';
    const selected = new URLSearchParams(location.search).get('component') ?? 'hc-sr04';
    const [state, setState] = useState<any>(() => ({ ...initialMaker(), stage: 'guide', design, code: design.code, aiModel: 'offline-fixture', prompt: '保留我的未送出草稿',
        guide: { ...initialMaker().guide, run: 2, phase: 'review', componentIndex: design.component_ids.indexOf(selected),
            confirmed: Object.fromEntries(design.wiring.map((w: any) => [w.id, { signature: wireSignature(w), at: 100 }])) } }));
    const controller = useAssistant(state, setState, null, null, 'offline-fixture');
    const hardwareCalls: string[] = [];
    const run: any = { id: `help-fixture-${selected}-${scenario}`, project_id: design.id, revision: scenario === 'old-version' ? 1 : design.revision,
        component_id: selected, guide_key: componentTestKey(design, state.guide, selected), template_version: 'fixture', wiring_hash: 'fixture',
        created_at: 100, finished_at: 110, outcome: ['passed', 'failed'].includes(scenario) ? scenario : 'inconclusive',
        phase: 'finished', failed_phase: 'sampling_far', reason: selected === 'hc-sr04' ? 'no_echo' : 'display_black',
        detail: 'Synthetic selected run detail', logs: ['fixture log line: data only'], samples: { near: { count: 0, median_cm: null } },
        latest: null, heartbeat_at: 100, exit_code: 0, reserved: false, program_stopped: true, invalidated: scenario === 'stale', options: [] };
    if (scenario === 'cancelled') run.reason = 'cancelled';
    if (scenario === 'missing-dependency') { run.reason = 'missing_dependency'; run.phase = 'preflight'; run.failed_phase = 'preflight'; run.detail = "ModuleNotFoundError: No module named 'luma'"; }
    const tests: any = { status: { connected: true, test_busy: false, active: null, results: scenario === 'untested' ? [] : [run] },
        pending: false, error: null, start: async () => { hardwareCalls.push('start'); }, action: async () => { hardwareCalls.push('action'); }, connect: async () => { hardwareCalls.push('connect'); } };
    const onDebug = async (cid: string, runId?: string, symptom?: string, evidence?: any) => {
        const snapshot = enterDebug(state, cid, runId, symptom); setState(snapshot);
        if (!evidence) return false;
        const request = componentTestHelpRequest(design, evidence, 'zh-TW');
        return controller.sendTestHelp(snapshot, request.text, request.context);
    };
    const model = { id: 'offline-fixture', name: 'Mock transport only', efforts: ['low'], default_effort: 'low', excluded_efforts: [] };
    const legacy = { ai: { logged_in: true }, busy: false, aiOptions: { options: { models: [model] }, selectedModel: model, selectionValid: true } } as never;
    (window as any).__testHelpQa = { state, run, hardwareCalls, busy: controller.busy, mobileContext: controller.mobileContext, record: controller.record };
    return <main className="app tinkro-theme" style={{ display: 'grid', gridTemplateColumns: 'minmax(350px,1fr) minmax(380px,560px)', gap: 20, padding: 20, height: '100vh' }}>
        <section><h2>隔離 UI QA：{scenario} · {selected}</h2><p>真實測試卡／助手；模擬 API。未執行 Pi、AI 或相機。</p>
            <nav style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>{['failed', 'passed', 'untested', 'cancelled', 'stale', 'old-version', 'missing-dependency'].map(value => <a key={value} href={`/?scenario=${value}`}>{value}</a>)}</nav>
            <ComponentTestCard design={design} session={state.guide} tests={tests} onViewWiring={() => {}} onDebug={onDebug} view="dock" /></section>
        <UnifiedAssistant state={state} setState={setState} controller={controller} legacy={legacy} onNewProject={async () => false} />
    </main>;
}
if (location.pathname === '/phone') localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify({ token: 'synthetic-phone-token', session_id: 'help-fixture-phone',
    conversation_id: 'help-fixture-conversation', context_id: 'help-fixture-context', title: '隔離測試協助', base_url: location.origin }));
createRoot(document.getElementById('root')!).render(<LocaleProvider>{location.pathname === '/phone' ? <MobileWebApp /> : <Preview />}</LocaleProvider>);
