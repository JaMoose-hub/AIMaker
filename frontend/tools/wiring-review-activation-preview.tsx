// Render the real assistant entry with in-memory records; no backend, cloud or Pi calls.
import React, {useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AiDebugPanel} from '../src/components/AiDebugPanel';
import {WiringPhotoSequence} from '../src/components/WiringPhotoSequence';
import {FramingGuide} from '../src/components/WiringReviewCard';
import {applyFixturePhotoAction} from './wiring_photo_mock.mjs';
import {initialMaker, makerCatalog, type MakerState, type ProjectDesign} from '../src/lib/maker';
import {componentTestKey} from '../src/lib/componentTests';
import {LocaleProvider} from '../src/lib/i18n';
import type {DebugContext} from '../src/lib/debug';
import type {DebugSession, DebugSessionAction, useDebugSession} from '../src/lib/debugSessions';
import {boundWiringAction, type WiringPhotoRole, type WiringReviewAction, type WiringReviewState} from '../src/lib/wiringReview';
import '../src/styles.css';
import '../src/debug.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import './wiring-review-preview.css';

const query=new URLSearchParams(location.search);
document.documentElement.dataset.theme=query.get('theme')==='light'?'light':'dark';
const roles:WiringPhotoRole[]=['pi_side_a','pi_side_b','component_header'];
const wire=makerCatalog.modules.find(module=>module.id==='hc-sr04')!.steps.find(step=>step.componentPin==='ECHO')!;
const wireId=wire.id;
const design:ProjectDesign={id:'activation-fixture-project',revision:1,source:'demo',prompt:'isolated preview',catalog_version:makerCatalog.version,
  title:'接線核對入口測試',summary:'模擬作品',features:[],component_ids:['hc-sr04','mrd-tf240-8p-cs'],parameters:{distance_cm:20,sample_ms:100},
  wiring:[{...wire,componentId:'hc-sr04'}],bom:[],instructions:[],tests:[],code:'# fixture only',logic:'',unresolved:[],requirements:{imports:[],devices:[]}};
const initialState:MakerState={...initialMaker(),stage:'guide',design,code:design.code,debug:{selectedComponentId:'hc-sr04'}};
const slot=(role:WiringPhotoRole,serial?:number)=>({role,capture_id:serial?`${role}-${serial}`:role,image_url:query.get('brokenPhoto')===role&&!serial?'/fixture-missing.svg':`/fixture-${role}.svg`,size:[1200,900] as [number,number],sha256:`synthetic-fixture-${serial??0}`,crop:null,crop_source:'none' as const,available:true});
const row={wire_id:wireId,expected:{board_pin:wire.boardPin,physical_pin:12,bcm:18,component_pin:'Echo',connection_kind:wire.connectionKind},
  pi_candidates:[{id:'blue-a',capture_id:'pi_side_a',role:'pi_side_a' as const,physical_pin:null,pin_label:null,color:'blue',evidence:'接頭 A：藍色，腳號待確認。'},
    {id:'blue-b',capture_id:'pi_side_b',role:'pi_side_b' as const,physical_pin:null,pin_label:null,color:'blue',evidence:'另一個藍色候選，不能只憑顏色確認。'}],
  component_candidates:[{id:'echo',capture_id:'component_header',role:'component_header' as const,physical_pin:null,pin_label:'Echo',color:'blue',evidence:'Echo 標籤旁可見藍色線。'}],
  comparison:'ambiguous' as const,evidence:'全部為模擬觀察。',next_step:'親自沿線核對兩端。'};
const readyReview:WiringReviewState={id:`fixture-review-${query.get('run')??'base'}`,revision:1,round:1,component_id:'hc-sr04',status:'ready',photo_flow_version:2,
  slots:Object.fromEntries(roles.map(role=>[role,slot(role)])) as WiringReviewState['slots'],observations:row.pi_candidates,results:[row],reviews:{},missing_roles:[],no_progress_count:0};
type Scenario='normal'|'failed'|'software'|'symptom'|'progress'|'photos';
const baseRecord=():DebugSession=>({id:'fixture-session',status:'awaiting_capture',phase:'awaiting_user',symptom:'',instruction:'請描述目前遇到的問題。',
  capture_task:null,observations:[],evidence:[],jobs:[],messages:[],purpose:'wiring_review',updated_at:Date.now()/1000,
  binding:{project_id:design.id,code_hash:'fixture-code'},camera:{source:'device',runtime_revision:1},current_target:true,camera_current:true});
