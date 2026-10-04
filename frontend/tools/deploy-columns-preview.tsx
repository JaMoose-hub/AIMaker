// Isolated layout fixture: real deployment components, no hardware/API access.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {LocaleProvider} from '../src/lib/i18n';
import {AssistantWorkspace} from '../src/components/AssistantWorkspace';
import {PiDeployPanel} from '../src/components/PiDeployPanel';
import {WorkspaceHeader} from '../src/components/WorkspaceHeader';
import '../src/maker.css';
import '../src/styles.css';
import '../src/debug.css';
import '../src/responsive.css';
import '../src/tinkro.css';
import '../src/assistant.css';

const sample=Array.from({length:90},(_,i)=>`print("Preview distance sample ${i}")`).join('\n');
const project:any={id:'deploy-layout-fixture',source:'demo',title:'桌上型距離與顯示監測器',component_ids:['hc-sr04','mrd-tf240-8p-cs'],unresolved:[]};
function Preview(){
  const [code,setCode]=useState(sample),[aiOpen,setAiOpen]=useState(true);
  return <div className="app maker-layout tinkro-theme maker-stage-deploy"><main className="main">
    <WorkspaceHeader saveStatus={null}
      brand={<div className="brand"><div className="brand-text"><img className="brand-logo" src="/brand/tinkro-dark.png" alt="Tinkro"/><small className="brand-subtitle">Vibe Maker<br/>Studio</small></div></div>}
      navigation={<nav className="maker-nav" aria-label="作品工作流程"><button><span>01</span>設計與藍圖</button><button><span>02</span>接線引導＋AI 除錯</button><button className="active"><span>03</span>部署與執行</button></nav>}>
      <button aria-label="手機連線">手機</button><button aria-label="Pi 連線">Pi</button><button aria-label="設定">⚙</button>
    </WorkspaceHeader>
    <AssistantWorkspace aiOpen={aiOpen} onAiOpen={setAiOpen} assistant={<section className="unified-assistant">
      <header className="unified-assistant-heading"><div><strong>Tinkro AI</strong><small>03 · 程式與輸出</small></div></header>
      <div className="unified-message-list"><article className="ai-debug-message is-assistant"><header><strong>Tinkro AI</strong></header>
        <p className="assistant-message-text">左側修改作品程式，右側查看執行輸出。這是隔離排版預覽，沒有連接 Pi 或執行硬體。</p></article></div>
      <label className="unified-composer">AI 對話<textarea aria-label="AI 對話" placeholder="提問或修改都可以；操作由你確認。"/></label>
    </section>}><div className="assistant-project-workspace"><div className="maker-deploy-main">
      <PiDeployPanel project={project} draft={code} onDraftChange={setCode}/>
    </div></div></AssistantWorkspace>
  </main></div>;
}
window.fetch=async()=>{throw Error('Network actions disabled in isolated deployment preview');};
window.WebSocket=class {constructor(){throw Error('WebSockets disabled in isolated deployment preview');}} as any;
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview/></LocaleProvider>);
