"""AETHER 1.5 Windows desktop entry point: native WebView2 window, stdlib server, bundled assets.

No Python/Node/compiler on the end user's machine (frozen with PyInstaller). Microsoft Edge
WebView2 Runtime is required (preinstalled on Windows 11 and current Windows 10).

    AETHER_1_5.exe                       normal start (desktop window, Live Mode → sign in)
    AETHER_1_5.exe --smoke-test --report smoke.json [--data-dir DIR]
                                          headless release acceptance of the frozen build (no window, synthetic data only)
    AETHER_1_5.exe --ble-diagnostics --report ble.json [--scan-seconds N]
                                          frozen-runtime Bluetooth check: bleak/WinRT import, radio state and one real
                                          HRS scan through the radio. Reads nothing from and writes nothing to accounts.

Source reconstruction note (BLE personal integration, 2026-11-15): the 1.5 desktop_native.py source was not in the
handoff. This file was rebuilt from the frozen bytecode of AETHER_1_5.exe (Python 3.13, verified function by function)
and then extended (device-manager shutdown, --ble-diagnostics). See BLE_BASELINE_AUDIT.md.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
from pathlib import Path

APP_TITLE = 'AETHER 1.5 — Adaptive Ecosystem for Human Exploration and Resilience'
MODELS = ('anatom.glb', 'carablik.glb', 'cosmo11.glb', 'cosmo11_lite.glb', 'meza.glb', 'skeleton.glb')


def resource_root() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def data_dir(override: str | None) -> Path:
    """Per-user writable data directory; never write personal data into the app bundle."""
    if override:
        base = Path(override)
    elif sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', str(Path.home()))) / 'space.aether.desktop'
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support' / 'space.aether.desktop'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'space.aether.desktop'
    base.mkdir(parents=True, exist_ok=True)
    return base


def prepare_env(data: Path):
    # Must run before app.* is imported: db.DB_PATH and the NASA folder are read at import time.
    os.environ['AETHER_DB_PATH'] = str(data / 'aether.sqlite3')
    os.environ['AETHER_RELEASE'] = '1'
    os.environ['AETHER_LEGACY_DEMO'] = '0'
    os.environ.setdefault('AETHER_NASA_DATA_DIR', str(data / 'nasa_osdr'))
    os.environ.pop('AETHER_DISABLE_TOKEN', None)      # the desktop build always enforces the token
    os.environ.pop('AETHER_OSDR_TEST_MIRROR', None)   # never a fixture mirror in the product
    root = resource_root()
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(root / 'web' / 'backend'))


def start_server():
    from app.devserver import serve
    assets = resource_root() / 'web' / 'frontend' / 'dist'
    if not (assets / 'index.html').is_file():
        raise RuntimeError('Production frontend assets missing. Run the documented Windows build before launching.')
    httpd = serve(port=0, static=str(assets))
    threading.Thread(target=httpd.serve_forever, daemon=True, name='aether-http').start()
    return httpd, 'http://127.0.0.1:' + str(httpd.server_port)


def _get(url, token=None, data=None):
    headers = {'Content-Type': 'application/json'} if data is not None else {}
    if token:
        headers['X-AETHER-Token'] = token
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def smoke(report: str | None, data: Path, phase: str) -> int:
    from release_smoke import run
    return run(report, data, phase)


def legacy_smoke_14(report: str | None, data: Path, phase: str) -> int:
    """AETHER 1.4 smoke (legacy demo routes). Kept for reference; the 1.5 release uses release_smoke.run."""
    httpd, url = start_server()
    token = httpd.policy.token
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'pass': bool(ok), 'detail': str(detail)[:300]})
    try:
        if phase == 'restart':
            st, body = _get(url + '/api/biosignals/sessions', token)
            sessions = json.loads(body) if st == 200 else []
            check('restart: DEMO session persisted in SQLite', any(s['source_type'] == 'simulated_demo' for s in sessions), len(sessions))
            st, body = _get(url + '/api/nasa/imports', token)
            check('restart: NASA import history persisted', st == 200 and len(json.loads(body)['imports']) >= 1)
        else:
            st, body = _get(url + '/api/health')
            health = json.loads(body) if st == 200 else {}
            check('backend health', st == 200 and health.get('release_version') == '1.4.0', health.get('release_version'))
            st, html = _get(url + '/')
            text = html.decode('utf-8', 'replace')
            check('frontend index served with session token', st == 200 and 'aether-session-token' in text and token in text)
            for marker in ('Real Biosignal Intelligence', 'DEMO MODE', 'NASA OSDR human reference data', './aether-nasa-data-lab.js'):
                check(f'bundle marker: {marker}', marker in text)
            st, js = _get(url + '/aether-nasa-data-lab.js')
            check('NASA Data Lab 1.4 asset', st == 200 and b'AETHER NASA Data Lab 1.4' in js)
            for model in MODELS:
                st, glb = _get(url + '/models/' + model)
                check(f'3D asset {model}', st == 200 and glb[:4] == b'glTF' and len(glb) > 100_000, len(glb))
            check('security: data route refuses missing token', _get(url + '/api/nasa/imports')[0] == 401)
            st, _ = _get(url + '/api/nasa/imports', token)
            check('security: data route accepts session token', st == 200)
            for path in ('/api/astronauts', '/api/phantom/A01?day=67', '/api/symbiosis?day=67', '/api/co-orbit',
                         '/api/mission-lab/scenarios', '/api/recovery/sessions/A01', '/api/connectors'):
                st, _ = _get(url + path, token)
                check(f'module API {path}', st == 200, st)
            st, body = _get(url + '/api/biosignals/demo/recording', token, json.dumps({'confirm_simulated': True}).encode())
            demo = json.loads(body) if st == 200 else {}
            check('DEMO recording created and labelled simulated', demo.get('source_type') == 'simulated_demo', st)
            if demo:
                st, body = _get(url + f"/api/biosignals/sessions/{demo['id']}/analysis", token, b'{}')
                a = json.loads(body) if st == 200 else {}
                check('PHANTOM adapter analyses DEMO recording', a.get('simulated') is True and a.get('outcome') in ('flag', 'no_flag'), a.get('outcome'))
            csv = 'Sample Name,Value (mg/dL)\nS1_L-3,90\nS1_R+1,95\n'
            st, body = _get(url + '/api/nasa/local-csv', token, json.dumps({'study_id': 575, 'filename': 'smoke.csv', 'content': csv, 'column': 'Value (mg/dL)', 'label_column': 'Sample Name'}).encode())
            check('NASA offline CSV import (labelled unverified)', st == 200 and json.loads(body)['provenance']['source_type'] == 'user_supplied_file_unverified', st)
            st, _ = _get(url + '/api/biosignals/sensor/diagnostics', token)
            check('BLE diagnostics endpoint', st == 200)
            try:
                import bleak  # noqa: F401
                check('bleak bundled (BLE runtime)', True)
            except ImportError as exc:
                check('bleak bundled (BLE runtime)', False, exc)
    finally:
        httpd.shutdown(); httpd.server_close()

    if phase == 'first':
        # Real process restart: launch a fresh copy of this program on the same data folder.
        cmd = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())])
        out = data / 'smoke-restart.json'
        r = subprocess.run(cmd + ['--smoke-test', '--smoke-phase', 'restart', '--data-dir', str(data), '--report', str(out)],
                           capture_output=True, text=True, timeout=180)
        try:
            checks += json.loads(out.read_text(encoding='utf-8'))['checks']
        except (OSError, ValueError, KeyError):
            check('restart phase produced a report', False, (r.stderr or '')[-300:])
    result = {'status': 'pass' if all(c['pass'] for c in checks) else 'fail', 'phase': phase,
              'frozen': bool(getattr(sys, 'frozen', False)), 'platform': sys.platform, 'python': sys.version.split()[0],
              'passed': sum(c['pass'] for c in checks), 'failed': sum(not c['pass'] for c in checks), 'checks': checks,
              'not_covered': ['native WebView2 window rendering (requires interactive Windows session)', 'physical BLE hardware']}
    if report:
        Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
    if phase == 'first':
        for c in checks:
            print(('PASS ' if c['pass'] else 'FAIL ') + c['check'])
        print(f"{result['passed']} passed, {result['failed']} failed")
    return 0 if result['status'] == 'pass' else 1


def fatal(message: str, data: Path):
    log = data / 'portable-error.log'
    log.write_text(message, encoding='utf-8')
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message[-1500:] + f'\n\nLog: {log}', 'AETHER could not start', 0x10)
        except Exception:
            pass
    print(message, file=sys.stderr)


def ble_diagnostics(report: str | None, scan_seconds: float) -> int:
    """Frozen-runtime Bluetooth proof: imports, radio, and one scan through the real radio (no account, no storage)."""
    from app.devices.runtime import BleakTransport, classify_ble_error
    t = BleakTransport()
    result = {'frozen': bool(getattr(sys, 'frozen', False)), 'platform': sys.platform, 'python': sys.version.split()[0],
              'diagnostics': t.diagnostics(), 'imports': {}, 'scan': None, 'hardware_verified': False}
    for mod in ('bleak', 'bleak.backends.winrt.scanner', 'bleak.backends.winrt.client', 'winrt.windows.devices.bluetooth',
                'winrt.windows.devices.bluetooth.advertisement', 'winrt.windows.devices.bluetooth.genericattributeprofile',
                'winrt.windows.devices.radios', 'winrt.windows.foundation', 'winrt.windows.storage.streams'):
        try:
            __import__(mod)
            result['imports'][mod] = 'ok'
        except Exception as exc:
            result['imports'][mod] = f'{type(exc).__name__}: {exc}'[:200]
    if result['diagnostics']['scan_available']:
        try:
            found = t.scan(True, scan_seconds)
            # addresses are not written to the report: only counts and HRS advertisement flags
            result['scan'] = {'status': 'completed', 'devices_with_name_or_hrs': len(found),
                              'hrs_advertised': sum(1 for d in found if d['advertised_hrs']),
                              'names': sorted({d['name'] for d in found})[:20]}
        except Exception as exc:
            code, message = classify_ble_error(exc)
            result['scan'] = {'status': 'failed', 'reason_code': code, 'reason': message}
    else:
        result['scan'] = {'status': 'not_run', 'reason_code': result['diagnostics']['reason_code'],
                          'reason': result['diagnostics']['reason']}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if report:
        Path(report).write_text(text, encoding='utf-8')
    print(text)
    return 0 if all(v == 'ok' for v in result['imports'].values()) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--smoke-phase', default='first', choices=('first', 'restart'))
    parser.add_argument('--report')
    parser.add_argument('--data-dir', help='Use this data folder (default: %%APPDATA%%\\space.aether.desktop)')
    parser.add_argument('--ble-diagnostics', action='store_true')
    parser.add_argument('--scan-seconds', type=float, default=6.0)
    a = parser.parse_args()
    if (a.smoke_test or a.ble_diagnostics) and not a.data_dir:
        a.data_dir = tempfile.mkdtemp(prefix='aether-smoke-')  # never touch the user's real data
    data = data_dir(a.data_dir)
    prepare_env(data)
    if a.ble_diagnostics:
        sys.exit(ble_diagnostics(a.report, max(1.0, min(15.0, a.scan_seconds))))
    if a.smoke_test:
        try:
            sys.exit(smoke(a.report, data, a.smoke_phase))
        except Exception as exc:
            if a.report:
                Path(a.report).write_text(json.dumps({'status': 'FAIL', 'error': str(exc), 'frozen': bool(getattr(sys, 'frozen', False))}), encoding='utf-8')
            sys.exit(1)
    httpd = None
    try:
        httpd, url = start_server()
        import webview

        class Files:
            def choose_mmash(self, folder=False):
                result = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
                                                               directory=str(Path.home()), allow_multiple=False,
                                                               file_types=('MMASH ZIP (*.zip)',) if not folder else ())
                return result[0] if result else None
        webview.create_window(APP_TITLE, url + '/?mode=live#/login', js_api=Files(), width=1500, height=930,
                              min_size=(1024, 680), background_color='#030B17')
        # GUI backend is selected per OS; the original hard-coded EdgeChromium
        # crashes on macOS and Linux before any window appears.
        gui = {'win32': 'edgechromium', 'darwin': 'cocoa'}.get(sys.platform, 'gtk')
        webview.start(gui=gui, private_mode=False, storage_path=str(data / 'webview'))
    except Exception:
        fatal('AETHER failed to start.\n\nWindows: install the Edge WebView2 Runtime. '
              'macOS: use the native Cocoa/WebKit build. Linux: install GTK3/WebKit2GTK 4.1 system libraries.\n\n'
              + traceback.format_exc(), data)
        sys.exit(1)
    finally:
        try:
            from app.ble_sensor import sensor
            if sensor.state['connection'] in ('connected', 'reconnecting'):
                sensor.call(sensor.disconnect())
        except Exception:
            pass
        if httpd:
            # server_close() also stops the 1.5 Device Manager: pending rows are flushed and active recordings are
            # closed as 'saved_on_shutdown' before storage stops.
            httpd.shutdown(); httpd.server_close()


if __name__ == '__main__':
    main()
