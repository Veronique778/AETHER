@echo off
rem AETHER 1.5 portable: verify the frozen Bluetooth runtime and the radio on THIS Windows PC (no account data used).
cd /d "%~dp0"
"AETHER_1_5.exe" --ble-diagnostics --report "%USERPROFILE%\Desktop\aether_ble_diagnostics.json"
echo Report: %USERPROFILE%\Desktop\aether_ble_diagnostics.json
"AETHER_1_5.exe" --smoke-test --report "%USERPROFILE%\Desktop\aether_smoke.json"
echo Report: %USERPROFILE%\Desktop\aether_smoke.json
pause
