# Production bundle + isolated fixture APIs only. Never invoke a hardware action.
$ErrorActionPreference = 'Stop'
$outputDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    # The CLI mouse command accepts integer viewport coordinates.
    if ($BrowserArgs[0] -eq 'mouse' -and $BrowserArgs[1] -eq 'move') {
        $BrowserArgs[2] = [string][Math]::Round([double]$BrowserArgs[2])
        $BrowserArgs[3] = [string][Math]::Round([double]$BrowserArgs[3])
    }
    $result = & npx --yes agent-browser --session guide-height @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session guide-height eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
function ReadLayout {
    Evaluate @'
(() => {
 const root=document.querySelector('.assistant-wiring-stage'),camera=root.querySelector('.video-workspace'),guide=root.querySelector('.wiring-workspace'),handle=root.querySelector('.guide-resize-handle');
 const c=camera.getBoundingClientRect(),g=guide.getBoundingClientRect(),r=root.getBoundingClientRect(),h=handle?.getBoundingClientRect();
 return {camera:c.height,guide:g.height,total:r.height,x:h?(h.left+h.right)/2:0,y:h?(h.top+h.bottom)/2:0,
   min:Number(handle?.getAttribute('aria-valuemin')),max:Number(handle?.getAttribute('aria-valuemax')),now:Number(handle?.getAttribute('aria-valuenow')),
   preference:localStorage.getItem('boardvision.guide-height.v1'),enabled:!!handle};
})()
'@
}
function Drag([double]$Delta) {
    $m=ReadLayout
    Browser @('mouse','move',"$($m.x)","$($m.y)") | Out-Null
    Browser @('mouse','down','left') | Out-Null
    Browser @('mouse','move',"$($m.x)","$($m.y+$Delta)") | Out-Null
    Browser @('mouse','up','left') | Out-Null
    Browser @('snapshot','-i') | Out-Null
}
Browser @('set','viewport','1651','871') | Out-Null
Browser @('open','http://127.0.0.1:18780/?lang=zh-TW&guide-case=ready') | Out-Null
Browser @('snapshot','-i') | Out-Null
Evaluate "localStorage.removeItem('boardvision.guide-height.v1');true" | Out-Null
Browser @('open','http://127.0.0.1:18780/?lang=zh-TW&guide-case=ready') | Out-Null
Browser @('snapshot','-i') | Out-Null
Evaluate @'
window.__heightQa={camera:document.querySelector('.video-workspace'),image:document.querySelector('.video-shell'),guide:document.querySelector('.wiring-workspace'),project:localStorage.getItem('boardvision.maker.v1')};true
'@ | Out-Null
$before=ReadLayout
Drag 60
$after=ReadLayout
if ([Math]::Abs($after.camera-$before.camera-60) -gt 1 -or [Math]::Abs($after.guide-$before.guide+60) -gt 1) { throw 'Pointer drag did not resize both panes' }
Evaluate @'
(() => {
 const q=window.__heightQa;
 if(q.camera!==document.querySelector('.video-workspace')||q.image!==document.querySelector('.video-shell')||q.guide!==document.querySelector('.wiring-workspace'))throw Error('camera/guide remounted');
 if(q.project!==localStorage.getItem('boardvision.maker.v1'))throw Error('layout changed project');
 return true;
})()
'@ | Out-Null
Browser @('screenshot',(Join-Path $outputDir 'guide-height-dragged-1651x871.png')) | Out-Null
Browser @('press','Home') | Out-Null
$min=ReadLayout
if ($min.now -ne $min.min) { throw 'Home did not reach minimum camera height' }
Browser @('press','End') | Out-Null
$max=ReadLayout
if ($max.now -ne $max.max -or $max.guide -lt 239) { throw 'End did not retain usable guide height' }
Browser @('press','ArrowUp') | Out-Null
$key=ReadLayout
if ([Math]::Abs($max.camera-$key.camera-24) -gt 1) { throw 'ArrowUp did not adjust height' }
# Cancel an actual captured drag: neither layout nor preference may be committed.
Browser @('mouse','move',"$($key.x)","$($key.y)") | Out-Null
Browser @('mouse','down','left') | Out-Null
Browser @('mouse','move',"$($key.x)","$($key.y-55)") | Out-Null
Browser @('press','Escape') | Out-Null
Browser @('mouse','up','left') | Out-Null
$cancel=ReadLayout
if ([Math]::Abs($cancel.camera-$key.camera) -gt 1 -or $cancel.preference -ne $key.preference) { throw 'Cancelled drag changed saved layout' }
Browser @('open','http://127.0.0.1:18780/?lang=zh-TW&guide-case=ready') | Out-Null
Browser @('snapshot','-i') | Out-Null
$restored=ReadLayout
if ([Math]::Abs($restored.camera-$key.camera) -gt 1 -or $restored.preference -ne $key.preference) { throw 'Refresh lost the height preference' }
Browser @('dblclick','.guide-resize-handle') | Out-Null
Browser @('snapshot','-i') | Out-Null
$reset=ReadLayout
if ($reset.preference -or [Math]::Abs($reset.camera-$before.camera) -gt 1) { throw 'Double-click did not reset the split' }
# Wire browsing and 2D view keep the same camera and divider.
Evaluate "document.querySelector('.guide-navigation > button:first-child').click();true" | Out-Null
Browser @('snapshot','-i') | Out-Null
Browser @('click','.wiring-view-toggle') | Out-Null
Browser @('snapshot','-i') | Out-Null
$active=ReadLayout
if (!$active.enabled -or [Math]::Abs($active.camera-$reset.camera) -gt 1) { throw 'Active wire/2D changed the split' }
Browser @('screenshot',(Join-Path $outputDir 'guide-height-active-2d-1651x871.png')) | Out-Null
Browser @('click','.guide-visibility-toggle') | Out-Null
Browser @('snapshot','-i') | Out-Null
if ((ReadLayout).enabled) { throw 'Collapsed guide retained a divider' }
Browser @('click','.guide-visibility-toggle') | Out-Null
Browser @('snapshot','-i') | Out-Null
if (!(ReadLayout).enabled) { throw 'Reopened guide lost resizing' }
Write-Host 'PASS native drag, bounds, keyboard, Escape, refresh, reset, wire/2D and guide visibility'
$metrics=foreach ($sample in @(@(1651,871,'dark','zh-TW','ready'),@(1440,871,'light','en','visual'),@(1352,520,'dark','en','ready'),@(390,871,'light','en','ready'))) {
    $w,$h,$theme,$locale,$scenario=$sample
    Browser @('set','viewport',"$w","$h") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=$scenario") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $result=Evaluate @'
(() => {
 const root=document.querySelector('.assistant-wiring-stage'),handle=root.querySelector('.guide-resize-handle'),guide=root.querySelector('.wiring-workspace'),errors=[];
 const camera=root.querySelector('.video-workspace'),c=camera.getBoundingClientRect(),g=guide.getBoundingClientRect(),r=root.getBoundingClientRect();
 const enabled=!!handle;
 if(innerWidth>=1100&&innerHeight>=520&&!enabled)errors.push('desktop divider missing');
 if(innerWidth<=700&&enabled)errors.push('phone divider should be hidden');
 if(enabled){
   if(handle.getAttribute('aria-orientation')!=='horizontal')errors.push('incorrect separator orientation');
   if(Math.abs(c.height+g.height+18-r.height)>1||g.top<c.bottom||g.bottom>r.bottom+1)errors.push('split geometry/overflow');
   for(const b of guide.querySelectorAll('.guide-navigation button')){const p=b.getBoundingClientRect();if(p.top<g.top||p.bottom>g.bottom)errors.push('navigation clipped');}
 }
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 if(!document.querySelector('.guide-navigation'))errors.push('guide controls missing');
 errors.push(...window.__stageQa.errors);
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected business write');
 return {width:innerWidth,height:innerHeight,theme:document.documentElement.dataset.theme,enabled,camera:c.height,guide:g.height,errors,writes};
})()
'@
    if ($result.errors.Count) { throw "Layout failed: $($result | ConvertTo-Json -Depth 6 -Compress)" }
    Browser @('screenshot',(Join-Path $outputDir "guide-height-$theme-${w}x$h.png")) | Out-Null
    Write-Host "PASS $theme ${w}x$h"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'guide-height-matrix.json') -Encoding utf8
