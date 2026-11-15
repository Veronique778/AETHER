@echo off
setlocal
cd /d "%~dp0"
title AETHER 1.1 - Desktop Application
set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -c "import sys,sysconfig; assert not sysconfig.get_config_var('Py_GIL_DISABLED')" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3.13"
)
if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
 echo [AETHER] Python was not found. A standalone installer requires a Windows build.
 echo [AETHER] No Node.js is required for this application.
 pause
 exit /b 1
)
echo [AETHER] Starting desktop application. No Node.js or external browser.
%PY_CMD% desktop_launch.py %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
 echo.
 echo [AETHER] Application exited with error %CODE%.
 echo [AETHER] Read %%APPDATA%%\space.aether.desktop\logs\launcher_error.log
 pause
)
exit /b %CODE%
