# Isolated preview only. No camera, AI generation, Pi tests or deployments.
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$outputDir = Join-Path $qaRoot 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session guide-compact @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session guide-compact eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$samples = @(
    @(1413,871,'dark','zh-TW','ready'), @(1651,871,'dark','zh-TW','ready'),
    @(1352,871,'light','en','disconnected'), @(1100,871,'light','en','ready'),
    @(390,871,'light','en','ready'), @(1352,520,'dark','zh-TW','ready'),
    @(1352,520,'dark','zh-TW','lost')
)
$metrics = foreach ($sample in $samples) {
    $width,$height,$theme,$locale,$scenario = $sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=$scenario") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    # Completed overview -> last wire -> CS (step 4/7), as in the user's screenshot.
    1..4 | ForEach-Object {
        Evaluate "document.querySelector('.guide-navigation > button:first-child').click(); true" | Out-Null
        Browser @('snapshot','-i') | Out-Null
    }
    $result = Evaluate @'
(() => {
 const guide=document.querySelector('.compact-guide.active'), body=guide.querySelector('.guide-panel-body'), footer=guide.querySelector('.guide-panel-footer');
 const controls=footer.querySelector('.guide-test-controls'), card=guide.querySelector('.guide-connection-card');
 const scenario=new URLSearchParams(location.search).get('guide-case'), errors=[];
 if (!card.textContent.includes('CS') || !card.textContent.includes('Pin 24')) errors.push('wrong endpoint');
 for(const [name,el] of [['body',body],['controls',controls]]) {
   if (getComputedStyle(el).overflowY!=='visible' || el.scrollHeight>el.clientHeight+1) errors.push(name+' still scrolls');
 }
 const instructions=body.querySelector('[data-view=instructions]');
 if(scenario==='lost') {
   if(instructions.closest('[hidden]') || ![...controls.querySelectorAll('button')].some(b=>/Stop this test|停止本次測試/.test(b.textContent))) errors.push('lost test hidden');
   if(controls.querySelector('input[type=radio]'))errors.push('lost test can confirm');
 } else if(!instructions.closest('[hidden]')) errors.push('idle test information not collapsed');
 if(!body.querySelector('.guide-pin-caution') || guide.querySelector('.guide-ai-help'))errors.push('safety/help presentation');
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 const controlBox=controls.getBoundingClientRect(), footerBox=footer.getBoundingClientRect();
 if(controlBox.bottom>footerBox.bottom+1)errors.push('test controls clipped');
 if(innerWidth>=1100 && innerHeight>=800 && guide.getBoundingClientRect().bottom>innerHeight+1)errors.push('normal desktop needs outer scroll');
 window.__compactQa={errors,before:localStorage.getItem('boardvision.maker.v1')};
 return {width:innerWidth,height:innerHeight,theme:document.documentElement.dataset.theme,scenario,errors,
   guideHeight:Math.round(guide.getBoundingClientRect().height),bodyHeight:body.clientHeight,bodyScrollHeight:body.scrollHeight,controlsHeight:controls.clientHeight};
})()
'@
    if ($result.errors.Count) { throw "Compact guide failed: $($result | ConvertTo-Json -Depth 5 -Compress)" }
    Evaluate "document.querySelector('.guide-primary-action').scrollIntoView({block:'nearest'});true" | Out-Null
    Browser @('screenshot',(Join-Path $outputDir "wiring-compact-$scenario-$theme-$locale-${width}x$height.png")) | Out-Null
    Evaluate "document.querySelector('.guide-reference-toggle').scrollIntoView({block:'center'});true" | Out-Null
    Browser @('click','.guide-reference-toggle') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $expanded = Evaluate @'
(() => {
 const body=document.querySelector('.guide-panel-body'),details=body.querySelector('.compact-guide-details');
 return !details.hidden && getComputedStyle(body).overflowY==='visible' && body.scrollHeight<=body.clientHeight+1;
})()
'@
    if (!$expanded) { throw 'Expanded reference creates an inner scroll pane' }
    Browser @('press','Escape') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $checks = Evaluate @'
(() => {
 const {before,errors}=window.__compactQa;
 if(!document.querySelector('.compact-guide-details').hidden || document.activeElement!==document.querySelector('.guide-reference-toggle'))errors.push('reference close/focus failed');
 if(before!==localStorage.getItem('boardvision.maker.v1'))errors.push('reference mutated wiring');
 errors.push(...window.__stageQa.errors);
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected business write');
 return {errors,businessWrites:writes};
})()
'@
    if ($checks.errors.Count) { throw "Reference checks failed: $($checks | ConvertTo-Json -Depth 5 -Compress)" }
    Write-Host "PASS compact $scenario $theme $locale ${width}x$height - no inner scrolling, reference/controls preserved"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'wiring-compact-matrix.json') -Encoding utf8
