// AETHER 1.0 FINAL E2E – mandatory scenarios A–O of the release brief that a headless browser can verify.
// Usage: node e2e-v10.mjs <url-of-running-backend-serving-the-UI> [screenshot-dir]
//   e.g. python -m app.devserver --port 8765 --static ../frontend/dist-offline  →  node e2e-v10.mjs http://127.0.0.1:8765/ /tmp/shots
// Playwright is resolved from AETHER_PLAYWRIGHT_FROM (same convention as the other browser tests).
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.AETHER_PLAYWRIGHT_FROM ?? '/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const base = process.argv[2] ?? 'http://127.0.0.1:8000/';
const shots = process.argv[3] ?? null;
const only = (process.env.E2E_ONLY ?? '').split(',').filter(Boolean);
if (shots) mkdirSync(shots, { recursive: true });
const origin = new URL(base).origin;
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const errors = []; const results = []; const external = new Set();
page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('request', (r) => { const u = r.url(); if (/^https?:/.test(u) && !u.startsWith(origin)) external.add(new URL(u).host); });
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + extra : ''}`);
const safe = async (name, fn) => { if (only.length && !only.includes(name)) return; try { await fn(); } catch (e) { check(name, false, String(e.message).split('\n')[0].slice(0, 200)); } };
const go = async (r) => { await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(900); };
const shot = async (n) => { if (shots) await page.screenshot({ path: `${shots}/${n}.png`, fullPage: false }); };
const api = (path, init) => page.evaluate(async ([p, i]) => { const r = await fetch(p, i); return { status: r.status, body: await r.json() }; }, [path, init]);
const runEngine = async (template) => {
  await go('/mission-lab?tab=engine');
  await page.getByRole('button', { name: new RegExp(template) }).first().click();
  await page.getByLabel('Crew plan (CO-ORBIT)').selectOption('standard');
  const prev = await page.evaluate(() => localStorage.getItem('aether.engineRun'));
  await page.getByRole('button', { name: 'Run engine' }).click();
  await page.waitForFunction((p) => { const id = localStorage.getItem('aether.engineRun'); return id && id !== p; }, prev, { timeout: 120000 }).catch(() => undefined);
  await page.getByText('PHANTOM 1.0 vs 2.0 – physiology only, hidden synthetic labels').waitFor({ timeout: 120000 });
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(600);
};

await page.goto(base + '?mode=live'); await page.waitForTimeout(1500);

await safe('A-startup', async () => {
  const h = await api('/api/health');
  check('A: backend reports API contract 1.0', h.body.api_contract_version === '1.0', h.body.version);
  check('A: UI shows Live mode', (await page.getByText(/Live/).count()) > 0);
  check('A: release identifier visible', (await page.getByText(/AETHER 1\.4/).count()) > 0); // 1.4: was 'AETHER 1.0 FINAL'; the shipped 1.3 UI still said 1.1
  await shot('01-mission-control');
});

await safe('B-navigation', async () => {
  const routes = ['/', '/body', '/phantom', '/symbiosis', '/co-orbit', '/recovery', '/mission-lab', '/science'];
  let ok = 0;
  for (const r of routes) { await go(r); if ((await page.locator('main h1, main h2').count()) > 0) ok++; }
  check('B: all 8 modules render a heading', ok === routes.length, `${ok}/${routes.length}`);
});

await safe('C-global-state', async () => {
  await page.evaluate(() => localStorage.setItem('aether.astronaut', 'A02'));
  await page.reload(); await page.waitForTimeout(1500);
  await go('/body'); const a = await page.evaluate(() => localStorage.getItem('aether.astronaut'));
  await go('/phantom'); const b = await page.evaluate(() => localStorage.getItem('aether.astronaut'));
  check('C: selected astronaut persists across modules and reload', a === 'A02' && b === 'A02');
  await page.evaluate(() => localStorage.setItem('aether.astronaut', 'A01')); await page.reload(); await page.waitForTimeout(1200);
});

await safe('D-body', async () => {
  await go('/body'); await page.waitForTimeout(2500);
  check('D: BODY viewport renders a canvas', (await page.locator('main canvas').count()) > 0);
  await shot('02-body');
});

await safe('E-phantom-labels', async () => {
  await go('/phantom');
  await page.getByText('Beyond single-signal z-scores').waitFor({ timeout: 20000 });
  check('E: daily card names the legacy 0.9 rule', (await page.getByText('PHANTOM 2.0 (legacy 0.9 rule)', { exact: false }).count()) > 0);
  check('E: daily state shown explicitly', await page.getByTestId('phantom2-today-state').isVisible());
  await shot('03-phantom');
});

await safe('G-coorbit-rejection', async () => {
  // pulse_shift → only recommendation "60-min blocks"; with all tasks required the backend rejects it (B5 study 30/30).
  await runEngine('Heart-rate shift');
  const recs = (await api(`/api/engine/runs/${await page.evaluate(() => localStorage.getItem('aether.engineRun'))}/coorbit`)).body;
  check('G: engine label shows noise-adaptive PHANTOM 2.0', (await page.getByText('PHANTOM 2.0 · noise-adaptive (1.0)').count()) > 0);
  await go('/co-orbit');
  const panel = page.getByRole('region', { name: 'PHANTOM-derived planning constraints' });
  await panel.getByRole('list', { name: 'Recommendations' }).waitFor({ timeout: 40000 });
  check('G: recommendation carries cabin context', (await panel.getByText(/Cabin context:/).count()) > 0, `${recs.recommendations.length} recs`);
  const boxes = panel.getByRole('checkbox'); const n = await boxes.count();
  for (let i = 0; i < n; i++) await boxes.nth(i).check();
  await panel.getByLabel('Approved by').fill('Flight surgeon (E2E)');
  await panel.getByRole('button', { name: /compute proposal/ }).click();
  const dec = panel.getByTestId('coorbit-decision'); await dec.waitFor({ timeout: 90000 });
  const st = await dec.getAttribute('data-decision-status');
  check('G: infeasible proposal shown as REJECTED', st === 'rejected_no_feasible_schedule', st);
  check('G: backend reason displayed', await dec.getByText('Why the optimisation failed').isVisible());
  check('G: schedule in force preserved and shown', await panel.getByRole('list', { name: 'Schedule in force – unchanged' }).isVisible());
  check('G: no "proposed schedule" for a rejected plan', (await panel.getByRole('list', { name: 'Proposed schedule' }).count()) === 0);
  check('G: next actions offered', await dec.getByText('What you can do next').isVisible());
  check('G: never labelled as applied', (await panel.getByText(/new schedule valid|applied to the plan/i).count()) === 0);
  await panel.scrollIntoViewIfNeeded(); await shot('05-coorbit-rejected');
  await panel.getByRole('button', { name: /^Reject \d+/ }).click();
  await panel.getByText('Recommendations rejected – nothing changed').waitFor({ timeout: 30000 });
  check('G: explicit human rejection recorded, nothing changed', true);
});

await safe('F-symbiosis', async () => {
  await runEngine('Cabin environment');
  await go('/symbiosis');
  const ev = page.getByTestId('environment-events'); await ev.waitFor({ timeout: 60000 });
  check('F: cabin events listed separately', await ev.getByRole('region', { name: 'Cabin events' }).isVisible() && (await ev.getByText('CO₂ increase').count()) > 0);
  check('F: sensor faults in their own section', await ev.getByRole('region', { name: 'Sensor faults' }).isVisible());
  check('F: crew context framed as hypotheses', await ev.getByText('Crew context – hypotheses, not causes').isVisible());
  check('F: no diagnosis wording', (await ev.getByText(/diagnos(is|ed) of|you have/i).count()) === 0);
  check('F: global scenario banner matches the applied run', (await page.getByText(/Scenario applied: Engine · Cabin environment/).count()) > 0);
  await ev.scrollIntoViewIfNeeded(); await page.waitForTimeout(1500); await shot('04-symbiosis-events');
});

await safe('H-recovery', async () => {
  await go('/recovery'); await page.waitForTimeout(800);
  const before = (await api('/api/recovery/sessions/A01')).body.length;
  const save = await api('/api/recovery/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ astronaut_id: 'A01', activity: 'mind-pulse', before_mood: 4, after_mood: 6, duration_seconds: 60 }) });
  const after = (await api('/api/recovery/sessions/A01')).body.length;
  check('H: session persisted through the API', save.status === 200 && after === before + 1);
  await shot('06-recovery');
});

await safe('I-mission-lab', async () => {
  await go('/mission-lab?tab=engine');
  check('I: engine run present with schedules and detectors', (await page.getByText('PHANTOM 1.0 vs 2.0 – physiology only, hidden synthetic labels').count()) > 0);
  await shot('07-mission-lab');
});

await safe('J-science', async () => {
  await go('/science');
  await page.getByRole('heading', { name: /Scientific core/ }).waitFor({ timeout: 15000 });
  check('J: evidence library offline (local API)', (await page.getByRole('table', { name: 'Evidence library' }).locator('tbody tr').count()) === 16);
  await shot('08-science');
});

await safe('M-offline', async () => {
  check('M: no request left the local origin during the run', external.size === 0, [...external].join(', '));
});

await safe('N-responsive', async () => {
  for (const [w, h] of [[1366, 768], [1920, 1080]]) {
    await page.setViewportSize({ width: w, height: h });
    let bad = [];
    for (const r of ['/', '/co-orbit', '/symbiosis', '/phantom']) {
      await go(r);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (over > 2) bad.push(`${r}:${over}px`);
    }
    check(`N: no horizontal overflow at ${w}×${h}`, bad.length === 0, bad.join(' '));
  }
  await page.setViewportSize({ width: 1600, height: 1000 });
});

await safe('O-a11y', async () => {
  await go('/co-orbit');
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
  const focus = await page.evaluate(() => { const e = document.activeElement; return e ? `${e.tagName}:${(e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 30)}` : 'none'; });
  check('O: keyboard focus reaches interactive controls', !/BODY|none/.test(focus), focus);
  const unnamed = await page.evaluate(() => [...document.querySelectorAll('button')].filter((b) => !(b.getAttribute('aria-label') || b.textContent || '').trim()).length);
  check('O: every button has an accessible name', unnamed === 0, `${unnamed} unnamed`);
});

await safe('L-backend-failure', async () => {
  // Point the UI at a port with nothing listening: Live Mode must say "offline", never fall back to mock data.
  const p2 = await ctx.newPage();
  await p2.route('**/api/**', (r) => r.abort());
  await p2.goto(base + '?mode=live'); await p2.waitForTimeout(3000);
  const text = await p2.evaluate(() => document.body.innerText);
  check('L: backend failure is reported to the user', /offline|cannot reach|not reachable|retry/i.test(text));
  check('L: no demo data substituted in Live Mode', !/Demo Mode active/i.test(text));
  if (shots) await p2.screenshot({ path: `${shots}/09-backend-offline.png` });
  await p2.close();
});

await browser.close();
console.log(results.join('\n'));
const passed = results.filter((r) => r.startsWith('PASS')).length;
console.log(`${passed}/${results.length} passed`);
console.log(errors.length ? `console errors (${errors.length}):\n` + errors.slice(0, 10).join('\n') : 'no console errors');
process.exit(passed === results.length && !errors.length ? 0 : 1);
