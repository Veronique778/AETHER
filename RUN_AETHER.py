"""AETHER: select this file in PyCharm and click the green Run button.
First run: Node.js 20+ and internet are needed to compile the original React design.
Afterwards: Python alone runs the already built frontend + backend.
"""
from __future__ import annotations
import importlib.util, os, shutil, subprocess, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'web' / 'backend'
FRONTEND = ROOT / 'web' / 'frontend'
# v0.8: the prebuilt offline bundle (dist-offline) is preferred; `npm run build` output (dist) otherwise.
DIST = FRONTEND / 'dist-offline' if (FRONTEND / 'dist-offline' / 'index.html').exists() else FRONTEND / 'dist'
PUBLIC = FRONTEND / 'public'

def prepare():
    # Hybrid source contains additional RAR 3D features that are not present in the
    # precompiled fallback dist-offline/index.html. Rebuild on first launch when possible.
    stamp = ROOT / '.aether-hybrid-built'
    if not stamp.exists():
        npm = shutil.which('npm.cmd') or shutil.which('npm')
        if npm:
            try:
                if not (FRONTEND / 'node_modules' / 'esbuild').exists():
                    print('[AETHER] Installing React dependencies for HYBRID build...', flush=True)
                    subprocess.run([npm, 'ci'], cwd=FRONTEND, check=True)
                print('[AETHER] Building current HYBRID React UI and RAR 3D models...', flush=True)
                subprocess.run([npm, 'run', 'build:offline', '--', '--mode', 'live', '--api', '', '--out', 'dist-offline'], cwd=FRONTEND, check=True)
                stamp.write_text('AETHER 1.0 FINAL HYBRID\n', encoding='utf-8')
            except (subprocess.CalledProcessError, OSError) as exc:
                print(f'[AETHER] WARNING: current UI build failed ({exc}). Prebuilt 1.0 frontend will be used as fallback.', flush=True)
        else:
            print('[AETHER] WARNING: Node/npm unavailable; prebuilt 1.0 frontend will be used as fallback. RAR ship UI requires a rebuild.', flush=True)
    if importlib.util.find_spec('fastapi') is None or importlib.util.find_spec('uvicorn') is None:
        print('[AETHER] Installing Python dependencies (first run)…', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(BACKEND/'requirements.txt')], check=True)
    if not (DIST / 'index.html').exists():
        npm = shutil.which('npm.cmd') or shutil.which('npm')
        if not npm:
            raise RuntimeError('Node.js 20+ is needed ONCE to build the original design. Install it from https://nodejs.org and click Run again.')
        if not (FRONTEND/'node_modules'/'vite').exists():
            print('[AETHER] Installing React design dependencies (first run)…', flush=True)
            subprocess.run([npm, 'ci'], cwd=FRONTEND, check=True)
        print('[AETHER] Building original React + 3D design (first run)…', flush=True)
        subprocess.run([npm, 'run', 'build'], cwd=FRONTEND, check=True)

def main():
    prepare()
    sys.path.insert(0, str(BACKEND))
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from app.main import app
    # Keep API endpoints untouched; mount the precompiled design at root.
    if (DIST / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=str(DIST/'assets')), name='aether-assets')
    @app.get('/')
    def index(): return FileResponse(str(DIST/'index.html'))
    @app.get('/{path:path}')
    def spa_fallback(path: str):
        if path.startswith('api/') or path.startswith('docs') or path.startswith('openapi'):
            from fastapi import HTTPException
            raise HTTPException(404)
        for base in (DIST, PUBLIC):  # GLB models live once in web/frontend/public
            candidate = (base/path).resolve()
            if candidate.is_relative_to(base.resolve()) and candidate.is_file(): return FileResponse(str(candidate))
        return FileResponse(str(DIST/'index.html'))
    # Frontend and API use the same localhost origin/port.
    os.environ.setdefault('AETHER_DB_PATH', str(ROOT/'runtime'/'aether.sqlite3'))
    def open_browser():
        for _ in range(80):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1) as r:
                    if r.status == 200:
                        webbrowser.open('http://127.0.0.1:8000/?mode=live')
                        print('[AETHER] Interface: http://127.0.0.1:8000/?mode=live', flush=True)
                        return
            except Exception: time.sleep(.25)
    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn
    print('[AETHER] Starting original interface + Python modules on one port…', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='info')

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('\n[AETHER] START ERROR:', exc, '\nSee README_PYCHARM_UA.md', flush=True)
        raise
