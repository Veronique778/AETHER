@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\AETHER_1_1_PORTABLE\AETHER_1_1.exe" (
  echo ERROR: Portable EXE not found. Extract the COMPLETE archive.
  exit /b 2
)
echo Checking frozen backend, React UI and 3D GLB without Python or Node...
"dist\AETHER_1_1_PORTABLE\AETHER_1_1.exe" --smoke-test
set result=%errorlevel%
if not "%result%"=="0" (echo Smoke test failed; check %%LOCALAPPDATA%%\AETHER logs and Windows WebView2 installation.) else (echo Headless smoke passed. Complete the GUI and real hardware checklist manually.)
exit /b %result%
