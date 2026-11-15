/**
 * AETHER v0.6 desktop integration test – emulated shell.
 *
 * Runs the DESKTOP frontend bundle (desktop/dist) in Chromium (WebView2 is Chromium-based) exactly as the
 * Tauri shell does: `window.__AETHER_DESKTOP__` is injected before load, a stand-in for `window.__TAURI__`
 * records native fullscreen calls, and the real backend sidecar (desktop/backend/aether_backend.py) is started
 * late, with a stand-in "shell" parent process, on a free 127.0.0.1 port with its own data directory.
 * It does NOT replace testing the packaged Windows build (see docs/DESKTOP_V0.6.md §Windows test plan).
 *
 *   node desktop/tests/desktop-webview.mjs            (needs Playwright + Chromium and python3)
 */
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(process.env.PLAYWRIGHT_REQUIRE_BASE ?? '/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PY = process.env.PYTHON ?? 'python3';
const results = [];
const check = (name, ok, extra = '') => { results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + extra : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const freePort = () => new Promise((res) => { const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

const work = mkdtempSync(join(tmpdir(), 'aether-desktop-'));
const dataDir = join(work, 'AppData', 'Roaming', 'space.aether.desktop');
const profile = join(work, 'webview-profile');
const uiPort = await freePort();
const apiPort = await freePort();
const apiBase = `http://127.0.0.1:${apiPort}`;

// Static server for the desktop bundle (stands in for the tauri:// asset protocol).
const ui = spawn(PY, ['-m', 'http.server', String(uiPort), '--bind', '127.0.0.1', '--directory', join(root, 'dist')], { stdio: 'ignore' });
let shell = null; let sidecar = null; const sidecarLog = [];
const startSidecar = () => {
  shell = spawn(PY, ['-c', 'import time; time.sleep(3600)'], { stdio: 'ignore' });   // stands in for the AETHER window process
  sidecar = spawn(PY, [join(root, 'backend', 'aether_backend.py'), '--port', String(apiPort), '--parent-pid', String(shell.pid)],
    { env: { ...process.env, AETHER_DB_PATH: join(dataDir, 'aether.sqlite3') } });
  sidecar.stdout.on('data', (d) => sidecarLog.push(String(d).trim()));
  sidecar.stderr.on('data', (d) => sidecarLog.push(String(d).trim()));
};
const exited = (p, ms) => new Promise((res) => { if (p.exitCode !== null || p.signalCode) return res(true); const t = setTimeout(() => res(false), ms); p.once('exit', () => { clearTimeout(t); res(true); }); });

const info = (extra = {}) => ({ apiBase, version: '1.0.0', dataDir, logFile: join(dataDir, 'logs', 'backend.log'), backendError: null, ...extra });
const initScript = (i) => `window.__AETHER_DESKTOP__ = Object.freeze(${JSON.stringify(i)});
window.__fsCalls = []; let __fs = false;
window.__TAURI__ = { window: { getCurrentWindow: () => ({ isFullscreen: async () => __fs, setFullscreen: async (v) => { __fs = v; window.__fsCalls.push(v); } }) } };`;
const external = [];
const open = async (i = info()) => {
  const ctx = await chromium.launchPersistentContext(profile, { viewport: { width: 1600, height: 960 }, acceptDownloads: true });
  await ctx.addInitScript(initScript(i));
  await ctx.route('**/*', (route) => { const u = new URL(route.request().url()); if (!['127.0.0.1', 'localhost'].includes(u.hostname) && !u.protocol.startsWith('data') && !u.protocol.startsWith('blob')) { external.push(u.href); return route.abort(); } return route.continue(); });
  const page = ctx.pages()[0] ?? await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_CONNECTION_REFUSED/.test(m.text())) errors.push(m.text()); });
  return { ctx, page, errors };
};
const go = async (page, r) => { await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(800); };

try {
  await sleep(600);
  // 1. Startup: UI first, backend becomes ready later (as on a cold start of the packaged app).
  let { ctx, page, errors } = await open();
  await page.goto(`http://127.0.0.1:${uiPort}/index.html`);
  await page.waitForTimeout(700);
  check('STARTUP: loading state while backend starts', await page.getByText('Starting the AETHER backend').isVisible());
  startSidecar();
  await page.getByText(/Live Mode · API v/).waitFor({ timeout: 30000 });
  check('STARTUP: waits for backend, then Live Mode connects', true, sidecarLog.find((l) => l.includes('READY')) ?? '');
  check('STARTUP: backend bound to 127.0.0.1 with app-data DB', sidecarLog.some((l) => l.includes('host=127.0.0.1') && l.includes(dataDir)));

  // 2. Navigation across all modules.
  for (const [link, h] of [['BODY', /Alex Vega/], ['PHANTOM', /Analysis/], ['SYMBIOSIS', /Habitat conditions/], ['CO-ORBIT', /Crew coordination/], ['RECOVERY', /Recovery space/], ['MISSION LAB', /Scenario explorer/], ['Mission Control', /Mission Control/]]) {
    await page.getByRole('navigation', { name: 'Modules' }).first().getByRole('link', { name: new RegExp('^' + link) }).click(); await page.waitForTimeout(700);
    check(`NAV: ${link}`, await page.getByRole('heading', { level: 1, name: h }).first().isVisible());
  }

  // 3. 3D rendering (WebGL2 renderer, not the canvas fallback).
  await go(page, '/body'); await page.waitForTimeout(800);
  check('BODY: 3D twin renders with WebGL (not the canvas fallback)', await page.getByText('WebGL', { exact: true }).first().isVisible() && !(await page.getByText('Canvas fallback').count()));

  // 4. MISSION LAB scenario → cross-module propagation → reset.
  await go(page, '/mission-lab');
  await page.getByRole('button', { name: /^Elevated CO₂/ }).click();
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(400);
  check('LAB: scenario applied (banner + toast)', await page.getByRole('region', { name: 'Applied scenario' }).isVisible() && await page.getByText(/Scenario applied: Elevated CO₂/).first().isVisible());
  for (const [path, re] of [['/symbiosis', /Cabin conditions under the scenario/], ['/phantom', /PHANTOM on recorded data vs on the modelled scenario day/], ['/body', /modelled vs actual/], ['/co-orbit', /Modelled crew plan/]]) {
    await go(page, path); await page.waitForTimeout(600);
    check(`SCENARIO → ${path} (live backend model)`, await page.getByText(re).first().isVisible());
  }
  await page.getByRole('button', { name: 'Reset scenario' }).click();

  // 5. Data: settings (localStorage), experiment (localStorage), measurement (backend SQLite).
  await go(page, '/settings'); await page.getByRole('radio', { name: 'Flight surgeon' }).click();
  await go(page, '/mission-lab'); await page.getByRole('button', { name: /^Start simulation \(/ }).click(); await page.waitForTimeout(1500);
  await page.getByRole('button', { name: 'Pause' }).click(); await page.getByRole('button', { name: 'Save experiment' }).click();
  await go(page, '/body'); await page.getByRole('button', { name: 'Record measurement' }).click();
  await page.getByLabel('Reaction time (ms)').fill('287'); await page.getByRole('button', { name: 'Save measurement' }).click(); await page.waitForTimeout(600);
  await page.keyboard.press('Escape');

  // 6. Fullscreen: F11 and HTML fullscreen (Earth Window) map to the native window.
  await go(page, '/');
  await page.keyboard.press('F11'); await page.waitForTimeout(200);
  await page.keyboard.press('F11'); await page.waitForTimeout(200);
  check('FULLSCREEN: F11 toggles native window', JSON.stringify(await page.evaluate(() => window.__fsCalls)) === '[true,false]');
  await go(page, '/recovery/earth-window'); await page.getByRole('radio', { name: '6' }).click(); await page.getByRole('button', { name: 'Begin activity' }).click(); await page.waitForTimeout(400);
  await page.getByRole('button', { name: 'View full screen' }).click(); await page.waitForTimeout(500);
  check('FULLSCREEN: Earth Window → native fullscreen', (await page.evaluate(() => window.__fsCalls)).at(-1) === true);
  await page.evaluate(() => document.exitFullscreen?.()); await page.waitForTimeout(400);
  check('FULLSCREEN: exit restores window', (await page.evaluate(() => window.__fsCalls)).at(-1) === false);

  // 7. Resizing.
  for (const [w, h] of [[1024, 680], [1366, 768], [1920, 1080]]) {
    await page.setViewportSize({ width: w, height: h }); await go(page, '/'); await page.waitForTimeout(500);
    const r = await page.evaluate(() => ({ clip: getComputedStyle(document.documentElement).overflowX === 'clip', main: document.getElementById('main').getBoundingClientRect().right, w: innerWidth }));
    check(`RESIZE: ${w}×${h} layout fits the window`, r.clip && r.main <= r.w + 1 && await page.getByRole('heading', { level: 1, name: /Mission Control/ }).isVisible(), `main right ${Math.round(r.main)} / ${r.w}`);
  }
  check('RUNTIME: no page errors in session 1', errors.length === 0, errors.join(' | '));
  await ctx.close();

  // 8. Restart: app closed → backend stopped → relaunch with the same profile and data dir.
  shell.kill();
  check('SHUTDOWN: backend exits when the app process ends', await exited(sidecar, 8000));
  startSidecar();
  ({ ctx, page, errors } = await open());
  await page.goto(`http://127.0.0.1:${uiPort}/index.html`);
  await page.getByText(/Live Mode · API v/).waitFor({ timeout: 30000 });
  check('PERSIST: role setting survives restart', await page.getByText('Flight surgeon').first().isVisible());
  await go(page, '/mission-lab?tab=experiments');
  check('PERSIST: saved experiment survives restart', await page.getByText(/[1-9]\d* saved/).isVisible());
  await go(page, '/body?tab=history'); await page.getByLabel('Manual entries only').check().catch(() => undefined); await page.waitForTimeout(300);
  check('PERSIST: measurement stored in app-data SQLite survives restart', (await page.getByText('287').count()) >= 1);

  // 9. Offline / no backend: Demo Mode keeps working.
  shell.kill(); await exited(sidecar, 8000);
  await go(page, '/settings'); await page.getByRole('radio', { name: 'Demo Mode' }).click(); await go(page, '/'); await page.waitForTimeout(1000);
  check('OFFLINE: Demo Mode works with backend stopped', await page.getByText(/Demo Mode · labelled synthetic data/).isVisible() && await page.getByRole('region', { name: 'Digital twin preview' }).isVisible());
  await go(page, '/settings'); await page.getByRole('radio', { name: 'Live Mode' }).click();
  await ctx.close();

  // 10. Backend start failure is reported, with a way forward.
  ({ ctx, page, errors } = await open(info({ backendError: 'bundled backend not found: aether-backend' })));
  await page.goto(`http://127.0.0.1:${uiPort}/index.html`); await page.waitForTimeout(1500);
  check('ERROR: start failure explained (no endless spinner)', await page.getByText(/did not start/).isVisible() && await page.getByText(/backend\.log/).isVisible());
  await page.getByRole('button', { name: 'Use demo adapter' }).click(); await page.waitForTimeout(800);
  check('ERROR: switch to Demo Mode from failure screen', await page.getByRole('heading', { level: 1, name: /Mission Control/ }).isVisible());
  await ctx.close();

  check('OFFLINE: no request left 127.0.0.1 (no CDN, fonts or remote assets)', external.length === 0, external.slice(0, 3).join(' '));
} catch (e) {
  check('UNEXPECTED', false, String(e.message).split('\n')[0]);
} finally {
  shell?.kill(); sidecar?.kill(); ui.kill();
}
console.log(results.join('\n'));
console.log(`${results.filter((r) => r.startsWith('PASS')).length}/${results.length} passed`);
