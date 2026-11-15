@echo off
setlocal
set AETHER_FROM_BAT=1
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py "%~dp0START_AETHER.py"
goto done
:use_python
python "%~dp0START_AETHER.py"
:done
echo.
echo AETHER has stopped. Any error is shown above.
pause
