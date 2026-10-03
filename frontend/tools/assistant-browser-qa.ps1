# Isolated fixture only. Start tests.assistant_preview on 18781 and maker-stage-preview --assistant on 18780.
# Does not contact 8100, SSH, a camera, or a real model. Screenshots/metrics are generated test artifacts.
param([switch]$Quick)
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$qaOutput = Join-Path $qaRoot 'docs/qa/unified-assistant'
New-Item -ItemType Directory -Force -Path $qaOutput | Out-Null
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session tinkro-unified @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session tinkro-unified eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$metrics = [System.Collections.Generic.List[object]]::new()
if (!$Quick) {
foreach ($theme in @('dark','light')) {
    foreach ($locale in @('en','zh-TW')) {
        foreach ($width in @(1651,1440,1352,390)) {
            Browser @('set','viewport',"$width",'871') | Out-Null
            Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme") | Out-Null
            Browser @('snapshot','-i') | Out-Null
            foreach ($stage in 0..2) {
                Evaluate "document.querySelectorAll('.maker-nav button')[$stage].click(); true" | Out-Null
                Browser @('snapshot','-i') | Out-Null
                $sample = Evaluate @'
(() => {
  const visible = el => !!el && el.getClientRects().length > 0;
  const state = JSON.parse(localStorage.getItem('boardvision.maker.v1'));
  return {width:innerWidth,height:innerHeight,theme:document.documentElement.dataset.theme,
    stage:state.stage,conversation:localStorage.getItem('boardvision.assistant.v1'),
    overflow:document.documentElement.scrollWidth-innerWidth,errors:window.__stageQa.errors,
    composers:document.querySelectorAll('#unified-prompt').length,
    deploy:visible(document.querySelector('.pi-deploy-panel')),
    cameraNodes:document.querySelectorAll('.video-workspace').length,
    businessWrites:window.__stageQa.requests.filter(r=>r.method==='POST'&&!r.path.startsWith('/api/assistant/')&&r.path!=='/api/ai/estimate')};
})()
'@
                $sample | Add-Member -NotePropertyName locale -NotePropertyValue $locale
                $metrics.Add($sample)
                if ($sample.overflow -gt 1 -or $sample.errors.Count -or $sample.composers -ne 1 -or $sample.businessWrites.Count) {
                    throw "Layout/state failure: $($sample | ConvertTo-Json -Depth 5 -Compress)"
                }
                if (($width -eq 1651 -and $locale -eq 'en') -or ($width -eq 390 -and $locale -eq 'zh-TW')) {
                    Browser @('screenshot',(Join-Path $qaOutput "$($sample.stage)-$theme-$locale-$width.png")) | Out-Null
                }
            }
            if ($width -eq 390) {
                Evaluate "window.__qaCamera=document.querySelector('.video-workspace');document.querySelectorAll('.assistant-mobile-tabs button')[1].click(); true" | Out-Null
                Browser @('snapshot','-i') | Out-Null
                $mobile = Evaluate "({sameCamera:window.__qaCamera===document.querySelector('.video-workspace'),inputVisible:document.querySelector('#unified-prompt').getClientRects().length>0,overflow:document.documentElement.scrollWidth-innerWidth})"
                if (!$mobile.sameCamera -or !$mobile.inputVisible -or $mobile.overflow -gt 1) { throw 'Mobile tab failure' }
                Browser @('screenshot',(Join-Path $qaOutput "ai-$theme-$locale-390.png")) | Out-Null
            }
            Write-Output "PASS $theme $locale ${width}x871 - stages 01/02/03"
        }
    }
}
}
Browser @('set','viewport','1651','871') | Out-Null
Browser @('open','http://127.0.0.1:18780/?lang=en&theme=dark') | Out-Null
Browser @('snapshot','-i') | Out-Null
Evaluate "document.querySelector('.assistant-resizer').focus(); true" | Out-Null
Browser @('press','End') | Out-Null
$size = Evaluate "({width:localStorage.getItem('boardvision.assistant-width.v1'),outline:getComputedStyle(document.activeElement).outlineWidth})"
if ($size.width -ne '520' -or $size.outline -eq '0px') { throw 'Keyboard resizing/focus failed' }
Browser @('press','Home') | Out-Null
if ((Evaluate "localStorage.getItem('boardvision.assistant-width.v1')") -ne '320') { throw 'Width minimum failed' }
Browser @('press','Enter') | Out-Null
Evaluate "window.__qaCamera=document.querySelector('.video-workspace');window.__qaInput=document.querySelector('#unified-prompt');document.querySelector('.assistant-collapse').click(); true" | Out-Null
Browser @('snapshot','-i') | Out-Null
Evaluate "document.querySelector('.assistant-collapse').click(); true" | Out-Null
if (!(Evaluate "window.__qaCamera===document.querySelector('.video-workspace')&&window.__qaInput===document.querySelector('#unified-prompt')")) { throw 'Collapse remounted a component' }
Browser @('set','viewport','1352','520') | Out-Null
foreach ($stage in 0..2) {
    Browser @('snapshot','-i') | Out-Null
    Evaluate "document.querySelectorAll('.maker-nav button')[$stage].click(); true" | Out-Null
    Browser @('screenshot',(Join-Path $qaOutput "stage$stage-dark-en-1352x520.png")) | Out-Null
    if ((Evaluate 'document.documentElement.scrollWidth-innerWidth') -gt 1) { throw 'Low-height overflow' }
}
if ($metrics.Count) { $metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $qaOutput 'layout-matrix.json') -Encoding utf8 }
Write-Output "Saved $($metrics.Count) layout checks. No AI or hardware operations submitted."
