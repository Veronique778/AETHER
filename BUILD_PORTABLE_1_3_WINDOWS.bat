@echo off
setlocal
cd /d "%~dp0"
echo AETHER 1.3 - Windows x64 native application build (no Node.js needed)
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher not found. Install standard Python 3.13 x64 from python.org.
  exit /b 1
)
py -3.13 -c "import sys,sysconfig; assert sys.version_info[:2]==(3,13) and sys.maxsize>2**32 and not sysconfig.get_config_var('Py_GIL_DISABLED')" || exit /b 1
py -3.13 -m pip install --only-binary=:all: --no-binary=proxy-tools pyinstaller "pywebview>=5,<7" "bleak>=1.1,<3" "numpy>=1.26,<3" "scipy>=1.11,<2" "pydantic>=2.6,<3" || exit /b 1
py -3.13 -m PyInstaller --noconfirm --clean AETHER_1_3_PORTABLE.spec || exit /b 1
if not exist "dist\AETHER_1_3_PORTABLE\AETHER_1_3.exe" exit /b 2
echo Build complete. Smoke test will validate backend/UI/3D in the FROZEN exe.
"dist\AETHER_1_3_PORTABLE\AETHER_1_3.exe" --smoke-test --report "aether_1_3_portable_smoke.json" || exit /b 3
if not exist "aether_1_3_portable_smoke.json" exit /b 4
echo PASS. Open dist\AETHER_1_3_PORTABLE\AETHER_1_3.exe. Edge WebView2 is required.
endlocal
