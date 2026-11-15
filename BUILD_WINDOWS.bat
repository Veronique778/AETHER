@echo off
chcp 65001 >nul
title AETHER 1.0 FINAL - Windows build
echo.
echo  AETHER 1.0 FINAL - builds dist-windows\AETHER_SETUP.exe and dist-windows\portable\AETHER.exe
echo  Needs (one-time): Node.js 20+, Python 3.11-3.13 x64, Rust (MSVC), VS 2022 Build Tools (C++).
echo  See README.md, section "Build the Windows installer".
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\scripts\build-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo  BUILD FAILED - read the message above. Most common cause: a missing prerequisite.
  pause
  exit /b 1
)
echo.
echo  Done. Installer: %~dp0dist-windows\AETHER_SETUP.exe
pause
