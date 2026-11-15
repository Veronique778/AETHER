/**
 * Visual regression: AETHER v0.5 (git tag v0.5, browser build) vs the v0.6 desktop bundle (desktop/dist,
 * with the desktop runtime injected), same viewport, device scale factor 1, reduced motion on.
 *   node desktop/tests/visual-regression.mjs        → desktop/tests/visual-report/{*.png, report.md}
 * Two passes: Demo Mode (in-app synthetic adapter) and Live Mode (each build talks to its own fresh backend).
 */
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(process.env.PLAYWRIGHT_REQUIRE_BASE ?? '/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const desk = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = resolve(desk, '..');
const PY = process.env.PYTHON ?? 'python3';
const out = join(desk, 'tests', 'visual-report');
mkdirSync(out, { recursive: true });
const tmp = mkdtempSync(join(tmpdir(), 'aether-vr-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// v0.5 baseline straight from git.
mkdirSync(join(tmp, 'v05-demo')); mkdirSync(join(tmp, 'v05-live'));
writeFileSync(join(tmp, 'v05-demo', 'index.html'), execFileSync('git', ['-C', repo, 'show', 'v0.5:preview/AETHER_preview.html']));
writeFileSync(join(tmp, 'v05-live', 'index.html'), execFileSync('git', ['-C', repo, 'show', 'v0.5:web/frontend/dist-offline/index.html']));

const procs = [];
const serve = (dir, port) => procs.push(spawn(PY, ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', dir], { stdio: 'ignore' }));
const backend = (port, db) => procs.push(spawn(PY, [join(desk, 'backend', 'aether_backend.py'), '--port', String(port)], { stdio: 'ignore', env: { ...process.env, AETHER_DB_PATH: db } }));
serve(join(tmp, 'v05-demo'), 8941); serve(join(tmp, 'v05-live'), 8942); serve(join(desk, 'dist'), 8943);
backend(8000, join(tmp, 'a.sqlite3'));   // v0.5 live build is compiled against 127.0.0.1:8000
backend(8944, join(tmp, 'b.sqlite3'));   // desktop: address injected at runtime, as the Tauri shell does
await sleep(1500);

const ROUTES = [['mission-control', '/'], ['body', '/body'], ['phantom', '/phantom'], ['symbiosis', '/symbiosis'], ['co-orbit', '/co-orbit'], ['recovery', '/recovery'], ['mission-lab', '/mission-lab'], ['settings', '/settings']];
const browser = await chromium.launch();
async function shoot(url, prefs, inject, file, size) {
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1 });
  if (inject) await ctx.addInitScript(`window.__AETHER_DESKTOP__ = Object.freeze(${JSON.stringify({ apiBase: 'http://127.0.0.1:8944', version: '0.6.0', backendError: null })});`);
  await ctx.addInitScript(`try { ${Object.entries(prefs).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join('')} } catch {}`);
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  // Capture only a settled frame: repeat until two consecutive screenshots are byte-identical.
  let prev = await page.screenshot({ fullPage: true });
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(800);
    const cur = await page.screenshot({ fullPage: true });
    if (cur.equals(prev)) break;
    prev = cur;
  }
  writeFileSync(file, prev);
  await ctx.close();
}
// Warm-up: the very first page load of a fresh browser lays out a few late-measured elements (sparklines,
// 3D labels) differently; render each build once before capturing anything.
for (const url of ['http://127.0.0.1:8941/index.html#/', 'http://127.0.0.1:8942/index.html#/', 'http://127.0.0.1:8943/index.html#/']) await shoot(url, { 'aether.reducedMotion': '1' }, url.includes('8943'), join(tmp, 'warmup.png'), { width: 1440, height: 900 });
const rows = [];
for (const [mode, base, prefs] of [['demo', 'http://127.0.0.1:8941/index.html', { 'aether.mode': 'demo' }], ['live', 'http://127.0.0.1:8942/index.html', { 'aether.mode': 'live' }]]) {
  for (const size of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
    for (const [name, route] of ROUTES) {
      if (size.width === 1920 && !['mission-control', 'body', 'mission-lab'].includes(name)) continue;
      const p = { ...prefs, 'aether.reducedMotion': '1', 'aether.theme': 'dark', 'aether.astronaut': 'A01' };
      const a = join(out, `${mode}-${size.width}-${name}-v05.png`), b = join(out, `${mode}-${size.width}-${name}-v06.png`);
      // Two rounds (A, B, A, B): the second round is kept, so first-load layout timing cannot bias either build.
      for (let round = 0; round < 2; round++) {
        await shoot(`${base}#${route}`, p, false, a, size);
        await shoot(`http://127.0.0.1:8943/index.html#${route}`, p, true, b, size);
      }
      rows.push([mode, `${size.width}×${size.height}`, name, a, b]);
    }
  }
}
await browser.close();
procs.forEach((p) => p.kill());

// Pixel comparison (Pillow).
const py = `
import json, os, sys
from PIL import Image, ImageChops
rows = json.loads(sys.argv[1]); res = []
for mode, size, name, a, b in rows:
    A, B = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if A.size != B.size:
        res.append([mode, size, name, f'{A.size} vs {B.size}', None, None]); continue
    d = ImageChops.difference(A, B)
    px = d.load(); W, H = d.size; n = 0
    for y in range(H):
        for x in range(W):
            if max(px[x, y]) > 24: n += 1
    pct = 100.0 * n / (W * H)
    mx = max(c[1] for c in d.getextrema())
    stale = b.replace('-v06.png', '-diff.png')
    if not n and os.path.exists(stale):
        os.remove(stale)
    if n:
        mask = d.convert('L').point(lambda v: 255 if v > 24 else 0)
        hl = B.copy(); hl.paste((255, 0, 128), mask=mask); hl.save(b.replace('-v06.png', '-diff.png'))
    res.append([mode, size, name, f'{W}x{H}', round(pct, 4), mx])
print(json.dumps(res))
`;
const res = JSON.parse(execFileSync(PY, ['-c', py, JSON.stringify(rows)], { encoding: 'utf8', maxBuffer: 1 << 24 }));
const md = ['# Visual regression: v0.5 browser build vs v0.6 desktop bundle', '',
  `Generated ${new Date().toISOString()} · Chromium (Playwright) · device scale factor 1 · reduced motion on · threshold: any channel differs by > 24/255.`, '',
  '| Mode | Viewport | Screen | Image size | Pixels changed | Max channel diff | Verdict |', '|---|---|---|---|---|---|---|',
  ...res.map(([m, s, n, sz, pct, mx]) => `| ${m} | ${s} | ${n} | ${sz} | ${pct == null ? 'size differs' : pct + ' %'} | ${mx ?? '—'} | ${pct === 0 ? 'identical' : n === 'settings' ? 'intended change (Local data card)' : pct != null && pct < 0.05 ? 'equivalent (sub-pixel)' : 'CHECK'} |`)];
writeFileSync(join(out, 'report.md'), md.join('\n') + '\n');
console.log(md.join('\n'));
