"""One-step local setup and API launch. Uses only stdlib before selecting Python."""
from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser

ROOT = Path(__file__).resolve().parent
SUPPORTED = {(3, 11), (3, 12), (3, 13)}


def supported_python(command):
    try:
        result = subprocess.run(command + ['-c',
            'import sys,struct,json; print(json.dumps([list(sys.version_info[:2]),struct.calcsize("P")*8]))'],
            capture_output=True, text=True, timeout=15, cwd=ROOT)
        version, bits = json.loads(result.stdout.strip())
        return result.returncode == 0 and tuple(version) in SUPPORTED and bits == 64
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def select_python():
    candidates = [[sys.executable]]
    if os.name == 'nt':
        candidates = [['py', '-3.11'], ['py', '-3.12'], ['py', '-3.13']] + candidates
    else:
        candidates += [['python3.12'], ['python3.11'], ['python3.13']]
    for candidate in candidates:
        if supported_python(candidate):
            return candidate
    raise RuntimeError('Python 3.11, 3.12 or 3.13 (64-bit) is required. Run: py --list')


def dependencies_ready(python):
    code = '''
import fastapi, numpy, scipy, pydantic, uvicorn, httpx
from importlib.metadata import version
from pathlib import Path
for line in Path('requirements-mission.txt').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '==' in line:
        name, wanted = line.split('==', 1)
        assert version(name) == wanted, name
'''
    return subprocess.run([str(python), '-c', code], cwd=ROOT,
                          capture_output=True).returncode == 0


def environment_python():
    relative = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
    for name in ('.venv', '.venv-aether'):
        python = ROOT / name / relative
        if python.exists() and supported_python([str(python)]):
            return python
    base = select_python()
    # Preserve an existing, incompatible environment rather than deleting it.
    target = ROOT / ('.venv-aether' if (ROOT / '.venv').exists() else '.venv')
    if target.exists():
        raise RuntimeError('Both environment folders are incompatible. Extract the ZIP into a new folder.')
    print('Creating a local Python environment...', flush=True)
    subprocess.run(base + ['-m', 'venv', str(target)], cwd=ROOT, check=True)
    return target / relative


def serve(open_browser=True, db_path=None):
    import uvicorn
    from mission_systems.api import create_app
    sock = None
    for port in range(8000, 8011):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.bind(('127.0.0.1', port))
            candidate.listen(128)
            sock = candidate
            break
        except OSError:
            candidate.close()
    if sock is None:
        raise RuntimeError('Ports 8000-8010 are busy. Close an earlier AETHER server and retry.')
    url = f'http://127.0.0.1:{port}/docs'
    server = uvicorn.Server(uvicorn.Config(create_app(db_path), host='127.0.0.1', port=port))
    stopped = threading.Event()

    def ready():
        while not stopped.wait(.1):
            if server.started:
                print('\nAETHER is ready: ' + url, flush=True)
                print('Keep this window open. Press Ctrl+C to stop.', flush=True)
                if open_browser:
                    try:
                        if not webbrowser.open(url):
                            print('Open the address above in your browser.', flush=True)
                    except Exception:
                        print('Open the address above in your browser.', flush=True)
                return

    thread = threading.Thread(target=ready, daemon=True)
    thread.start()
    try:
        server.run(sockets=[sock])
    finally:
        stopped.set()
        thread.join(timeout=1)
        sock.close()


def main():
    parser = argparse.ArgumentParser(description='Start AETHER with automatic local setup')
    parser.add_argument('--server', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='Check Python without installing anything')
    parser.add_argument('--db', default=None, help='Optional database path')
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.check:
        print('Compatible Python:', select_python())
        return 0
    if args.server:
        serve(not args.no_browser, args.db)
        return 0
    print('AETHER Mission Systems — starting...', flush=True)
    python = environment_python()
    print('Python: ' + str(python), flush=True)
    if not dependencies_ready(python):
        print('Installing dependencies. Internet is needed for this first setup. Please wait...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-mission.txt')],
                       cwd=ROOT, check=True)
    command = [str(python), str(Path(__file__).resolve()), '--server']
    if args.no_browser:
        command.append('--no-browser')
    if args.db:
        command += ['--db', args.db]
    return subprocess.call(command, cwd=ROOT)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nAETHER stopped.')
    except Exception as exc:
        message = 'AETHER could not start: ' + str(exc)
        print('\n' + message, flush=True)
        try:
            (ROOT / 'start_error.log').write_text(traceback.format_exc(), encoding='utf-8')
            print('Details saved in start_error.log', flush=True)
        except OSError:
            pass
        if os.name == 'nt' and not os.environ.get('AETHER_FROM_BAT'):
            try:
                input('Press Enter to close...')
            except EOFError:
                pass
        sys.exit(1)
