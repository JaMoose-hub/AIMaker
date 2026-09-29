// Real UI components with synthetic state. Bundled only by tinkro-preview.mjs.
// No camera, Pi, cloud, production storage or production API is reachable.
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {LocaleProvider, useI18n} from '../src/lib/i18n';
import {initialMaker, makerCatalog, type MakerStage} from '../src/lib/maker';
import {MakerSplitLayout} from '../src/components/MakerSplitLayout';
import {MakerAssistant} from '../src/components/MakerAssistant';
import {DesignStudio} from '../src/components/DesignStudio';
import {BlueprintPage} from '../src/components/BlueprintPage';
import {ProjectGuidePanel} from '../src/components/ProjectGuidePanel';
import {DebugPage} from '../src/components/DebugPage';
import {AiDebugPanel} from '../src/components/AiDebugPanel';
import {PiDeployPanel} from '../src/components/PiDeployPanel';
import {PiConnectionControl} from '../src/components/PiConnectionControl';
import '../src/maker.css';
import '../src/styles.css';
import '../src/debug.css';
import '../src/responsive.css';
import '../src/tinkro.css';

const deny = () => { throw Error('Hardware/cloud actions are disabled in this isolated preview'); };
const noop = () => {};
const illustration = 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="1000" height="700" fill="#eef3f9"/><g fill="none" stroke="#417abe" stroke-width="5"><ellipse cx="500" cy="470" rx="290" ry="95"/><ellipse cx="500" cy="300" rx="290" ry="95"/><path d="M250 340v170m500-170v170M350 260v190m300-190v190"/><rect x="375" y="165" width="250" height="190" rx="20"/></g><rect x="395" y="185" width="210" height="145" rx="8" fill="#203065"/><text x="500" y="263" text-anchor="middle" font-family="sans-serif" font-size="36" fill="#fff">20.0 cm</text><circle cx="420" cy="390" r="37" fill="#16b9a6"/><circle cx="520" cy="390" r="37" fill="#16b9a6"/><text x="500" y="635" text-anchor="middle" font-family="sans-serif" font-size="22" fill="#52627b">Layout fixture · not a generated design</text></svg>`);
const project:any = {
  id:'tinkro-ui-fixture',revision:1,source:'demo',catalog_version:makerCatalog.version,
  title:'桌上型距離監測器',summary:'前方物體靠近時，在螢幕顯示距離與警告。上下兩層壓克力圓盤由支柱固定。',
  component_ids:makerCatalog.modules.map(m=>m.id),parameters:{distance_cm:20,sample_ms:200},
  wiring:makerCatalog.modules.flatMap(m=>m.steps.map(w=>({...w,componentId:m.id}))),
  bom:[{id:'pi',name:'Raspberry Pi 5',quantity:1,price:2500,purpose:'控制與執行程式'},...makerCatalog.modules.map(m=>({id:m.id,name:m.name['zh-TW'],quantity:1,price:150,purpose:m.functionalTest['zh-TW']}))],
  instructions:['斷電後依照 Blueprint 逐條接線。','接好一個零件，即可執行固定功能測試。'],tests:[],unresolved:[],features:[],
  code:'# Tinkro · isolated preview\nwhile True:\n    distance = read_distance()\n    display_distance(distance)\n',logic:'',requirements:{imports:[],devices:[]},
  image:{url:illustration,width:1000,height:700},assembly:{description:'兩層圓盤與支柱，僅示範結構。',parts:[{kind:'standoff',quantity:4},{kind:'acrylic-panel',quantity:2}]},
};
const session:any = {pending:false,error:'',create:deny,action:deny,contextChanged:noop,
  record:{id:'ui-session',status:'stopped',phase:'stopped',model:'offline-fixture',instruction:'這是模擬檢查紀錄，並未測試實體硬體。',updated_at:Date.now()/1000,
    evidence:[],jobs:[],test_results:[],observations:[],messages:[
      {id:'1',role:'user',created_at:Date.now()/1000,text:'螢幕沒有顯示距離，可以幫我看看嗎？'},
      {id:'2',role:'assistant',created_at:Date.now()/1000,text:'先確認螢幕是否亮起。我們會一次檢查一個零件；需要測試或停止目前作品時，會先請你確認。這是隔離 UI 預覽，沒有使用相機或執行硬體。'},
    ]}};

function Preview() {
  const {t,locale,setLocale}=useI18n();
  const [state,setState]=useState<any>({...initialMaker(),design:project,code:project.code,
    conversation:[{role:'user',text:'我想做一個放在桌上的距離監測器。'},{role:'assistant',text:'我們可以用 Pi 5、超音波感測器和螢幕。先看看右邊的概念，再一起準備接線。'}]});
  const stage:MakerStage=state.stage;
  const navigate=(stage:MakerStage)=>setState((s:any)=>({...s,stage}));
  const assistant:any={ai:{logged_in:true},aiOptions:{estimate:{},selectionValid:true},busy:false,error:'',phase:'design',generate:deny,retryImage:deny,
    loadDemo:()=>setState((s:any)=>({...s,candidate:project})),clearConversation:()=>setState((s:any)=>({...s,conversation:[]}))};
  return <div className={`app tinkro-theme pi-deploy-layout maker-layout maker-stage-${stage}${stage==='guide'?' maker-wiring-full-width':''}`}><main className="main">
    <header className="header maker-header"><div className="brand"><div className="brand-text"><h1 className="brand-title"><img className="brand-logo" src="/brand/tinkro-dark.png" alt="Tinkro" width={152} height={48}/></h1><div className="brand-subtitle">{t('app.subtitle')}</div></div></div><small className="maker-save-status">隔離預覽 · 模擬資料 · 不連接硬體</small>
      <div className="workspace-toolbar maker-workflow-toolbar"><nav className="maker-nav" aria-label="作品工作流程">{(['design','blueprint','guide','debug','deploy'] as MakerStage[]).map((name,i)=><button key={name} className={stage===name?'active':''} aria-current={stage===name?'step':undefined} onClick={()=>navigate(name)}><span>0{i+1}</span>{(locale==='en'?['Design','Blueprint','Pin wiring','Test & debug','Deploy & run']:['設計作品','Blueprint','Pin 接線引導','測試與除錯','部署與執行'])[i]}</button>)}</nav>
      <div className="maker-model-menu"><span className="maker-model-label">AI 模型</span><div className="maker-model-value">Offline preview</div></div><PiConnectionControl/>
      <div className="runtime-toolbar"><label className="runtime-select"><span>控制器</span><select defaultValue="pi"><option value="pi">Raspberry Pi 5</option></select></label><label className="runtime-select locale-select"><span>語言</span><select value={locale} onChange={e=>setLocale(e.target.value)}><option value="zh-TW">繁體中文</option><option value="en">English</option></select></label></div></div>
    </header>
    {stage==='design'?<MakerSplitLayout stage="design" left={<MakerAssistant state={state} setState={setState} assistant={assistant} onReview={()=>navigate('design')}/>}><DesignStudio state={state} setState={setState} onAdopt={()=>navigate('blueprint')}/></MakerSplitLayout>:null}
    {stage==='blueprint'?<BlueprintPage design={project} hasCandidate={false} generating={false} onGuide={()=>navigate('guide')} onEdit={()=>navigate('design')}/>:null}
    {stage==='guide'||stage==='debug'?<div className="video-guide-stage">
      {stage==='debug'?<div className="debug-camera-toolbar"><strong>Webcam 即時畫面</strong><span>無相機的排版預覽</span><button>選擇鏡頭</button><button>智慧調整</button></div>:<button className="guide-visibility-toggle">接線引導 · 模擬畫面</button>}
      <div className="video-shell" style={{display:'grid',placeItems:'center',background:'#111b30'}}><div style={{textAlign:'center',padding:24}}><img src="/brand/tinkro-symbol.svg" alt="" width={64} height={64}/><h2>Camera workspace</h2><p>保留鏡頭畫面與 GPIO 疊圖座標</p><small>隔離測試不啟動鏡頭、AI 或 Pi</small></div></div>
      {stage==='guide'?<ProjectGuidePanel design={project} session={state.guide} visible disabled={false} pinsById={new Map()} onChange={guide=>setState((s:any)=>({...s,guide}))} onTargetChange={noop} onVisibleChange={noop} onDeploy={()=>navigate('deploy')} onDebug={()=>navigate('debug')}/>:null}
    </div>:null}
    {stage==='debug'?<DebugPage state={state} onCase={noop} onCode={noop} onWiring={()=>navigate('guide')} onDeploy={()=>navigate('deploy')} onSelect={cid=>setState((s:any)=>({...s,debug:{selectedComponentId:cid}}))} assistant={({context,codeHash,onRetest,onTrial,onReviewRepair,onManual})=><AiDebugPanel state={state} context={context} currentCodeHash={codeHash} session={session} webcamReady eyeActive={false} cameraSource="device" cameraRuntimeRevision={1} onReturnWebcam={deny} onCase={noop} onRetest={onRetest} onTrial={onTrial} onReviewRepair={onReviewRepair} onManual={onManual} onWiring={()=>navigate('guide')}/>}/>:null}
    {stage==='deploy'?<div className="maker-deploy-main"><PiDeployPanel project={project} draft={state.code} onDraftChange={code=>setState((s:any)=>({...s,code}))} onDebug={()=>navigate('debug')}/></div>:null}
  </main></div>;
}
// These are assertions, not mocks returning successful hardware responses.
window.fetch=async()=>{throw Error('Unexpected network request in isolated preview');};
window.WebSocket=class {constructor(){throw Error('Unexpected WebSocket in isolated preview');}} as any;
localStorage.setItem('boardvision.locale.v1','zh-TW');
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview/></LocaleProvider>);
