# Isolated production-bundle preview only; never invoke a hardware action.
$ErrorActionPreference = 'Stop'
$outputDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path 'docs/qa/unified-assistant'
function Browser([string[]]$BrowserArgs) {
    $result = & npx --yes agent-browser --session slim-header @BrowserArgs
    if ($LASTEXITCODE -ne 0) { throw "Browser failed: $BrowserArgs" }
    return $result
}
function Evaluate([string]$Script) {
    $result = $Script | & npx --yes agent-browser --session slim-header eval --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Browser evaluation failed' }
    return ($result -join "`n") | ConvertFrom-Json
}
$samples = @(
    @(1651,871,'dark','zh-TW'), @(1440,871,'light','en'), @(1352,871,'dark','en'),
    @(1210,871,'light','en'), @(1100,871,'dark','zh-TW'), @(390,871,'light','en'),
    @(1352,520,'dark','zh-TW')
)
$metrics = foreach ($sample in $samples) {
    $width,$height,$theme,$locale = $sample
    Browser @('set','viewport',"$width","$height") | Out-Null
    Browser @('open',"http://127.0.0.1:18780/?lang=$locale&theme=$theme&guide-case=ready") | Out-Null
    Browser @('snapshot','-i') | Out-Null
    $initial = Evaluate @'
(() => {
 const header=document.querySelector('.maker-header'), logo=header.querySelector('.brand-title'), subtitle=header.querySelector('.brand-subtitle');
 const h=header.getBoundingClientRect(), l=logo.getBoundingClientRect(), s=subtitle.getBoundingClientRect(), errors=[];
 if(innerWidth>=1352 && h.height>46)errors.push('desktop header too tall');
 if(s.left<l.right || Math.abs((s.top+s.bottom)/2-(l.top+l.bottom)/2)>1) errors.push('descriptor not beside logo');
 if(getComputedStyle(subtitle).display==='none'||!subtitle.textContent.includes('Vibe Maker Studio'))errors.push('descriptor missing');
 const buttons=[...header.querySelectorAll('.maker-nav button,.pi-global-connect,.pi-execution-menu > summary,.runtime-settings > summary')];
 if(header.querySelectorAll('.maker-nav button').length!==3)errors.push('missing workflow stage');
 for(const b of buttons){
   const r=b.getBoundingClientRect();
   if(r.left<h.left||r.right>h.right||r.top<h.top||r.bottom>h.bottom)errors.push('control outside header');
   if(innerWidth<=960&&r.height<44)errors.push('touch control below 44px');
 }
 for(let i=0;i<buttons.length;i++)for(let j=i+1;j<buttons.length;j++){
   const a=buttons[i].getBoundingClientRect(),b=buttons[j].getBoundingClientRect();
   if(a.right>b.left+1&&b.right>a.left+1&&a.bottom>b.top+1&&b.bottom>a.top+1)errors.push('overlapping controls');
 }
 if(document.documentElement.scrollWidth>innerWidth+1)errors.push('horizontal overflow');
 window.__headerQa={errors,saved:localStorage.getItem('boardvision.maker.v1'),headerHeight:h.height};
 header.querySelector('.runtime-settings > summary').click();
 return {headerHeight:h.height};
})()
'@
    Browser @('snapshot','-i') | Out-Null
    $result = Evaluate @'
(() => {
 const {errors,saved,headerHeight}=window.__headerQa, settings=document.querySelector('.runtime-settings');
 const p=settings.querySelector('.runtime-settings-popover').getBoundingClientRect();
 if(!settings.open||p.left<0||p.right>innerWidth||p.top<0||p.bottom>innerHeight)errors.push('settings clipped');
 if(settings.querySelectorAll('select').length!==3)errors.push('settings controls missing');
 settings.querySelector('summary').click();
 if(localStorage.getItem('boardvision.maker.v1')!==saved)errors.push('project changed');
 errors.push(...window.__stageQa.errors);
 const writes=window.__stageQa.requests.filter(r=>r.method!=='GET'&&!r.path.startsWith('/api/assistant/')&&!['/api/ai/estimate','/api/mobile/context'].includes(r.path));
 if(writes.length)errors.push('unexpected business write');
 return {width:innerWidth,height:innerHeight,query:location.search,headerHeight,errors,writes};
})()
'@
    Browser @('snapshot','-i') | Out-Null
    if ($result.errors.Count) { throw "Header failed: $($result | ConvertTo-Json -Depth 5 -Compress)" }
    Browser @('screenshot',(Join-Path $outputDir "header-slim-$theme-$locale-${width}x$height.png")) | Out-Null
    Write-Host "PASS header $theme $locale ${width}x$height : $($result.headerHeight)px"
    $result
}
$metrics | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputDir 'header-slim-matrix.json') -Encoding utf8
