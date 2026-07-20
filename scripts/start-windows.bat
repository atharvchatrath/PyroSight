@echo off
rem PyroSight — one-click Windows demo launcher.
rem Opens backend + frontend in separate windows, then the browser.
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo First run: executing setup...
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
)

start "PyroSight Backend" powershell -ExecutionPolicy Bypass -NoExit -File scripts\run-backend.ps1
start "PyroSight Frontend" powershell -ExecutionPolicy Bypass -NoExit -File scripts\run-frontend.ps1

echo Waiting for services to come up...
timeout /t 8 /nobreak > nul
start http://localhost:3100
