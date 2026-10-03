# Isolated preview only. No messages, captures, model calls or Pi actions.
param([int]$OnlyWidth=0)
$ErrorActionPreference='Stop'
$qaOutput=Join-Path (Resolve-Path "$PSScriptRoot/../..").Path 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result=& npx --yes agent-browser --session ai-tools @BrowserArgs
    if($LASTEXITCODE -ne 0){throw "Browser failed: $BrowserArgs"}
    return $result
}
function Evaluate([string]$Script) {
    $result=$Script | & npx --yes agent-browser --session ai-tools eval --stdin
    if($LASTEXITCODE -ne 0){throw 'Evaluation failed'}
    return ($result -join "`n") | ConvertFrom-Json
}
$samples=@(@(1413,871,'dark','zh-TW'),@(1413,871,'light','en'),@(1100,871,'dark','en'),@(390,871,'light','en'),@(1352,520,'dark','zh-TW'))
$metrics=foreach($sample in $samples) {
    if($OnlyWidth -and $sample[0] -ne $OnlyWidth){continue}
    $width,$height,$theme,$locale=$sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=ready") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if($width -lt 1100){Browser @('click','.assistant-mobile-tabs button:last-child') | Out-Null}
    if($width -eq 1100){Evaluate "document.querySelector('.assistant-resizer').focus();true" | Out-Null; Browser @('press','Home') | Out-Null}
    Browser @('fill','#unified-prompt','QA draft - do not send') | Out-Null
    Evaluate @'
(() => {
 const s=JSON.parse(localStorage.getItem('boardvision.maker.v1'));
 window.__toolsQa={video:document.querySelector('.video-shell'),input:document.querySelector('#unified-prompt'),guideVisible:localStorage.getItem('boardvision.wiring-guide-visible.v1'),project:JSON.stringify([s.design,s.code,s.guide])};
 document.querySelector('.assistant-debug-toolbar').scrollIntoView({block:'nearest'});return true;
})()
'@ | Out-Null
    $result=Evaluate @'
(() => {
 const errors=[...window.__stageQa.errors], toolbar=document.querySelector('.assistant-debug-toolbar'), settings=document.querySelector('#assistant-debug-settings');
 if(!settings.hidden||document.querySelector('.assistant-suggestions').open)errors.push('tools not collapsed by default');
 if(document.querySelector('.unified-composer .assistant-quick'))errors.push('old question chips still visible');
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 for(const el of toolbar.querySelectorAll('button')) {
   const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
   if(!hit||!el.contains(hit))errors.push('obstructed toolbar control');
   if(innerWidth<1100&&r.height<44)errors.push('small touch target');
 }
 return {width:innerWidth,height:innerHeight,toolbarHeight:toolbar.getBoundingClientRect().height,errors};
})()
'@
    if($result.errors.Count){throw ($result | ConvertTo-Json -Compress)}
    Browser @('screenshot',(Join-Path $qaOutput "ai-tools-$theme-${width}x$height.png")) | Out-Null
    Browser @('click','.assistant-debug-tools-toggle') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    Browser @('select','#assistant-debug-settings select','thorough') | Out-Null
    Browser @('press','Escape') | Out-Null
    if(!(Evaluate "document.querySelector('#assistant-debug-settings').hidden && document.activeElement===document.querySelector('.assistant-debug-tools-toggle')")){throw 'Settings Escape/focus failed'}
    Browser @('click','.assistant-debug-tools-toggle') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if(!(Evaluate "document.querySelector('#assistant-debug-settings select').value==='thorough'")){throw 'Photo style lost'}
    Browser @('click','#assistant-debug-settings button[aria-controls=ai-debug-records]') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if(!(Evaluate "!document.querySelector('#ai-debug-records').hidden && document.activeElement===document.querySelector('#ai-debug-records-heading')")){throw 'Records unavailable'}
    Browser @('press','Escape') | Out-Null
    if(!(Evaluate "document.querySelector('#ai-debug-records').hidden && document.activeElement===document.querySelector('#assistant-debug-settings button[aria-controls=ai-debug-records]')")){throw 'Records return focus failed'}
    Browser @('click','#assistant-debug-settings button[aria-controls=debug-manual-tools]') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if(!(Evaluate "!document.querySelector('#debug-manual-tools').hidden")){throw 'Manual tools unavailable'}
    Browser @('press','Escape') | Out-Null
    if(!(Evaluate "document.querySelector('#debug-manual-tools').hidden && document.activeElement===document.querySelector('#assistant-debug-settings button[aria-controls=debug-manual-tools]')")){throw 'Manual return focus failed'}
    Browser @('click','.assistant-debug-tools-toggle') | Out-Null
    Evaluate "document.querySelector('.assistant-suggestions summary').scrollIntoView({block:'center'});true" | Out-Null
    Browser @('click','.assistant-suggestions summary') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if(!(Evaluate "(() => {const r=document.querySelector('.assistant-suggestion-list').getBoundingClientRect();return document.querySelector('.assistant-suggestions').open&&r.top>=0&&r.left>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1;})()")){throw 'Suggestions clipped'}
    Browser @('press','Escape') | Out-Null
    if(!(Evaluate "!document.querySelector('.assistant-suggestions').open && document.activeElement===document.querySelector('.assistant-suggestions summary')")){throw 'Suggestions Escape/focus failed'}
    Browser @('click','.assistant-suggestions summary') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    Browser @('click','.assistant-suggestion-list button:first-child') | Out-Null
    $after=Evaluate @'
(() => {
 const errors=[...window.__stageQa.errors],s=JSON.parse(localStorage.getItem('boardvision.maker.v1')),q=window.__toolsQa;
 if(q.video!==document.querySelector('.video-shell')||q.input!==document.querySelector('#unified-prompt'))errors.push('camera/input remounted');
 if(q.project!==JSON.stringify([s.design,s.code,s.guide]))errors.push('project changed');
 if(q.guideVisible!==localStorage.getItem('boardvision.wiring-guide-visible.v1'))errors.push('Escape changed guide visibility');
 if(!q.input.value||q.input.value==='QA draft - do not send'||document.activeElement!==q.input||document.querySelector('.assistant-suggestions').open)errors.push('suggestion did not fill/focus draft');
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected hardware action');
 return errors;
})()
'@
    if($after.Count){throw ($after -join ', ')}
    Write-Host "PASS tools $theme $locale ${width}x$height toolbar=$($result.toolbarHeight)px"
    $result
}
$matrixName=if($OnlyWidth){"ai-tools-matrix-$OnlyWidth.json"}else{'ai-tools-matrix.json'}
$metrics | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $qaOutput $matrixName) -Encoding utf8
$stats=Invoke-RestMethod 'http://127.0.0.1:18781/api/assistant-qa'
if($stats.model_calls.Count -or $stats.image_calls){throw 'Unexpected model/image call'}
Write-Host 'PASS zero model/image calls'
