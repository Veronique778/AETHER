@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo  AETHER 1.4 - Windows x64 portable desktop build
echo  Builder needs: Windows 10/11 x64, standard CPython 3.13 x64
echo  (python.org, NOT the free-threaded 3.13t build), internet for pip.
echo  End users need NO Python and NO Node.js. They need the
echo  Microsoft Edge WebView2 Runtime (preinstalled on Windows 11).
echo ============================================================
where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python Launcher "py" not found. Install Python 3.13 x64 from python.org.
  exit /b 1
)
py -3.13 -c "import sys,sysconfig; assert sys.version_info[:2]==(3,13) and sys.maxsize>2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')" || (
  echo ERROR: need standard 64-bit CPython 3.13 ^(not 3.13t^).
  exit /b 1
)
if not exist "web\frontend\dist-offline\BUILD_INFO.json" (
  echo ERROR: web\frontend\dist-offline is missing or was not produced by scripts\build-offline.mjs.
  exit /b 1
)
echo [1/5] Creating isolated build environment .build-venv
py -3.13 -m venv .build-venv || exit /b 1
call .build-venv\Scripts\activate.bat || exit /b 1
echo [2/5] Installing pinned build dependencies (binary wheels only)
python -m pip install --disable-pip-version-check --only-binary=:all: --no-binary=proxy-tools -r requirements-windows-build.txt || exit /b 1
echo [3/5] Running backend tests before freezing
pushd web\backend
python -m pytest -q tests -p no:cacheprovider -o faulthandler_timeout=180
set TESTRESULT=%errorlevel%
popd
if not "%TESTRESULT%"=="0" (
  echo ERROR: backend tests failed - not building.
  exit /b 2
)
echo [4/5] Freezing with PyInstaller
python -m PyInstaller --noconfirm --clean AETHER_1_4_PORTABLE.spec || exit /b 3
if not exist "dist\AETHER_1_4_PORTABLE\AETHER_1_4.exe" (
  echo ERROR: dist\AETHER_1_4_PORTABLE\AETHER_1_4.exe was not produced.
  exit /b 3
)
echo [5/5] Post-build smoke test of the FROZEN executable (headless, temp data folder)
"dist\AETHER_1_4_PORTABLE\AETHER_1_4.exe" --smoke-test --report "aether_1_4_portable_smoke.json"
if errorlevel 1 (
  echo ERROR: frozen smoke test failed - see aether_1_4_portable_smoke.json
  exit /b 4
)
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\AETHER_1_4_PORTABLE\*','aether_1_4_portable_smoke.json','README_WINDOWS_1_4.txt' -DestinationPath 'AETHER_1_4_FINAL_WINDOWS_BINARY.zip'" || exit /b 5
echo.
echo PASS. Portable app: dist\AETHER_1_4_PORTABLE\AETHER_1_4.exe
echo       Archive:      AETHER_1_4_FINAL_WINDOWS_BINARY.zip
echo Manual checks still required: open the window, click through modules, physical BLE strap.
endlocal
