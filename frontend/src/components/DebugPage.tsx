import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useDebug, codeHash, type DebugCase } from "../lib/debug";
import { componentComplete, componentTestKey, testReasons } from "../lib/componentTests";
import { useComponentTests } from "../lib/useComponentTests";
import { usePiConnection } from "../lib/PiConnection";
import { useMakerText } from "../lib/useMaker";
import type { MakerState, ProjectDesign, ProjectGuideState } from "../lib/maker";
import { ComponentTestCard } from "./ComponentTestCard";

function TargetedTest({design, guide, cid, focusRequest, onWiring, before, after, report, programSelected = false}: {
  design:ProjectDesign;guide:ProjectGuideState;cid:string;focusRequest:number;onWiring:(cid:string,pin?:string)=>void;
  before?:ReactNode;after?:ReactNode;report?:ReactNode;programSelected?:boolean;
}) {
  const tr = useMakerText();
  const card = useRef<HTMLElement>(null);
  const session = {...guide, componentIndex:Math.max(0,design.component_ids.findIndex(id=>id===cid))};
  // One polling/action owner for both panes. Choosing a component never starts a run.
  const tests = useComponentTests(design, session);
  useEffect(()=>{
    if (!focusRequest || !card.current) return;
    card.current.focus({preventScroll:true});
  },[cid,focusRequest]);
  const name = cid==="hc-sr04"?"HC-SR04+":"MRD-TFT240";
  const showTest = !programSelected || Boolean(tests.status?.active);
  const complete = componentComplete(design, session, cid);
  return <div className="debug-workspace">
    <div className="debug-controls">
      {before}
      {showTest ? <section ref={card} id="debug-targeted-retest" className="debug-retest-target" tabIndex={-1} aria-labelledby="debug-retest-heading">
        <h3 id="debug-retest-heading">{tr("測試零件", "Test component")} · {name}</h3>
        {tests.status?.active || complete ? <ComponentTestCard key={cid+"-controls"} view="controls" design={design} session={session} tests={tests} onViewWiring={()=>onWiring(cid)} /> :
          <><p className="debug-next-step">{tr("這個零件還有接線未確認。先查看接線步驟，逐腳確認完成後，就能在這裡測試。", "Confirm the remaining wiring steps before testing this component.")}</p><button onClick={()=>onWiring(cid)}>{tr("查看相關接線", "Review related wiring")}</button></>}
        <details><summary>{tr("找特定腳位", "Find a specific pin")}</summary>{design.wiring.filter(w=>w.componentId===cid).map(w=><button key={w.id} onClick={()=>onWiring(cid,w.componentPin)}>{w.componentPin}</button>)}</details>
      </section> : null}
      {after}
    </div>
    <aside className="debug-results" aria-label={tr("輸出結果與報告", "Results and reports")}>
      <h3>{tr("輸出結果", "Results")} · {programSelected ? tr("作品程式", "Project program") : name}</h3>
      {!programSelected ? <>
        <ComponentTestCard key={cid+"-results"} view="results" design={design} session={session} tests={tests} onViewWiring={()=>onWiring(cid)} />
        {!tests.status?.active && !tests.status?.results?.some(run=>run.component_id===cid) && !complete ? <p className="debug-empty">{tr("還沒有這個零件的測試結果。完成左側接線確認後，就能開始測試。", "No test results for this component yet. Confirm its wiring on the left to start.")}</p> : null}
      </> : <p className="workflow-muted">{tr("這裡顯示作品層級的分析與報告，不代表個別零件已通過測試。", "Project-level analysis and reports do not confirm that individual components passed.")}</p>}
      {report}
    </aside>
  </div>;
}

