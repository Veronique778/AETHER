"""Browser E2E for the AETHER website (Playwright · Chromium · headless). Serves dist/ with a static server.

    python tests/e2e.py --dist dist [--dist-with-url dist-url] [--out artifacts]
Exit code 0 only if every check passed. Writes e2e_result.json, external_links.json and screenshots to --out.
"""
import argparse
import functools
import http.server
import json
import re
import sys
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument('--dist', default='dist')
ap.add_argument('--dist-with-url')
ap.add_argument('--out', default='artifacts')
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
checks, errors = [], []


def check(name, ok, detail=''):
    checks.append({'check': name, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.glb': 'model/gltf-binary', '.js': 'text/javascript'}

    def log_message(self, *args):
        pass


def serve(directory):
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(Path(directory).resolve())))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}/'


EXPECTED = {'Stable resting rhythm': 'no_flag', 'Sustained +15 bpm change': 'flag', 'Slow drift +20 bpm': 'flag',
            'Short bursts (e.g. stairs)': 'flag', 'Contact loss + data gap': 'flag', 'Too short to judge (50 min)': 'insufficient_data'}

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--no-proxy-server'])
    srv, url = serve(a.dist)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.goto(url)
    expect(page.get_by_role('heading', name='The Future of Human Health Beyond Earth')).to_be_visible()
    check('hero title + subtitle', page.get_by_text('Adaptive Ecosystem for Human Exploration and Resilience').count() >= 1)
    check('no download URL configured → "Download coming soon", no dead link',
          page.get_by_text('Download coming soon').count() >= 2 and page.locator('[data-testid=download-link]').count() == 0)
    page.screenshot(path=str(out / 'hero_1440.png'))
    page.get_by_role('link', name='Explore Interactive Demo').click()
    page.wait_for_timeout(900)
    check('Explore Demo scrolls to the PHANTOM demo', page.evaluate("location.hash") == '#phantom'
          and page.evaluate("Math.abs(document.getElementById('phantom').getBoundingClientRect().top) < 120"))

    # ---- PHANTOM demo: every scenario, outcome as expected
    for label, expected in EXPECTED.items():
        page.get_by_role('radio', name=re.compile('^' + re.escape(label))).click()
        page.get_by_role('button', name='Run simulation').click()
        o = page.locator('[data-testid=phantom-outcome]')
        expect(o).to_contain_text(expected, timeout=5000)
        check(f'PHANTOM demo: {label} → {expected}', expected in o.inner_text())
    check('PHANTOM demo is labelled SYNTHETIC DEMO', page.locator('#phantom').get_by_text('SYNTHETIC DEMO').count() >= 2)
    page.get_by_role('radio', name=re.compile('^Contact loss')).click(); page.get_by_role('button', name='Run simulation').click()
    page.locator('#phantom').screenshot(path=str(out / 'phantom_demo.png'))

    # ---- BODY twin (lazy)
    page.locator('#body').scroll_into_view_if_needed()
    expect(page.locator('#body canvas').first).to_be_visible(timeout=15000)
    check('BODY 3D loads lazily when scrolled into view', True)
    body = page.locator('#body')
    xr = body.get_by_role('radio', name='X-ray'); sf = body.get_by_role('radio', name='Surface')
    for mode, btn in (('Surface', sf), ('X-ray', xr)):
        btn.click(); page.wait_for_timeout(300)
        boxes = body.get_by_role('checkbox')
        ok = boxes.count() == 5
        for i in range(5):
            b = boxes.nth(i); before = b.is_checked(); b.click(); ok = ok and b.is_checked() != before and b.is_enabled(); b.click()
        check(f'BODY {mode}: all 5 system checkboxes enabled and toggle', ok)
    check('Surface / X-ray switch', xr.get_attribute('aria-checked') == 'true')
    body.get_by_role('button', name='Respiratory', exact=True).click()
    check('system selection updates the info panel', body.get_by_text('Selected · Respiratory').count() == 1)
    canvas = body.locator('canvas').first; bb = canvas.bounding_box()
    page.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2); page.mouse.down(); page.mouse.move(bb['x'] + bb['width'] / 2 + 120, bb['y'] + bb['height'] / 2, steps=8); page.mouse.up()
    canvas.focus(); page.keyboard.press('ArrowLeft'); page.keyboard.press('+')
    check('rotate (drag/keys) and zoom without errors', not errors, errors[:2])
    body.get_by_role('combobox').select_option('anatom')
    page.wait_for_timeout(2500)
    check('switch to team GLB model (anatom.glb) loads', body.get_by_role('alert').count() == 0 and body.get_by_text('Loading anatom.glb').count() == 0)
    sf.click(); page.wait_for_timeout(500)
    body.screenshot(path=str(out / 'body_twin.png'))
    tip = body.get_by_role('button', name='About Cardiovascular')
    check('info tooltips present for every system', body.get_by_role('button', name=re.compile('^About ')).count() == 5 and tip.count() == 1)

    # ---- Explore modules dialogs
    names = ['BODY', 'PHANTOM', 'BIOSIGNALS', 'SYMBIOSIS', 'CO-ORBIT', 'RECOVERY', 'MISSION LAB']
    ok = True
    for n in names:
        page.locator('#modules').get_by_role('button', name=re.compile('^' + re.escape(n))).click()
        d = page.get_by_role('dialog')
        ok = ok and d.is_visible() and n in d.inner_text() and 'Status' in d.inner_text()
        page.keyboard.press('Escape'); page.wait_for_timeout(100)
        ok = ok and page.get_by_role('dialog').count() == 0
    check('all 7 module cards open a detail dialog (Escape closes)', ok)

    # ---- download section
    page.locator('#download').scroll_into_view_if_needed()
    check('download block: version, requirements, install steps, limitations, SHA-256',
          all(page.locator('#download').get_by_text(t).count() >= 1 for t in ['Ready to Explore AETHER?', 'System requirements', 'Install the portable app', 'Scientific limitations', 'Windows 10 or 11, 64-bit'])
          and len(page.locator('[data-testid=sha256]').inner_text()) == 64)
    page.locator('#download').screenshot(path=str(out / 'download.png'))
    check('footer states no NASA endorsement', page.get_by_text('not affiliated with, endorsed by or sponsored by NASA').count() == 1)

    # ---- links
    hrefs = page.eval_on_selector_all('a[href]', 'els => els.map(e => e.getAttribute("href"))')
    internal = [h for h in hrefs if h.startswith('#')]
    missing = [h for h in set(internal) if h != '#' and page.locator(h).count() == 0]
    external = sorted({h for h in hrefs if h.startswith('http')})
    check(f'all {len(set(internal))} in-page links resolve', not missing, missing)
    check('external links are https, open in a new tab with noopener',
          all(h.startswith('https://') for h in external)
          and page.eval_on_selector_all('a[href^="http"]', 'els => els.every(e => e.target === "_blank" && /noopener/.test(e.rel))'))
    (out / 'external_links.json').write_text(json.dumps(external, indent=2), encoding='utf-8')

    # ---- responsive + mobile menu
    for w, h in ((375, 812), (768, 1024), (1440, 900)):
        p = browser.new_page(viewport={'width': w, 'height': h}); p.goto(url); p.wait_for_timeout(400)
        check(f'{w}px: no horizontal overflow', p.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
        p.screenshot(path=str(out / f'home_{w}.png'), full_page=False)
        if w == 375:
            p.get_by_role('button', name='Open menu').click()
            p.locator('#mobile-menu').get_by_role('link', name='Download').click(); p.wait_for_timeout(900)
            check('mobile menu navigates', p.evaluate("location.hash") == '#download')
            p.locator('#body').scroll_into_view_if_needed(); expect(p.locator('#body canvas').first).to_be_visible(timeout=15000)
            check('375px: BODY twin usable without overflow', p.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            p.screenshot(path=str(out / 'body_375.png'))
        p.close()
    srv.shutdown()

    # ---- no WebGL → canvas fallback
    b2 = pw.chromium.launch(args=['--no-proxy-server', '--disable-webgl', '--disable-webgl2', '--disable-3d-apis'])
    srv, url = serve(a.dist); p = b2.new_page(); p.goto(url + '#body'); p.wait_for_timeout(500)
    p.locator('#body').scroll_into_view_if_needed()
    expect(p.locator('#body canvas').first).to_be_visible(timeout=15000)
    check('no WebGL: notice shown and the twin still renders (Canvas 2D fallback)', p.get_by_text('WebGL is not available').count() == 1)
    b2.close(); srv.shutdown()

    # ---- configured URL variant
    if a.dist_with_url:
        srv, url = serve(a.dist_with_url); p = browser.new_page(); p.goto(url)
        links = p.locator('[data-testid=download-link]')
        check('with WINDOWS_DOWNLOAD_URL set: real download buttons (https, new tab)', links.count() >= 2
              and links.first.get_attribute('href').startswith('https://') and links.first.get_attribute('target') == '_blank'
              and p.get_by_text('Download coming soon').count() == 0)
        srv.shutdown()
    browser.close()

check('no console / page errors', not errors, errors[:3])
res = {'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks), 'checks': checks}
(out / 'e2e_result.json').write_text(json.dumps(res, indent=2), encoding='utf-8')
print(f"{res['passed']} passed, {res['failed']} failed")
sys.exit(0 if res['failed'] == 0 else 1)
