# Board Vision - demo mode: build frontend, start backend, open a chromeless
# Edge app window. One-click path used for the executive demo.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Write-Host "[1/3] Building frontend..."
Push-Location "$root\frontend"
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }
Pop-Location

Write-Host "[2/3] Starting backend on http://127.0.0.1:8100 ..."
Start-Process -WorkingDirectory "$root\backend" powershell -ArgumentList @(
    "-Command", "uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --timeout-graceful-shutdown 3"
)

Write-Host "[3/3] Waiting for backend, then opening app window..."
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-RestMethod "http://127.0.0.1:8100/api/config" -TimeoutSec 2 | Out-Null
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
Start-Process msedge "--app=http://127.0.0.1:8100"
