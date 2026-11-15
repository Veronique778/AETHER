@echo off
setlocal
cd /d "%~dp0"
echo AETHER 1.5 Unified Windows build from latest source
call BUILD_WINDOWS_1_5.bat
if errorlevel 1 exit /b %errorlevel%
if not exist "dist\AETHER_1_5_PORTABLE\AETHER_1_5.exe" (
  echo Missing compiled EXE
  exit /b 2
)
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\AETHER_1_5_PORTABLE' -DestinationPath 'AETHER_1_5_UNIFIED_WINDOWS_x64.zip'"
if errorlevel 1 exit /b 3
powershell -NoProfile -Command "Get-FileHash -Algorithm SHA256 'AETHER_1_5_UNIFIED_WINDOWS_x64.zip'"
echo IMPORTANT: verify the new EXE manually in Live Mode and with physical BLE hardware before publishing.
endlocal
