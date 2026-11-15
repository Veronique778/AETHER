@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo AETHER 1.5 - BUILD FROM LATEST SENSOR ECOSYSTEM SOURCE
if not exist "web\frontend\src\features\personal\PersonalTwin.tsx" (echo ERROR: latest PersonalTwin source missing & exit /b 20)
if exist "AETHER_1_5_UNIFIED_WINDOWS_x64.zip" del /q "AETHER_1_5_UNIFIED_WINDOWS_x64.zip"
call BUILD_UNIFIED_WINDOWS.bat
if errorlevel 1 (echo BUILD FAILED - DO NOT PUBLISH! & exit /b 1)
py -3.13 tools\final_release_gate.py --platform windows --archive AETHER_1_5_UNIFIED_WINDOWS_x64.zip --smoke aether_1_5_portable_smoke.json --ble aether_1_5_ble_diagnostics.json
if errorlevel 1 (echo RELEASE GATE FAILED - DO NOT PUBLISH! & exit /b 2)
echo.
echo SOFTWARE RELEASE CANDIDATE BUILT: AETHER_1_5_UNIFIED_WINDOWS_x64.zip
echo BEFORE PUBLIC RELEASE: manually launch the newly built EXE and test Live Sensors, BODY 3D, PHANTOM, Crew/Mission, RECOVERY on Windows.
echo No physical Bluetooth verified unless you test your actual device.
pause
endlocal
