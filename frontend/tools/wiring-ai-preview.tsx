// Isolated interactive integration fixture. No production storage or hardware hooks.
import React, {useState,useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {LocaleProvider} from '../src/lib/i18n';
import {initialMaker,makerCatalog,reviewProjectWire,wireSignature,enterDebug} from '../src/lib/maker';
import {componentTestKey} from '../src/lib/componentTests';
import {DebugPage} from '../src/components/DebugPage';
import {AiDebugPanel} from '../src/components/AiDebugPanel';
import {ProjectGuidePanel} from '../src/components/ProjectGuidePanel';
import {GuidePaneLayout} from '../src/components/GuidePaneLayout';
import {WiringWorkspace} from '../src/components/WiringWorkspace';
import {StepDiagramView,WiringViewToggle} from '../src/components/StepDiagramView';
import {DiagramInspectionView} from '../src/components/DiagramInspectionView';
import {inspectDiagramInMaker,type DiagramInspection} from '../src/lib/debugEvidence';
import {StatusBar} from '../src/components/StatusBar';
import {ThemeSelect} from '../src/components/ThemeSelect';
import {ComponentOverlayPreview} from './component-overlay-preview';
import hc from '../../profiles/components/hc-sr04/vision_profile.json';
import tft from '../../profiles/components/mrd-tf240-8p-cs/vision_profile.json';
import '../src/styles.css';
import '../src/maker.css';
import '../src/debug.css';
import '../src/responsive.css';
import '../src/guideAi.css';
import '../src/tinkro.css';

const noop=()=>{};
const design:any={id:'isolated-wiring-fixture',revision:2,catalog_version:makerCatalog.version,profile_versions:{'hc-sr04':{version:'1',sha256:'fixture'}},
  title:'隔離接線預覽',summary:'Synthetic UI fixtures only',component_ids:makerCatalog.modules.map(m=>m.id),
  wiring:makerCatalog.modules.flatMap(m=>m.steps.map(w=>({...w,id:`${m.id}:${w.id}`,componentId:m.id}))),
  code:'# isolated fixture',parameters:{distance_cm:20,sample_ms:200},unresolved:[],bom:[],instructions:[],requirements:{imports:[],devices:[]}};
const modules=makerCatalog.modules.map(m=>{const profile=m.id==='hc-sr04'?hc:tft;const pins=[...profile.pins].sort((a,b)=>a.x_norm-b.x_norm);return {id:m.id,name:m.name,safety:m.safety,unresolved:m.unresolved,pins,pin_order:pins.map(p=>p.id),header_at_top:pins.reduce((n,p)=>n+p.y_norm,0)/pins.length<.5,canonical_orientation:profile.canonical_orientation};});
const snapshot=(rev:number)=>({id:`diagram-v${rev}`,schema_version:'debug-diagram-v1',created_at:1700000000+rev,project_id:design.id,project_revision:rev,
  design:{...design,revision:rev,wiring:design.wiring.map((wire:any)=>rev===1&&wire.id==='hc-sr04:trig'?{...wire,boardPin:'GPIO27',boardLabel:'Pin 13 · GPIO27'}:wire)},
  render_snapshot:{modules:modules.map(module=>rev===1&&module.id==='hc-sr04'?{...module,pin_order:[...module.pin_order].reverse(),header_at_top:true}:module),catalog_version:makerCatalog.version,profile_versions:design.profile_versions}});
const evidence:any={id:'photo-one',session_id:'qa-check',target:'module_header',frame_id:42,source:'device',available:true,captured_at:1700000010,same_frame:true,mode:'pin_crops',
  views:['overview','pi_pins','component_pins','pi_reading','component_reading','pi_contact','component_contact'].map(name=>({name,frame_id:42,size:[960,540],...(name.includes('reading')?{source_view:name.replace('reading','pins'),adds_no_detail:true}:{})}))};
const initialMessages:any[]=[
  {id:'m1',role:'user',text:'這條 TRIG 線應該怎麼接？',created_at:1},
  {id:'m2',role:'assistant',text:'歷史接線圖 v1，僅供檢视。',created_at:2,diagram_refs:[{snapshot_id:'diagram-v1',wire_ids:['hc-sr04:trig'],caption:'上一版接法'}]},
  {id:'m3',role:'assistant',text:'本輪照片是模擬測試資料。請查看 HC-SR04+ TRIG 到 Pi Pin 11 的設計接法。',created_at:3,model:'offline-fixture',session_id:'qa-check',capture_ids:['photo-one'],diagram_refs:[{snapshot_id:'diagram-v2',wire_ids:['hc-sr04:trig','hc-sr04:echo'],caption:'請對照目前這兩條線'}]},
];
function Preview(){
  const scenario=new URLSearchParams(location.search).get('scenario')??'flow';
  const [cameraReady,setCameraReady]=useState(true);
  const [eventCount,setEventCount]=useState(0);
  const restarting=scenario.startsWith('restart');
  const [resetRound,setResetRound]=useState(restarting&&sessionStorage.getItem(`qa-round:${scenario}`)==='fresh');
  const reviewing=!resetRound&&(['review','partial-review'].includes(scenario)||restarting);
  const videoStageRef=useRef<HTMLDivElement|null>(null);
  const [stage,setStage]=useState<'design'|'guide'|'deploy'>('guide');
  const [assistantOpen,setAssistantOpen]=useState(!restarting&&!['flow','2d','prepare','review','partial-review'].includes(scenario));
  const [assistantIntent,setAssistantIntent]=useState<'wiring'|'debug'>(scenario==='flow'?'wiring':'debug');
  const [visible,setVisible]=useState(true);
  const [evidenceDiagram,setEvidenceDiagram]=useState<(DiagramInspection&{requestId:number})|null>(null);
  const [state,setState]=useState<any>({...initialMaker(),design,code:design.code,debug:resetRound?{}:{caseId:'qa-case',panelOpen:assistantOpen,intent:assistantIntent},guide:{...initialMaker().guide,phase:resetRound||scenario==='prepare'?'prepare':reviewing?'review':'active',mode:scenario==='2d'?'2d':'camera',...(resetRound||['flow','2d','prepare'].includes(scenario)?{}:{confirmed:Object.fromEntries((reviewing?design.wiring.slice(0,scenario==='partial-review'?2:4):design.wiring).map((wire:any)=>[wire.id,{signature:wireSignature(wire),at:1700000000}]))})}});
  const [messages,setMessages]=useState(resetRound?[]:initialMessages);
  const events=useRef<any[]>([]);
  const debugNavigations=useRef<any[]>([]);
  const binding={project_id:design.id,code_hash:'qa-code',test_keys:Object.fromEntries(design.component_ids.map((cid:string)=>[cid,componentTestKey(design,state.guide,cid)]))};
  const testCid=scenario==='tft'?'mrd-tf240-8p-cs':'hc-sr04';
  const run:any={id:`qa-${testCid}`,project_id:design.id,revision:2,component_id:testCid,guide_key:binding.test_keys[testCid],outcome:scenario==='tft'?'awaiting_confirmation':'running',phase:scenario==='tft'?'awaiting_visual':'awaiting_near',reserved:true,invalidated:false,created_at:Date.now()/1000,reason:null,samples:{},logs:[],options:['1234','5678','9012'],program_stopped:false};
  const savedOutcome=new URLSearchParams(location.search).get('outcome')??'inconclusive';
  const savedRun={...run,created_at:1700000000,finished_at:1700000010,reserved:false,phase:'finished',outcome:savedOutcome,
    reason:savedOutcome==='passed'?null:savedOutcome==='failed'?'no_echo':'wiring_changed',invalidated:savedOutcome==='inconclusive',
    samples:{near:{count:76,median_cm:35.3},far:{count:64,median_cm:39}}};
  const trial:any={id:'qa-trial',project_id:design.id,binding,phase:'awaiting_visual',outcome:'awaiting_confirmation',reserved:false,created_at:Date.now()/1000,program_stopped:false,evidence:{program_ok:true,structured:true,sample_seq:12,display_seq:12}};
  const diagnostic:any={id:'qa-case',status:'ready',binding,rounds:1,finished_at:1700000030,current_target:true,issues:[],eligible:true,evidence:{environment_ready:true,tests:[],pi:{program:'stopped',logs:[]}},...(scenario==='repair'?{analysis:{facts:'合成程式測試',possible_causes:'合成判斷條件',next_step:'檢查候選差異'},candidate:{id:'qa-candidate',base_hash:'qa-code',code_hash:'qa-repaired',applied:false,diff:'- limit = 10\n+ limit = 20',offline:{passed:true}}}:{} )};
  const record:any=resetRound?null:{id:'qa-check',conversation_id:'qa-history',purpose:scenario==='flow'?'wiring_review':'debug',status:scenario==='repair'?'awaiting_repair':scenario==='trial'?'awaiting_trial_visual':scenario==='tft'?'awaiting_visual':'awaiting_capture',phase:scenario==='repair'?'repair_ready':'awaiting_user',instruction:'請回覆你看到的接腳標籤。',symptom:'請檢查接線',model:'offline-fixture',updated_at:1700000030,
    messages:scenario==='countdown'?messages:[],evidence:[evidence],observations:[],jobs:[],test_results:scenario==='tft'?[run]:[],capture_task:null,diagrams:[],binding,current_target:true,camera_current:true,...(scenario==='repair'?{diagnosis:{case_id:'qa-case'}}:{}),...(scenario==='trial'?{trial_result:trial}:{})};
  const log=async(kind:string,payload:any)=>{events.current.push({kind,...payload});setEventCount(events.current.length);return {code:'# isolated repaired fixture'};};
  (window as any).__wiringQa={events:events.current,debugNavigations:debugNavigations.current,
    debug:{record:resetRound?null:diagnostic,pending:false,error:'',trials:{active:null,results:scenario==='trial'?[trial]:[]},action:(path:string,body:any)=>log('debug',{path,body})},
    pi:{status:{connected:scenario!=='flow',program:'stopped',deployment:'idle',logs:[],execution:{jobs:[]}},networkError:false,pending:false},
    tests:()=>({status:{connected:scenario!=='flow',test_busy:false,active:['hc','tft'].includes(scenario)?run:null,results:scenario==='review'?[savedRun]:[],execution:{jobs:[]}},error:null,pending:false,invalidate:async()=>{if(restarting)await log('invalidate',{});return scenario!=='restart-invalidate-failure';},action:(test:any,action:string,data:any)=>log('test',{id:test.id,action,data}),start:()=>log('test',{action:'start'})})};
  const session:any={record,conversation:{id:resetRound?'qa-fresh':'qa-history',project_id:design.id,messages,evidence:resetRound?[]:[evidence],diagrams:resetRound?[]:[snapshot(1),snapshot(2)]},pending:false,error:'',resetVersion:resetRound?1:0,contextChanged:async()=>record,targetChanged:noop,
    create:async()=>record,createConversation:async()=>({id:'qa-history'}),attachDiagram:async()=>snapshot(2),
    action:async(name:string,_context:any,text:string)=>{await log('session',{action:name});if(name==='message'){setMessages(old=>[...old,{id:`m${old.length+1}`,role:'user',text,created_at:100+old.length},{id:`m${old.length+2}`,role:'assistant',text:'隔離預覽已收到訊息；沿用同一份對話紀錄。',created_at:101+old.length}]);}return record;}};
  const wire=design.wiring.filter((w:any)=>w.componentId===design.component_ids[state.guide.componentIndex])[state.guide.index];
  const target={component_id:wire.componentId,wire_id:wire.id};
  const onWiring=(cid:string,pin?:string)=>{setEvidenceDiagram(null);setStage('guide');setVisible(true);setAssistantOpen(false);setState((s:any)=>({...s,guide:reviewProjectWire(design,s.guide,cid,pin,'debug')}));};
  const openDebug=(componentId?:string,runId?:string,symptom?:string)=>{debugNavigations.current.push({componentId,runId,symptom});setStage('guide');setAssistantOpen(true);setAssistantIntent(state.guide.inspection?assistantIntent:'debug');setState((s:any)=>enterDebug({...s,debug:{...s.debug,intent:assistantIntent}},componentId,runId,symptom));};
  const [captureRequired,setCaptureRequired]=useState(false);
  const [captureGeneration,setCaptureGeneration]=useState(0);
  const [captureOverride,setCaptureOverride]=useState<number|null>(null);
  const cameraActions=useRef<string[]>([]);
  (window as any).__wiringQa.cameraActions=cameraActions.current;
  const showDiagram=state.guide.mode==='2d'&&(!captureRequired||captureOverride===captureGeneration);
  const onDiagram=(inspection:DiagramInspection)=>{setStage('guide');setVisible(true);setAssistantOpen(true);setEvidenceDiagram(old=>({...inspection,requestId:(old?.requestId??0)+1}));setCaptureOverride(captureGeneration);setState((s:any)=>inspectDiagramInMaker(s,inspection));};
  const assistantPanel=<DebugPage key={session.resetVersion} state={state} variant="wiring" embedded assistantOpen onAssistantOpenChange={setAssistantOpen} assistantIntent={assistantIntent} onAssistantIntentChange={setAssistantIntent} wiringTarget={target} sessionRecord={record} onCase={noop} onCode={(code)=>setState((s:any)=>({...s,code}))} onWiring={onWiring} onDeploy={()=>setStage('deploy')} onSelect={cid=>setState((s:any)=>({...s,debug:{...s.debug,selectedComponentId:cid}}))}
    assistant={props=><AiDebugPanel {...props} state={state} currentCodeHash={props.codeHash} session={session} variant={assistantIntent} wiringTarget={target} onOpenDebug={openDebug} webcamReady={cameraReady} eyeActive={false} cameraSource="device" cameraRuntimeRevision={1} onReturnWebcam={noop} onCase={noop} onWiring={onWiring} onDiagram={onDiagram}/>} />;
  return <div className={`app tinkro-theme maker-layout pi-deploy-layout maker-stage-${stage}${stage==='guide'?' maker-wiring-full-width':''}`}>
    <main className="main"><header className="header maker-header"><ThemeSelect/><h1>Tinkro · 隔離接線 QA</h1><small>合成照片、模擬 API、無硬體／模型／正式儲存</small><nav className="maker-nav" aria-label="作品工作流程">{([['design','01 設計與藍圖'],['guide','02 接線引導＋AI 除錯'],['deploy','03 部署與執行']] as const).map(([value,label])=><button key={value} aria-current={stage===value?'step':undefined} onClick={()=>setStage(value)}>{label}</button>)}</nav></header>
    {scenario==='countdown'?<div className="qa-capture-controls"><output aria-label="隔離動作紀錄">{eventCount} · {events.current.map(item=>item.action).join(', ')}</output><button onClick={()=>setCameraReady(value=>!value)}>切換相機就緒（僅測試）</button><button onClick={()=>setMessages(old=>[...old,{id:`long-${old.length}`,role:'assistant',created_at:Date.now()/1000,text:'最新回覆從這裡開始。\n\n'+('這是隔離測試的長回覆，用來確認訊息開頭能完整顯示，不會跳到狀態卡。\n\n').repeat(14)}])}>新增長回覆（僅測試）</button></div>:null}
    {stage==='design'?<section aria-label="隔離設計頁">設計頁替身；導覽返回會保留既有對話。</section>:null}{stage==='deploy'?<section aria-label="隔離部署頁">部署頁替身；不連線或執行作品。</section>:null}
    {stage==='guide'?<>
    <GuidePaneLayout stageRef={videoStageRef} className={`video-guide-stage${showDiagram?' maker-2d':''}`} visible resizable={visible}>
      <button className="guide-visibility-toggle" onClick={()=>setVisible(!visible)}>{visible?'隱藏側邊面板':'顯示側邊面板'}</button>
      <div className="video-workspace"><div className="video-control-toolbar">
        <WiringViewToggle diagramVisible={showDiagram} captureRequired={captureRequired} onChange={mode=>{setEvidenceDiagram(null);setCaptureOverride(mode==='2d'?captureGeneration:null);setState((s:any)=>({...s,guide:{...s.guide,mode}}));}}/>
        <StatusBar compact webcamTuningVisible videoControls={!showDiagram?<><button>即時追蹤 · 模擬</button><button>左右鏡像</button><button>校正方向</button></>:null} onOpenCalibrate={()=>cameraActions.current.push('calibrate')} calibrateDisabled={false}
          onOpenCameraPicker={()=>cameraActions.current.push('camera')} cameraPickerVisible cameraPickerDisabled={false}
          onEnterSmartGlassesDemo={()=>cameraActions.current.push('glasses')} smartGlassesDemoDisabled={false} onEnterOpticalHud={()=>cameraActions.current.push('hud')} opticalHudDisabled={false}
          accuracy={null} pinsById={new Map()} boardId="raspberry-pi-5" runtimeRevision={1}/>
      </div><div className="video-shell" hidden={showDiagram} style={{background:'#dce8ee',placeItems:'center',borderRadius:12}} aria-label="模擬鏡頭">合成畫面 · 不開啟相機</div>
      {showDiagram?evidenceDiagram?<DiagramInspectionView key={evidenceDiagram.requestId} inspection={evidenceDiagram} currentDesign={design} capturePending={captureRequired} onReturn={()=>setEvidenceDiagram(null)}/>:<StepDiagramView design={design} wire={wire} capturePending={captureRequired}/>:null}</div>
      <WiringWorkspace design={design} guide={state.guide} visible={visible} assistantOpen={assistantOpen} onAssistantOpenChange={setAssistantOpen} onClose={()=>setVisible(false)} assistant={assistantPanel} replyId={messages.filter(m=>m.role==='assistant').at(-1)?.id}>
        <ProjectGuidePanel design={design} session={state.guide} visible embedded disabled={false} pinsById={new Map()} onChange={guide=>setState((s:any)=>({...s,guide}))} onTargetChange={noop} onVisibleChange={setVisible} onDeploy={()=>setStage('deploy')} onDebug={openDebug} onHelp={()=>{setAssistantOpen(true);setAssistantIntent('wiring');}}
          onBeforeEdit={restarting?async()=>{await log('stop',{});if(scenario==='restart-stop-failure')throw Error('hardware_work_active');return true;}:undefined}
          onRestart={restarting?async guide=>{await log('restart-conversation',{});if(scenario==='restart-reset-failure')throw Error('connection_lost');sessionStorage.setItem(`qa-round:${scenario}`,'fresh');setResetRound(true);setMessages([]);setEvidenceDiagram(null);setState((s:any)=>({...s,guide,debug:{intent:'wiring'}}));setAssistantIntent('wiring');return true;}:undefined}/>
      </WiringWorkspace>
    </GuidePaneLayout>
    </>:null}
    <output id="qa-guide-state" hidden>{JSON.stringify({phase:state.guide.phase,index:state.guide.index,componentIndex:state.guide.componentIndex,inspection:state.guide.inspection,confirmed:state.guide.confirmed})}</output>
    <output id="qa-view-binding" hidden>{JSON.stringify({code:state.code,debug:state.debug,binding,assistantIntent})}</output>
    <button id="qa-request-capture" hidden onClick={()=>{setCaptureGeneration(old=>old+1);setCaptureRequired(true);}}>Synthetic capture request</button>
    <button id="qa-finish-capture" hidden onClick={()=>setCaptureRequired(false)}>Synthetic capture finish</button>
    </main>
  </div>;
}
window.fetch=async()=>{throw Error('Unexpected fetch in isolated wiring QA');};
window.WebSocket=class{constructor(){throw Error('Unexpected WebSocket in isolated wiring QA');}} as any;
const fixtureLocale=new URLSearchParams(location.search).get('locale');
if(fixtureLocale==='en'||fixtureLocale==='zh-TW')localStorage.setItem('boardvision.locale.v1',fixtureLocale);
createRoot(document.getElementById('root')!).render(<LocaleProvider>{new URLSearchParams(location.search).get('scenario')==='overlay'?<ComponentOverlayPreview/>:<Preview/>}</LocaleProvider>);
