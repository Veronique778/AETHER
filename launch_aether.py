"""One-click Windows launcher for AETHER (Python backend + original React frontend).
Requires Python 3.11+ and Node.js 20+. Installs dependencies on first run.
"""
from __future__ import annotations
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'web' / 'backend'
FRONTEND = ROOT / 'web' / 'frontend'
VENV = ROOT / '.aether-venv'
PORT = 8000


def message(msg):
    print(f'\n[AETHER] {msg}', flush=True)


def run_checked(cmd, cwd=None):
    message('Running: ' + ' '.join(map(str, cmd)))
    subprocess.run(cmd, cwd=cwd, check=True)


def available(port):
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    if not available(PORT):
        raise RuntimeError('Port 8000 is already in use. Close the previous AETHER backend first.')
    if not available(5173):
        raise RuntimeError('Port 5173 is already in use. Close the previous AETHER frontend first.')
    if not shutil.which('npm'):
        raise RuntimeError('Node.js/npm is missing. Install Node.js 20+ from https://nodejs.org/ then restart this launcher. For an instant preview use OPEN_DEMO_NO_INSTALL.bat.')

    if not VENV.exists():
        message('Creating isolated Python environment (first run only)...')
        run_checked([sys.executable, '-m', 'venv', str(VENV)])
    python = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    deps_stamp = VENV / '.aether-requirements-ready'
    if not deps_stamp.exists():
        message('Installing Python packages (first run only; internet needed)...')
        run_checked([str(python), '-m', 'pip', 'install', '-r', str(BACKEND / 'requirements.txt')])
        deps_stamp.write_text('installed\n')
    if not (FRONTEND / 'node_modules' / 'vite').exists():
        message('Installing frontend packages (first run only; internet needed)...')
        run_checked(['npm.cmd' if os.name == 'nt' else 'npm', 'ci'], cwd=FRONTEND)

    message('Starting API and graphical interface...')
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    backend = subprocess.Popen([str(python), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(PORT)], cwd=BACKEND, creationflags=creationflags)
    frontend = None
    try:
        npm = 'npm.cmd' if os.name == 'nt' else 'npm'
        frontend = subprocess.Popen([npm, 'run', 'dev'], cwd=FRONTEND, creationflags=creationflags)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if backend.poll() is not None or frontend.poll() is not None:
                raise RuntimeError('A server stopped unexpectedly. See the error messages above.')
            if healthy('http://127.0.0.1:8000/api/health') and healthy('http://127.0.0.1:5173/'):
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Timed out waiting for the servers. See the error messages above.')
        message('READY! Opening http://127.0.0.1:5173/ in your browser.')
        webbrowser.open('http://127.0.0.1:5173/')
        message('Keep this window open while using AETHER. Press Ctrl+C here to stop.')
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
        message('One of the servers has stopped. Check the messages above.')
    except KeyboardInterrupt:
        message('Stopping AETHER...')
    finally:
        for proc in (frontend, backend):
            if proc and proc.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    proc.terminate()
                    try: proc.wait(timeout=4)
                    except subprocess.TimeoutExpired: proc.kill()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        message('ERROR: ' + str(exc))
        message('If setup fails, open OPEN_DEMO_NO_INSTALL.bat for an offline preview.')
        sys.exit(1)
