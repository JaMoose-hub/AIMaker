# Board Vision - development mode: backend (hot reload) + Vite dev server.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

Start-Process -WorkingDirectory "$root\backend" powershell -ArgumentList @(
    "-NoExit", "-Command",
    "uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload --timeout-graceful-shutdown 3"
)
Start-Process -WorkingDirectory "$root\frontend" powershell -ArgumentList @(
    "-NoExit", "-Command", "npm run dev"
)
Write-Host "Backend  -> http://127.0.0.1:8100  (API/MJPEG/WS)"
Write-Host "Frontend -> Vite dev server (URL shown in its window, proxies to backend)"
