// Real UI components with synthetic state. Bundled only by tinkro-preview.mjs.
// No camera, Pi, cloud, production storage or production API is reachable.
import React, {useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {LocaleProvider, useI18n} from '../src/lib/i18n';
import {initialMaker, makerCatalog, currentWire, enterDebug, reviewProjectWire, confirmConcept, newMakerProject, wireSignature, validDesign, type MakerStage} from '../src/lib/maker';
import {useMaker} from '../src/lib/useMaker';
import {MAKER_STORAGE} from '../src/lib/makerMigration';
import {MakerSplitLayout} from '../src/components/MakerSplitLayout';
import {MakerAssistant} from '../src/components/MakerAssistant';
import {DesignStudio} from '../src/components/DesignStudio';
import {BlueprintPage} from '../src/components/BlueprintPage';
import {ProjectGuidePanel} from '../src/components/ProjectGuidePanel';
import {DebugPage} from '../src/components/DebugPage';
import {AiDebugPanel} from '../src/components/AiDebugPanel';
import {PiDeployPanel} from '../src/components/PiDeployPanel';
import {PiConnectionControl} from '../src/components/PiConnectionControl';
import {WorkspaceHeader} from '../src/components/WorkspaceHeader';
import {MakerModelMenu} from '../src/components/MakerModelMenu';
import {RuntimeToolbar} from '../src/components/RuntimeToolbar';
import {GuidePaneLayout} from '../src/components/GuidePaneLayout';
import '../src/maker.css';
import '../src/styles.css';
import '../src/debug.css';
import '../src/responsive.css';
import '../src/tinkro.css';
import '../src/guideAi.css';

const deny = () => { throw Error('Hardware/cloud actions are disabled in this isolated preview'); };
const noop = () => {};
const options = new URLSearchParams(location.search);
const languageAudit = options.has('languageAudit');
const replyFixtures:Record<string,Record<string,string>>={
  paragraph:{'zh-TW':'已改成上下雙層圓盤，距離警告設定不變。確認右側預覽後再套用。',en:'The base now uses two round acrylic layers. The distance warning stays unchanged; review the preview before applying it.'},
  bullets:{'zh-TW':'- 圓盤：外型柔和，適合桌面。\n- 方盒：排列整齊，方便擺放。',en:'- Round base: a softer desktop shape.\n- Square base: a tidy, easy-to-place layout.'},
  steps:{'zh-TW':'2. 先確認造型。\n3. 再確認接線；未確認電壓前不要通電。',en:'2. Review the shape first.\n3. Check the wiring; do not power on until voltage is confirmed.'},
  mixed:{'zh-TW':'可以選這兩種配置：\n- 螢幕放上層。\n- 螢幕放前側。\n\n接線仍待確認。',en:'Choose between these layouts:\n- Screen on the upper layer.\n- Screen on the front.\n\nWiring remains unverified.'},
  long:{'zh-TW':'隔離預覽中的歷史長回覆，並非新的模型回覆。'.repeat(30)+'未確認電壓前不要通電。',en:'This deliberately long historical reply is an offline fixture, not a new model response. '.repeat(30)+'Do not power on until voltage is confirmed.'},
};
const headerEvents: string[] = [];
(window as any).__headerQa = {events: headerEvents};
const model = {id:'gpt-6-luna',name:'GPT-6-Luna',efforts:['low','medium','high'],default_effort:'low',excluded_efforts:[],description:'Offline model fixture; no AI request.'};
const controllers:any[] = ['raspberry-pi-5','arduino-uno'].map((board_id,i)=>({board_id,name:{'zh-TW':i?'Arduino Uno':'Raspberry Pi 5',en:i?'Arduino Uno':'Raspberry Pi 5'},active:!i,model:{},pose_landmarks:4,wiring_guide_available:true,electrical_verification_available:false}));
const illustration = 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700"><rect width="1000" height="700" fill="#eef3f9"/><g fill="none" stroke="#417abe" stroke-width="5"><ellipse cx="500" cy="470" rx="290" ry="95"/><ellipse cx="500" cy="300" rx="290" ry="95"/><path d="M250 340v170m500-170v170M350 260v190m300-190v190"/><rect x="375" y="165" width="250" height="190" rx="20"/></g><rect x="395" y="185" width="210" height="145" rx="8" fill="#203065"/><text x="500" y="263" text-anchor="middle" font-family="sans-serif" font-size="36" fill="#fff">20.0 cm</text><circle cx="420" cy="390" r="37" fill="#16b9a6"/><circle cx="520" cy="390" r="37" fill="#16b9a6"/><text x="500" y="635" text-anchor="middle" font-family="sans-serif" font-size="22" fill="#52627b">Layout fixture · not a generated design</text></svg>`);
const project:any = {
  id:'tinkro-ui-fixture',revision:1,source:'demo',catalog_version:makerCatalog.version,
  title:'桌上型距離監測器',summary:'前方物體靠近時，在螢幕顯示距離與警告。上下兩層壓克力圓盤由支柱固定。',
  component_ids:makerCatalog.modules.map(m=>m.id),parameters:{distance_cm:20,sample_ms:200},
  wiring:makerCatalog.modules.flatMap(m=>m.steps.map(w=>({...w,id:`${m.id}:${w.id}`,componentId:m.id}))),
  bom:[{id:'pi',name:'Raspberry Pi 5',quantity:1,price:2500,purpose:'控制與執行程式'},...makerCatalog.modules.map(m=>({id:m.id,name:m.name['zh-TW'],quantity:1,price:150,purpose:m.functionalTest['zh-TW']}))],
  instructions:['斷電後依照 Blueprint 逐條接線。','接好一個零件，即可執行固定功能測試。'],tests:[],unresolved:[],features:[],
  code:'# Tinkro · isolated preview\nwhile True:\n    distance = read_distance()\n    display_distance(distance)\n',logic:'',requirements:{imports:[],devices:[]},
  image:{url:illustration,width:1000,height:700},assembly:{description:'兩層圓盤與支柱，僅示範結構。',parts:[{kind:'standoff',quantity:4},{kind:'acrylic-panel',quantity:2}]},
};
const discardFixture=options.get('discard');
if(options.get('deployState')==='blocked') project.unresolved=[
  'Offline layout fixture: verify the module power specification before deployment.',
  'Offline layout fixture: confirm the wiring configuration. No hardware action was performed.',
  'Offline layout fixture: resolve the remaining design issue before deployment.',
];
if(languageAudit) Object.assign(project,{
  title:'桌上型距離與顯示監測器',
  summary:'ILI9341 顯示 RGB 測試圖；搭配 HC-SR04+ 時顯示真實距離與警告。供電相容性及背光狀態仍需實機核對。',
  instructions:['關閉電源後，依逐腳引導接線。'],
  bom:project.bom.map((item:any)=>({...item,purpose:item.id==='pi'?'控制與執行 / Controller':makerCatalog.modules.find(m=>m.id===item.id)?.name.en??'Offline fixture'})),
  assembly:{...project.assembly,description:'Two acrylic layers with standoffs; offline layout fixture only.',parts:project.assembly.parts.map((part:any)=>({...part,purpose:'Offline layout fixture'}))},
});
const confirmedProject={...project,revision:2,source:'ai',title:'Confirmed project v2',assembly:{...project.assembly,parts:project.assembly.parts.map((part:any)=>({...part,purpose:'Offline layout fixture'}))},image:{id:'a'.repeat(32),url:`/api/design/images/${'a'.repeat(32)}`,width:1000,height:700}};
const unconfirmedProject={...confirmedProject,revision:3,title:'Unconfirmed preview v3',code:'# Unconfirmed preview code',image:{id:'b'.repeat(32),url:`/api/design/images/${'b'.repeat(32)}`,width:1000,height:700}};
// Production storage is unreachable: this entry point is served on its own fixture origin.
if(discardFixture&&!localStorage.getItem(MAKER_STORAGE)){
  if(!validDesign(confirmedProject)||!validDesign(unconfirmedProject))throw Error('Invalid discard fixture');
  const initial=initialMaker();
  localStorage.setItem(MAKER_STORAGE,JSON.stringify({...initial,design:discardFixture==='empty'?null:confirmedProject,candidate:unconfirmedProject,
    code:'# Manual approved draft',prompt:'Keep this unsent input',aiJobId:discardFixture==='busy'?'offline-discard-job':null,
    guide:{...initial.guide,mode:'2d',confirmed:{[project.wiring[0].id]:{signature:wireSignature(project.wiring[0]),mode:'2d',at:'2026-09-30T09:00:00Z'}}},
    conversation:[{role:'user',text:'Keep this conversation'}]}));
}
if(languageAudit&&!localStorage.getItem(MAKER_STORAGE)){
  const initial=initialMaker();
  const localizedFixture={...confirmedProject,source:'demo',title:project.title,summary:project.summary,instructions:project.instructions,bom:project.bom,assembly:project.assembly};
  if(!validDesign(localizedFixture))throw Error('Invalid language fixture');
  localStorage.setItem(MAKER_STORAGE,JSON.stringify({...initial,design:localizedFixture,code:project.code,
    debug:{panelOpen:true,intent:'wiring'},conversation:[{role:'user',text:'保留我原本的中文需求'},{role:'assistant',text:'保留先前中文回覆'}]}));
}
const session:any = {pending:false,error:'',create:deny,action:deny,contextChanged:noop,targetChanged:noop,
  record:{id:'ui-session',status:'stopped',phase:'stopped',model:'offline-fixture',instruction:languageAudit?'本次 AI 協作除錯已停止。':'這是模擬檢查紀錄，並未測試實體硬體。',updated_at:Date.now()/1000,
    evidence:[],jobs:[],test_results:[],observations:[],messages:[
      {id:'1',role:'user',created_at:Date.now()/1000,text:'螢幕沒有顯示距離，可以幫我看看嗎？'},
      {id:'2',role:'assistant',created_at:Date.now()/1000,text:'先確認螢幕是否亮起。我們會一次檢查一個零件；需要測試或停止目前作品時，會先請你確認。這是隔離 UI 預覽，沒有使用相機或執行硬體。'},
    ]}};

function Preview() {
  const {t,locale,setLocale}=useI18n();
  const [board,setBoard]=useState('raspberry-pi-5');
  const videoStageRef=useRef<HTMLDivElement|null>(null);
  const generationFixture=options.get('generation');
  const [generationPhase,setGenerationPhase]=useState<'design'|'image'>('design');
  const fixtureDesign=generationFixture==='first'?null:generationFixture==='empty'?{...project,image:undefined}:project;
  const persisted=useMaker();
  const [enqueuing,setEnqueuing]=useState(discardFixture==='enqueue');
  const [previewState,setPreviewState]=useState<any>({...initialMaker(),design:fixtureDesign,code:project.code,aiJobId:generationFixture?'offline-job':null,
    conversation:[{role:'user',text:'我想做一個放在桌上的距離監測器。'},{role:'assistant',text:replyFixtures[options.get('reply')??'']?.[locale]??'可以用 Pi 5、超音波感測器與螢幕完成桌上型距離監測器。先看看右邊的作品概念與外觀。確認後再到製作藍圖查看零件與接線。接線前請先斷電，實際功能仍需逐項測試。'}]});
  const state:any=discardFixture||languageAudit?persisted.state:previewState;
  const setState=discardFixture||languageAudit?persisted.setState:setPreviewState;
  if(languageAudit)(window as any).__languageQa={...(window as any).__languageQa,state,events:headerEvents};
  const stage:MakerStage=state.stage;
  const navigate=(stage:MakerStage)=>setState((s:any)=>({...s,stage}));
  const assistantIntent:'wiring'|'debug'=state.debug?.intent??'wiring';
  const wire=currentWire(project,state.guide);
  const wiringTarget=assistantIntent==='wiring'&&wire?{component_id:wire.componentId,wire_id:wire.id}:undefined;
  const openDebug=(componentId?:string,runId?:string,symptom?:string)=>setState((s:any)=>enterDebug(s,componentId,runId,symptom));
  const inspectWiring=(componentId:string,pin?:string)=>setState((s:any)=>({...s,stage:'guide',guide:reviewProjectWire(project,s.guide,componentId,pin,'debug'),debug:{...s.debug,panelOpen:false}}));
  const assistant:any={ai:{logged_in:true},aiOptions:{estimate:{},selectionValid:true,selectedModel:model,options:{default_model:model.id,models:[model]},refresh:deny},login:deny,busy:enqueuing||Boolean(state.aiJobId),error:'',phase:generationPhase,generate:deny,retryImage:deny,
    loadDemo:()=>setState((s:any)=>({...s,candidate:project})),clearConversation:()=>setState((s:any)=>({...s,conversation:[]}))};
  const newProject=options.has('newProject')?async()=>{
    if(assistant.busy)return false;
    localStorage.setItem(`${MAKER_STORAGE}.before-new-project`,JSON.stringify(state));
    setState(newMakerProject);return true;
  }:undefined;
  return <div className={`app tinkro-theme pi-deploy-layout maker-layout maker-stage-${stage}${stage==='guide'?' maker-wiring-full-width':''}`}><main className="main">
    <WorkspaceHeader
      brand={<div className="brand"><div className="brand-text"><h1 className="brand-title"><img className="brand-logo" src="/brand/tinkro-dark.png" alt="Tinkro" width={152} height={48}/></h1><div className="brand-subtitle">{t('app.subtitle')}</div></div></div>}
      navigation={<nav className="maker-nav" aria-label={locale==='en'?'Maker workflow':'作品工作流程'}>{(['design','guide','deploy'] as MakerStage[]).map((name,i)=><button key={name} className={stage===name?'active':''} aria-current={stage===name?'step':undefined} onClick={()=>navigate(name)}><span>0{i+1}</span>{(locale==='en'?['Design & blueprint','Wiring + AI debug','Deploy & run']:['設計與藍圖','接線引導＋AI 除錯','部署與執行'])[i]}</button>)}</nav>}
      saveStatus={<small className={`maker-save-status ${options.has('storageError')?'maker-warning':'maker-muted'}`} role={options.has('storageError')?'alert':'status'}>{options.has('storageError')?(locale==='en'?'Storage failed; keep this page open':'儲存失敗，請勿關閉頁面'):(locale==='en'?'Draft saved in this browser':'作品草稿已保存於此瀏覽器')}</small>}>
      <MakerModelMenu state={state} setState={setState} assistant={assistant}/><PiConnectionControl/>
      <RuntimeToolbar controllers={controllers} activeBoardId={board} busy={false} disabled={false}
        error={options.has('runtimeError')?'Offline fixture: controller selection failed. No hardware action was performed.':null}
        onControllerChange={id=>{headerEvents.push(`controller:${id}`);setBoard(id);}}
        onLocaleChange={value=>{headerEvents.push(`locale:${value}`);setLocale(value);}}/>
    </WorkspaceHeader>
    {stage==='design'?<div className="maker-design-stage">
      {state.designView==='blueprint'?<BlueprintPage design={discardFixture?state.design:project} hasCandidate={Boolean(state.candidate)} generating={false} onGuide={()=>navigate('guide')} onEdit={()=>setState((s:any)=>({...s,designView:'concept'}))} onViewChange={view=>setState((s:any)=>({...s,designView:view}))}/>:
        <MakerSplitLayout stage="design" left={<MakerAssistant state={state} setState={setState} assistant={assistant} onNewProject={newProject} onReview={()=>setState((s:any)=>({...s,designView:'concept'}))}/>}><DesignStudio state={state} setState={setState} generationPhase={assistant.phase} busy={assistant.busy} onAdopt={replace=>setState((s:any)=>discardFixture?confirmConcept(s,replace):({...s,designView:'blueprint'}))} onViewChange={view=>setState((s:any)=>({...s,designView:view}))}/></MakerSplitLayout>}
    </div>:null}
    {discardFixture?<nav aria-label="Offline discard fixture" style={{display:'flex',flexWrap:'wrap',gap:8}}>
      <button onClick={()=>{setEnqueuing(false);setState((s:any)=>({...s,aiJobId:null,candidate:unconfirmedProject}));}}>Fixture: ready preview</button>
    </nav>:null}
    {generationFixture?<nav aria-label="Offline generation fixture" style={{display:'flex',flexWrap:'wrap',gap:8}}>
      <button onClick={()=>{setGenerationPhase('image');setState((s:any)=>({...s,aiJobId:'offline-job'}));}}>Fixture: image phase</button>
      <button onClick={()=>setState((s:any)=>({...s,aiJobId:null,candidate:{...project,source:'ai'}}))}>Fixture: complete</button>
      <button onClick={()=>setState((s:any)=>({...s,aiJobId:null,candidate:{...project,source:'ai',image:undefined,image_error:'Offline fixture: generation failed.'}}))}>Fixture: fail</button>
      <button onClick={()=>setState((s:any)=>({...s,aiJobId:null,candidate:null}))}>Fixture: stop</button>
    </nav>:null}
    {stage==='guide'?<><GuidePaneLayout stageRef={videoStageRef} className="video-guide-stage" visible resizable>
      <button className="guide-visibility-toggle">{locale==='en'?'Wiring guide · offline fixture':'接線引導 · 模擬畫面'}</button>
      <div className="video-shell" style={{display:'grid',placeItems:'center',background:'#111b30'}}><div style={{textAlign:'center',padding:24}}><img src="/brand/tinkro-symbol.svg" alt="" width={64} height={64}/><h2>Camera workspace</h2><p>{locale==='en'?'Camera workspace and GPIO overlay coordinates are preserved':'保留鏡頭畫面與 GPIO 疊圖座標'}</p><small>{locale==='en'?'Isolated preview: no camera, AI or Pi execution':'隔離測試不啟動鏡頭、AI 或 Pi'}</small></div></div>
      <ProjectGuidePanel design={project} session={state.guide} visible disabled={false} pinsById={new Map()} onChange={guide=>setState((s:any)=>({...s,guide}))} onTargetChange={noop} onVisibleChange={noop} onDeploy={()=>navigate('deploy')} onDebug={openDebug}/>
    </GuidePaneLayout>
      <DebugPage state={state} variant="wiring" assistantOpen={state.debug?.panelOpen??false}
        onAssistantOpenChange={panelOpen=>setState((s:any)=>({...s,debug:{...s.debug,panelOpen}}))}
        assistantIntent={assistantIntent} onAssistantIntentChange={intent=>setState((s:any)=>({...s,debug:{...s.debug,intent}}))}
        wiringTarget={wiringTarget} sessionRecord={session.record} onSessionAnalyse={deny}
        onCase={noop} onCode={noop} onWiring={inspectWiring} onDeploy={()=>navigate('deploy')} onSelect={cid=>setState((s:any)=>({...s,debug:{...s.debug,selectedComponentId:cid}}))}
        assistant={props=>{if(languageAudit)(window as any).__languageQa.context=props.context;return <AiDebugPanel {...props} state={state} currentCodeHash={props.codeHash} session={session}
          variant={assistantIntent} wiringTarget={wiringTarget} onOpenDebug={()=>openDebug()}
          webcamReady eyeActive={false} cameraSource="device" cameraRuntimeRevision={1} onReturnWebcam={deny} onCase={noop} onWiring={inspectWiring}/>;}}/>
    </>:null}
    {stage==='deploy'?<div className="maker-deploy-main"><PiDeployPanel project={project} draft={state.code} onDraftChange={code=>setState((s:any)=>({...s,code}))} onDebug={()=>openDebug()}/></div>:null}
  </main></div>;
}
// These are assertions, not mocks returning successful hardware responses.
window.fetch=async()=>{throw Error('Unexpected network request in isolated preview');};
window.WebSocket=class {constructor(){throw Error('Unexpected WebSocket in isolated preview');}} as any;
localStorage.setItem('boardvision.locale.v1',options.get('locale')==='en'?'en':'zh-TW');
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview/></LocaleProvider>);
