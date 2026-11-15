"""AETHER desktop backend sidecar (v0.6).

Thin launcher around the UNCHANGED AETHER backend (web/backend/app). The Tauri shell starts it on a free
localhost port, passes the per-user data directory, and stops it on exit.

    aether-backend --port 8765 [--parent-pid 1234] [--server auto|fastapi|stdlib]

Safety / lifecycle:
  * binds to 127.0.0.1 only (no LAN exposure);
  * exits when the parent (the AETHER window process) disappears – no orphaned servers after a crash;
  * exits cleanly on SIGTERM / SIGINT / CTRL_BREAK;
  * the SQLite database path comes from AETHER_DB_PATH (set by the shell to the app-data directory).

Server: FastAPI + uvicorn (primary, app.main) when installed; otherwise the stdlib fallback (app.devserver),
which serves the same /api routes through the same app.service layer.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

HOST = '127.0.0.1'


def _add_backend_to_path() -> None:
    """Running from source: make web/backend importable. In the PyInstaller build `app` is bundled."""
    if getattr(sys, 'frozen', False):
        return
    here = Path(__file__).resolve()
    backend = here.parents[2] / 'web' / 'backend'
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _parent_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return os.getppid() != 1


def watch_parent(pid: int, on_exit) -> None:
    """Background thread: call on_exit() as soon as the parent process ends."""
    def run():
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.WaitForSingleObject(handle, INFINITE)
                kernel32.CloseHandle(handle)
            on_exit('parent process ended')
            return
        while _parent_alive_posix(pid):
            time.sleep(1.0)
        on_exit('parent process ended')
    threading.Thread(target=run, name='parent-watch', daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='aether-backend', description='AETHER desktop backend sidecar')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--parent-pid', type=int, default=None)
    ap.add_argument('--server', choices=['auto', 'fastapi', 'stdlib'], default='auto')
    a = ap.parse_args(argv)

    _add_backend_to_path()
    db_path = os.environ.get('AETHER_DB_PATH')
    if db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # The desktop webview origin (Windows: http://tauri.localhost) must be allowed by FastAPI's CORS.
    os.environ.setdefault('AETHER_CORS_ORIGINS', 'http://tauri.localhost,https://tauri.localhost,tauri://localhost')

    server_kind = a.server
    if server_kind == 'auto':
        try:
            import fastapi  # noqa: F401
            import uvicorn  # noqa: F401
            server_kind = 'fastapi'
        except ImportError:
            server_kind = 'stdlib'

    stop_event = threading.Event()
    state: dict = {}

    def shutdown(reason: str = 'signal') -> None:
        if stop_event.is_set():
            return
        stop_event.set()
        # The desktop shell owns stdout and may already have closed the pipe.
        try:
            print(f'AETHER_BACKEND_STOPPING reason="{reason}"', flush=True)
        except OSError:
            pass
        if 'uvicorn' in state:
            state['uvicorn'].should_exit = True
        if 'httpd' in state:
            threading.Thread(target=state['httpd'].shutdown, daemon=True).start()
        # Hard stop if a graceful shutdown hangs.
        hard_stop = threading.Timer(5.0, lambda: os._exit(0))
        hard_stop.daemon = True
        hard_stop.start()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGBREAK', None)):
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: shutdown('signal'))
            except (ValueError, OSError):
                pass
    if a.parent_pid:
        watch_parent(a.parent_pid, shutdown)

    print(f'AETHER_BACKEND_STARTING server={server_kind} host={HOST} port={a.port} db={db_path or "(default)"}', flush=True)
    if server_kind == 'fastapi':
        import uvicorn
        from app.main import app as fastapi_app
        config = uvicorn.Config(fastapi_app, host=HOST, port=a.port, log_level='warning', access_log=False, lifespan='on')
        server = uvicorn.Server(config)
        state['uvicorn'] = server
        print(f'AETHER_BACKEND_READY url=http://{HOST}:{a.port}', flush=True)
        server.run()
    else:
        from app.devserver import serve
        httpd = serve(HOST, a.port)
        state['httpd'] = httpd
        print(f'AETHER_BACKEND_READY url=http://{HOST}:{a.port}', flush=True)
        httpd.serve_forever(poll_interval=0.25)
        httpd.server_close()
    print('AETHER_BACKEND_STOPPED', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
