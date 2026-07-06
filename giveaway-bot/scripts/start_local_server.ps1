# Локальный сервер для OBS (Windows PowerShell).
# Запуск: powershell -ExecutionPolicy Bypass -File .\scripts\start_local_server.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

Write-Host "==============================================="
Write-Host " Local server started for OBS Hybrid Roulette"
Write-Host " Folder: $ProjectRoot"
Write-Host " URL for wheel: http://localhost:58971/wheel.html"
Write-Host " URL for panel: http://localhost:58971/panel.html"
Write-Host " Stop server: Ctrl+C"
Write-Host "==============================================="
Write-Host ""

if (Get-Command python -ErrorAction SilentlyContinue) {
    python server.py
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 server.py
} else {
    Write-Host "[ERROR] Python not found. Install from https://www.python.org/"
    Write-Host "        During setup, enable 'Add python.exe to PATH'."
    exit 1
}
