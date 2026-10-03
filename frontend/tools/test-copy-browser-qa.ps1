# Read-only UI scenarios; 18780/18781 are isolated fixtures, never the real Pi.
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$outputDir = Join-Path $qaRoot 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session compact-test @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session compact-test eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$samples = @(
    @(1651,871,'dark','zh-TW','awaiting_near'),
    @(1413,871,'dark','zh-TW','awaiting_near'),
    @(1413,871,'dark','zh-TW','awaiting_far'),
    @(1413,871,'dark','zh-TW','sampling_near'),
    @(1413,871,'dark','zh-TW','display_red'),
    @(1352,871,'light','en','display_code'),
    @(1413,871,'dark','zh-TW','awaiting_visual'),
    @(1352,871,'light','en','awaiting_visual'),
    @(390,871,'light','en','awaiting_visual'),
    @(1352,520,'dark','zh-TW','lost')
)
$metrics = foreach ($sample in $samples) {
    $width,$height,$theme,$locale,$phase = $sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    $query = if ($phase -eq 'lost') {'guide-case=lost'} else {"test-phase=$phase"}
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&$query") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $initial = Evaluate @'
(() => {
 const body=document.querySelector('.guide-panel-body'), controls=document.querySelector('.guide-test-controls');
 const details=body.querySelector('.test-diagnostics'), phase=new URLSearchParams(location.search).get('test-phase');
 const errors=[], saved=localStorage.getItem('boardvision.maker.v1');
 if(!body.querySelector('.test-next-step') || !details || details.open) errors.push('missing instruction or expanded telemetry');
 if(/最後回報時間|Last report time/.test(body.innerText))errors.push('telemetry shown by default');
 if(body.querySelector('.test-reading')) errors.push('placeholder reading shown');
 if(innerWidth>1100&&innerHeight>=800){
   if(body.scrollHeight>body.clientHeight+1)errors.push('default instructions require inner scroll');
   if(controls.scrollHeight>controls.clientHeight+1)errors.push('default test actions require inner scroll');
   const c=controls.getBoundingClientRect();
   for(const b of controls.querySelectorAll('button,input')){
     const r=b.getBoundingClientRect();
     if(r.top<c.top-1||r.bottom>c.bottom+1||r.bottom>innerHeight+1)errors.push('default test control clipped');
   }
 }
 if(![...controls.querySelectorAll('button')].some(b=>/停止本次測試|Stop this test/.test(b.textContent)))errors.push('stop missing');
 if(phase==='display_code'&&!/15/.test(body.querySelector('.test-next-step').textContent))errors.push('code hold duration missing');
 if(phase==='awaiting_visual'){
   const confirm=controls.querySelector('.test-visual-confirm > button');
   if(controls.querySelectorAll('input[type=radio]').length!==4 || !confirm.disabled)errors.push('confirmation guard missing');
   controls.querySelector('input[type=radio]').click();
   controls.querySelector('input[type=checkbox]').click();
 } else if(controls.querySelector('input[type=radio]'))errors.push('premature screen confirmation');
 window.__compactTestQa={errors,saved};
 details.querySelector('summary').click();
 return {phase};
})()
'@
    Browser @('snapshot','-i') | Out-Null
    $result = Evaluate @'
(() => {
 const {errors,saved}=window.__compactTestQa;
 const body=document.querySelector('.guide-panel-body'),controls=document.querySelector('.guide-test-controls');
 const details=body.querySelector('.test-diagnostics');
 if(!details.open||!/Last report time|最後回報時間/.test(details.innerText))errors.push('telemetry unavailable');
 details.querySelector('summary').click();
 const confirm=controls.querySelector('.test-visual-confirm > button');
 if(confirm?.disabled)errors.push('code and colors not accepted');
 const target=confirm??controls.querySelector('button');
 target.scrollIntoView({block:'center'});target.focus();
 const r=target.getBoundingClientRect(),c=controls.getBoundingClientRect();
 if(r.top<c.top-1||r.bottom>c.bottom+1||r.top<0||r.bottom>innerHeight+1)errors.push('control unreachable');
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 if(localStorage.getItem('boardvision.maker.v1')!==saved)errors.push('project changed');
 errors.push(...window.__stageQa.errors);
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected hardware write');
 return {width:innerWidth,height:innerHeight,query:location.search,bodyHeight:body.clientHeight,bodyScrollHeight:body.scrollHeight,controlsHeight:controls.clientHeight,controlsScrollHeight:controls.scrollHeight,errors,writes};
})()
'@
    Browser @('snapshot','-i') | Out-Null
    if ($result.errors.Count) { throw "Test presentation failed: $($result | ConvertTo-Json -Depth 5 -Compress)" }
    Browser @('screenshot',(Join-Path $outputDir "test-compact-$phase-$theme-$locale-${width}x$height.png")) | Out-Null
    Write-Host "PASS $phase $theme $locale ${width}x$height"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'test-compact-matrix.json') -Encoding utf8
