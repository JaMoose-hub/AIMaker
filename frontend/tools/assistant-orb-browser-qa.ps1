# Isolated QA only: never submit a message, capture a photo or operate Pi.
$ErrorActionPreference='Stop'
$qaOutput=Join-Path (Resolve-Path "$PSScriptRoot/../..").Path 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result=& npx --yes agent-browser --session ai-orb @BrowserArgs
    if($LASTEXITCODE -ne 0){throw "Browser failed: $BrowserArgs"}
    return $result
}
function Evaluate([string]$Script) {
    $result=$Script | & npx --yes agent-browser --session ai-orb eval --stdin
    if($LASTEXITCODE -ne 0){throw 'Evaluation failed'}
    return ($result -join "`n") | ConvertFrom-Json
}
$metrics=foreach($sample in @(@(1413,871,'dark','zh-TW'),@(1413,871,'light','en'),@(1100,871,'dark','en'),@(390,871,'light','en'),@(1352,520,'dark','zh-TW'))) {
    $width,$height,$theme,$locale=$sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=ready") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    if($width -lt 1100){Browser @('click','.assistant-mobile-tabs button:last-child') | Out-Null}
    if($width -eq 1100){Evaluate "document.querySelector('.assistant-resizer').focus();true" | Out-Null; Browser @('press','Home') | Out-Null}
    Browser @('fill','#unified-prompt','QA draft - do not send') | Out-Null
    Evaluate @'
(() => {
 const work=JSON.parse(localStorage.getItem('boardvision.maker.v1'));
 window.__orbQa={video:document.querySelector('.video-shell'),chat:document.querySelector('.assistant-chat-content'),input:document.querySelector('#unified-prompt'),project:JSON.stringify([work.design,work.code,work.guide])};
 document.querySelector('.assistant-collapse').focus();return true;
})()
'@ | Out-Null
    if($width -ge 1100){
        Browser @('press','Enter') | Out-Null
        Browser @('snapshot','-i') | Out-Null
        $closed=Evaluate "document.querySelector('.assistant-collapse').getAttribute('aria-expanded')==='false' && getComputedStyle(document.querySelector('.assistant-chat-content')).display==='none'"
        if(!$closed){throw 'Keyboard collapse failed'}
        Browser @('screenshot',(Join-Path $qaOutput "ai-orb-collapsed-$theme-${width}x$height.png")) | Out-Null
        Browser @('press','Enter') | Out-Null
    } else {
        Browser @('click','.assistant-mobile-tabs button:first-child') | Out-Null
        Browser @('click','.assistant-mobile-tabs button:last-child') | Out-Null
    }
    Browser @('snapshot','-i') | Out-Null
    $result=Evaluate @'
(() => {
 const errors=[...window.__stageQa.errors], q=window.__orbQa, work=JSON.parse(localStorage.getItem('boardvision.maker.v1'));
 if(q.video!==document.querySelector('.video-shell')||q.chat!==document.querySelector('.assistant-chat-content')||q.input!==document.querySelector('#unified-prompt')) errors.push('pane remounted');
 if(q.input.value!=='QA draft - do not send'||q.project!==JSON.stringify([work.design,work.code,work.guide]))errors.push('draft/project changed');
 const send=document.querySelector('.assistant-send'),model=document.querySelector('.assistant-input-actions summary'),orb=document.querySelector('.assistant-collapse');
 if(send.disabled)errors.push('valid draft disabled');
 if(innerWidth>=1100 && getComputedStyle(orb).borderRadius!=='50%')errors.push('orb theme override');
 if(innerWidth<1100 && getComputedStyle(orb).display!=='none')errors.push('desktop orb leaked into mobile');
 send.scrollIntoView({block:'nearest'});
 for(const el of [send,model,...(innerWidth>=1100?[orb]:[])]){
   const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
   if((innerHeight>=800 || el!==orb) && (!hit||!el.contains(hit)))errors.push('control obstructed: '+el.className);
   if(innerWidth<1100&&(r.width<44||r.height<44))errors.push('small mobile target');
 }
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected hardware write');
 return {width:innerWidth,height:innerHeight,errors,sendSize:send.getBoundingClientRect().width,modelSize:model.getBoundingClientRect().width};
})()
'@
    if($result.errors.Count){throw ($result | ConvertTo-Json -Compress)}
    Browser @('screenshot',(Join-Path $qaOutput "ai-orb-open-$theme-${width}x$height.png")) | Out-Null
    Browser @('click','.assistant-input-actions summary') | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $popover=Evaluate "(() => {const menu=document.querySelector('.assistant-input-actions .maker-model-menu'),r=menu.querySelector('.maker-model-popover').getBoundingClientRect();return menu.open && r.top>=0 && r.left>=0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1;})()"
    if(!$popover){throw 'Model popover clipped'}
    Browser @('press','Escape') | Out-Null
    $focus=Evaluate "!document.querySelector('.assistant-input-actions .maker-model-menu').open && document.activeElement===document.querySelector('.assistant-input-actions summary')"
    if(!$focus){throw 'Model keyboard focus not restored'}
    Browser @('click','#unified-prompt') | Out-Null
    Browser @('press','Control+a') | Out-Null
    Browser @('press','Backspace') | Out-Null
    if(!(Evaluate "document.querySelector('.assistant-send').disabled")){throw 'Empty send enabled'}
    Write-Host "PASS orb/composer $theme $locale ${width}x$height"
    $result
}
$metrics | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $qaOutput 'ai-orb-matrix.json') -Encoding utf8
Browser @('set','media','dark','reduced-motion') | Out-Null
$reduced=Evaluate "getComputedStyle(document.querySelector('.assistant-orb-energy')).animationName==='none' && getComputedStyle(document.querySelector('.assistant-workspace')).transitionDuration==='0s'"
if(!$reduced){throw 'Reduced-motion override failed'}
Write-Host 'PASS reduced motion'
