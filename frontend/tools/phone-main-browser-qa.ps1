param([string]$BaseUrl='http://127.0.0.1:18780')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$repoRoot=Split-Path $PSScriptRoot -Parent
$qaDir=Join-Path (Split-Path $repoRoot -Parent) 'docs/qa/unified-assistant'
function Invoke-PhoneBrowser {
  param([string[]]$Arguments)
  if($Arguments[0] -eq 'eval'){
    $result=$Arguments[1] | & npx --yes agent-browser --session phone-main eval --stdin
  }else{
    $result=& npx --yes agent-browser --session phone-main @Arguments
  }
  if($LASTEXITCODE -ne 0){throw "Browser check failed: $($Arguments -join ' ')`n$result"}
  return $result
}
$cases=@(
  @{name='desktop';width=1413;height=871;lang='zh-TW';theme='dark'},
  @{name='light-en';width=1352;height=871;lang='en';theme='light'},
  @{name='short-en';width=1352;height=520;lang='en';theme='light'},
  @{name='mobile-en';width=390;height=871;lang='en';theme='light'}
)
foreach($case in $cases){
  $null=Invoke-PhoneBrowser @('set','viewport',"$($case.width)","$($case.height)")
  $null=Invoke-PhoneBrowser @('open',"$BaseUrl/?lang=$($case.lang)&theme=$($case.theme)&guide-case=ready&phone-preview=1")
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $null=Invoke-PhoneBrowser @('click','.mobile-header-slot button')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $null=Invoke-PhoneBrowser @('eval','(() => {if(window.__stageQa.phoneViewers.opened)throw Error("Popup opened another viewer");return true;})()')
  $null=Invoke-PhoneBrowser @('click','.mobile-companion-panel>header>button')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $null=Invoke-PhoneBrowser @('click','.mobile-view-controls-slot button:first-child')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $script=@'
(async () => {
  const p=document.querySelector('.mobile-main-preview'),video=p.querySelector('video');
  for(let i=0;i<20&&!video.videoWidth;i++)await new Promise(r=>setTimeout(r,50));
  const entry=document.querySelector('.mobile-header-slot button').getBoundingClientRect();
  const pi=document.querySelector('.pi-global-connect').getBoundingClientRect();
  const views=document.querySelector('.mobile-view-controls-slot').getBoundingClientRect();
  const tools=document.querySelector('.camera-tools-menu .statusbar-toggle').getBoundingClientRect();
  const capture=p.querySelector('.mobile-stream-capture>button').getBoundingClientRect(),box=p.getBoundingClientRect();
  if(entry.right>pi.left+1||Math.abs((entry.top+entry.height/2)-(pi.top+pi.height/2))>1)throw Error('Phone connection must sit left of Pi');
  if(views.right>tools.left+1||Math.abs((views.top+views.height/2)-(tools.top+tools.height/2))>1)throw Error('Phone views must share camera tools row');
  if(p.scrollHeight>p.clientHeight+1||document.documentElement.scrollWidth>innerWidth+1)throw Error('Unnecessary overflow');
  if(capture.bottom>box.bottom+1||capture.top<box.top||!video.videoWidth)throw Error('Capture or video not visible');
  if(document.querySelector('.mobile-companion-panel')||!document.querySelector('.video-shell').hidden)throw Error('Source display mismatch');
  if(window.__stageQa.phoneViewers.opened!==1||window.__stageQa.phoneViewers.closed||window.__stageQa.errors.length)throw Error('Viewer lifecycle/error');
  if(innerWidth<=1099&&capture.height<44)throw Error('Touch target too small');
  window.__phoneQaOriginal={webcam:document.querySelector('.video-shell'),maker:localStorage.getItem('boardvision.maker.v1')};
  return {viewport:[innerWidth,innerHeight],oneViewer:true,videoSize:[video.videoWidth,video.videoHeight],captureFits:true,noInnerOverflow:true,errors:window.__stageQa.errors};
})()
'@
  $metrics=Invoke-PhoneBrowser @('eval',$script)
  Write-Output "$($case.name): $metrics"
  $null=Invoke-PhoneBrowser @('screenshot',(Join-Path $qaDir "phone-main-$($case.name).png"))
  if($case.name -eq 'desktop'){
    $null=Invoke-PhoneBrowser @('click','.assistant-collapse')
    $null=Invoke-PhoneBrowser @('snapshot','-i')
  }
  $null=Invoke-PhoneBrowser @('click','.mobile-header-slot button')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $null=Invoke-PhoneBrowser @('eval','(() => {const r=document.querySelector(".mobile-companion-panel").getBoundingClientRect();if(r.left<0||r.right>innerWidth||r.top<0||r.bottom>innerHeight||window.__stageQa.phoneViewers.opened!==1)throw Error("Panel fit/duplicate viewer");return true;})()')
  $null=Invoke-PhoneBrowser @('click','.mobile-companion-panel>header>button')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $null=Invoke-PhoneBrowser @('click','.mobile-main-preview>header>button')
  $null=Invoke-PhoneBrowser @('snapshot','-i')
  $returnCheck=@'
(() => {
  const webcam=document.querySelector('.video-shell'),qa=window.__stageQa;
  if(webcam!==window.__phoneQaOriginal.webcam||webcam.hidden||localStorage.getItem('boardvision.maker.v1')!==window.__phoneQaOriginal.maker)throw Error('Webcam/project changed');
  if(qa.phoneViewers.opened!==1||qa.phoneViewers.closed!==1||qa.errors.length)throw Error('Viewer cleanup/error');
  const allowed=['/api/assistant/conversations','/api/mobile/context','/api/mobile/stream/offer','/api/ai/estimate'];
  const writes=qa.requests.filter(r=>r.method!=='GET');
  if(writes.some(r=>!allowed.includes(r.path)))throw Error('Unexpected camera/Pi/cloud write');
  return {retainedWebcam:true,unchangedProject:true,viewers:qa.phoneViewers,writes};
})()
'@
  $checked=Invoke-PhoneBrowser @('eval',$returnCheck)
  Write-Output "$($case.name) return: $checked"
}
