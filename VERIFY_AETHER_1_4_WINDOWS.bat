@echo off
setlocal
cd /d "%~dp0"
set EXE=dist\AETHER_1_4_PORTABLE\AETHER_1_4.exe
if not exist "%EXE%" set EXE=AETHER_1_4.exe
if not exist "%EXE%" (
  echo ERROR: AETHER_1_4.exe not found. Extract the COMPLETE archive or run BUILD_PORTABLE_1_4_WINDOWS.bat.
  exit /b 2
)
"%EXE%" --smoke-test --report aether_1_4_smoke.json
if errorlevel 1 (echo Smoke test FAILED - see aether_1_4_smoke.json) else (echo Headless smoke PASSED. Now complete the manual GUI and BLE checklist in WINDOWS_BUILD_REPORT.md.)
endlocal
