@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo  AETHER 1.5 (BLE personal) - Windows x64 portable desktop build
echo  Builder: Windows 10/11 x64, standard CPython 3.13 x64 (python.org, not 3.13t),
echo  Node.js 20+ (for the React production build), internet for pip/npm.
echo  End users need NO Python/Node, only Microsoft Edge WebView2 Runtime.
echo ============================================================
where py >nul 2>nul || (echo ERROR: Python Launcher "py" not found. Install Python 3.13 x64. & exit /b 1)
py -3.13 -c "import sys,sysconfig; assert sys.version_info[:2]==(3,13) and sys.maxsize>2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')" || (echo ERROR: need standard 64-bit CPython 3.13. & exit /b 1)
where node >nul 2>nul || (echo ERROR: Node.js not found - needed to rebuild the React bundle from source. & exit /b 1)

echo [1/7] React production build from source (new content-hashed assets)
pushd web\frontend
call npm ci || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
rem Vite writes dist\ ; the release markers + BUILD_INFO.json are produced by the offline builder as a check:
node scripts\build-release.mjs --out dist || (popd & exit /b 1)
call npm test || (popd & exit /b 1)
popd

echo [2/7] Isolated build environment .build-venv-15
py -3.13 -m venv .build-venv-15 || exit /b 1
call .build-venv-15\Scripts\activate.bat || exit /b 1
echo [3/7] Build dependencies (binary wheels only)
python -m pip install --disable-pip-version-check --only-binary=:all: --no-binary=proxy-tools -r requirements-windows-build-1.5.txt || exit /b 1
python -c "import bleak, bleak.backends.winrt.scanner, winrt.windows.devices.radios; print('bleak OK')" || (echo ERROR: bleak/WinRT not importable. & exit /b 1)

echo [4/7] Backend tests (real SQLite, mock/simulated transports - not hardware)
pushd web\backend
python -m pytest -q tests -p no:cacheprovider -o faulthandler_timeout=600
set TESTRESULT=%errorlevel%
popd
if not "%TESTRESULT%"=="0" (echo ERROR: backend tests failed - not building. & exit /b 2)

echo [5/7] Freezing with PyInstaller
python -m PyInstaller --noconfirm --clean AETHER_1_5_PORTABLE.spec || exit /b 3
if not exist "dist\AETHER_1_5_PORTABLE\AETHER_1_5.exe" (echo ERROR: EXE not produced. & exit /b 3)

echo [6/7] Smoke test of the FROZEN executable (headless, temp data folder, synthetic + simulated HRS only)
"dist\AETHER_1_5_PORTABLE\AETHER_1_5.exe" --smoke-test --report "aether_1_5_portable_smoke.json"
if errorlevel 1 (echo ERROR: frozen smoke test failed - see aether_1_5_portable_smoke.json & exit /b 4)
echo [7/7] Bluetooth check in the FROZEN runtime (imports + radio + one real 6 s scan; no account data)
"dist\AETHER_1_5_PORTABLE\AETHER_1_5.exe" --ble-diagnostics --report "aether_1_5_ble_diagnostics.json"
if errorlevel 1 (echo ERROR: bleak/WinRT not importable in the frozen EXE - see aether_1_5_ble_diagnostics.json & exit /b 5)

copy /y BLE_HARDWARE_TEST_REPORT.md dist\AETHER_1_5_PORTABLE\ >nul
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\AETHER_1_5_PORTABLE\*','aether_1_5_portable_smoke.json','aether_1_5_ble_diagnostics.json' -DestinationPath 'AETHER_1_5_BLE_PERSONAL_PORTABLE.zip'" || exit /b 6
echo.
echo PASS. dist\AETHER_1_5_PORTABLE\AETHER_1_5.exe  -^>  AETHER_1_5_BLE_PERSONAL_PORTABLE.zip
echo Still manual: open the window, sign in, BIOSIGNALS with a PHYSICAL HRS strap (BLE_HARDWARE_TEST_REPORT.md).
endlocal
