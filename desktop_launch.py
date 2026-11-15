"""AETHER 1.0 FINAL — real Windows desktop-window quick launcher.

This starts the local scientific Python backend and displays the *same* React UI
inside a native application window (WebView2), not in an external browser tab.

For a standalone installer use BUILD_WINDOWS.bat (Tauri/PyInstaller toolchain).
The complete React UI and 3D assets are already compiled and shipped in this
package. Node.js / npm are never required on the user's computer.
The lightweight Python desktop wrapper requires pywebview + Edge WebView2,
which it attempts to set up automatically when missing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

from quick_start import (
    BACKEND,
    DIST,
    ROOT,
    check_python,
    code_ok,
    ensure_frontend_build,
    free_port,
    info,
    run,
    wait_for_health,
    venv_python,
)

TITLE = 'AETHER 1.1 — Real Biosignal Intelligence — Adaptive Ecosystem for Human Exploration and Resilience'
APP_DATA = Path(os.environ.get('APPDATA') or (ROOT / 'runtime')) / 'space.aether.desktop'
LOGS = APP_DATA / 'logs'
DATA = APP_DATA / 'aether.sqlite3'
WEBVIEW_DIR = APP_DATA / 'webview'


# The lightweight stdlib server needs only these three scientific dependencies.
# FastAPI, Uvicorn, pytest and httpx belong to development/testing, not quick start.
RUNTIME_PACKAGES = (
    ('pydantic', 'pydantic>=2.6,<3.0'),
    ('numpy', 'numpy>=1.26,<3.0'),
    ('scipy', 'scipy>=1.11,<2.0'),
)


def install_packages(python: Path, packages: list[str], name: str) -> None:
    """Install only missing packages, capturing the actual pip error for diagnosis."""
    if not packages:
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / 'pip_install.log'
    cmd = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
           '--only-binary=:all:', '--no-binary=proxy-tools', '--no-input', '--timeout', '15', '--retries', '1', '--prefer-binary',
           *packages]
    info(f'Preparing {name}: {", ".join(packages)}')
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', timeout=240,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        with log_path.open('a', encoding='utf-8') as f:
            f.write(f'\nAETHER installation timed out ({name})\n')
        raise RuntimeError(f'Installation timed out. The complete pip log is at {log_path}') from exc
    with log_path.open('a', encoding='utf-8') as f:
        f.write(f'\n--- {time.strftime("%Y-%m-%d %H:%M:%S")} {name}, exit={result.returncode} ---\n')
        f.write(' '.join(cmd) + '\n' + result.stdout + '\n')
    if result.returncode:
        lines = [x for x in result.stdout.splitlines() if x.strip()]
        tail = '\n'.join(lines[-14:])
        raise RuntimeError(
            f'Could not prepare {name} (pip exit {result.returncode}). '
            f'Full error: {log_path}\n\n{tail}'
        )


def check_webview(python: Path) -> None:
    """Require the native window host; do not silently open an external browser."""
    if code_ok(python, 'import webview'):
        return
    install_packages(python, ['pywebview>=5,<7'], 'desktop window (pywebview)')
    if not code_ok(python, 'import webview'):
        raise RuntimeError(f'pywebview could not be imported after installation. See {LOGS / "pip_install.log"}')


def _enable_system_site_packages(venv: Path) -> None:
    """Reuse installed scientific packages if the existing venv was made without inheritance."""
    cfg = venv / 'pyvenv.cfg'
    if not cfg.is_file():
        return
    content = cfg.read_text(encoding='utf-8')
    lines = content.splitlines()
    changed = False
    for i, line in enumerate(lines):
        if line.lower().strip().startswith('include-system-site-packages'):
            if line.split('=', 1)[-1].strip().lower() != 'true':
                lines[i] = 'include-system-site-packages = true'
                changed = True
            break
    else:
        lines.append('include-system-site-packages = true')
        changed = True
    if changed:
        cfg.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def runtime_python(*, smoke_test: bool = False) -> Path:
    """Reuse Python packages when available; install ONLY missing runtime packages."""
    system = Path(sys.executable)
    core_imports = 'import pydantic, numpy, scipy'
    if code_ok(system, core_imports) and (smoke_test or code_ok(system, 'import webview')):
        info('Existing Python runtime is ready: no installation needed.')
        return system

    env_dir = ROOT / '.aether-venv'
    py = venv_python()
    if py.is_file() and not code_ok(py, 'import sysconfig; assert not sysconfig.get_config_var("Py_GIL_DISABLED")'):
        import shutil
        resolved = env_dir.resolve()
        if resolved.parent != ROOT.resolve() or resolved.name != '.aether-venv':
            raise RuntimeError('Unexpected virtual environment path')
        shutil.rmtree(resolved)
    if not py.is_file():
        info('Creating private Python environment (one time).')
        run([str(system), '-m', 'venv', '--system-site-packages', str(env_dir)])
    else:
        _enable_system_site_packages(env_dir)

    missing = [spec for module, spec in RUNTIME_PACKAGES
               if not code_ok(py, f'import {module}')]
    install_packages(py, missing, 'scientific runtime')
    if not code_ok(py, core_imports):
        raise RuntimeError(f'One or more scientific packages failed to import. See {LOGS / "pip_install.log"}')
    if not smoke_test:
        check_webview(py)
    return py


def make_server_command(python: Path, port: int) -> list[str]:
    return [str(python), '-u', '-m', 'app.devserver', '--host', '127.0.0.1',
            '--port', str(port), '--static', str(DIST)]


def launch_server(python: Path):
    LOGS.mkdir(parents=True, exist_ok=True)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    port = free_port()
    env = os.environ.copy()
    env['AETHER_DB_PATH'] = str(DATA)
    # A separate diagnostic log prevents an invisible crash when started by double click.
    log_path = LOGS / 'backend.log'
    log_file = log_path.open('a', encoding='utf-8')
    log_file.write(f'\n--- AETHER DESKTOP START {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n')
    log_file.flush()
    args = make_server_command(python, port)
    kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        proc = subprocess.Popen(args, cwd=str(BACKEND), env=env, stdout=log_file,
                                stderr=subprocess.STDOUT, **kw)
    except BaseException:
        log_file.close()
        raise
    url = f'http://127.0.0.1:{port}'
    try:
        wait_for_health(url, proc, timeout=45.0)
    except BaseException:
        stop_server(proc)
        log_file.close()
        raise RuntimeError(f'Local backend could not start. Read {log_path}')
    return url, proc, log_file


def stop_server(proc) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class DesktopFiles:
    def choose_mmash(self, folder=False):
        import webview
        window=webview.windows[0]
        result=window.create_file_dialog(webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
                                        directory=str(Path.home()), allow_multiple=False, file_types=('MMASH ZIP (*.zip)',) if not folder else ())
        return result[0] if result else None


def run_desktop(*, smoke_test: bool = False, skip_setup: bool = False) -> None:
    if os.name != 'nt' and not smoke_test:
        raise RuntimeError('The native desktop window requires Windows 10/11. Use --smoke-test to verify the backend.')
    if not skip_setup:
        check_python()
        info('Checking the PREBUILT React design and RAR 3D assets (no Node.js)...')
        ensure_frontend_build()
        python = runtime_python(smoke_test=smoke_test)
    else:
        if not (DIST / 'index.html').is_file():
            raise RuntimeError('No prebuilt dist-offline/index.html found; cannot skip setup.')
        python = venv_python() if code_ok(venv_python(), 'import sysconfig; assert not sysconfig.get_config_var("Py_GIL_DISABLED")') else Path(sys.executable)
    # pywebview must run in the interpreter where its dependencies were installed.
    if not smoke_test and python.resolve() != Path(sys.executable).resolve():
        subprocess.run([str(python), str(Path(__file__).resolve()), '--skip-setup'], check=True)
        return
    url, proc, log_file = launch_server(python)
    try:
        # Headless integration smoke test: no graphical shell or Windows required.
        if smoke_test:
            with urllib.request.urlopen(url + '/api/health', timeout=8) as response:
                health = json.load(response)
            with urllib.request.urlopen(url + '/?mode=live', timeout=8) as response:
                html = response.read(5000).decode('utf-8', errors='replace')
            with urllib.request.urlopen(url + '/models/carablik.glb', timeout=8) as response:
                model_length = int(response.headers.get('Content-Length') or 0)
                first = response.read(4)
            assert isinstance(health, dict) and ('api_contract_version' in health or 'version' in health or 'api_version' in health), health
            assert '<html' in html.lower() and len(html) > 200, 'frontend missing'
            assert first == b'glTF' and model_length > 0, 'ship GLB missing'
            info('HEADLESS SMOKE PASS: backend, frontend, and RAR spacecraft model available locally.')
            return
        import webview
        info('Starting desktop application window (no external browser).')
        info(f'Storage: {APP_DATA}  |  Backend log: {LOGS / "backend.log"}')
        WEBVIEW_DIR.mkdir(parents=True, exist_ok=True)
        webview.create_window(TITLE, url + '/?mode=live',
                              js_api=DesktopFiles(), width=1500, height=930, min_size=(1024, 680),
                              background_color='#030B17', resizable=True, confirm_close=False)
        # Edge Chromium is necessary for Three.js/WebGL 3D scenes. Disable legacy IE fallback.
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(WEBVIEW_DIR))
    finally:
        stop_server(proc)
        log_file.close()
        info('AETHER closed; local backend stopped.')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--smoke-test', action='store_true', help='Headless HTTP validation without the GUI.')
    ap.add_argument('--skip-setup', action='store_true', help='Use existing venv and compiled UI without installations.')
    ap.add_argument('--diagnose', action='store_true', help='Print local environment, do not install packages.')
    args = ap.parse_args()
    if args.diagnose:
        print('AETHER desktop diagnostics')
        print('Python:', sys.version.split()[0])
        print('Windows:', os.name == 'nt')
        print('Frontend ready:', (DIST / 'index.html').exists())
        print('Backend source:', (BACKEND / 'app' / 'devserver.py').exists())
        print('Virtual env:', venv_python().exists())
        print('App data:', APP_DATA)
        return 0
    try:
        run_desktop(smoke_test=args.smoke_test, skip_setup=args.skip_setup)
    except BaseException:
        LOGS.mkdir(parents=True, exist_ok=True)
        log_path = LOGS / 'launcher_error.log'
        error = traceback.format_exc()
        log_path.write_text(error, encoding='utf-8')
        print('\n[AETHER] DESKTOP LAUNCH FAILED\n' + error, flush=True)
        print(f'Error report: {log_path}', flush=True)
        print('Runtime: Python 3.11–3.13 + Edge WebView2. React and 3D are PREBUILT. pip errors: '+str(LOGS / 'pip_install.log'), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
