// AETHER 1.4 end-to-end (headless Chromium via Playwright). Development-only.
// Starts web/backend/validation/e2e_server_1_4.py itself (mock BLE transport + optional OSDR fixture mirror),
// drives DATA SOURCE → ACQUISITION → ANALYSIS → UNCERTAINTY → INTERPRETATION → PROVENANCE → SAVE/REOPEN.
//   PLAYWRIGHT_BROWSERS_PATH=... AETHER_PLAYWRIGHT_FROM=<node_modules>/noop.js node tests/browser/e2e-v14.mjs [shotDir] [report.json]
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(process.env.AETHER_PLAYWRIGHT_FROM ?? '/opt/npm-tools/node_modules/noop.js');
const { chromium } = require('playwright');
const here = dirname(fileURLToPath(import.meta.url));
const backend = resolve(here, '../../../backend');
const staticDir = resolve(here, '../../dist-offline');
const shots = process.argv[2] ?? null; const reportPath = process.argv[3] ?? null;
if (shots) mkdirSync(shots, { recursive: true });
const data = mkdtempSync(join(tmpdir(), 'aether-e2e14-'));
const port = 18761;
const base = `http://127.0.0.1:${port}`;
const py = process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const results = []; const errors = []; const external = new Set();
const check = (name, ok, extra = '') => { results.push({ name, pass: !!ok, extra: String(extra).slice(0, 200) }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + String(extra).slice(0, 160) : ''}`); };
const safe = async (name, fn) => { try { await fn(); } catch (e) { check(name, false, String(e.message).split('\n')[0]); if (shots) await page.screenshot({ path: `${shots}/FAIL-${name.slice(0, 2).trim()}.png` }).catch(() => undefined); } };

let proc;
const start = async (mirror) => {
  proc = spawn(py, [join(backend, 'validation/e2e_server_1_4.py'), '--port', String(port), '--static', staticDir, ...(mirror ? ['--mirror'] : [])],
    { cwd: backend, env: { ...process.env, AETHER_DB_PATH: join(data, 'e2e.sqlite3'), AETHER_NASA_DATA_DIR: join(data, 'nasa') }, stdio: ['ignore', 'pipe', 'pipe'] });
  proc.stderr.on('data', (d) => process.stderr.write('[server] ' + d));
  for (let i = 0; i < 80; i++) { try { if ((await fetch(base + '/api/health')).ok) return; } catch { /* starting */ } await wait(250); }
  throw new Error('server did not start');
};
const stop = async () => { proc.kill(); await wait(800); };
const shot = async (page, n) => { if (shots) await page.screenshot({ path: `${shots}/${n}.png` }); };

await start(true);
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
const page = await ctx.newPage();
page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('request', (r) => { const u = r.url(); if (/^https?:/.test(u) && !u.startsWith('http://127.0.0.1')) external.add(new URL(u).host); });

await page.goto(base + '/?mode=live#/biosignals');
await safe('1 frontend loads live mode with BIOSIGNALS', async () => {
  await page.getByRole('heading', { name: 'Real Biosignal Intelligence' }).waitFor({ timeout: 20000 });
  check('1 frontend loads live mode with BIOSIGNALS', true);
  check('1 release label 1.4 visible', await page.getByText(/AETHER 1\.4/).count() > 0);
});

await safe('2 connector registry', async () => {
  await page.locator('[data-connector="apple_watch"]').waitFor({ timeout: 10000 });
  const apple = await page.locator('[data-connector="apple_watch"]').innerText();
  const ble = await page.locator('[data-connector="ble_hrs"]').innerText();
  check('2 Apple Watch listed as unsupported with access route', /unsupported/.test(apple) && /HealthKit/.test(apple));
  check('2 BLE HRS listed as automated tested (not physically verified)', /automated tested/.test(ble));
});

await safe('3 DEMO MODE', async () => {
  const create = page.getByRole('button', { name: 'Create simulated DEMO recording' });
  check('3 DEMO button disabled before explicit confirmation', await create.isDisabled());
  await page.getByText('I understand this recording is simulated').click();
  await create.click();
  await page.locator('[data-data-class="simulated_demo"]').waitFor({ timeout: 20000 });
  check('3 DEMO recording opens labelled SIMULATED', (await page.locator('[data-data-class="simulated_demo"]').innerText()).includes('SIMULATED'));
  await page.getByRole('button', { name: 'Run supported PHANTOM analysis' }).click();
  await page.getByText(/PHANTOM adapter · (flag|no_flag)/).waitFor({ timeout: 20000 });
  check('3 PHANTOM analysis returns a flag on the step change', await page.getByText('PHANTOM adapter · flag').count() > 0);
  check('3 uncertainty statement shown', await page.getByText(/Uncalibrated exploratory threshold/).count() > 0);
  await shot(page, '01-demo-analysis');
});

await safe('4 BODY shows the selected recording with 3D twin', async () => {
  await page.evaluate(() => { location.hash = '#/body'; });
  await page.getByText('BODY · recorded measurements').waitFor({ timeout: 15000 });
  await page.waitForTimeout(2500);
  check('4 BODY recording view with provenance label', await page.locator('[data-data-class="simulated_demo"]').count() > 0);
  check('4 BODY 3D canvas rendered', await page.locator('canvas').count() > 0);
  await shot(page, '02-body-recording');
});

await safe('5 PHANTOM shows recording + NASA reference context', async () => {
  await page.evaluate(() => { location.hash = '#/phantom'; });
  await page.getByTestId('nasa-reference-context').waitFor({ timeout: 45000 });
  await page.getByText(/No eligible NASA import yet|NASA reference context unavailable/).first().waitFor({ timeout: 15000 });
  check('5 NASA reference card present (no eligible import yet)', await page.getByText(/No eligible NASA import yet/).count() > 0);
  check('5 PHANTOM keeps the selected DEMO recording', await page.locator('[data-data-class="simulated_demo"]').count() > 0);
});

await safe('6 mock BLE acquisition', async () => {
  await page.evaluate(() => { location.hash = '#/biosignals'; });
  await page.getByRole('button', { name: 'Scan HRS monitors' }).click();
  await page.getByText(/MOCK HRS strap/).waitFor({ timeout: 15000 });
  await page.getByRole('button', { name: 'Connect / reconnect' }).first().click();
  await page.waitForFunction(() => /Heart rate: 6\d bpm/.test(document.querySelector('[data-testid="ble-live"]')?.textContent ?? ''), null, { timeout: 20000 });
  check('6 live HR from mock transport shown', true, await page.getByTestId('ble-live').innerText());
  await page.waitForFunction(() => /reconnects: [1-9]/.test(document.querySelector('[data-testid="ble-live"]')?.textContent ?? ''), null, { timeout: 30000 });
  const t = await page.getByTestId('ble-live').innerText();
  check('6 link loss → automatic reconnection, gap stored as missing', /gaps stored as missing: [1-9]/.test(t), t);
  await page.getByRole('button', { name: 'Stop, save & disconnect' }).click();
  await page.waitForFunction(() => /connection: disconnected/.test(document.querySelector('[data-testid="ble-live"]')?.textContent ?? ''), null, { timeout: 15000 });
  check('6 disconnect clears the live value', /Heart rate: — bpm/.test(await page.getByTestId('ble-live').innerText()));
  await shot(page, '03-ble-mock');
});

await safe('7 NASA Data Lab via fixture mirror', async () => {
  await page.getByRole('button', { name: 'Open NASA Open Data Research Lab' }).click();
  await page.locator('#aether-nasa-term').fill('inspiration4');
  await page.locator('#aether-nasa-search').click();
  await page.locator('[data-evidence-class]').first().waitFor({ timeout: 15000 });
  const classes = await page.locator('[data-evidence-class]').evaluateAll((n) => n.map((x) => x.getAttribute('data-evidence-class')));
  check('7 studies classified (human vs animal vs microbial)', classes.includes('human_in_vivo') && classes.includes('animal') && classes.includes('microbial'), classes.join(','));
  await page.locator('#aether-nasa-study-id').fill('575');
  await page.locator('#aether-nasa-files-btn').click();
  await page.getByText(/OSD-575: 9 file entries/).waitFor({ timeout: 15000 });
  check('7 unsupported formats explained (xlsx)', await page.getByText(/Not imported · XLSX/).count() > 0);
  const row = page.locator('#aether-nasa-files .aether-nasa-result', { hasText: 'Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv' });
  await row.getByRole('button', { name: 'Inspect & import from NASA' }).click();
  await page.getByText(/TEST FIXTURE MIRROR — NOT NASA DATA/).first().waitFor({ timeout: 15000 });
  check('7 fixture source can never pose as NASA', true);
  await page.locator('#aether-nasa-verified-column').selectOption('Sodium (mmol/L)');
  await page.locator('#aether-nasa-verified-label-column').selectOption('Sample Name');
  await page.locator('#aether-nasa-verified-run').click();
  await page.getByRole('table', { name: 'Timepoint summary' }).waitFor({ timeout: 15000 });
  const summary = await page.getByRole('table', { name: 'Verified NASA import summary' }).innerText();
  check('7 unit from header + censored value counted', /mmol\/L/.test(summary) && /<130/.test(summary), summary.replace(/\s+/g, ' ').slice(0, 150));
  check('7 PHANTOM use refused for non-NASA source', /Not used/.test(summary));
  await page.locator('#aether-nasa-history').click();
  await page.locator('#aether-nasa-history-list [data-import-id]').first().waitFor({ timeout: 10000 });
  check('7 import history lists the record with provenance', /SHA-256/.test(await page.locator('#aether-nasa-history-list').innerText()));
  await shot(page, '04-nasa-data-lab');
  await page.locator('#aether-nasa-close').click();
});

await safe('8 cross-origin page cannot use the local API', async () => {
  const before = await page.evaluate(async () => (await (await fetch('/api/biosignals/sessions')).json()).length);
  const evil = await ctx.newPage();
  const mirror = (await (await fetch(base + '/api/health')).json()) && null; void mirror;
  await evil.goto('about:blank');
  const r = await evil.evaluate(async (b) => {
    const out = {};
    try { await fetch(b + '/api/nasa/imports'); out.read = 'readable'; } catch { out.read = 'blocked'; }
    try { await fetch(b + '/api/biosignals/demo/recording', { method: 'POST', mode: 'no-cors', headers: { 'Content-Type': 'text/plain' }, body: '{"confirm_simulated":true}' }); out.write = 'sent'; } catch { out.write = 'blocked'; }
    return out;
  }, base);
  await evil.close();
  const after = await page.evaluate(async () => (await (await fetch('/api/biosignals/sessions')).json()).length);
  check('8 foreign page cannot read API data', r.read === 'blocked', JSON.stringify(r));
  check('8 foreign no-cors POST did not create a session', after === before, `${before}→${after}`);
});

await safe('9 restart: sessions and NASA history persist; selection reopens', async () => {
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('aether.biosignal.selection') || 'null'));
  await stop();
  await start(false);
  await page.goto(base + '/?mode=live#/phantom');
  await page.locator(`[data-data-class="${saved.source}"]`).waitFor({ timeout: 20000 });
  check('9 last selected recording reopens after backend restart', true, saved.source);
  await page.evaluate(() => { location.hash = '#/biosignals'; });
  await page.waitForFunction(() => document.querySelectorAll('select[aria-label="Local session"] option').length > 2, null, { timeout: 15000 });
  const options = await page.locator('select[aria-label="Local session"] option').allInnerTexts();
  check('9 DEMO and BLE sessions both persisted', options.some((o) => o.includes('SIMULATED')) && options.some((o) => o.includes('wearable')), options.length);
  await page.evaluate(() => { location.hash = '#/biosignals'; });
  await page.getByRole('button', { name: 'Open NASA Open Data Research Lab' }).click();
  await page.locator('#aether-nasa-history').click();
  await page.locator('#aether-nasa-history-list [data-import-id]').first().waitFor({ timeout: 10000 });
  check('9 NASA import history survives restart', true);
});

await safe('10 NASA unreachable → explicit error, nothing invented', async () => {
  await page.locator('#aether-nasa-term').fill('radiation');
  await page.locator('#aether-nasa-search').click();
  await page.waitForFunction(() => /unreachable|unavailable/i.test(document.getElementById('aether-nasa-search-status')?.textContent ?? ''), null, { timeout: 30000 });
  check('10 offline NASA search shows error state', true, await page.locator('#aether-nasa-search-status').innerText());
  check('10 no studies invented offline', await page.locator('#aether-nasa-studies .aether-nasa-result').count() === 0);
  await shot(page, '05-nasa-offline');
});

check('11 no console errors', errors.length === 0, errors.slice(0, 3).join(' | '));
check('11 no request left the machine (except blocked NASA attempt by backend)', external.size === 0, [...external].join(','));
await browser.close(); await stop();
const passed = results.filter((r) => r.pass).length;
console.log(`${passed}/${results.length} passed`);
if (reportPath) writeFileSync(reportPath, JSON.stringify({ suite: 'e2e-v14', browser: 'chromium headless (Playwright)', passed, failed: results.length - passed, results, errors }, null, 2));
process.exit(passed === results.length ? 0 : 1);
