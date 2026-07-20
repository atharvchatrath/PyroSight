# PyroSight one-time setup — Windows (PowerShell)
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "== PyroSight setup (Windows) ==" -ForegroundColor Cyan

# --- Python backend ---
if (-not (Test-Path ".venv")) {
    Write-Host "[1/3] Creating Python virtual environment..."
    python -m venv .venv
}
Write-Host "[2/3] Installing backend dependencies..."
& .venv\Scripts\python.exe -m pip install --upgrade pip -q
& .venv\Scripts\python.exe -m pip install -r backend\requirements.txt -q

# --- Frontend ---
Write-Host "[3/3] Installing frontend dependencies (npm)..."
Push-Location frontend
npm install --no-audit --no-fund
Pop-Location

Write-Host ""
Write-Host "Setup complete. Start the platform with:" -ForegroundColor Green
Write-Host "    scripts\run-backend.ps1     (terminal 1)"
Write-Host "    scripts\run-frontend.ps1    (terminal 2)"
Write-Host "then open http://localhost:3100"
