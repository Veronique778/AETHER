@echo off
rem AETHER API (FastAPI). Falls back to the stdlib server if FastAPI cannot be installed.
cd /d "%~dp0web\backend"
python -m pip install -r requirements.txt
python -c "import fastapi, uvicorn" 2>nul && (
  python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) || (
  echo FastAPI not available - starting the stdlib fallback server
  python -m app.devserver --port 8000
)
pause
