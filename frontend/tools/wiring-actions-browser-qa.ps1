# Isolated 18780/18781 fixtures only. Never click a hardware or AI submission.
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$outputDir = Join-Path $qaRoot 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session guide-actions @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session guide-actions eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$samples = @(
    @(1413,871,'dark','zh-TW','ready'), @(1651,871,'dark','zh-TW','visual'),
    @(1352,871,'light','en','disconnected'), @(1100,871,'light','en','ready'),
    @(390,871,'light','en','visual'), @(390,871,'dark','zh-TW','ready'),
    @(1352,520,'dark','zh-TW','lost')
)
$metrics = foreach ($sample in $samples) {
    $width,$height,$theme,$locale,$scenario = $sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=$scenario") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $result = Evaluate @'
(() => {
 const guide=document.querySelector('.compact-guide'), body=guide.querySelector('.guide-panel-body'), footer=guide.querySelector('.guide-panel-footer');
 const controls=footer.querySelector('.guide-test-controls'), nav=footer.querySelector('.guide-navigation');
 const scenario=new URLSearchParams(location.search).get('guide-case'), saved=localStorage.getItem('boardvision.maker.v1');
 const errors=[];
 if (!body.querySelector('[data-view=instructions]') || body.querySelector('.test-actions,.test-visual-confirm')) errors.push('misplaced instructions/actions');
 if (!controls || !nav || guide.querySelector('.guide-ai-help')) errors.push('missing actions or redundant AI help');
 if (controls.clientHeight<50 || body.clientHeight<70) errors.push('unusable scroll area');
 const buttons=[...controls.querySelectorAll('button')];
 if(scenario==='disconnected' && !controls.querySelector('.guide-primary-action')?.disabled) errors.push('disconnected start enabled');
 if(scenario==='ready' && controls.querySelector('.guide-primary-action')?.disabled) errors.push('ready start disabled');
 if(scenario==='lost' && (!buttons.some(b=>/Stop this test|停止本次測試/.test(b.textContent)) || controls.querySelector('input[type=radio]'))) errors.push('lost test safeguards missing');
 let target=buttons[0];
 if(scenario==='visual') {
   const code=controls.querySelector('input[type=radio]'), colors=controls.querySelector('input[type=checkbox]');
   target=controls.querySelector('.test-visual-confirm > button');
   if(!target.disabled || controls.querySelectorAll('input[type=radio]').length!==4) errors.push('premature confirmation');
   code.click();colors.click();
 }
 window.__guideActionQa={errors,saved,scenario};
 target.scrollIntoView({block:'nearest'});target.focus();
 return {prepared:true};
})()
'@
    Browser @('snapshot','-i') | Out-Null
    $result = Evaluate @'
(() => {
 const {errors,saved,scenario}=window.__guideActionQa;
 const controls=document.querySelector('.guide-test-controls'), footer=document.querySelector('.guide-panel-footer'), nav=document.querySelector('.guide-navigation');
 const target=scenario==='visual'?controls.querySelector('.test-visual-confirm > button'):controls.querySelector('button');
 target.scrollIntoView({block:'nearest'});
 const r=target.getBoundingClientRect(),c=controls.getBoundingClientRect(),f=footer.getBoundingClientRect(),n=nav.getBoundingClientRect();
 if(r.top<c.top-1||r.bottom>c.bottom+1||r.top<0||r.bottom>innerHeight+1)errors.push('test control not reachable');
 if(n.top<f.top-1||n.bottom>f.bottom+1||n.bottom>c.top+1)errors.push('navigation clipped or overlapped');
 if(scenario==='visual' && target.disabled)errors.push('selected code/colors not accepted');
 if(saved!==localStorage.getItem('boardvision.maker.v1'))errors.push('layout changed project state');
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 errors.push(...window.__stageQa.errors);
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected business write');
 return {width:innerWidth,height:innerHeight,scenario,errors,bodyHeight:document.querySelector('.guide-panel-body').clientHeight,controlsHeight:controls.clientHeight,businessWrites:writes};
})()
'@
    if ($result.errors.Count) { throw "Guide actions failed: $($result | ConvertTo-Json -Depth 5 -Compress)" }
    Browser @('screenshot',(Join-Path $outputDir "wiring-actions-$scenario-$theme-$locale-${width}x$height.png")) | Out-Null
    Write-Host "PASS $scenario $theme $locale ${width}x$height - instructions/actions, navigation, no writes"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'wiring-actions-matrix.json') -Encoding utf8
