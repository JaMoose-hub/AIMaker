# Run against the isolated assistant fixture on 18780/18781 only. No hardware or AI submissions.
$ErrorActionPreference = 'Stop'
$qaRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$outputDir = Join-Path $qaRoot 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session guide-layout @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session guide-layout eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$samples = @(
    @(1651,871,'dark','en'), @(1413,871,'dark','zh-TW'),
    @(1352,871,'light','en'), @(1100,871,'light','en'),
    @(390,871,'dark','zh-TW'), @(390,871,'light','en'),
    @(1352,520,'light','en')
)
$metrics = foreach ($sample in $samples) {
    $width,$height,$theme,$locale = $sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    Evaluate "document.querySelectorAll('.maker-nav button')[1].click(); true" | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $result = Evaluate @'
(() => {
 const rect = s => document.querySelector(s).getBoundingClientRect();
 const camera = rect('.video-workspace'), image = rect('.video-shell'), guide = rect('.wiring-workspace'), footer = rect('.guide-panel-footer');
 const primary = rect('.guide-navigation button:last-child');
 return {width:innerWidth,height:innerHeight,theme:document.documentElement.dataset.theme,
   overflow:document.documentElement.scrollWidth-innerWidth,errors:window.__stageQa.errors,
   stacked:guide.top >= Math.max(camera.bottom,image.bottom) && Math.abs(guide.left-camera.left)<2 && Math.abs(guide.width-camera.width)<2,
   actionsInside:primary.left >= guide.left && primary.right <= guide.right && primary.top >= footer.top && primary.bottom <= footer.bottom,
   toolbar:document.querySelector('.assistant-demo-entry').closest('.video-control-toolbar') !== null,
   // Mobile context sync is separate work in this checkout, blocked by this fixture.
   businessWrites:window.__stageQa.requests.filter(r=>r.method==='POST'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path))};
})()
'@
    if (!$result.stacked -or !$result.actionsInside -or !$result.toolbar -or $result.overflow -gt 1 -or $result.errors.Count -or $result.businessWrites.Count) {
        throw "Wiring layout regression: $($result | ConvertTo-Json -Depth 4 -Compress)"
    }
    if ($width -eq 1413) {
    Evaluate @'
window.__layoutBefore = {camera:document.querySelector('.video-workspace'),state:localStorage.getItem('boardvision.maker.v1')};
document.querySelector('.guide-visibility-toggle').click(); true
'@ | Out-Null
    Browser @('snapshot','-i') | Out-Null
    Evaluate "document.querySelector('.guide-visibility-toggle').click(); true" | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $preserved = Evaluate "window.__layoutBefore.camera===document.querySelector('.video-workspace') && window.__layoutBefore.state===localStorage.getItem('boardvision.maker.v1')"
    if (!$preserved) { throw 'Guide collapse reset the camera/project state' }
    }
    Evaluate "document.querySelector('.guide-panel-footer button').scrollIntoView({block:'nearest'});document.querySelector('.guide-panel-footer button').focus();true" | Out-Null
    $focus = Evaluate "getComputedStyle(document.activeElement).outlineWidth !== '0px'"
    if (!$focus) { throw 'Wiring action keyboard focus is invisible' }
    Browser @('screenshot',(Join-Path $outputDir "wiring-layout-$theme-$locale-${width}x$height.png")) | Out-Null
    Write-Host "PASS $theme $locale ${width}x$height - stacked guide, toolbar, actions, focus, state"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'wiring-layout-matrix.json') -Encoding utf8
