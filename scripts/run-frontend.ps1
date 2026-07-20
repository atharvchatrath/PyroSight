# PyroSight frontend — Windows launcher. Opens on http://localhost:3100
$ErrorActionPreference = "Stop"
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) "frontend")
npm run dev
