"""E2E-E · Browser E2E of the Live Mode personal Bluetooth workflow (Playwright, Chromium, headless).

    python tests/browser/ble_personal_ui_e2e.py --dist dist --out ../../artifacts/ui [--old-dist <portable dist>]

Server: web/backend/tests/ui_e2e_server.py (same devserver + release env + production Device Manager). The radio is
replaced by tests/fakes/fake_bleak (a test double of the bleak LIBRARY): this proves the UI ↔ API ↔ manager ↔ SQLite
↔ PHANTOM path, NOT physical Bluetooth. The SIMULATED strap step uses the shipped synthetic transport.
Writes screenshots + ui_e2e_result.json to --out. Exit code 0 only if every check passed.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve()
FRONTEND = HERE.parents[2]
BACKEND = FRONTEND.parent / 'backend'
PASSWORD = 'Ui-E2E-Password-2026!'
SCENARIO = [
    {'address': 'C4:7A:1C:00:12:9F', 'name': 'AETHER Test Strap', 'advertise_hrs': True, 'has_hrs': True, 'hr': 64, 'rr': [960], 'interval_s': 0.25},
    {'address': 'AA:BB:CC:00:00:01', 'name': 'Smart Watch', 'advertise_hrs': False, 'has_hrs': False},
]

ap = argparse.ArgumentParser()
ap.add_argument('--dist', default=str(FRONTEND / 'dist'))
ap.add_argument('--out', default=str(FRONTEND.parents[1] / 'artifacts' / 'ui'))
ap.add_argument('--old-dist')
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix='aether-ui-e2e-'))
db = tmp / 'ui.sqlite3'
scenario = tmp / 'scenario.json'; scenario.write_text(json.dumps(SCENARIO), encoding='utf-8')
checks, console_errors = [], []


def check(name, ok, detail=''):
    checks.append({'check': name, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)


def start(dist):
    p = subprocess.Popen([sys.executable, str(BACKEND / 'tests' / 'ui_e2e_server.py'), '--static', str(Path(dist).resolve()), '--db', str(db),
                          '--fake-bleak', str(scenario)], cwd=str(BACKEND), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = p.stdout.readline()
    if not line:
        raise RuntimeError('server failed: ' + p.stderr.read()[-2000:])
    return p, 'http://127.0.0.1:%d' % json.loads(line)['port']


def stop(p):
    p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()


def register_and_login(page, url, login):
    page.goto(url + '/?mode=live#/register')
    page.locator('input[name=login]').fill(login)
    page.locator('input[name=display_name]').fill('UI E2E')
    page.locator('input[name=password]').fill(PASSWORD)
    page.get_by_role('button', name='Create account').click()
    page.get_by_text('I saved this recovery code somewhere secure.').click()
    page.get_by_role('button', name='Continue to sign in').click()
    login_form(page, login)


def login_form(page, login):
    page.locator('input[name=login]').fill(login)
    page.locator('input[name=password]').fill(PASSWORD)
    page.get_by_role('button', name='Sign in').click()
    page.wait_for_function("() => !location.hash.startsWith('#/login')", timeout=15000)


def go(page, url, route):
    page.evaluate(f"location.hash = '#{route}'")
    page.wait_for_timeout(300)


def no_overflow(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--no-proxy-server'])  # loopback only; never through a proxy
    result = {'checks': checks}
    # ------------------------------------------------------------------ BEFORE: old portable bundle (bug reproduction)
    if a.old_dist:
        proc, url = start(a.old_dist)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            register_and_login(page, url, 'before_fix')
            go(page, url, '/biosignals')
            gate = page.get_by_text('DEMO / RESEARCH · personal API is separate')
            expect(gate).to_be_visible(timeout=10000)
            check('BEFORE (old bundle): Live Mode BIOSIGNALS blocked by the DEMO/RESEARCH guard', gate.is_visible())
            page.screenshot(path=str(out / 'before_live_biosignals_blocked.png'), full_page=True)
            page.close()
        finally:
            stop(proc)
        db.unlink(missing_ok=True)

    proc, url = start(a.dist)
    try:
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: console_errors.append(str(e)))
        page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        register_and_login(page, url, 'ui_alice')
        check('Live Mode → register → login', True)
        # ---------------------------------------------------------------- UI-01 BIOSIGNALS reachable in Live Mode
        go(page, url, '/biosignals')
        expect(page.get_by_role('heading', name='BIOSIGNALS · Bluetooth Heart Rate Service')).to_be_visible(timeout=10000)
        check('UI-01 BIOSIGNALS opens in Live Mode (no DEMO/RESEARCH gate)', page.get_by_text('DEMO / RESEARCH · personal API is separate').count() == 0)
        expect(page.get_by_text('Authenticated owner')).to_be_visible()
        expect(page.get_by_text('not verified (hardware_verified=false)')).to_be_visible()
        check('system state: backend, owner, BLE runtime, radio, hardware_verified=false', page.get_by_text('ui_alice').count() > 0)
        page.screenshot(path=str(out / 'after_live_biosignals_system_state.png'), full_page=True)
        # ---------------------------------------------------------------- scan → select → connect → receiving
        page.get_by_role('button', name='Scan HRS monitors').click()
        strap = page.get_by_role('button', name='AETHER Test Strap')
        expect(strap).to_be_visible(timeout=15000)
        check('scan shows HRS-advertising device only', page.get_by_role('button', name='Smart Watch').count() == 0)
        strap.click()
        page.get_by_role('button', name='Connect & start recording').click()
        expect(page.get_by_text('Recording', exact=True).first).to_be_visible(timeout=20000)
        expect(page.get_by_label('Current heart rate')).to_contain_text('64', timeout=15000)
        check('connect → Recording with real HRS notifications (64 bpm) and REAL SENSOR label',
              page.get_by_text('REAL SENSOR · Bluetooth HRS').count() > 0)
        page.screenshot(path=str(out / 'after_recording_live.png'), full_page=True)
        page.wait_for_timeout(1500)
        page.get_by_role('button', name='Stop, save & disconnect').click()
        expect(page.get_by_text('Saved', exact=True).first).to_be_visible(timeout=15000)
        check('Stop & save → Saved', True)
        page.screenshot(path=str(out / 'after_saved.png'), full_page=True)
        # ---------------------------------------------------------------- PHANTOM on the saved recording
        page.get_by_role('button', name='Analyse in PHANTOM').click()
        expect(page.get_by_role('heading', name='PHANTOM · personal analysis')).to_be_visible(timeout=10000)
        page.get_by_role('button', name='Run personal PHANTOM').click()
        expect(page.get_by_role('heading', name='Insufficient data')).to_be_visible(timeout=20000)
        check('PHANTOM on a short REAL SENSOR recording → insufficient_data (no fake flag)',
              page.get_by_text('REAL SENSOR', exact=True).count() > 0)
        page.screenshot(path=str(out / 'after_phantom_insufficient.png'), full_page=True)
        # ---------------------------------------------------------------- BODY personal history
        go(page, url, '/body')
        expect(page.get_by_text('PERSONAL MONITORING · authenticated account', exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_role('cell', name='real', exact=True).first).to_be_visible(timeout=10000)
        check('BODY personal history shows the stored BLE rows (origin real)', True)
        # ---------------------------------------------------------------- unsupported device
        go(page, url, '/biosignals')
        page.get_by_role('button', name='Scan nearby; verify HRS').click()
        watch = page.get_by_role('button', name='Smart Watch')
        expect(watch).to_be_visible(timeout=15000)
        watch.click()
        page.get_by_role('button', name='Connect & start recording').click()
        expect(page.get_by_text('Unsupported device', exact=True)).to_be_visible(timeout=15000)
        check('unsupported device (no GATT HRS) → honest "Unsupported device"', True)
        page.screenshot(path=str(out / 'after_unsupported_device.png'), full_page=True)
        # ---------------------------------------------------------------- simulated strap (SYNTHETIC)
        page.get_by_role('button', name='Test with simulated HRS').click()
        expect(page.get_by_text('SYNTHETIC · simulated HRS').first).to_be_visible(timeout=15000)
        expect(page.get_by_text('Recording', exact=True).first).to_be_visible(timeout=20000)
        check('simulated HRS is labelled SYNTHETIC while recording', True)
        page.wait_for_timeout(1500)
        page.get_by_role('button', name='Stop, save & disconnect').click()
        expect(page.get_by_text('Saved', exact=True).first).to_be_visible(timeout=15000)
        page.get_by_role('button', name='Refresh').click()
        page.wait_for_timeout(800)
        hist = page.get_by_label('Recording history')
        check('history lists REAL SENSOR and SYNTHETIC sessions separately',
              hist.get_by_text('REAL SENSOR · Bluetooth HRS').count() >= 1 and hist.get_by_text('SYNTHETIC · simulated HRS').count() >= 1)
        # ---------------------------------------------------------------- responsive
        for w in (375, 768, 1440):
            page.set_viewport_size({'width': w, 'height': 900})
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / f'live_sensors_{w}px.png'), full_page=True)
            check(f'responsive {w}px: no horizontal page overflow', no_overflow(page))
        page.set_viewport_size({'width': 1440, 'height': 1000})
        # ---------------------------------------------------------------- logout / re-login → same history
        page.get_by_role('button', name='Sign out').first.click()
        page.wait_for_timeout(800)
        go(page, url, '/login')
        login_form(page, 'ui_alice')
        go(page, url, '/biosignals')
        hist = page.get_by_label('Recording history')
        expect(hist.get_by_text('SYNTHETIC · simulated HRS').first).to_be_visible(timeout=10000)
        check('logout → re-login → same recording history', hist.get_by_text('REAL SENSOR · Bluetooth HRS').count() >= 1)
        page.close()
    finally:
        stop(proc)
    # ---------------------------------------------------------------- restart the backend process: history persists
    proc, url = start(a.dist)
    try:
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto(url + '/?mode=live#/login')
        login_form(page, 'ui_alice')
        go(page, url, '/biosignals')
        hist = page.get_by_label('Recording history')
        expect(hist.get_by_text('REAL SENSOR · Bluetooth HRS').first).to_be_visible(timeout=10000)
        check('backend restart → same SQLite history', hist.get_by_text('SYNTHETIC · simulated HRS').count() >= 1)
        page.screenshot(path=str(out / 'after_restart_history.png'), full_page=True)
        # ---------------------------------------------------------------- other screens still gated in Live Mode
        go(page, url, '/symbiosis')
        check('Live Mode: synthetic mission screens stay behind the DEMO/RESEARCH gate',
              page.get_by_text('DEMO / RESEARCH · personal API is separate').count() == 1)
        # ---------------------------------------------------------------- Demo Mode preserved and isolated
        page.goto(url + '/?mode=demo#/biosignals')
        page.wait_for_timeout(1500)
        check('Demo Mode BIOSIGNALS: legacy routes reported as isolated, no "Biosignal request failed"',
              page.get_by_text('local legacy recordings are isolated in this release').count() == 1
              and page.get_by_text('Biosignal request failed').count() == 0)
        page.screenshot(path=str(out / 'after_demo_mode_biosignals.png'), full_page=True)
        page.evaluate("localStorage.setItem('aether.biosignal.selection', JSON.stringify({source: 'synthetic', sessionId: ''}))")
        page.goto(url + '/?mode=demo#/body')
        page.reload()
        boxes = page.get_by_role('checkbox', name=re.compile(r'^Show .+ layer$'))
        expect(boxes.first).to_be_visible(timeout=15000)
        box = boxes.first
        before = box.is_checked(); enabled = box.is_enabled()
        box.click(); page.wait_for_timeout(200)
        check('REG-01 BODY Surface checkbox enabled and toggles (BODY fix kept)', enabled and box.is_checked() != before)
        page.close()
    finally:
        stop(proc)
    browser.close()

real_errors = [e for e in console_errors if 'status of 4' not in e and 'status of 5' not in e]
check('no uncaught page errors', not real_errors, real_errors[:3])
result.update(passed=sum(c['passed'] for c in checks), failed=sum(not c['passed'] for c in checks),
              browser='Chromium (Playwright, headless)', radio='tests/fakes/fake_bleak (test double) — NOT hardware',
              hardware_verified=False)
(out / 'ui_e2e_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(f"{result['passed']} passed, {result['failed']} failed")
sys.exit(0 if result['failed'] == 0 else 1)
