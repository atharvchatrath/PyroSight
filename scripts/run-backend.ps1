# PyroSight backend — Windows launcher.
#   scripts\run-backend.ps1              -> simulation mode (no hardware)
#   scripts\run-backend.ps1 -Webcam      -> live mode with your webcam + AI detector
param(
    [switch]$Webcam
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) "backend")

if ($Webcam) {
    $env:PYROSIGHT_MODE = "live"
    $env:PYROSIGHT_RGB_SOURCE = "webcam"
    Write-Host "Starting PyroSight backend in LIVE mode (webcam + neural detector)..."
} else {
    Write-Host "Starting PyroSight backend in SIM mode (synthetic building, no hardware)..."
}
& ..\.venv\Scripts\python.exe run.py
