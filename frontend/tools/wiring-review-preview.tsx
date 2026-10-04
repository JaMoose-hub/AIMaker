// Isolated UI fixture. All actions below are in-memory; no API, camera or Pi calls.
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {WiringReviewCard} from '../src/components/WiringReviewCard';
import type {WiringPhotoRole, WiringReviewState, WiringReviewAction, WiringHumanDecision} from '../src/lib/wiringReview';
import '../src/styles.css';
import '../src/debug.css';
import '../src/tinkro.css';
import '../src/assistant.css';
import './wiring-review-preview.css';

document.documentElement.dataset.theme=new URLSearchParams(location.search).get('theme')==='light'?'light':'dark';

const roles:WiringPhotoRole[]=['pi_side_a','pi_side_b','component_header'];
const events:unknown[]=[];
const slot=(role:WiringPhotoRole)=>({role,capture_id:role,image_url:`/fixture-${role}.svg`,size:[1200,900] as [number,number],sha256:'synthetic-fixture',crop:null,crop_source:'none' as const,available:true});
const row=()=>({wire_id:'echo',expected:{board_pin:'12',physical_pin:12,bcm:18,component_pin:'Echo',connection_kind:'divider'},
  pi_candidates:[{id:'blue-a',capture_id:'pi_side_a',role:'pi_side_a' as const,physical_pin:null,pin_label:null,color:'blue',evidence:'藍色接頭可見，插接底部部分遮擋。'},
    {id:'blue-b',capture_id:'pi_side_b',role:'pi_side_b' as const,physical_pin:null,pin_label:null,color:'blue',evidence:'另一個藍色接頭候選，不能只靠顏色確定。'}],
  component_candidates:[{id:'echo',capture_id:'component_header',role:'component_header' as const,physical_pin:null,pin_label:'Echo',color:'blue',evidence:'Echo 標籤旁的接頭露出藍色線。'}],
  comparison:'ambiguous' as const,evidence:'模擬資料：兩個同色候選。',next_step:'沿著同一條線親自核對兩端。'});
const initial:WiringReviewState={id:'fixture-review',revision:1,round:1,component_id:'hc-sr04',status:'ready',slots:Object.fromEntries(roles.map(role=>[role,slot(role)])) as WiringReviewState['slots'],
  observations:row().pi_candidates,results:[row()],reviews:{},missing_roles:[],no_progress_count:0};
function App(){
  const [review,setReview]=useState(initial);
  const [started,setStarted]=useState(!new URLSearchParams(location.search).has('empty'));
  const [count,setCount]=useState(0);
  const [fail,setFail]=useState(false);
  const [busy,setBusy]=useState(false);
  (window as unknown as {wiringReviewQa:unknown}).wiringReviewQa={review,events};
  async function action(value:WiringReviewAction){
    events.push(value);setCount(events.length);
    if(fail)throw new Error('模擬儲存失敗，原圖保留。');
    if(started&&(value.review_id!==review.id||value.revision!==review.revision))throw new Error('Fixture revision mismatch');
    if(value.op==='start')setStarted(true);
    if(value.op==='analyse'){
      setBusy(true);
      await new Promise(done=>setTimeout(done,180));
      setBusy(false);
    }
    setReview(old=>value.op==='start'||value.op==='changed'?{...old,revision:old.revision+1,round:old.round+1,component_id:value.component_id??old.component_id,status:'collecting',
      slots:{pi_side_a:null,pi_side_b:null,component_header:null},observations:[],results:[],reviews:{}}:
      value.op==='capture'?{...old,revision:old.revision+1,status:'collecting',slots:{...old.slots,[value.role!]:slot(value.role!)},results:[],reviews:{}}:
      value.op==='crop'?{...old,revision:old.revision+1,status:'collecting',slots:{...old.slots,[value.role!]:{...old.slots[value.role!]!,crop:value.crop??null,crop_source:'manual'}},results:[],reviews:{}}:
      value.op==='analyse'?{...old,revision:old.revision+1,status:'ready',observations:row().pi_candidates,results:[row()]}:old);
    return true;
  }
  async function human(wireId:string,decision:WiringHumanDecision){
    events.push({human:wireId,decision});setCount(events.length);
    setReview(old=>({...old,revision:old.revision+1,reviews:{...old.reviews,[wireId]:{decision,source:'human',at:Date.now()/1000,review_revision:old.revision}}}));
  }
  return <div className="app tinkro-theme fixture-page"><main className="fixture-main"><h1>接線引導 · 隔離操作驗證</h1><p className="fixture-warning">全部是模擬圖片與資料，不會連接硬體或雲端。</p>
    <label><input type="checkbox" checked={fail} onChange={event=>setFail(event.target.checked)} />模擬儲存錯誤</label>
    <button type="button" onClick={()=>{setReview(initial);events.length=0;setCount(0);setFail(false);}}>重設模擬資料</button>
    <div className="unified-debug-tools"><section className="ai-debug-panel is-actions-only"><div className="ai-debug-chat"><div className="ai-debug-chat-content">
    <WiringReviewCard review={started?review:null} components={[{id:'hc-sr04',label:'HC-SR04 超音波'},{id:'mrd-tf240-8p-cs',label:'TFT 顯示器'}]}
      componentId="hc-sr04" busy={busy} captureReady onAction={action} onReview={human}
      onRetest={componentId=>{events.push({retest:componentId});setCount(events.length);}}
      onInspectWire={wireId=>{events.push({inspect:wireId});setCount(events.length);}} />
    </div></div></section></div>
    <details open><summary>模擬操作紀錄：{count}</summary><pre id="fixture-events">{JSON.stringify(events,null,2)}</pre></details>
  </main></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
