"""One-click Windows launcher for AETHER 1.0 FINAL HYBRID.

Production desktop runtime. The React frontend is PREBUILT and included in the ZIP.
No Node.js, npm, internet, or JavaScript compilation is needed to start the UI.
The native desktop window is provided by desktop_launch.py.

Run from START_AETHER.bat or QUICK_START_AETHER.bat.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / 'web' / 'frontend'
BACKEND = ROOT / 'web' / 'backend'
DIST = FRONTEND / 'dist-offline'
VENV = ROOT / '.aether-venv'
STAMP = ROOT / '.aether-quick-build.json'
REQUIREMENTS = BACKEND / 'requirements.txt'
URL_HOST = '127.0.0.1'


class SetupError(RuntimeError):
    pass


def info(msg: str) -> None:
    print(f'\n[AETHER] {msg}', flush=True)


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    info('>> ' + ' '.join(str(x) for x in cmd))
    try:
        subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)
    except subprocess.CalledProcessError as exc:
        raise SetupError(f'Command failed (exit {exc.returncode}): {" ".join(str(x) for x in cmd)}') from exc


def venv_python() -> Path:
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_python() -> None:
    import sysconfig
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SetupError("Use standard Python 3.13, not free-threaded Python 3.13t.")
    if not ((3, 11) <= sys.version_info[:2] <= (3, 13)):
        raise SetupError('Python 3.11–3.13 is required (Python 3.12 recommended).')
    if not (ROOT / 'web' / 'backend' / 'app' / 'devserver.py').is_file():
        raise SetupError('Files are missing. Extract the entire AETHER ZIP, do not run it inside the archive.')
    if not (FRONTEND / 'scripts' / 'build-offline.mjs').is_file():
        raise SetupError('Frontend files are missing. Extract the entire AETHER ZIP first.')


def code_ok(python: Path, imports: str) -> bool:
    if not python.is_file():
        return False
    result = subprocess.run([str(python), '-c', imports], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def ensure_python_environment() -> Path:
    py = venv_python()
    if not py.is_file():
        info('Step 1/3: Creating a private Python environment (first launch only).')
        run([sys.executable, '-m', 'venv', str(VENV)])
    dep_hash = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    ready = VENV / '.requirements-sha256'
    if not (ready.exists() and ready.read_text(encoding='utf-8').strip() == dep_hash
            and code_ok(py, 'import fastapi, uvicorn, pydantic, numpy, scipy')):
        info('Step 1/3: Installing scientific backend dependencies (internet required once).')
        run([str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(REQUIREMENTS)])
        if not code_ok(py, 'import fastapi, uvicorn, pydantic, numpy, scipy'):
            raise SetupError('The backend packages did not install correctly. Check Python version and network access.')
        ready.write_text(dep_hash + '\n', encoding='utf-8')
    else:
        info('Step 1/3: Python environment is ready.')
    return py


def source_signature() -> str:
    """A cheap source/asset manifest to avoid rebuilding on every launch."""
    h = hashlib.sha256()
    files = [FRONTEND / 'index.html', FRONTEND / 'package.json', FRONTEND / 'package-lock.json',
             FRONTEND / 'scripts' / 'build-offline.mjs']
    files.extend(p for base in (FRONTEND / 'src', FRONTEND / 'public') if base.exists()
                 for p in base.rglob('*') if p.is_file())
    for path in sorted(set(files)):
        if not path.is_file():
            continue
        st = path.stat()
        h.update(str(path.relative_to(FRONTEND)).encode('utf-8'))
        h.update(f':{st.st_size}:{st.st_mtime_ns}\n'.encode('ascii'))
    return h.hexdigest()


def node_info() -> tuple[str, str]:
    node = shutil.which('node')
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    if not node or not npm:
        raise SetupError('Node.js 20+ is needed ONCE for the complete RAR design. Install LTS from https://nodejs.org/, then launch again. For an old static preview, use OPEN_DEMO_NO_INSTALL.bat.')
    try:
        ver = subprocess.check_output([node, '-p', 'process.versions.node'], text=True, timeout=15).strip()
        major = int(ver.split('.')[0])
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SetupError('Cannot determine Node.js version. Reinstall Node.js LTS.') from exc
    if major < 20:
        raise SetupError(f'Installed Node.js {ver} is too old; use Node.js 20+ from https://nodejs.org/.')
    return node, npm


def ensure_frontend_build() -> None:
    """Verify the shipped, precompiled hybrid UI; NEVER invoke Node/npm at runtime."""
    built = DIST / 'index.html'
    if not built.is_file() or built.stat().st_size < 200_000:
        raise SetupError('AETHER UI is missing. Extract the COMPLETE ZIP. Node.js is not needed.')
    html = built.read_text(encoding='utf-8', errors='replace')
    if 'AETHER' not in html or 'carablik.glb' not in html:
        raise SetupError('Incorrect or outdated AETHER UI bundle. Re-extract this ZIP.')
    for model in ('carablik.glb', 'anatom.glb', 'skeleton.glb'):
        f = DIST / 'models' / model
        if not f.is_file() or f.stat().st_size < 1000:
            raise SetupError(f'Missing model from supplied application: {f}')
    info('Precompiled AETHER hybrid interface ready. Node.js is NOT required.')


def free_port() -> int:
    for port in [8000, *range(8001, 8020)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((URL_HOST, port)) != 0:
                return port
    raise SetupError('Local ports 8000–8019 are occupied. Close old AETHER instances and try again.')


def wait_for_health(url: str, proc: subprocess.Popen, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SetupError(f'The backend exited with code {proc.returncode}. Read errors above.')
        try:
            with urllib.request.urlopen(url + '/api/health', timeout=1.5) as resp:
                if resp.status == 200 and json.loads(resp.read()).get('api_version', True):
                    return
        except (urllib.error.URLError, ValueError, OSError):
            pass
        time.sleep(0.4)
    raise SetupError('Backend did not respond to /api/health. Check the error messages above.')


def run_server(python: Path) -> None:
    info('Step 3/3: Starting AETHER Live Mode on this computer.')
    port = free_port()
    url = f'http://{URL_HOST}:{port}'
    env = os.environ.copy()
    env['AETHER_DB_PATH'] = str(ROOT / 'runtime' / 'aether.sqlite3')
    (ROOT / 'runtime').mkdir(exist_ok=True)
    cmd = [str(python), '-u', '-m', 'app.devserver', '--host', URL_HOST, '--port', str(port), '--static', str(DIST)]
    proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env)
    try:
        wait_for_health(url, proc)
        info('READY! Opening ' + url + '/?mode=live')
        info('Keep this black window open while using AETHER. Ctrl+C stops the application.')
        webbrowser.open(url + '/?mode=live')
        while proc.poll() is None:
            time.sleep(0.7)
        raise SetupError(f'AETHER server exited (code {proc.returncode}).')
    except KeyboardInterrupt:
        info('Stopping AETHER.')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def diagnostics() -> None:
    print('AETHER 1.0 FINAL HYBRID — quick-start checks')
    print('  Python:', sys.version.split()[0])
    print('  Project:', ROOT)
    print('  Backend:', BACKEND.is_dir())
    print('  Frontend:', FRONTEND.is_dir())
    print('  Built UI present:', (DIST / 'index.html').is_file())
    print('  Quick-build stamp:', STAMP.is_file())
    print('  Virtual environment:', venv_python().is_file())
    print('  Frontend build: included, no Node.js required')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose', action='store_true', help='Check setup without installing anything')
    args = parser.parse_args()
    if args.diagnose:
        diagnostics()
        return 0
    try:
        check_python()
        # Build first so a missing Node installation doesn't install unused Python packages.
        ensure_frontend_build()
        py = ensure_python_environment()
        run_server(py)
        return 0
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        info('START FAILED: ' + str(exc))
        info('The existing project was not deleted. You can retry the same launcher.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