export function DebugPage({state, onCase, onCode, onWiring, onDeploy, onSelect}: {
  state:MakerState; onCase:(id:string)=>void; onCode:(code:string,expected:string)=>void;
  onWiring:(cid:string,pin?:string)=>void; onDeploy:()=>void; onSelect:(cid:string)=>void;
}) {
  const tr = useMakerText();
  const pi = usePiConnection();
  const debug = useDebug(state.debug?.caseId, state.design?.id);
  const [hash,setHash] = useState("");
  const [programSelected,setProgramSelected] = useState(false);
  const [copied,setCopied] = useState(false);
  const [visualRun,setVisualRun] = useState("");
  const [retestFocusRequest,setRetestFocusRequest] = useState(0);
  const [confirmAction,setConfirmAction] = useState<"apply"|"restore"|null>(null);
  const agentDetails = useRef<HTMLDetailsElement>(null);
  const reportDetails = useRef<HTMLDetailsElement>(null);
  const trialCard = useRef<HTMLElement>(null);
  const trialDetails = useRef<HTMLDetailsElement>(null);
  const record = debug.record;
  const context = useMemo(()=>({project:state.design,code:state.code,
    test_keys:Object.fromEntries(state.design?.component_ids.map(cid=>[cid,componentTestKey(state.design!,state.guide,cid)])??[]),
    entry:state.debug??{}}), [state.design,state.code,state.guide,state.debug]);
  useEffect(()=>{let active=true;setHash("");void codeHash(state.code).then(value=>{if(active)setHash(value);});return()=>{active=false;};},[state.code]);
  const stale = Boolean(record && (record.current_target===false || record.binding.code_hash!==hash || record.binding.project_id!==(state.design?.id??null) || JSON.stringify(record.binding.test_keys??{})!==JSON.stringify(context.test_keys)));
  const working = debug.pending || record?.status === "diagnosing" || record?.status === "analysing";
  const cid = state.design?.component_ids.find(id=>id===(state.debug?.selectedComponentId??state.debug?.componentId)) ?? state.design?.component_ids[0];
  const issues = record?.issues ?? [];
  // Connection actions live in the top toolbar. Keep their evidence in the
  // report, but reserve the recommendation card for actual test/code issues.
  const recommendations = stale ? [] : issues.filter(item=>item.next_action!=="reconnect" && item.reason!=="connection_lost" && (!item.component_id || (!programSelected && item.component_id===cid)));
  const issue = recommendations[0];
  const trial = debug.trials.active ?? debug.trials.results.at(-1);
  const trialCurrent = trial?.binding.code_hash===hash && trial.project_id===state.design?.id && JSON.stringify(trial.binding.test_keys??{})===JSON.stringify(context.test_keys);
  const trialQueued = pi.status?.execution?.jobs.some(j=>j.kind==="trial" && !["failed","cancelled","finished"].includes(j.state));
  const reasons:Record<string,[string,string]> = {
    syntax_error:["程式有一段寫法需要修正，可以請 AI 幫你找出來。","Part of the code needs correcting. AI can help you find it."],
    different_program:["Pi 執行的版本與目前草稿不同。","Pi is running a different version from this draft."],
    execution_changed:["進入除錯後，Pi 執行版本已改變；目前日誌不能當成先前程式的證據。","The Pi invocation changed after entering Debug; current logs are not evidence for the earlier program."],
    telemetry_unknown:["還不能確認距離或畫面有持續更新，請再觀察一次實體反應。","We cannot yet confirm that readings or the display keep updating. Observe the hardware response."],
    display_stalled:["程式還在執行，但沒有繼續送出新畫面。先檢查程式，不必急著重接線。","The program is running but no longer sending new images. Check the code before rewiring."],
    untested:["尚未測試；可以單項重測，也可以稍後處理。","Not tested; retest this module or continue later."],
    stale_result:["之前的結果已不能代表目前接線。只要重測這個零件，不必全部重來。","The earlier result no longer represents this wiring. Retest just this component, not everything."],
    visual_required:["程式已結束，請確認本次實體畫面是否同步更新。","Run finished. Confirm whether the physical display updated in sync."],
    insufficient_evidence:["證據不足，未判定整合通過。請確認新距離、移動變化及實體畫面。","Insufficient evidence; fresh samples, movement and physical observation are required."],
    unsupported_draft:["手寫或已修改的硬體程式只提供分析，不自動覆蓋。","Custom hardware code is diagnosis-only; no automatic replacement."],
    repair_limit_reached:["本案例已達兩輪，請保留紀錄並交由工程檢查。","Two-round limit reached; retain evidence for engineering review."],
    stale_candidate:["草稿或接線已變更，不能套用舊修復。","Draft or wiring changed; this candidate cannot be applied."],
    stale_diagnosis:["診斷與目前草稿不同，請重新診斷。","Diagnosis belongs to a different draft; diagnose again."],
    case_not_found:["先前診斷紀錄已不存在；按一鍵診斷建立新紀錄。正在執行的試跑仍可停止。","Previous diagnosis is unavailable; run diagnosis again. Active trials can still be stopped."],
    stale_restore:["草稿已變更，不能直接還原舊備份；請先保留目前修改。","The draft changed; preserve current edits before restoring an older backup."],
    backend_restarted:["上次工作已中斷，不會自動重送。","Previous operation interrupted; it will not be replayed."],
    no_echo:["還沒有收到足夠的距離讀值，現在不能判定接錯線。","Not enough distance readings yet. This does not mean the wiring is wrong."],
    movement_not_confirmed:["這次沒有測到明顯的遠近變化，準備好物體後可以再試一次。","We did not detect a clear near/far change. Prepare the target and try again."],
    missing_dependency:["Pi 還缺少測試需要的套件，先完成環境準備，不用重接線。","Pi needs some software before testing. Complete setup; no rewiring is needed."],
    reader_error:["讀取距離的程式中斷了，這不代表你接錯線。","The distance-reading program stopped unexpectedly. This does not mean you wired it incorrectly."],
  };
  const message=(reason?:string)=>{const text=reason&&(reasons[reason]??testReasons[reason]);return text?tr(...text):reason?tr("還不能確認原因，請展開詳細報告查看。","The cause is not confirmed. See the detailed report."):tr("尚未檢查","Not checked yet");};
  const outcome=(value?:string)=>({passed:tr("功能通過（歷史紀錄）","Passed (historical record)"),failed:tr("未通過","Not passed"),running:tr("執行中","Running"),awaiting_confirmation:tr("等待使用者確認","Awaiting confirmation"),inconclusive:tr("無法判定","Inconclusive")}[value??""]??tr("未測試","Not tested"));
  const progress:Record<string,string>={environment:tr("檢查連線與環境","Checking connection and environment"),code_and_results:tr("核對程式與測試紀錄","Checking code and test records"),finished:tr("檢查完成","Checks complete")};
  const program:Record<string,string>={running:tr("執行中","Running"),stopped:tr("已停止","Stopped"),inactive:tr("未執行","Inactive"),failed:tr("執行失敗","Failed"),starting:tr("啟動中","Starting"),stopping:tr("停止中","Stopping"),unknown:tr("未知","Unknown")};
  const connected = Boolean(pi.status?.connected) && !pi.networkError;
  const showProblem = Boolean(issue || record?.status==="diagnosing" || (connected && (!record || stale || issues.length===0)));
  const moduleName = (id:string) => id==="hc-sr04"?"HC-SR04+":id==="mrd-tf240-8p-cs"?"MRD-TFT240":id;
  const problemTitle = record?.status==="diagnosing" ? tr("正在幫你檢查…", "Checking things for you…")
    : !record ? tr("先做一次快速檢查", "Start with a quick check")
    : stale ? tr("作品有更新，再檢查一次", "Your project changed. Check again")
    : issue?.reason==="no_echo" ? tr("先讓 HC-SR04+ 測到距離", "Let's get a distance reading")
    : issue?.reason==="missing_dependency" ? tr("先把 Pi 的測試工具準備好", "Let's get Pi ready for testing")
    : issue?.component_id ? `${moduleName(issue.component_id)} · ${tr("需要再確認一次", "Needs another check")}`
    : issue ? tr("有一個地方需要你確認", "One thing needs your attention")
    : record.status==="ready" ? tr("目前沒有找到阻礙執行的問題", "No blocking issue found")
    : tr("還需要一些資訊", "We need a little more information");
  const nextStep = record?.status==="diagnosing" ? tr("稍等一下，檢查完成後會告訴你下一步。", "Please wait. We'll suggest the next step when the check finishes.")
    : !record||stale ? tr("按上方「幫我檢查」，先看看連線、零件紀錄與程式。", "Use Check for me above to review the connection, test records and code.")
    : issue?.next_action==="prepare_environment" ? tr("先展開「詳細檢查報告」查看缺少的套件或設定；請勿為此改接線。", "Open the detailed report for missing software or settings. Do not rewire for this issue.")
    : issue?.next_action==="execution_manager"||issue?.next_action==="stop_or_retry" ? tr("查看上方「執行管理」，先確認目前正在執行什麼，再決定是否停止或重測。", "Check Execution at the top to see what is running before deciding to stop or retry.")
    : issue?.next_action==="review_version" ? tr("Pi 上的程式可能不是這份草稿。先在報告核對版本，再決定是否重新部署。", "The Pi program may differ from this draft. Review its version in the report before redeploying.")
    : issue?.next_action==="analyse" ? tr("可以請 AI 幫你理解程式問題；看過建議並確認後才會修改。", "Ask AI to explain the code issue. Nothing is changed until you review and confirm.")
    : issue?.next_action==="trial" ? tr("做一次 60 秒試跑，移動前方物體並觀察實體畫面；先不要把沒有紀錄當作接錯線。", "Try a 60-second run, move the target and observe the display. Missing records do not mean the wiring is wrong.")
    : issue?.component_id==="hc-sr04" ? tr("在 HC-SR04+ 前放一本書或平整物體，再測一次；仍無讀值時才回頭核對接線。", "Place a book or flat object in front of HC-SR04+ and retest. Review wiring if readings are still absent.")
    : issue?.component_id ? tr("按下重測，看看螢幕是否出現顏色和數字，再依你看到的狀況繼續。", "Retest, look for colors and a code on the screen, then choose what you see.")
    : issue ? tr("可以請 AI 幫你理解程式問題；看過建議並確認後才會修改。", "Ask AI to explain the code issue. Nothing is changed until you review and confirm.")
    : tr("可以做一次 60 秒試跑，親眼確認零件反應；也可以先前往部署。", "Try a 60-second run to observe the hardware, or continue to deployment.");
  function openRetest(componentId:string) {
    if (!state.design?.component_ids.some(id=>id===componentId)) return;
    setProgramSelected(false);
    onSelect(componentId);
    setRetestFocusRequest(request=>request+1);
  }
  function revealDetails(target:HTMLDetailsElement|null) {
    if (!target) return;
    target.open = true;
    target.querySelector("summary")?.focus({preventScroll:true});
    target.scrollIntoView({behavior:"auto",block:"start"});
  }
  async function diagnose() { const next=await debug.action<DebugCase>("debug/cases",{context,case_id:state.debug?.caseId});if(next)onCase(next.id); }
  async function agent() {if(record)await debug.action(`debug/cases/${record.id}/actions`,{action:"analyse",context,model:state.aiModel||null,effort:state.aiEffort});}
  async function apply() {
    if(!record?.candidate)return;
    setConfirmAction(null);
    const result=await debug.action<{code:string}>(`debug/cases/${record.id}/actions`,{action:"apply",context,candidate_id:record.candidate.id,confirmed:true});
    if(result)onCode(result.code,context.code);
  }
  async function restore() {
    if(!record)return;
    setConfirmAction(null);
    const result=await debug.action<{code:string}>(`debug/cases/${record.id}/actions`,{action:"restore",context,confirmed:true});if(result)onCode(result.code,context.code);
  }
  const focusedReport = record ? {...record, selected_component:programSelected?"program":cid, issues:issues.filter(item=>!item.component_id || (!programSelected && item.component_id===cid)), evidence:{...record.evidence, tests:record.evidence?.tests?.filter(run=>!programSelected && run.component_id===cid)}} : null;
  async function copy() {try{await navigator.clipboard.writeText(JSON.stringify({diagnosis:focusedReport,trials:debug.trials},null,2));setCopied(true);}catch{setCopied(false);}}
  const controls = <>    <div className="debug-symptom-picker" aria-label={tr("選擇遇到的狀況", "Choose the problem")}>
      {state.design?.component_ids.includes("hc-sr04")?<button className="debug-symptom" aria-pressed={!programSelected && cid==="hc-sr04"} aria-controls="debug-targeted-retest" onClick={()=>openRetest("hc-sr04")}><span className="workflow-eyebrow">HC-SR04+</span><strong>{tr("測不到距離，或數字不對", "No distance, or unexpected readings")}</strong><span>{tr("放好物體，測一次遠近反應", "Place a target and check near/far response")}</span><b>{tr("檢查這個零件 →", "Check this component →")}</b></button>:null}
      {state.design?.component_ids.includes("mrd-tf240-8p-cs")?<button className="debug-symptom" aria-pressed={!programSelected && cid==="mrd-tf240-8p-cs"} aria-controls="debug-targeted-retest" onClick={()=>openRetest("mrd-tf240-8p-cs")}><span className="workflow-eyebrow">MRD-TFT240</span><strong>{tr("沒有畫面，或顏色不對", "No picture, or wrong colors")}</strong><span>{tr("測試顏色與數字，確認螢幕反應", "Check the screen with colors and a code")}</span><b>{tr("檢查這個零件 →", "Check this component →")}</b></button>:null}
      <button className="debug-symptom" aria-pressed={programSelected} onClick={()=>{setProgramSelected(true);revealDetails(agentDetails.current);}}><span className="workflow-eyebrow">{tr("作品程式", "Project program")}</span><strong>{tr("作品沒有反應，或出現錯誤", "Project won't run, or shows an error")}</strong><span>{tr("先檢查程式，再決定是否請 AI 幫忙", "Check the code, then decide whether to ask AI")}</span><b>{tr("看看怎麼處理 →", "See what to do →")}</b></button>
    </div>
</>;
  const trialOutput = <>      {trial?<section className="debug-trial-result"><h3>{tr("整體作品試跑結果", "Whole-project trial result")}</h3><p className="workflow-state neutral">{outcome(trial.outcome)} · {new Date(trial.created_at*1000).toLocaleString()}</p>
        {!trialCurrent?<p>{tr("此為不同草稿／作品的歷史試跑，不可驗證目前作品。","This run is for another draft/project and cannot validate the current one.")}</p>:null}
        {trial.program_stopped?<p className="guide-caution">{tr("原作品已停止，測試結束不會自動重啟。","Original project stopped; it will not restart automatically.")}</p>:null}
        <ul><li>{tr("程式有正常運作嗎？","Is the program working?")}: {trial.evidence?.program_ok?tr("有", "Yes"):tr("還不能確認","Not confirmed yet")}</li><li>{tr("有收到新的距離嗎？","Any new distance readings?")}: {(trial.evidence?.sample_seq??0)>0?tr("有", "Yes"):tr("還沒有","Not yet")}</li><li>{tr("有送出新的畫面嗎？","Any new images sent?")}: {(trial.evidence?.display_seq??0)>0?tr("有，還需要看實體螢幕確認", "Yes; check the physical screen too"):tr("還沒有","Not yet")}</li><li>{tr("最後回報時間","Last report time")}: {trial.heartbeat_at?new Date(trial.heartbeat_at*1000).toLocaleTimeString():"—"}</li></ul>
        {trial.reason?<p>{message(trial.reason)}</p>:null}
        {trial.outcome==="awaiting_confirmation"&&trialCurrent?<><label><input type="checkbox" checked={visualRun===trial.id} onChange={e=>setVisualRun(e.target.checked?trial.id:"")}/>{tr("我已觀察本次實體反應：移動後距離有變化；有螢幕時也同步更新。","I observed this run: distance changed with movement, and the screen (if present) updated in sync.")}</label><button disabled={debug.pending||visualRun!==trial.id} onClick={()=>void debug.action(`debug/trials/${trial.id}/actions`,{action:"visual",context,observed:true})}>{tr("送出本次目視確認","Confirm this observation")}</button></>:null}
        {trial.outcome==="awaiting_confirmation"&&trialCurrent?<button disabled={debug.pending} onClick={()=>void debug.action(`debug/trials/${trial.id}/actions`,{action:"visual",context,observed:false})}>{tr("沒有同步／無反應","No sync / no response")}</button>:null}
        <details><summary>{tr("本次試跑證據與日誌","Trial evidence and logs")}</summary><pre>{JSON.stringify(trial,null,2)}</pre></details>
      </section>:null}
</>;
  const reports = <>{trialOutput}    {showProblem?<section className="debug-problem"><span className="workflow-eyebrow">{tr("建議先做這件事","Your next step")}</span><h3>{problemTitle}</h3>
      <p>{record?.status==="diagnosing"?tr("正在讀取狀態，先不用改接線。","Reading the current status. No need to rewire."):issue?message(issue.reason):!stale&&record?.status==="ready"?tr("軟體檢查沒有發現阻塞，但實體反應仍需要你確認。","Software checks found no blocker. You still need to observe the hardware."):tr("我們會把需要注意的地方整理在這裡，一次處理一件事。","We'll collect what needs attention here, one step at a time.")}</p>
      <p className="debug-next-step">{nextStep}</p>
      <div className="debug-actions">
      {connected&&issue?.component_id&&state.design?.component_ids.some(id=>id===issue.component_id)?<button className="guide-primary-action" aria-controls="debug-targeted-retest" onClick={()=>openRetest(issue.component_id!)}>{tr("重測", "Retest")} {moduleName(issue.component_id)}</button>:null}
      {connected&&issue?.next_action==="analyse"?<button className="workflow-secondary" onClick={()=>revealDetails(agentDetails.current)}>{tr("看看 AI 可以怎麼幫忙","See how AI can help")}</button>:null}
      {connected&&["prepare_environment","review_version"].includes(issue?.next_action??"")?<button className="workflow-secondary" onClick={()=>revealDetails(reportDetails.current)}>{tr("查看需要處理的項目","See what needs attention")}</button>:null}
      {connected&&issue?.next_action==="trial"?<button className="workflow-secondary" onClick={()=>revealDetails(trialDetails.current)}>{tr("前往 60 秒試跑","Go to the 60-second trial")}</button>:null}
      </div>
      {recommendations.length>1?<details><summary>{tr("其他待確認項目","Other things to check")} ({recommendations.length-1})</summary>{recommendations.slice(1).map((item,i)=><p key={i}>{item.component_id?moduleName(item.component_id):"Pi"} · {message(item.reason)}</p>)}</details>:null}
    </section>:null}
    <details className="debug-overview"><summary>{tr("查看上次檢查的結果", "Review the last check")}</summary>
    <div className="debug-status-grid">
      <article><span className="workflow-eyebrow">01</span><h3>{tr("Pi 連線","Pi connection")}</h3><strong className={`workflow-state ${connected?"good":"neutral"}`}>{connected?tr("已連線","Connected"):tr("還沒連上","Not connected")}</strong><small>{record?.evidence?.environment_ready?tr("環境：上次檢查已準備好","Setup was ready at last check"):tr("環境準備尚待確認","Setup still needs checking")}</small></article>
      {["hc-sr04","mrd-tf240-8p-cs"].map((id,index)=>{const run=record?.evidence?.tests?.filter(r=>r.component_id===id).at(-1);const matches=run&&!run.invalidated&&run.guide_key===context.test_keys[id]&&record?.current_target!==false;return <article key={id}><span className="workflow-eyebrow">0{index+2}</span><h3>{moduleName(id)}</h3><strong className="workflow-state neutral">{state.design?.component_ids.some(cid=>cid===id)?matches?outcome(run.outcome):run?tr("需要再確認","Needs another check"):tr("還沒測試","Not tested yet"):tr("這份作品沒有使用","Not used in this project")}</strong><small>{run?`${tr("上次測試","Last tested")} ${new Date(run.created_at*1000).toLocaleString()}`:tr("測試後會保留結果","Results appear after testing")}</small></article>;})}
      <article><span className="workflow-eyebrow">04</span><h3>{tr("作品程式","Project program")}</h3><strong className="workflow-state neutral">{record?program[record.evidence?.pi?.program??"unknown"]??tr("待確認","Not yet confirmed"):tr("還沒檢查","Not checked yet")}</strong><small>{tr("以最近一次檢查為準","As of the last check")}</small></article>
    </div>
    </details>
    <details ref={agentDetails} className="debug-agent workflow-details"><summary><strong>{tr("還是沒解決？讓 AI 幫忙","Still stuck? Ask AI for help")}</strong><span>{record?.analysis?tr("已有分析建議，展開查看","Suggestions ready · open to review"):tr("解釋程式問題，修改前會先問你","Understand the code · review before changes")}</span></summary><div className="workflow-details-body"><p className="workflow-muted">{tr("AI 分析涵蓋整份作品程式；零件是否正常仍以該零件測試為準。", "AI reviews the whole project; component health still depends on its own test.")}</p>
      <p>{tr("AI 可以幫你看程式，不會直接改接線或啟動作品。按下分析才會傳送程式與檢查紀錄，密碼與金鑰會先遮蔽。", "AI can review the code, but won't rewire or start your project. Only Analyze sends code and checks; passwords and keys are redacted.")}</p>
      {!record||stale?<p className="workflow-muted">{tr("先按「幫我檢查」，讓 AI 有足夠的資訊可以判斷。","Run Check for me first so AI has evidence to work with.")}</p>:null}
      {!record||stale?<button className="guide-primary-action" disabled={working} onClick={()=>void diagnose()}>{tr("先幫我檢查", "Check first")}</button>:null}
      <button disabled={!state.design||!record||stale||working||(record.rounds>=2)} onClick={()=>void agent()}>{tr("請 AI 幫我分析","Ask AI to analyze")} ({record?.rounds??0}/2)</button>
      {record?.eligible===false?<p>{message("unsupported_draft")}</p>:null}
      {(record?.rounds??0)>=2?<p>{message("repair_limit_reached")}</p>:null}
      {record?.analysis?<div className="debug-ai-result"><h3>{tr("AI 已完成分析", "AI review is ready")}</h3><p>{stale?tr("這是先前的分析，重新檢查後再決定下一步。", "This is an earlier review. Check again before deciding what to do."):record.candidate?tr("有一份程式修改建議。先看修改內容，確認後才會套用。", "A code change is suggested. Review it before confirming any change."):tr("目前沒有可直接套用的修改。可依本頁建議重測，或展開完整分析。", "There is no ready-to-apply change. Follow the suggested test or open the full review.")}</p><details className="debug-analysis-details"><summary>{tr("查看完整 AI 分析（進階）", "Full AI review (advanced)")}</summary><p>{tr("檢查紀錄", "Evidence")}: {record.analysis.facts}</p><p>{tr("可能原因（尚未確認）", "Possible causes (unconfirmed)")}: {record.analysis.possible_causes}</p><p>{tr("AI 建議", "AI suggestions")}: {record.analysis.next_step}</p></details></div>:null}
      {record?.candidate?<><details><summary>{tr("候選修改差異／離線測試","Candidate diff / offline checks")}</summary><pre>{record.candidate.diff}</pre><pre>{JSON.stringify(record.candidate.offline,null,2)}</pre></details><button disabled={working||stale||record.candidate.applied} onClick={()=>setConfirmAction("apply")}>{tr("套用修復並試跑","Apply repair and trial")}</button></>:null}
      {record?.can_restore?<button disabled={working} onClick={()=>setConfirmAction("restore")}>{tr("還原上一版草稿","Restore previous draft")}</button>:null}
      {confirmAction?<div className="guide-caution" role="group" aria-label={tr("確認草稿變更","Confirm draft change")}><p>{confirmAction==="apply"?tr("套用此邏輯修復並加入 60 秒試跑佇列？若需停止目前程式，還會在執行管理要求確認。","Apply this logic repair and queue a 60-second trial? Stopping the current program requires a separate handoff confirmation."):tr("還原上一版草稿？不會停止或重新啟動 Pi 程式。","Restore the previous draft? This does not stop or restart Pi programs.")}</p><button disabled={working||(confirmAction==="apply"&&stale)} onClick={()=>void(confirmAction==="apply"?apply():restore())}>{tr("確認執行","Confirm")}</button><button onClick={()=>setConfirmAction(null)}>{tr("取消","Cancel")}</button></div>:null}
    </div></details>
    <details ref={reportDetails} className="workflow-details debug-report"><summary><strong>{tr("詳細檢查報告","Detailed check report")}</strong><span>{tr("需要協助時再展開 · 紀錄、版本與修改歷程","Records, versions and changes, when you need them")}</span></summary><div className="workflow-details-body">
      {state.debug?.source?<p>{tr("問題來源","Entry")}: {state.debug.source==="guide"?"03":"05"} · {state.debug.componentId??state.debug.deployment?.run_id??"Pi"} {state.debug.runId?`· ${state.debug.runId.slice(0,8)}`:""} {state.debug.symptom?`· ${message(state.debug.symptom)}`:""}</p>:null}
      <p><b>{tr("已確認事項：","Confirmed: ")}</b>{issue?.fact||tr("還沒有足夠資訊確認原因。","Not enough information to confirm a cause yet.")}</p>
      <small>{tr("實際版本","Actual version")}: {record?.evidence?.pi?.version?.code_hash.slice(0,12)??tr("尚未取得","Not available")}</small>
      <button onClick={()=>void copy()}>{copied?tr("已複製","Copied"):tr("複製報告，尋求協助","Copy report for support")}</button>
      <p className="workflow-muted">{tr("報告已遮蔽密碼與金鑰。","Passwords and keys are redacted.")}</p><pre>{JSON.stringify(focusedReport,null,2)}</pre>
    </div></details>
    {debug.error||record?.error?<p className="pi-error" role="alert">{debug.error.includes("404")?tr("除錯 API 尚未載入，請重新啟動 Board Vision 後端。","Debug API is unavailable; restart the Board Vision backend."):message(debug.error||record?.error)}</p>:null}
</>;
  const trialTools = <>    <section ref={trialCard} className="debug-trial" tabIndex={-1}><details ref={trialDetails} className="debug-tool" open={Boolean(trial?.reserved||trial?.outcome==="awaiting_confirmation"||trialQueued)||undefined}><summary><strong>{tr("零件都好了？一起試跑 60 秒", "Components ready? Try them together for 60 seconds")}</strong><span>{tr("最後再做，不必每次都測", "Optional final check")}</span></summary><p>{tr("移動前方物體，看看距離與實體螢幕是否一起變化。只試跑 60 秒，不覆蓋正式作品。", "Move the target and watch whether distance and the screen change together. This 60-second trial does not replace the deployed project.")}</p>
      <button disabled={!state.design||debug.pending||trialQueued||Boolean(trial?.reserved)} onClick={()=>void debug.action("debug/trials",{context,request_id:crypto.randomUUID()})}>{tr("開始 60 秒試跑","Start 60-second trial")}</button>
      {trial?.reserved?<button disabled={debug.pending} onClick={()=>void debug.action(`debug/trials/${trial.id}/actions`,{action:"stop"})}>{tr("停止本次試跑","Stop this trial")}</button>:null}
      {trialQueued?<p>{tr("已排入共用佇列；若需交接，請在上方執行管理確認。","Queued; confirm any handoff in Execution above.")}</p>:null}
    </details></section>
</>;
  return <section className="debug-page" aria-label={tr("測試與除錯","Test & debug")}>
    <header className="debug-heading workflow-heading"><div><div className="workflow-eyebrow">{tr("04 · 測試與除錯", "04 · Test & debug")}</div><h2>{tr("哪個地方沒有正常運作？", "What isn't working?")}</h2>
      <p className="workflow-subtitle">{tr("選擇你看到的狀況，我們帶你檢查。不確定就按「幫我檢查」。", "Choose what you see and we'll guide you. Not sure? Choose Check for me.")}</p></div>
      <div className="workflow-heading-actions"><button className="guide-primary-action" disabled={working} onClick={()=>void diagnose()}>{working?tr("正在檢查…","Checking…"):tr("幫我檢查","Check for me")}</button>
      <button className="workflow-secondary" onClick={onDeploy}>{tr("先去啟動作品 →","Go to deployment →")}</button></div></header>
    <div className="debug-check-note"><span>{tr("「幫我檢查」不會改程式或接線，也不會啟動測試或 AI。", "Check for me won't change code or wiring, start tests, or contact AI.")}</span>
      <span className="debug-timestamp" role="status">{record?.status==="diagnosing"?(progress[record.progress]??tr("檢查中","Checking")):record?.finished_at?`${tr("上次檢查","Last checked")} ${new Date(record.finished_at*1000).toLocaleString()}`:tr("還沒有檢查紀錄","No checks yet")}</span></div>
    {stale?<p className="guide-caution">{tr("這是上次的檢查紀錄。作品已更新，請按「幫我檢查」。","These are earlier results. The project changed; choose Check for me.")}</p>:null}
    {state.design&&cid ? <TargetedTest design={state.design} guide={state.guide} cid={cid} focusRequest={retestFocusRequest} onWiring={onWiring} programSelected={programSelected} before={controls} after={trialTools} report={reports}/> :
      <div className="debug-workspace"><div className="debug-controls">{controls}<p>{tr("先建立作品，就能使用零件測試與試跑。現在仍可以檢查 Pi 連線。","Create a project to test components. You can still check the Pi connection.")}</p>{trialTools}</div><aside className="debug-results" aria-label={tr("輸出結果與報告", "Results and reports")}><h3>{tr("輸出結果", "Results")}</h3>{reports}</aside></div>}
    <small>{tr("改接線前斷電，接好再上電測試。功能通過不代表所有線路與電壓已驗證。","Power off before rewiring, then power on to test. Functional success does not verify all wiring or voltages.")}</small>
  </section>;
}
