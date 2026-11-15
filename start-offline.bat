@echo off
rem API + prebuilt UI on one port. Needs only Python 3.11+ and pydantic. Open http://127.0.0.1:8000
cd /d "%~dp0web\backend"
python -m app.devserver --port 8000 --static ..\frontend\dist-offline
pause
