param([switch]$Detect, [string]$Out)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskRepo = Split-Path (Split-Path $taskRoot -Parent) -Parent
$taskAttachments = 'C:\Users\james\.codex\codex-remote-attachments\01a0f603-c738-7ac3-80d0-ef2d01b31c21\CCE9760F-3F2D-43B7-80DC-149FA0D4EFB7'
$taskRuntime = 'C:\Users\james\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskBackendRuntime = Join-Path $taskRepo 'backend\.venv\Scripts\python.exe'
if ($Detect) { $taskRuntime = $taskBackendRuntime }
if (-not (Test-Path -LiteralPath $taskRuntime)) { throw "找不到 Python：$taskRuntime" }
$taskPhoto = Join-Path $taskAttachments '2-照片-2.jpg'
$taskSecond = Join-Path $taskAttachments '1-照片-1.jpg'
if (-not (Test-Path -LiteralPath $taskPhoto) -or -not (Test-Path -LiteralPath $taskSecond)) {
    throw '本次附件不存在，請用 poc.py --image 指定自己的照片。'
}
if (-not $Out) { $Out = Join-Path $taskRepo ('runs\gpio-photo-poc\' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$taskArgs = @('-X', 'utf8', (Join-Path $taskRoot 'poc.py'), '--image', $taskPhoto, '--image', $taskSecond,
              '--markers', (Join-Path $taskRoot 'assistant-prelabels.json'), '--out', $Out)
if ($Detect) { $taskArgs += '--detect' }
& $taskRuntime @taskArgs
if ($LASTEXITCODE -ne 0) { throw "POC 執行失敗：$LASTEXITCODE" }