const scenarioRecord=(scenario:Scenario):DebugSession|null=>scenario==='normal'||scenario==='symptom'?null:{...baseRecord(),purpose:'debug',
  ...(scenario==='progress'?{purpose:'wiring_review' as const,wiring_review:readyReview}:{}),
  ...(scenario==='photos'?{purpose:'wiring_review' as const,wiring_review:{...readyReview,status:'collecting' as const,observations:[],results:[]}}:{}),
  ...(scenario==='failed'?{symptom:'超音波測不到距離',test_results:[{id:'test-failed',component_id:'hc-sr04',outcome:'failed',reason:'no_echo',guide_key:componentTestKey(design,initialState.guide,'hc-sr04')}]}:{}),
  ...(scenario==='software'?{symptom:'程式沒有反應',test_results:[{id:'test-software',component_id:'hc-sr04',outcome:'failed',reason:'missing_dependency',phase:'preflight',guide_key:componentTestKey(design,initialState.guide,'hc-sr04')}]}:{})};

function App(){
  const first=(query.get('scenario')??'normal') as Scenario;
  const [scenario,setScenario]=useState<Scenario>(first);
  const [state,setState]=useState(initialState);
  const [record,setRecord]=useState<DebugSession|null>(scenarioRecord(first));
  const [shown,setShown]=useState(true);
  const [failAccept,setFailAccept]=useState(query.has('failAccept'));
  const [failedImages,setFailedImages]=useState<string[]>([]);
  const live=useRef(record);live.current=record;
  const events=useRef<unknown[]>([]);
  const captureSerial=useRef(0);
  const [,changed]=useState(0);
  const push=(value:unknown)=>{events.current.push(value);changed(events.current.length);};
  const adopt=(value:DebugSession)=>{live.current=value;setRecord(value);return value;};
  const context=useMemo<DebugContext>(()=>({project:state.design,code:state.code,entry:{},test_keys:Object.fromEntries(design.component_ids.map(id=>[id,componentTestKey(design,state.guide,id)])),
    guide_confirmations:state.guide.confirmed,guide_run:state.guide.run??0}),[state]);
  function choose(next:Scenario){
    setScenario(next);setRecord(scenarioRecord(next));setState({...initialState,debug:{...initialState.debug,...(next==='symptom'?{symptom:'超音波測不到距離'}:{})}});
    events.current=[];changed(0);
  }
  async function action(name:DebugSessionAction,_context?:DebugContext,_text?:string,_mode?:string,payload?:WiringReviewAction){
    push({action:name,payload});
    const before=live.current??baseRecord();
    if(name==='prepare_wiring')return adopt({...before,wiring_edit_ready:true,purpose:'wiring_review'});
    if(name!=='wiring_review'||!payload)return before;
    const old=before.wiring_review??readyReview;
    if(payload.op==='accept_photo') {
      if(failAccept)throw new Error('模擬照片接受失敗，照片尚未存入本輪。');
      return adopt({...before,wiring_review:applyFixturePhotoAction(old,payload)});
    }
    const next:WiringReviewState=payload.op==='start'||payload.op==='changed'?{...readyReview,id:`fixture-review-${old.round+1}`,round:old.round+1,status:'collecting' as const,slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:[],reviews:{}}:
      payload.op==='capture'?applyFixturePhotoAction(old,payload,{captureSlot:(role:WiringPhotoRole)=>slot(role,++captureSerial.current)}):
      payload.op==='analyse'?{...old,revision:old.revision+1,status:'ready',results:[{...row,
        pi_candidates:row.pi_candidates.map(candidate=>({...candidate,capture_id:old.slots[candidate.role]!.capture_id})),
        component_candidates:row.component_candidates.map(candidate=>({...candidate,capture_id:old.slots[candidate.role]!.capture_id}))}],observations:[],reviews:{}}:
      payload.op==='review'?{...old,revision:old.revision+1,reviews:{...old.reviews,[payload.wire_id!]:{decision:payload.decision!,source:'human',at:Date.now()/1000,review_revision:old.revision}}}:
      payload.op==='crop'?{...old,revision:old.revision+1,slots:{...old.slots,[payload.role!]:{...old.slots[payload.role!]!,crop:payload.crop??null,crop_source:'manual' as const}}}:old;
    return adopt({...before,wiring_review:next});
  }
  const session={record,pending:false,error:'',resetVersion:0,conversation:null,action,
    create:async(...args:unknown[])=>{push({create:args.at(-1)});return adopt(baseRecord());},
    contextChanged:async()=>{push({contextChanged:true});return live.current??undefined;},restartConversation:async()=>false} as unknown as ReturnType<typeof useDebugSession>;
  (window as unknown as {wiringActivationQa:unknown}).wiringActivationQa={scenario,events:events.current,record,state};
  return <div className="app tinkro-theme fixture-page"><main className="fixture-main">
    <h1>接線核對 · 按需入口驗證</h1><p className="fixture-warning">使用真實 AiDebugPanel；圖片、工作階段與操作均為模擬，不會連接雲端或硬體。</p>
    <label>情境 <select aria-label="測試情境" value={scenario} onChange={event=>choose(event.target.value as Scenario)}>
      <option value="normal">正常聊天</option><option value="failed">超音波無回波</option><option value="software">環境缺套件</option>
      <option value="symptom">使用者說測不到距離</option><option value="progress">已開始逐線核對</option>
      <option value="photos">已拍好三張，逐張選照片</option>
    </select></label>
    <label><input type="checkbox" checked={failAccept} onChange={event=>setFailAccept(event.target.checked)} />模擬接受照片失敗</label>
    <button type="button" onClick={()=>setShown(value=>!value)}>{shown?'離開助手（模擬導航）':'返回助手（保留伺服器紀錄）'}</button>
    <div className="assistant-workspace"><div className="assistant-project-workspace"><div className="unified-debug-tools">
    <section className="debug-page debug-chat-page guide-ai-workspace is-docked" data-open="true"><div className="debug-page-content"><div className="debug-chat-view">
    {shown && query.get('surface')==='phone' && record?.wiring_review ? <WiringPhotoSequence review={record.wiring_review} disabled={false} waiting={false} captureReady humanOnly={false}
      failedCaptures={failedImages} captureLabel="使用手機取像（模擬）" onCapture={role=>void action('wiring_review',context,undefined,undefined,boundWiringAction(record.wiring_review!,{op:'capture',role}))}
      onAccept={(role,photo)=>action('wiring_review',context,undefined,undefined,boundWiringAction(record.wiring_review!,{op:'accept_photo',role,capture_id:photo.capture_id,sha256:photo.sha256}))}
      onAnalyse={()=>void action('wiring_review',context,undefined,undefined,boundWiringAction(record.wiring_review!,{op:'analyse'}))}
      onPhoto={photo=>push({view:photo.capture_id})} onImageError={id=>setFailedImages(values=>[...values,id])} framing={role=><FramingGuide role={role}/>} /> : shown ? <AiDebugPanel key={scenario} state={state} context={context} currentCodeHash="fixture-code" session={session}
      webcamReady eyeActive={false} cameraSource="device" cameraRuntimeRevision={1} repairCaseId={null} repairAppliedHash={null} repairCandidateReady={false}
      onReturnWebcam={()=>push({returnWebcam:true})} onCase={id=>push({case:id})} onRetest={id=>push({retest:id})} onTrial={()=>push({trial:true})}
      onReviewRepair={()=>push({repair:true})} onManual={()=>push({manual:true})} onWiring={(id,pin)=>push({inspect:id,pin})}
      onReviewGuideChange={guide=>setState(old=>({...old,guide}))} actionsOnly variant="wiring"
      headerControls={<div className="assistant-debug-mode"><button type="button" onClick={()=>push({mode:'wiring'})}>問接法</button><button type="button" onClick={()=>push({mode:'debug'})}>功能異常</button></div>} /> : null}
    </div></div></section></div></div></div>
    <details><summary>模擬操作紀錄：{events.current.length}</summary><pre id="fixture-events">{JSON.stringify(events.current,null,2)}</pre></details>
  </main></div>;
}
createRoot(document.getElementById('root')!).render(<LocaleProvider><App/></LocaleProvider>);
